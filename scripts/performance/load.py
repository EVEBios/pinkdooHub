"""Closed-loop HTTP profiles for the disposable capacity-test stack.

The module intentionally has no retry policy.  A lost response on a non-idempotent
order creation is an unknown business result and therefore aborts the profile.
Tokens and request bodies remain in memory; samples contain only bounded operation
names and aggregate-safe measurements.
"""

from __future__ import annotations

import asyncio
from array import array
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import re
import secrets
import time
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

import httpx

from app.tasks.mard_catalog import build_swatch_png, load_manifest


HEX_PATTERN = re.compile(r"^#[0-9A-F]{6}$")
MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "tasks"
    / "manifests"
    / "mard_221.json"
)
FROZEN_MANIFEST = load_manifest(MANIFEST)
DEFAULT_TIMEOUT_SECONDS = 5.0
IMAGE_CONNECTIONS_PER_USER = 4
IMAGE_JOURNEY_PERIOD_SECONDS = 6.0
IMAGE_PROFILE_MODEL = "per-vu-fixed-period-palette-page-load"
IMAGE_PROFILE_MODEL_VERSION = "palette-page-load-v3"
SAMPLE_SCHEMA_VERSION = 1
HISTOGRAM_MAX_MILLISECONDS = 10_000
MAX_SUCCESS_EVIDENCE_SAMPLES = 2_048
MAX_FAILURE_EVIDENCE_SAMPLES = 64
WRITE_JOURNEY_PERIOD_SECONDS = 6.0
WRITE_KEY_SCOPES = frozenset({"ramp", "warmup", "measured"})
COMPATIBILITY_IMAGE_BASE_URL = (
    "https://pinkdoohub-performance.invalid/uploads/products"
)
COMPATIBILITY_IMAGE_BASE = urlsplit(COMPATIBILITY_IMAGE_BASE_URL)
DEFAULT_ORIGIN_PORTS = {"http": 80, "https": 443}


class LoadProfileError(RuntimeError):
    """An unexpected transport, HTTP, envelope or business assertion failure."""


class MeasuredRequestFailure(LoadProfileError):
    """Carries a sanitized failed sample across the request boundary."""

    def __init__(self, sample: "RequestSample") -> None:
        super().__init__(sample.error_type or "request failed")
        self.sample = sample


class ProfileExecutionError(LoadProfileError):
    """Carries all sanitized samples collected before fail-fast cancellation."""

    def __init__(self, result: "ProfileResult") -> None:
        super().__init__(f"profile aborted: {result.profile}")
        self.result = result


@dataclass(frozen=True, slots=True)
class Persona:
    username: str
    user_id: int
    access_token: str = field(repr=False)

    @property
    def authorization(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


@dataclass(frozen=True, slots=True)
class ImageFixture:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class FrozenDataset:
    color_product_id: int
    small_color_product_id: int
    fixed_product_ids: tuple[int, ...]
    color_kit_color_id: int
    color_count: int
    images: tuple[ImageFixture, ...]
    admin: Persona
    customers: tuple[Persona, ...]

    def safe_summary(self) -> dict[str, object]:
        return {
            "color_count": self.color_count,
            "color_product_id": self.color_product_id,
            "customer_count": len(self.customers),
            "fixed_product_count": len(self.fixed_product_ids),
            "image_count": len(self.images),
            "image_sizes": summarize_numbers(image.size for image in self.images),
            "small_color_product_id": self.small_color_product_id,
        }


@dataclass(frozen=True, slots=True)
class RequestSpec:
    method: str
    path: str
    operation: str
    expected_statuses: tuple[int, ...] = (200,)
    headers: Mapping[str, str] = field(default_factory=dict)
    json_body: object | None = None


@dataclass(frozen=True, slots=True)
class WireResponse:
    status_code: int
    headers: Mapping[str, str]
    raw_body: bytes
    decoded_body: bytes

    def json(self) -> object:
        try:
            return json.loads(self.decoded_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LoadProfileError("response is not valid UTF-8 JSON") from error


@dataclass(slots=True)
class RequestSample:
    schema_version: int
    profile: str
    operation: str
    round_number: int
    vus: int
    status_code: int | None
    ok: bool
    error_type: str | None
    latency_ms: float
    ttfb_ms: float | None
    download_ms: float | None
    wire_body_bytes: int
    decoded_body_bytes: int
    content_encoding: str
    completed_at_utc: str

    def safe_record(self) -> dict[str, object]:
        return asdict(self)


class MillisecondHistogram:
    """Fixed-memory, fail-closed millisecond histogram for HTTP timings."""

    def __init__(self) -> None:
        # The final bucket is overflow.  Values are rounded up so a percentile
        # can never look faster than the observed request when used by a gate.
        self.counts = array("Q", [0]) * (HISTOGRAM_MAX_MILLISECONDS + 2)
        self.count = 0
        self.maximum: float | None = None

    def add(self, value: float) -> None:
        if not math.isfinite(value) or value < 0:
            raise ValueError("request timing must be finite and non-negative")
        bucket = min(
            math.ceil(value),
            HISTOGRAM_MAX_MILLISECONDS + 1,
        )
        self.counts[bucket] += 1
        self.count += 1
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def percentile(self, percentile: float) -> float | None:
        if self.count == 0:
            return None
        if not 0 < percentile <= 100:
            raise ValueError("percentile must be in (0, 100]")
        target = math.ceil(percentile / 100 * self.count)
        cumulative = 0
        for bucket, count in enumerate(self.counts):
            cumulative += count
            if cumulative >= target:
                if bucket == HISTOGRAM_MAX_MILLISECONDS + 1:
                    # Overflow can only make a threshold decision stricter.
                    return round(float(self.maximum), 6)
                return float(bucket)
        raise AssertionError("histogram count mismatch")

    def summary(self) -> dict[str, object]:
        return {
            "count": self.count,
            "p50": self.percentile(50),
            "p90": self.percentile(90),
            "p95": self.percentile(95),
            "p99": self.percentile(99),
            "max": round(self.maximum, 6) if self.maximum is not None else None,
        }


@dataclass(slots=True)
class SampleStatistics:
    """Exact counters plus bounded timing histograms for one operation."""

    count: int = 0
    successful: int = 0
    failed: int = 0
    wire_body_bytes: int = 0
    decoded_body_bytes: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    content_encodings: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    latency: MillisecondHistogram = field(default_factory=MillisecondHistogram)
    ttfb: MillisecondHistogram = field(default_factory=MillisecondHistogram)
    download: MillisecondHistogram = field(default_factory=MillisecondHistogram)

    def add(self, sample: RequestSample) -> None:
        self.count += 1
        status = str(sample.status_code)
        self.statuses[status] = self.statuses.get(status, 0) + 1
        if sample.ok:
            self.successful += 1
            self.wire_body_bytes += sample.wire_body_bytes
            self.decoded_body_bytes += sample.decoded_body_bytes
            self.content_encodings[sample.content_encoding] = (
                self.content_encodings.get(sample.content_encoding, 0) + 1
            )
            self.latency.add(sample.latency_ms)
            if sample.ttfb_ms is not None:
                self.ttfb.add(sample.ttfb_ms)
            if sample.download_ms is not None:
                self.download.add(sample.download_ms)
        else:
            self.failed += 1
            error = sample.error_type or "unknown"
            self.errors[error] = self.errors.get(error, 0) + 1

    def summary(self) -> dict[str, object]:
        return {
            "count": self.count,
            "ok": self.successful,
            "failed": self.failed,
            "latency_ms": self.latency.summary(),
            "ttfb_ms": self.ttfb.summary(),
            "download_ms": self.download.summary(),
            "wire_body_bytes": self.wire_body_bytes,
            "decoded_body_bytes": self.decoded_body_bytes,
            "statuses": dict(sorted(self.statuses.items())),
            "content_encodings": dict(sorted(self.content_encodings.items())),
            "errors": dict(sorted(self.errors.items())),
        }


class SampleCollector:
    """Online exact aggregation with a hard-capped deterministic raw sample."""

    def __init__(self, samples: Iterable[RequestSample] = ()) -> None:
        self.statistics = SampleStatistics()
        self.operations: dict[str, SampleStatistics] = {}
        self._success_reservoir: list[tuple[int, RequestSample]] = []
        self._failure_records: list[tuple[int, RequestSample]] = []
        self._success_seen = 0
        self._failure_records_dropped = 0
        for sample in samples:
            self.append(sample)

    def append(self, sample: RequestSample) -> None:
        self.statistics.add(sample)
        operation_statistics = self.operations.get(sample.operation)
        if operation_statistics is None:
            operation_statistics = SampleStatistics()
            self.operations[sample.operation] = operation_statistics
        operation_statistics.add(sample)
        ordinal = self.statistics.count
        if not sample.ok:
            if len(self._failure_records) < MAX_FAILURE_EVIDENCE_SAMPLES:
                self._failure_records.append((ordinal, sample))
            else:
                self._failure_records_dropped += 1
            return
        self._success_seen += 1
        if len(self._success_reservoir) < MAX_SUCCESS_EVIDENCE_SAMPLES:
            self._success_reservoir.append((ordinal, sample))
            return
        selector = int.from_bytes(
            hashlib.blake2b(
                str(self._success_seen).encode("ascii"),
                digest_size=8,
                person=b"pinkdoo-perf",
            ).digest(),
            "big",
        ) % self._success_seen
        if selector < MAX_SUCCESS_EVIDENCE_SAMPLES:
            self._success_reservoir[selector] = (ordinal, sample)

    def __len__(self) -> int:
        return self.statistics.count

    def evidence_records(self) -> Iterable[dict[str, object]]:
        selected = [
            (ordinal, sample, "deterministic_success_reservoir")
            for ordinal, sample in self._success_reservoir
        ] + [
            (ordinal, sample, "failure")
            for ordinal, sample in self._failure_records
        ]
        for ordinal, sample, selection in sorted(selected, key=lambda item: item[0]):
            yield {
                **sample.safe_record(),
                "sample_ordinal": ordinal,
                "evidence_selection": selection,
            }

    def summary(self) -> dict[str, object]:
        return {
            "completed_requests": self.statistics.count,
            "successful_requests": self.statistics.successful,
            "failed_requests": self.statistics.failed,
            "latency_ms": self.statistics.latency.summary(),
            "ttfb_ms": self.statistics.ttfb.summary(),
            "download_ms": self.statistics.download.summary(),
            "wire_body_bytes": self.statistics.wire_body_bytes,
            "decoded_body_bytes": self.statistics.decoded_body_bytes,
            "content_encodings": dict(
                sorted(self.statistics.content_encodings.items())
            ),
            "errors": dict(sorted(self.statistics.errors.items())),
            "operations": {
                name: statistics.summary()
                for name, statistics in sorted(self.operations.items())
            },
            "raw_sample_evidence": {
                "success_records_retained": len(self._success_reservoir),
                "success_record_limit": MAX_SUCCESS_EVIDENCE_SAMPLES,
                "failure_records_retained": len(self._failure_records),
                "failure_record_limit": MAX_FAILURE_EVIDENCE_SAMPLES,
                "failure_records_dropped": self._failure_records_dropped,
                "selection": "deterministic reservoir by successful-request ordinal",
                "aggregate_counters": "complete",
                "timing_histogram_resolution_ms": 1,
                "timing_histogram_overflow_ms": HISTOGRAM_MAX_MILLISECONDS,
                "timing_rounding": "ceiling (fail-closed)",
            },
        }


@dataclass(slots=True)
class ProfileResult:
    profile: str
    round_number: int
    vus: int
    configured_duration_seconds: float
    measured_duration_seconds: float
    samples: SampleCollector | Sequence[RequestSample]
    completed_journeys: int = 0
    setup: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.samples, SampleCollector):
            self.samples = SampleCollector(self.samples)

    def summary(self) -> dict[str, object]:
        assert isinstance(self.samples, SampleCollector)
        aggregate = self.samples.summary()
        return {
            "profile": self.profile,
            "round": self.round_number,
            "vus": self.vus,
            "configured_duration_seconds": self.configured_duration_seconds,
            "measured_duration_seconds": round(self.measured_duration_seconds, 6),
            **aggregate,
            "completed_journeys": self.completed_journeys,
            "rps": round(len(self.samples) / self.measured_duration_seconds, 6),
            "setup": self.setup,
            "percentile_algorithm": (
                "nearest-rank over fixed 1ms ceiling histogram; exact counts and maxima"
            ),
        }


def nearest_rank(values: Iterable[float], percentile: float) -> float | None:
    """Return the deterministic nearest-rank percentile used by the report."""

    ordered = sorted(values)
    if not ordered:
        return None
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")
    index = max(0, math.ceil(percentile / 100 * len(ordered)) - 1)
    return round(ordered[index], 6)


def summarize_numbers(values: Iterable[float | int]) -> dict[str, object]:
    ordered = [float(value) for value in values]
    if not ordered:
        return {"count": 0, "p50": None, "p90": None, "p95": None, "p99": None, "max": None}
    return {
        "count": len(ordered),
        "p50": nearest_rank(ordered, 50),
        "p90": nearest_rank(ordered, 90),
        "p95": nearest_rank(ordered, 95),
        "p99": nearest_rank(ordered, 99),
        "max": round(max(ordered), 6),
    }


def summarize_samples(samples: Sequence[RequestSample]) -> dict[str, object]:
    successful = [sample for sample in samples if sample.ok]
    return {
        "count": len(samples),
        "ok": len(successful),
        "failed": len(samples) - len(successful),
        "latency_ms": summarize_numbers(
            sample.latency_ms for sample in successful
        ),
        "ttfb_ms": summarize_numbers(
            sample.ttfb_ms
            for sample in successful
            if sample.ttfb_ms is not None
        ),
        "download_ms": summarize_numbers(
            sample.download_ms
            for sample in successful
            if sample.download_ms is not None
        ),
        "wire_body_bytes": sum(sample.wire_body_bytes for sample in successful),
        "decoded_body_bytes": sum(
            sample.decoded_body_bytes for sample in successful
        ),
        "statuses": _count_values(
            str(sample.status_code) for sample in samples
        ),
    }


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _decode_wire_body(raw_body: bytes, encoding: str) -> bytes:
    normalized = encoding.strip().lower()
    if normalized in ("", "identity"):
        return raw_body
    if normalized == "gzip":
        try:
            return gzip.decompress(raw_body)
        except (OSError, EOFError) as error:
            raise LoadProfileError("gzip response body is invalid") from error
    raise LoadProfileError("profile received an unsupported content encoding")


async def measured_request(
    client: httpx.AsyncClient,
    *,
    profile: str,
    round_number: int,
    vus: int,
    spec: RequestSpec,
) -> tuple[RequestSample, WireResponse]:
    """Read encoded chunks directly so wire bytes are not auto-decompressed."""

    started = time.perf_counter()
    first_byte_at: float | None = None
    status_code: int | None = None
    raw_body = bytearray()
    try:
        async with client.stream(
            spec.method,
            spec.path,
            headers=dict(spec.headers),
            json=spec.json_body,
        ) as response:
            status_code = response.status_code
            async for chunk in response.aiter_raw():
                if first_byte_at is None:
                    first_byte_at = time.perf_counter()
                raw_body.extend(chunk)
            finished = time.perf_counter()
            encoding = response.headers.get("content-encoding", "").lower()
            decoded = _decode_wire_body(bytes(raw_body), encoding)
            wire = WireResponse(
                status_code=status_code,
                headers=dict(response.headers),
                raw_body=bytes(raw_body),
                decoded_body=decoded,
            )
            if status_code not in spec.expected_statuses:
                raise LoadProfileError("unexpected HTTP status")
            sample = RequestSample(
                schema_version=SAMPLE_SCHEMA_VERSION,
                profile=profile,
                operation=spec.operation,
                round_number=round_number,
                vus=vus,
                status_code=status_code,
                ok=True,
                error_type=None,
                latency_ms=(finished - started) * 1000,
                ttfb_ms=(
                    (first_byte_at - started) * 1000
                    if first_byte_at is not None
                    else (finished - started) * 1000
                ),
                download_ms=(
                    (finished - first_byte_at) * 1000
                    if first_byte_at is not None
                    else 0.0
                ),
                wire_body_bytes=len(raw_body),
                decoded_body_bytes=len(decoded),
                content_encoding=encoding or "identity",
                completed_at_utc=datetime.now(timezone.utc).isoformat(),
            )
            return sample, wire
    except (httpx.HTTPError, LoadProfileError, UnicodeError, ValueError) as error:
        finished = time.perf_counter()
        sample = RequestSample(
            schema_version=SAMPLE_SCHEMA_VERSION,
            profile=profile,
            operation=spec.operation,
            round_number=round_number,
            vus=vus,
            status_code=status_code,
            ok=False,
            error_type=type(error).__name__,
            latency_ms=(finished - started) * 1000,
            ttfb_ms=(
                (first_byte_at - started) * 1000
                if first_byte_at is not None
                else None
            ),
            download_ms=(
                (finished - first_byte_at) * 1000
                if first_byte_at is not None
                else None
            ),
            wire_body_bytes=len(raw_body),
            decoded_body_bytes=0,
            content_encoding="unknown",
            completed_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        raise MeasuredRequestFailure(sample) from error


def _require_success_envelope(wire: WireResponse) -> dict[str, Any]:
    document = wire.json()
    if not isinstance(document, dict) or document.get("code") != 0:
        raise LoadProfileError("success response envelope is invalid")
    data = document.get("data")
    if not isinstance(data, dict):
        raise LoadProfileError("success response data is not an object")
    return data


def _effective_url_port(url: object) -> int:
    """Return an explicit or scheme-default port without exposing the URL."""

    try:
        scheme = str(getattr(url, "scheme", "")).casefold()
        explicit_port = getattr(url, "port")
    except ValueError as error:
        raise LoadProfileError("compatibility image URL port is invalid") from error
    if explicit_port is not None:
        return int(explicit_port)
    try:
        return DEFAULT_ORIGIN_PORTS[scheme]
    except KeyError as error:
        raise LoadProfileError(
            "compatibility image URL scheme has no default port"
        ) from error


def _compatibility_image_path(image_filename: str) -> str:
    return f"{COMPATIBILITY_IMAGE_BASE.path.rstrip('/')}/{image_filename}"


def _validated_compatibility_image_path(
    raw_url: object,
    *,
    expected_path: str,
) -> str:
    """Validate the frozen external origin before mapping it to a local path."""

    if not isinstance(raw_url, str):
        raise LoadProfileError("compatibility image URL is invalid")
    try:
        parsed = urlsplit(raw_url)
        actual_origin = (
            parsed.scheme.casefold(),
            parsed.hostname,
            _effective_url_port(parsed),
        )
        configured_origin = (
            COMPATIBILITY_IMAGE_BASE.scheme.casefold(),
            COMPATIBILITY_IMAGE_BASE.hostname,
            _effective_url_port(COMPATIBILITY_IMAGE_BASE),
        )
    except ValueError as error:
        raise LoadProfileError("compatibility image URL is invalid") from error
    if (
        actual_origin != configured_origin
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != expected_path
    ):
        raise LoadProfileError("compatibility image URL escaped the test namespace")
    return parsed.path


def _assert_color_detail(wire: WireResponse, expected_product_id: int) -> dict[str, Any]:
    data = _require_success_envelope(wire)
    if data.get("id") != expected_product_id:
        raise LoadProfileError("color product identity changed")
    colors = data.get("colors")
    if not isinstance(colors, list) or len(colors) != 221:
        raise LoadProfileError("largest color detail no longer contains 221 colors")
    seen_ids: set[int] = set()
    for color, expected in zip(colors, FROZEN_MANIFEST):
        if not isinstance(color, dict):
            raise LoadProfileError("color option is not an object")
        value = color.get("swatch_hex")
        if not isinstance(value, str) or HEX_PATTERN.fullmatch(value) is None:
            raise LoadProfileError("color option HEX is not canonical")
        color_id = color.get("id")
        if (
            not isinstance(color_id, int)
            or color_id in seen_ids
            or not color.get("available")
        ):
            raise LoadProfileError("color option identity or availability changed")
        seen_ids.add(color_id)
        if (
            color.get("slot_no") != expected.slot_no
            or color.get("color_code") != expected.color_code
            or color.get("name") != expected.name
            or value != expected.hex
        ):
            raise LoadProfileError("color option differs from the frozen manifest")
        try:
            _validated_compatibility_image_path(
                color.get("swatch_image_url"),
                expected_path=_compatibility_image_path(expected.image_filename),
            )
        except LoadProfileError as error:
            raise LoadProfileError(
                "color option differs from the frozen manifest"
            ) from error
    return data


async def _plain_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
    json_body: object | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    try:
        response = await client.request(
            method,
            path,
            headers=dict(headers or {}),
            json=json_body,
        )
    except httpx.HTTPError as error:
        raise LoadProfileError("setup HTTP request failed") from error
    if response.status_code != expected_status:
        raise LoadProfileError("setup request returned an unexpected status")
    try:
        document = response.json()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LoadProfileError("setup response is not JSON") from error
    if not isinstance(document, dict) or document.get("code") != 0:
        raise LoadProfileError("setup response envelope is invalid")
    data = document.get("data")
    if not isinstance(data, dict):
        raise LoadProfileError("setup response data is invalid")
    return data


async def discover_dataset(
    client: httpx.AsyncClient,
    *,
    password: str,
) -> FrozenDataset:
    """Discover deterministic IDs and obtain short-lived persona tokens once."""

    if len(password) < 20:
        raise LoadProfileError("persona password is too short")

    async def login(username: str) -> Persona:
        data = await _plain_json(
            client,
            "POST",
            "/api/v1/auth/login",
            json_body={"username": username, "password": password},
        )
        token = data.get("access_token")
        user = data.get("user")
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(user, dict)
            or not isinstance(user.get("id"), int)
            or user.get("username") != username
        ):
            raise LoadProfileError("persona login response is invalid")
        return Persona(username=username, user_id=user["id"], access_token=token)

    # Sequential login stays below the intentionally configured local auth limiter;
    # tokens never enter a report or command line.
    admin = await login("perf_admin")
    customers = tuple(
        [await login(f"perf_user_{number:02d}") for number in range(1, 11)]
    )
    listing = await _plain_json(
        client,
        "GET",
        "/api/v1/products?page=1&page_size=100&product_type=kit",
    )
    items = listing.get("items")
    if not isinstance(items, list) or len(items) != 10:
        raise LoadProfileError("synthetic product listing changed")
    by_name = {
        item.get("name"): item
        for item in items
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    try:
        color_id = int(by_name["Performance 221 Color Kit"]["id"])
        small_id = int(by_name["Performance 3 Color Kit"]["id"])
        fixed_ids = tuple(
            int(by_name[f"Performance Fixed Kit {number:02d}"]["id"])
            for number in range(1, 9)
        )
    except (KeyError, TypeError, ValueError) as error:
        raise LoadProfileError("synthetic product identities are incomplete") from error

    detail = await _plain_json(client, "GET", f"/api/v1/products/kit/{color_id}")
    colors = detail.get("colors")
    if not isinstance(colors, list):
        raise LoadProfileError("color detail is missing colors")
    wire = WireResponse(200, {}, b"", json.dumps({"code": 0, "data": detail}).encode())
    _assert_color_detail(wire, color_id)

    expected_images = {
        _compatibility_image_path(color.image_filename): build_swatch_png(color.rgb)
        for color in FROZEN_MANIFEST
    }
    response_paths: list[str] = []
    for color, expected in zip(colors, FROZEN_MANIFEST):
        path = _validated_compatibility_image_path(
            color.get("swatch_image_url"),
            expected_path=_compatibility_image_path(expected.image_filename),
        )
        if path not in expected_images:
            raise LoadProfileError(
                "compatibility image URL escaped the test namespace"
            )
        response_paths.append(path)
    if set(response_paths) != set(expected_images):
        raise LoadProfileError("compatibility image set differs from the manifest")
    images = tuple(
        ImageFixture(
            path=path,
            sha256=hashlib.sha256(expected_images[path]).hexdigest(),
            size=len(expected_images[path]),
        )
        for path in response_paths
    )
    first_color_id = colors[0].get("id")
    if not isinstance(first_color_id, int):
        raise LoadProfileError("color option ID is unavailable")
    return FrozenDataset(
        color_product_id=color_id,
        small_color_product_id=small_id,
        fixed_product_ids=fixed_ids,
        color_kit_color_id=first_color_id,
        color_count=len(colors),
        images=images,
        admin=admin,
        customers=customers,
    )


AssertResponse = Callable[[WireResponse], None]


async def _record(
    client: httpx.AsyncClient,
    samples: SampleCollector,
    *,
    profile: str,
    round_number: int,
    vus: int,
    spec: RequestSpec,
    assertion: AssertResponse,
) -> WireResponse:
    """Append transport and assertion failures before aborting the profile."""

    try:
        sample, wire = await measured_request(
            client,
            profile=profile,
            round_number=round_number,
            vus=vus,
            spec=spec,
        )
        assertion(wire)
    except MeasuredRequestFailure as error:
        samples.append(error.sample)
        raise
    except (LoadProfileError, asyncio.CancelledError) as error:
        # measured_request already creates a failure sample only internally.  When
        # the transport succeeded but the business assertion fails, persist an
        # explicit zero-sensitive assertion sample.
        if "sample" in locals():
            sample.ok = False
            sample.error_type = type(error).__name__
            samples.append(sample)
        raise
    samples.append(sample)
    return wire


async def _run_workers(
    *,
    profile: str,
    round_number: int,
    vus: int,
    duration_seconds: float,
    activation_ramp_seconds: float,
    worker: Callable[[int, float], Awaitable[int]],
) -> tuple[float, int]:
    if (
        not math.isfinite(duration_seconds)
        or not math.isfinite(activation_ramp_seconds)
        or duration_seconds <= 0
        or activation_ramp_seconds < 0
        or activation_ramp_seconds > duration_seconds
    ):
        raise ValueError("worker duration or activation ramp is invalid")
    started = time.perf_counter()
    deadline = started + duration_seconds

    async def activate(index: int) -> int:
        if activation_ramp_seconds:
            await asyncio.sleep(index * activation_ramp_seconds / vus)
        return await worker(index, deadline)

    tasks = [asyncio.create_task(activate(index)) for index in range(vus)]
    try:
        completed = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return time.perf_counter() - started, sum(completed)


def _header_contains_token(value: str, expected_token: str) -> bool:
    """Match one comma-delimited HTTP field token, case-insensitively."""

    expected = expected_token.casefold()
    return any(
        token.strip().casefold() == expected
        for token in value.split(",")
    )


def _assert_color_profile_response(
    wire: WireResponse,
    *,
    expected_product_id: int,
    expected_encoding: str,
) -> None:
    _assert_color_detail(wire, expected_product_id)
    actual_encoding = (
        wire.headers.get("content-encoding", "").strip().casefold()
        or "identity"
    )
    if actual_encoding != expected_encoding:
        raise LoadProfileError("response content encoding differs from profile")
    if not _header_contains_token(
        wire.headers.get("vary", ""),
        "accept-encoding",
    ):
        raise LoadProfileError(
            "color response is missing Vary: Accept-Encoding"
        )


async def run_color_profile(
    client: httpx.AsyncClient,
    dataset: FrozenDataset,
    *,
    encoding: str,
    round_number: int,
    vus: int,
    duration_seconds: float,
    activation_ramp_seconds: float = 0,
) -> ProfileResult:
    """A: continuously request the largest 221-color response."""

    if encoding not in ("identity", "gzip"):
        raise ValueError("color profile encoding must be identity or gzip")
    profile = f"A-color-{encoding}"
    samples = SampleCollector()

    def assertion(wire: WireResponse) -> None:
        _assert_color_profile_response(
            wire,
            expected_product_id=dataset.color_product_id,
            expected_encoding=encoding,
        )

    async def worker(_: int, deadline: float) -> int:
        while time.perf_counter() < deadline:
            await _record(
                client,
                samples,
                profile=profile,
                round_number=round_number,
                vus=vus,
                spec=RequestSpec(
                    "GET",
                    f"/api/v1/products/kit/{dataset.color_product_id}",
                    "color_detail_221",
                    headers={
                        "Accept-Encoding": encoding,
                        "Cache-Control": "no-cache",
                    },
                ),
                assertion=assertion,
            )
        return 0

    started = time.perf_counter()
    try:
        measured, _ = await _run_workers(
            profile=profile,
            round_number=round_number,
            vus=vus,
            duration_seconds=duration_seconds,
            activation_ramp_seconds=activation_ramp_seconds,
            worker=worker,
        )
    except (LoadProfileError, asyncio.CancelledError) as error:
        raise ProfileExecutionError(
            ProfileResult(
                profile, round_number, vus, duration_seconds,
                time.perf_counter() - started, samples,
                setup={"activation_ramp_seconds": activation_ramp_seconds},
            )
        ) from error
    return ProfileResult(
        profile, round_number, vus, duration_seconds, measured, samples,
        setup={"activation_ramp_seconds": activation_ramp_seconds},
    )


async def run_browse_profile(
    client: httpx.AsyncClient,
    dataset: FrozenDataset,
    *,
    run_seed: int,
    round_number: int,
    vus: int,
    duration_seconds: float,
    think_time_min: float,
    think_time_max: float,
    activation_ramp_seconds: float = 0,
) -> ProfileResult:
    """B: deterministic authenticated browsing with a frozen request mix."""

    if not 0 <= think_time_min <= think_time_max:
        raise ValueError("invalid browse think-time range")
    profile = "B-authenticated-browse"
    samples = SampleCollector()

    def product_list(wire: WireResponse) -> None:
        data = _require_success_envelope(wire)
        items = data.get("items")
        expected_ids = {
            dataset.color_product_id,
            dataset.small_color_product_id,
            *dataset.fixed_product_ids,
        }
        if (
            not isinstance(items, list)
            or len(items) != 10
            or data.get("total") != 10
            or data.get("page") != 1
            or data.get("page_size") != 10
            or data.get("pages") != 1
            or {
                item.get("id")
                for item in items
                if isinstance(item, dict)
            }
            != expected_ids
        ):
            raise LoadProfileError("synthetic product page changed")
        for item in items:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("product_type"), dict)
                or item["product_type"].get("value") != "kit"
                or not isinstance(item.get("cover_image"), str)
                or not isinstance(item.get("display_price"), str)
                or not isinstance(item.get("kit_kind"), dict)
            ):
                raise LoadProfileError("product list item contract changed")

    def fixed_detail(expected_id: int) -> AssertResponse:
        expected_name = (
            f"Performance Fixed Kit "
            f"{dataset.fixed_product_ids.index(expected_id) + 1:02d}"
        )

        def assertion(wire: WireResponse) -> None:
            data = _require_success_envelope(wire)
            if (
                data.get("id") != expected_id
                or data.get("name") != expected_name
                or not isinstance(data.get("product_type"), dict)
                or data["product_type"].get("value") != "kit"
                or not isinstance(data.get("kit_kind"), dict)
                or data["kit_kind"].get("value") != "fixed"
                or data.get("sale_unit_grams") is not None
                or data.get("price") != "0.01"
                or data.get("stock") != 10_000
                or data.get("available") is not True
                or data.get("colors") != []
                or not isinstance(data.get("images"), list)
                or len(data["images"]) != 1
            ):
                raise LoadProfileError("typical fixed Kit detail changed")

        return assertion

    def empty_order_list(wire: WireResponse) -> None:
        data = _require_success_envelope(wire)
        if (
            data.get("items") != []
            or data.get("total") != 0
            or data.get("page") != 1
            or data.get("page_size") != 10
            or data.get("pages") != 0
        ):
            raise LoadProfileError("read fixture order page changed before D")

    def identity(persona: Persona) -> AssertResponse:
        def assertion(wire: WireResponse) -> None:
            data = _require_success_envelope(wire)
            if data.get("id") != persona.user_id:
                raise LoadProfileError("authenticated identity escaped persona")
            if (
                data.get("username") != persona.username
                or data.get("role") != "user"
                or data.get("status") != "normal"
            ):
                raise LoadProfileError("authenticated user fixture changed")
            forbidden = {"password", "access_token", "refresh_token"}
            if forbidden.intersection(data):
                raise LoadProfileError("authenticated response leaked a credential field")
        return assertion

    def wallet(persona: Persona) -> AssertResponse:
        def assertion(wire: WireResponse) -> None:
            data = _require_success_envelope(wire)
            user = data.get("user")
            if not isinstance(user, dict) or user.get("id") != persona.user_id:
                raise LoadProfileError("wallet response escaped persona")
            wallet_data = data.get("wallet")
            if (
                user.get("username") != persona.username
                or not isinstance(wallet_data, dict)
                or wallet_data.get("user_id") != persona.user_id
                or wallet_data.get("balance") != "1000.00"
                or wallet_data.get("status") != "active"
                or wallet_data.get("capabilities")
                != {
                    "topup_enabled": False,
                    "wallet_payment_enabled": True,
                    "refund_enabled": True,
                }
            ):
                raise LoadProfileError("wallet fixture or capability contract changed")
            if "idempotency_key" in json.dumps(data, ensure_ascii=True):
                raise LoadProfileError("wallet response exposed idempotency metadata")
        return assertion

    async def worker(index: int, deadline: float) -> int:
        persona = dataset.customers[index]
        rng = random.Random(run_seed + round_number * 1000 + index)
        headers = {**persona.authorization, "Accept-Encoding": "gzip"}
        coverage_rolls = (5, 25, 45, 55, 65, 75, 85, 95, 15, 35)
        request_number = 0
        while time.perf_counter() < deadline:
            roll = (
                coverage_rolls[request_number]
                if request_number < len(coverage_rolls)
                else rng.randrange(100)
            )
            request_number += 1
            if roll < 20:
                spec = RequestSpec(
                    "GET", "/api/v1/products?page=1&page_size=10", "product_list", headers=headers
                )
                assertion = product_list
            elif roll < 40:
                fixed_id = dataset.fixed_product_ids[rng.randrange(len(dataset.fixed_product_ids))]
                spec = RequestSpec("GET", f"/api/v1/products/kit/{fixed_id}", "typical_kit_detail", headers=headers)
                assertion = fixed_detail(fixed_id)
            elif roll < 70:
                spec = RequestSpec("GET", f"/api/v1/products/kit/{dataset.color_product_id}", "color_detail_221", headers=headers)
                assertion = lambda wire: _assert_color_detail(wire, dataset.color_product_id)
            elif roll < 80:
                spec = RequestSpec("GET", "/api/v1/orders?page=1&page_size=10", "order_list", headers=headers)
                assertion = empty_order_list
            elif roll < 90:
                spec = RequestSpec("GET", "/api/v1/wallet", "wallet_summary", headers=headers)
                assertion = wallet(persona)
            else:
                spec = RequestSpec("GET", "/api/v1/users/me", "user_me", headers=headers)
                assertion = identity(persona)
            await _record(
                client,
                samples,
                profile=profile,
                round_number=round_number,
                vus=vus,
                spec=spec,
                assertion=assertion,
            )
            remaining = deadline - time.perf_counter()
            if remaining > 0:
                await asyncio.sleep(min(remaining, rng.uniform(think_time_min, think_time_max)))
        return 0

    setup = {
        "model": "closed-loop",
        "request_weights_percent": {
            "product_list": 20,
            "typical_kit_detail": 20,
            "color_detail_221": 30,
            "order_list": 10,
            "wallet_summary": 10,
            "user_me": 10,
        },
        "think_time_seconds": [think_time_min, think_time_max],
        "cart_behavior": "client-local; no server API exists",
        "activation_ramp_seconds": activation_ramp_seconds,
    }
    started = time.perf_counter()
    try:
        measured, _ = await _run_workers(
            profile=profile,
            round_number=round_number,
            vus=vus,
            duration_seconds=duration_seconds,
            activation_ramp_seconds=activation_ramp_seconds,
            worker=worker,
        )
    except (LoadProfileError, asyncio.CancelledError) as error:
        raise ProfileExecutionError(
            ProfileResult(
                profile, round_number, vus, duration_seconds,
                time.perf_counter() - started, samples, setup=setup,
            )
        ) from error
    return ProfileResult(
        profile,
        round_number,
        vus,
        duration_seconds,
        measured,
        samples,
        setup=setup,
    )


async def prime_image_validators(
    client: httpx.AsyncClient,
    images: Sequence[ImageFixture],
) -> dict[str, dict[str, str]]:
    validators: dict[str, dict[str, str]] = {}
    for image in images:
        response = await client.get(
            image.path,
            headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"},
        )
        content_type = response.headers.get("content-type", "").lower()
        if (
            response.status_code != 200
            or not content_type.startswith("image/png")
            or len(response.content) != image.size
            or hashlib.sha256(response.content).hexdigest() != image.sha256
        ):
            raise LoadProfileError("image cache prime failed")
        headers: dict[str, str] = {}
        if response.headers.get("etag"):
            headers["If-None-Match"] = response.headers["etag"]
        if response.headers.get("last-modified"):
            headers["If-Modified-Since"] = response.headers["last-modified"]
        if not headers:
            raise LoadProfileError("image response has no revalidation metadata")
        validators[image.path] = headers
    return validators


async def _run_palette_page_load(
    client: httpx.AsyncClient,
    samples: SampleCollector,
    *,
    profile: str,
    images: Sequence[ImageFixture],
    cache_state: str,
    validators: Mapping[str, Mapping[str, str]],
    round_number: int,
    vus: int,
    user_index: int,
    palette_load_number: int,
    deadline: float,
) -> tuple[int, ...] | None:
    """Load every frozen image exactly once, or return ``None`` at the deadline."""

    next_image_index = 0
    successful_visits = [0] * len(images)
    cold_cache_scope = secrets.token_hex(16)

    async def connection() -> None:
        nonlocal next_image_index
        while next_image_index < len(images):
            image_index = next_image_index
            next_image_index += 1
            image = images[image_index]
            headers = {"Accept-Encoding": "identity"}
            path = image.path
            if cache_state == "cold":
                headers["Cache-Control"] = "no-cache"
                path = (
                    f"{path}?performance_cold={cold_cache_scope}-{round_number}-"
                    f"{vus}-{user_index}-{palette_load_number}-{image_index}"
                )
                statuses = (200,)
            else:
                headers.update(validators[image.path])
                statuses = (304,)

            def assertion(
                wire: WireResponse,
                fixture: ImageFixture = image,
            ) -> None:
                if cache_state == "warm":
                    if wire.raw_body or wire.decoded_body:
                        raise LoadProfileError(
                            "revalidated PNG unexpectedly returned a body"
                        )
                    return
                content_type = wire.headers.get("content-type", "").lower()
                if not content_type.startswith("image/png"):
                    raise LoadProfileError(
                        "compatibility image content type changed"
                    )
                if (
                    len(wire.raw_body) != fixture.size
                    or hashlib.sha256(wire.raw_body).hexdigest()
                    != fixture.sha256
                ):
                    raise LoadProfileError("compatibility PNG content changed")

            await _record(
                client,
                samples,
                profile=profile,
                round_number=round_number,
                vus=vus,
                spec=RequestSpec(
                    "GET",
                    path,
                    "compatibility_png",
                    statuses,
                    headers,
                ),
                assertion=assertion,
            )
            successful_visits[image_index] += 1

    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        return None
    tasks = [
        asyncio.create_task(connection())
        for _ in range(min(IMAGE_CONNECTIONS_PER_USER, len(images)))
    ]
    group = asyncio.gather(*tasks)
    try:
        done, _ = await asyncio.wait((group,), timeout=remaining)
        if not done:
            return None
        await group
    finally:
        if not group.done():
            group.cancel()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # ``group`` owns its own terminal exception state in addition to the
        # child Tasks.  Retrieving only the child outcomes leaves a cancelled
        # _GatheringFuture to be reported later by the event loop.
        await asyncio.gather(group, return_exceptions=True)

    if any(visits != 1 for visits in successful_visits):
        raise LoadProfileError(
            "palette page load did not cover every image exactly once"
        )
    return tuple(successful_visits)


async def _run_palette_user_schedule(
    *,
    start_deadline: float,
    completion_deadline: float,
    execute_palette_load: Callable[[int, float], Awaitable[bool]],
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    """Run non-overlapping loads on a fixed per-VU six-second time line."""

    if (
        not math.isfinite(start_deadline)
        or not math.isfinite(completion_deadline)
        or start_deadline > completion_deadline
    ):
        raise ValueError("palette start/completion deadlines are invalid")
    next_scheduled_start = clock()
    palette_load_number = 0
    completed = 0
    while next_scheduled_start < start_deadline:
        delay = next_scheduled_start - clock()
        if delay > 0:
            await sleep(delay)
        if clock() >= start_deadline:
            break
        actual_start = clock()
        palette_load_number += 1
        if not await execute_palette_load(
            palette_load_number,
            completion_deadline,
        ):
            return completed
        completed += 1
        next_scheduled_start = actual_start + IMAGE_JOURNEY_PERIOD_SECONDS
    remaining = completion_deadline - clock()
    if remaining > 0:
        await sleep(remaining)
    return completed


async def run_image_profile(
    client: httpx.AsyncClient,
    dataset: FrozenDataset,
    *,
    cache_state: str,
    round_number: int,
    vus: int,
    duration_seconds: float,
    validators: Mapping[str, Mapping[str, str]] | None = None,
    activation_ramp_seconds: float = 0,
    completion_drain_seconds: float = 0,
) -> ProfileResult:
    """C: load one complete 221-PNG palette per VU on a fixed cadence."""

    if cache_state not in ("cold", "warm"):
        raise ValueError("image cache state must be cold or warm")
    if (
        not math.isfinite(duration_seconds)
        or not math.isfinite(completion_drain_seconds)
        or completion_drain_seconds < 0
        or completion_drain_seconds >= duration_seconds
    ):
        raise ValueError("image completion drain must be within profile duration")
    palette_start_window_seconds = duration_seconds - completion_drain_seconds
    if (
        not math.isfinite(activation_ramp_seconds)
        or activation_ramp_seconds < 0
        or activation_ramp_seconds > palette_start_window_seconds
    ):
        raise ValueError("image activation ramp must fit the palette start window")
    profile = f"C-png-{cache_state}"
    samples = SampleCollector()
    expected_image_count = len(FROZEN_MANIFEST)
    if (
        dataset.color_count != expected_image_count
        or len(dataset.images) != expected_image_count
        or len({image.path for image in dataset.images}) != expected_image_count
    ):
        raise LoadProfileError(
            "image profile requires the exact frozen 221-image palette"
        )
    if cache_state == "warm" and validators is None:
        validators = await prime_image_validators(client, dataset.images)
    validators = validators or {}
    if cache_state == "warm":
        expected_paths = {image.path for image in dataset.images}
        if set(validators) != expected_paths or any(
            not validator
            or not {"If-None-Match", "If-Modified-Since"}.intersection(
                validator
            )
            for validator in validators.values()
        ):
            raise LoadProfileError(
                "warm image validators do not cover the frozen palette"
            )

    completed_palette_loads_by_vu = [0] * vus
    completed_palette_loads_during_drain_by_vu = [0] * vus
    started_palette_loads_by_vu = [0] * vus
    completed_visits_per_image = [0] * len(dataset.images)

    async def user_worker(user_index: int, deadline: float) -> int:
        start_deadline = deadline - completion_drain_seconds

        async def execute_palette_load(
            palette_load_number: int,
            phase_deadline: float,
        ) -> bool:
            started_palette_loads_by_vu[user_index] += 1
            visits = await _run_palette_page_load(
                client,
                samples,
                profile=profile,
                images=dataset.images,
                cache_state=cache_state,
                validators=validators,
                round_number=round_number,
                vus=vus,
                user_index=user_index,
                palette_load_number=palette_load_number,
                deadline=phase_deadline,
            )
            if visits is None:
                raise LoadProfileError(
                    "palette page load did not complete before profile deadline"
                )
            completed_palette_loads_by_vu[user_index] += 1
            if time.perf_counter() > start_deadline:
                completed_palette_loads_during_drain_by_vu[user_index] += 1
            for image_index, count in enumerate(visits):
                completed_visits_per_image[image_index] += count
            return True

        await _run_palette_user_schedule(
            start_deadline=start_deadline,
            completion_deadline=deadline,
            execute_palette_load=execute_palette_load,
        )
        return 0

    def build_setup() -> dict[str, object]:
        completed = sum(completed_palette_loads_by_vu)
        incomplete_by_vu = [
            started - finished
            for started, finished in zip(
                started_palette_loads_by_vu,
                completed_palette_loads_by_vu,
            )
        ]
        requests_in_completed_loads = completed * len(dataset.images)
        completed_visit_min = min(completed_visits_per_image)
        completed_visit_max = max(completed_visits_per_image)
        return {
            "model_version": IMAGE_PROFILE_MODEL_VERSION,
            "model": IMAGE_PROFILE_MODEL,
            "cache_state": cache_state,
            "palette_load_period_seconds_per_vu": (
                IMAGE_JOURNEY_PERIOD_SECONDS
            ),
            "period_anchor": "each VU activation",
            "overrun_semantics": (
                "loads never overlap within a VU and consecutive starts are "
                "always at least one fixed period apart"
            ),
            "deadline_semantics": (
                "keep the configured palette-start window, then allow the "
                "configured bounded completion drain; cancel and await any load "
                "still incomplete at the drain deadline, record it, abort the "
                "profile, and exclude it from the completed palette-load count"
            ),
            "completion_drain_seconds": completion_drain_seconds,
            "palette_start_window_seconds": palette_start_window_seconds,
            "total_observation_seconds": duration_seconds,
            "request_rate_denominator": (
                "total observation including completion drain"
            ),
            "maximum_concurrent_image_requests_per_vu": (
                IMAGE_CONNECTIONS_PER_USER
            ),
            "maximum_in_flight_requests": (
                vus * IMAGE_CONNECTIONS_PER_USER
            ),
            "image_count": len(dataset.images),
            "started_palette_loads": sum(started_palette_loads_by_vu),
            "started_palette_loads_by_vu": list(
                started_palette_loads_by_vu
            ),
            "completed_palette_loads": completed,
            "completed_palette_loads_by_vu": list(
                completed_palette_loads_by_vu
            ),
            "completed_palette_loads_during_drain": sum(
                completed_palette_loads_during_drain_by_vu
            ),
            "completed_palette_loads_during_drain_by_vu": list(
                completed_palette_loads_during_drain_by_vu
            ),
            "incomplete_palette_loads": sum(incomplete_by_vu),
            "incomplete_palette_loads_by_vu": incomplete_by_vu,
            "coverage": {
                "manifest_image_count": len(dataset.images),
                "measured_image_requests": len(samples),
                "image_requests_in_completed_palette_loads": (
                    requests_in_completed_loads
                ),
                "image_requests_outside_completed_palette_loads": (
                    len(samples) - requests_in_completed_loads
                ),
                "distinct_manifest_images_in_completed_palette_loads": (
                    sum(count > 0 for count in completed_visits_per_image)
                ),
                "completed_palette_load_visits_per_image_min": (
                    completed_visit_min
                ),
                "completed_palette_load_visits_per_image_max": (
                    completed_visit_max
                ),
                "exactly_once_per_completed_palette_load": (
                    all(count == completed for count in completed_visits_per_image)
                    if completed
                    else None
                ),
            },
            "prime_requests_excluded_from_measurement": cache_state == "warm",
            "warm_semantics": (
                "conditional revalidation; 304 and zero body expected"
                if cache_state == "warm"
                else None
            ),
            "activation_ramp_seconds": activation_ramp_seconds,
        }

    started = time.perf_counter()
    try:
        measured, _ = await _run_workers(
            profile=profile,
            round_number=round_number,
            vus=vus,
            duration_seconds=duration_seconds,
            activation_ramp_seconds=activation_ramp_seconds,
            worker=user_worker,
        )
    except (LoadProfileError, asyncio.CancelledError) as error:
        raise ProfileExecutionError(
            ProfileResult(
                profile, round_number, vus, duration_seconds,
                time.perf_counter() - started, samples, setup=build_setup(),
            )
        ) from error
    return ProfileResult(
        profile,
        round_number,
        vus,
        duration_seconds,
        measured,
        samples,
        completed_journeys=0,
        setup=build_setup(),
    )


def _assert_order(wire: WireResponse, expected_status: str) -> int:
    data = _require_success_envelope(wire)
    order_id = data.get("id")
    status = data.get("status")
    if not isinstance(order_id, int) or not isinstance(status, dict) or status.get("value") != expected_status:
        raise LoadProfileError("order response facts changed")
    return order_id


async def _pace_after_write_journey(
    *,
    journey_started_at: float,
    deadline: float,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Pace from the actual start so a late wake-up cannot trigger catch-up."""

    now = clock()
    remaining = deadline - now
    if remaining <= 0:
        return
    next_start = journey_started_at + WRITE_JOURNEY_PERIOD_SECONDS
    await sleep(min(remaining, max(0.0, next_start - now)))


async def run_write_profile(
    client: httpx.AsyncClient,
    dataset: FrozenDataset,
    *,
    run_id: str,
    round_number: int,
    vus: int,
    duration_seconds: float,
    key_scope: str = "measured",
    activation_ramp_seconds: float = 0,
    on_journey_completed: Callable[[], None] | None = None,
) -> ProfileResult:
    """D: color cancel, wallet payment, assisted order and exact replays."""

    profile = "D-color-order-wallet-write"
    if key_scope not in WRITE_KEY_SCOPES:
        raise ValueError("write key scope is invalid")
    samples = SampleCollector()
    completed_counter = 0

    async def worker(index: int, deadline: float) -> int:
        nonlocal completed_counter
        persona = dataset.customers[index]
        customer_headers = {**persona.authorization, "Accept-Encoding": "gzip"}
        admin_headers = {**dataset.admin.authorization, "Accept-Encoding": "gzip"}
        journeys = 0
        maximum_journeys = math.ceil(
            duration_seconds / WRITE_JOURNEY_PERIOD_SECONDS
        )
        while time.perf_counter() < deadline and journeys < maximum_journeys:
            journey_started_at = time.perf_counter()
            sequence = journeys + 1
            key_prefix = (
                f"perf-{run_id}-{key_scope}-r{round_number}-v{vus}-"
                f"u{index}-j{sequence}"
            )
            body = {
                "items": [
                    {
                        "product_id": dataset.color_product_id,
                        "experience_option_id": None,
                        "kit_color_id": dataset.color_kit_color_id,
                        "quantity": 1,
                    }
                ],
                "remark": "Synthetic isolated performance journey",
            }

            cancel_order = await _record(
                client,
                samples,
                profile=profile,
                round_number=round_number,
                vus=vus,
                spec=RequestSpec("POST", "/api/v1/orders", "create_color_order_for_cancel", (201,), customer_headers, body),
                assertion=lambda wire: _assert_order(wire, "pending"),
            )
            cancel_id = _assert_order(cancel_order, "pending")
            await _record(
                client,
                samples,
                profile=profile,
                round_number=round_number,
                vus=vus,
                spec=RequestSpec("PATCH", f"/api/v1/orders/{cancel_id}/cancel", "cancel_color_order", (200,), customer_headers),
                assertion=lambda wire: _assert_order(wire, "cancelled"),
            )

            paid_order = await _record(
                client,
                samples,
                profile=profile,
                round_number=round_number,
                vus=vus,
                spec=RequestSpec("POST", "/api/v1/orders", "create_color_order_for_wallet", (201,), customer_headers, body),
                assertion=lambda wire: _assert_order(wire, "pending"),
            )
            paid_id = _assert_order(paid_order, "pending")
            payment_headers = {**customer_headers, "Idempotency-Key": f"{key_prefix}-pay"}
            first_payment = await _record(
                client,
                samples,
                profile=profile,
                round_number=round_number,
                vus=vus,
                spec=RequestSpec("POST", f"/api/v1/orders/{paid_id}/payments/wallet", "wallet_payment_first", (201,), payment_headers),
                assertion=lambda wire: _assert_wallet_payment(wire, paid_id),
            )
            first_payment_data = _require_success_envelope(first_payment)

            def assert_payment_replay(wire: WireResponse) -> None:
                _assert_wallet_payment(wire, paid_id)
                if _require_success_envelope(wire) != first_payment_data:
                    raise LoadProfileError(
                        "wallet payment replay changed immutable facts"
                    )

            await _record(
                client,
                samples,
                profile=profile,
                round_number=round_number,
                vus=vus,
                spec=RequestSpec("POST", f"/api/v1/orders/{paid_id}/payments/wallet", "wallet_payment_replay", (200,), payment_headers),
                assertion=assert_payment_replay,
            )

            assisted_headers = {**admin_headers, "Idempotency-Key": f"{key_prefix}-assisted"}
            assisted_path = f"/api/v1/admin/users/{persona.user_id}/wallet-orders"
            first_assisted = await _record(
                client,
                samples,
                profile=profile,
                round_number=round_number,
                vus=vus,
                spec=RequestSpec("POST", assisted_path, "assisted_order_first", (201,), assisted_headers, body),
                assertion=lambda wire: _assert_assisted_order(wire, persona.user_id),
            )
            first_assisted_data = _require_success_envelope(first_assisted)

            def assert_assisted_replay(wire: WireResponse) -> None:
                _assert_assisted_order(wire, persona.user_id)
                if _require_success_envelope(wire) != first_assisted_data:
                    raise LoadProfileError(
                        "assisted order replay changed immutable facts"
                    )

            await _record(
                client,
                samples,
                profile=profile,
                round_number=round_number,
                vus=vus,
                spec=RequestSpec("POST", assisted_path, "assisted_order_replay", (200,), assisted_headers, body),
                assertion=assert_assisted_replay,
            )
            journeys += 1
            completed_counter += 1
            if on_journey_completed is not None:
                on_journey_completed()
            await _pace_after_write_journey(
                journey_started_at=journey_started_at,
                deadline=deadline,
            )
        return journeys

    setup = {
        "mysql": "8.0.46",
        "payment_provider": "disabled",
        "real_external_side_effects": False,
        "requests_per_completed_journey": 7,
        "expected_new_orders_per_journey": 3,
        "expected_audit_actions_per_journey": {
            "CREATE_ORDER": 3,
            "CANCEL_ORDER": 1,
            "PAY_ORDER": 2,
        },
        "idempotency_key_scope": key_scope,
        "activation_ramp_seconds": activation_ramp_seconds,
        "journey_period_seconds_per_vu": WRITE_JOURNEY_PERIOD_SECONDS,
        "overrun_semantics": (
            "consecutive journey starts are paced from each actual start; "
            "missed slots are never replayed"
        ),
        "maximum_journeys_per_vu": math.ceil(
            duration_seconds / WRITE_JOURNEY_PERIOD_SECONDS
        ),
        "bounded_for_final_reconciliation": True,
    }
    started = time.perf_counter()
    try:
        measured, journeys = await _run_workers(
            profile=profile,
            round_number=round_number,
            vus=vus,
            duration_seconds=duration_seconds,
            activation_ramp_seconds=activation_ramp_seconds,
            worker=worker,
        )
    except (LoadProfileError, asyncio.CancelledError) as error:
        raise ProfileExecutionError(
            ProfileResult(
                profile, round_number, vus, duration_seconds,
                time.perf_counter() - started, samples,
                completed_journeys=completed_counter, setup=setup,
            )
        ) from error
    return ProfileResult(
        profile,
        round_number,
        vus,
        duration_seconds,
        measured,
        samples,
        completed_journeys=journeys,
        setup=setup,
    )


def _assert_wallet_payment(wire: WireResponse, order_id: int) -> None:
    data = _require_success_envelope(wire)
    status = data.get("order_status")
    payment = data.get("payment")
    if (
        data.get("order_id") != order_id
        or not isinstance(status, dict)
        or status.get("value") != "paid"
        or not isinstance(payment, dict)
        or payment.get("order_id") != order_id
        or payment.get("method") != "wallet"
        or payment.get("status") != "succeeded"
    ):
        raise LoadProfileError("wallet payment facts changed")


def _assert_assisted_order(wire: WireResponse, user_id: int) -> None:
    data = _require_success_envelope(wire)
    order = data.get("order")
    payment = data.get("payment")
    if (
        not isinstance(order, dict)
        or order.get("user_id") != user_id
        or not isinstance(order.get("status"), dict)
        or order["status"].get("value") != "paid"
        or not isinstance(payment, dict)
        or payment.get("order_id") != order.get("id")
        or payment.get("method") != "wallet"
        or payment.get("status") != "succeeded"
    ):
        raise LoadProfileError("assisted order facts changed")


def build_client(base_url: str, *, max_connections: int = 64) -> httpx.AsyncClient:
    """Create a bounded keep-alive client outside the shaped service envelope."""

    return httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_connections,
            keepalive_expiry=30,
        ),
        follow_redirects=False,
        trust_env=False,
    )
