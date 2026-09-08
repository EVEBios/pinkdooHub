"""压测 HTTP 计量、颜色契约和 D 幂等旅程单元测试。"""

import asyncio
from collections import Counter
import gc
import gzip
import hashlib
import json
import time

import httpx
import pytest

from scripts.performance import load


def _wire(
    document: object,
    *,
    encoding: str = "identity",
    headers: dict[str, str] | None = None,
) -> load.WireResponse:
    decoded = json.dumps(document).encode("utf-8")
    raw = gzip.compress(decoded) if encoding == "gzip" else decoded
    return load.WireResponse(
        status_code=200,
        headers={"content-encoding": encoding, **(headers or {})},
        raw_body=raw,
        decoded_body=decoded,
    )


def _stream_response(
    status: int,
    *,
    body: bytes | None = None,
    document: object | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    if document is not None:
        body = json.dumps(document).encode("utf-8")
        headers = {"Content-Type": "application/json", **(headers or {})}
    return httpx.Response(
        status,
        headers=headers,
        stream=httpx.ByteStream(body or b""),
    )


def _sample(operation: str, latency: float, *, ok: bool = True) -> load.RequestSample:
    return load.RequestSample(
        schema_version=1,
        profile="unit",
        operation=operation,
        round_number=1,
        vus=5,
        status_code=200,
        ok=ok,
        error_type=None if ok else "LoadProfileError",
        latency_ms=latency,
        ttfb_ms=latency / 2,
        download_ms=latency / 2,
        wire_body_bytes=100,
        decoded_body_bytes=400,
        content_encoding="gzip",
        completed_at_utc="2026-09-09T00:00:00+00:00",
    )


def _image_dataset() -> tuple[load.FrozenDataset, dict[str, bytes]]:
    bodies = {
        f"/uploads/products/performance-{index:03d}.png": (
            b"\x89PNG\r\n\x1a\n" + index.to_bytes(2, "big")
        )
        for index in range(221)
    }
    images = tuple(
        load.ImageFixture(
            path=path,
            sha256=hashlib.sha256(body).hexdigest(),
            size=len(body),
        )
        for path, body in bodies.items()
    )
    persona = load.Persona("perf_user_01", 7, "customer-token")
    return (
        load.FrozenDataset(
            color_product_id=12,
            small_color_product_id=13,
            fixed_product_ids=(1,),
            color_kit_color_id=22,
            color_count=221,
            images=images,
            admin=load.Persona("perf_admin", 1, "admin-token"),
            customers=(persona,),
        ),
        bodies,
    )


def _color_document(
    *,
    product_id: int = 99,
    image_base_url: str = load.COMPATIBILITY_IMAGE_BASE_URL,
) -> dict[str, object]:
    colors = [
        {
            "id": index,
            "slot_no": item.slot_no,
            "color_code": item.color_code,
            "name": item.name,
            "swatch_hex": item.hex,
            "swatch_image_url": (
                f"{image_base_url.rstrip('/')}/{item.image_filename}"
            ),
            "available": True,
        }
        for index, item in enumerate(load.FROZEN_MANIFEST, start=1)
    ]
    return {"code": 0, "data": {"id": product_id, "colors": colors}}


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ("identity", "gzip"))
async def test_measured_request_counts_actual_wire_bytes(encoding: str) -> None:
    decoded = b'{"code":0,"data":{"ok":true}}'
    body = gzip.compress(decoded) if encoding == "gzip" else decoded

    def handler(_: httpx.Request) -> httpx.Response:
        headers = {"Content-Encoding": encoding} if encoding == "gzip" else {}
        return _stream_response(200, headers=headers, body=body)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        sample, response = await load.measured_request(
            client,
            profile="unit",
            round_number=1,
            vus=1,
            spec=load.RequestSpec("GET", "/value", "value"),
        )

    assert sample.ok is True
    assert sample.wire_body_bytes == len(body)
    assert sample.decoded_body_bytes == len(decoded)
    assert response.raw_body == body
    assert response.decoded_body == decoded


@pytest.mark.asyncio
async def test_transport_or_status_failure_carries_a_sanitized_sample() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: _stream_response(503, body=b"no")
        ),
        base_url="http://test",
    ) as client:
        with pytest.raises(load.MeasuredRequestFailure) as captured:
            await load.measured_request(
                client,
                profile="unit",
                round_number=1,
                vus=1,
                spec=load.RequestSpec("GET", "/value", "value"),
            )

    assert captured.value.sample.status_code == 503
    assert captured.value.sample.ok is False
    assert captured.value.sample.error_type == "LoadProfileError"
    assert captured.value.sample.wire_body_bytes == 2


def test_frozen_221_color_manifest_is_checked_field_by_field() -> None:
    document = _color_document()
    colors = document["data"]["colors"]

    assert load._assert_color_detail(_wire(document), 99)["id"] == 99
    colors[17]["swatch_hex"] = "#000000"
    with pytest.raises(load.LoadProfileError, match="frozen manifest"):
        load._assert_color_detail(_wire(document), 99)


@pytest.mark.parametrize(
    "image_base_url",
    (
        "http://pinkdoohub-performance.invalid/uploads/products",
        "https://other.invalid/uploads/products",
        "https://pinkdoohub-performance.invalid:444/uploads/products",
        "https://pinkdoohub-performance.invalid:not-a-port/uploads/products",
        "https://user@pinkdoohub-performance.invalid/uploads/products",
    ),
)
def test_color_discovery_rejects_an_image_url_outside_configured_origin(
    image_base_url: str,
) -> None:
    document = _color_document(image_base_url=image_base_url)

    with pytest.raises(load.LoadProfileError, match="frozen manifest"):
        load._assert_color_detail(_wire(document), 99)


def test_color_discovery_accepts_explicit_default_port_before_path_mapping() -> None:
    item = load.FROZEN_MANIFEST[0]
    expected_path = load._compatibility_image_path(item.image_filename)
    url = (
        "https://pinkdoohub-performance.invalid:443/uploads/products/"
        f"{item.image_filename}"
    )

    assert load._validated_compatibility_image_path(
        url,
        expected_path=expected_path,
    ) == expected_path


@pytest.mark.parametrize("encoding", ("identity", "gzip"))
def test_color_profile_vary_uses_exact_case_insensitive_tokens(
    encoding: str,
) -> None:
    document = _color_document()
    load._assert_color_profile_response(
        _wire(
            document,
            encoding=encoding,
            headers={"vary": "Origin, aCcEpT-EnCoDiNg"},
        ),
        expected_product_id=99,
        expected_encoding=encoding,
    )

    for invalid_vary in ("", "X-Accept-Encoding", "Accept-Encoding-Extra"):
        with pytest.raises(load.LoadProfileError, match="Vary"):
            load._assert_color_profile_response(
                _wire(
                    document,
                    encoding=encoding,
                    headers={"vary": invalid_vary},
                ),
                expected_product_id=99,
                expected_encoding=encoding,
            )


def test_profile_summary_keeps_operation_percentiles_and_body_sizes() -> None:
    result = load.ProfileResult(
        "unit", 1, 5, 60, 60,
        [_sample("one", value) for value in (10, 20, 30, 40)]
        + [_sample("two", 50, ok=False)],
    ).summary()

    assert result["successful_requests"] == 4
    assert result["failed_requests"] == 1
    assert result["wire_body_bytes"] == 400
    assert result["decoded_body_bytes"] == 1600
    assert set(result["operations"]) == {"one", "two"}
    assert result["operations"]["one"]["latency_ms"]["p95"] is not None
    assert result["operations"]["one"]["content_encodings"] == {"gzip": 4}
    assert result["operations"]["two"]["errors"] == {"LoadProfileError": 1}


def test_online_collector_has_exact_counts_and_hard_capped_raw_evidence() -> None:
    collector = load.SampleCollector()
    total = load.MAX_SUCCESS_EVIDENCE_SAMPLES + 500
    for index in range(total):
        collector.append(_sample("one", 10.01 + index % 3))
    collector.append(_sample("one", 999, ok=False))

    summary = collector.summary()
    records = list(collector.evidence_records())

    assert len(collector) == total + 1
    assert summary["successful_requests"] == total
    assert summary["failed_requests"] == 1
    assert summary["latency_ms"]["p95"] == 13
    assert len(records) == load.MAX_SUCCESS_EVIDENCE_SAMPLES + 1
    assert sum(record["evidence_selection"] == "failure" for record in records) == 1
    assert summary["raw_sample_evidence"]["aggregate_counters"] == "complete"


@pytest.mark.asyncio
async def test_write_journey_scopes_keys_by_phase_round_vus_user_and_replays() -> None:
    seen_keys: list[str] = []
    seen: set[str] = set()
    next_order = 1
    completion_callbacks = 0

    def record_completion() -> None:
        nonlocal completion_callbacks
        completion_callbacks += 1

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal next_order
        await asyncio.sleep(0.01)
        key = request.headers.get("Idempotency-Key")
        if key:
            seen_keys.append(key)
        if request.url.path == "/api/v1/orders" and request.method == "POST":
            order_id = next_order
            next_order += 1
            data = {"id": order_id, "status": {"value": "pending"}}
            return _stream_response(201, document={"code": 0, "data": data})
        if request.url.path.endswith("/cancel"):
            order_id = int(request.url.path.split("/")[-2])
            data = {"id": order_id, "status": {"value": "cancelled"}}
            return _stream_response(200, document={"code": 0, "data": data})
        if request.url.path.endswith("/payments/wallet"):
            order_id = int(request.url.path.split("/")[-3])
            status = 200 if key in seen else 201
            seen.add(key or "")
            data = {
                "order_id": order_id,
                "order_status": {"value": "paid"},
                "payment": {
                    "order_id": order_id,
                    "method": "wallet",
                    "status": "succeeded",
                },
            }
            return _stream_response(status, document={"code": 0, "data": data})
        if request.url.path.endswith("/wallet-orders"):
            status = 200 if key in seen else 201
            seen.add(key or "")
            order_id = next_order
            if status == 201:
                next_order += 1
            else:
                order_id -= 1
            user_id = int(request.url.path.split("/")[-2])
            data = {
                "order": {
                    "id": order_id,
                    "user_id": user_id,
                    "status": {"value": "paid"},
                },
                "payment": {
                    "order_id": order_id,
                    "method": "wallet",
                    "status": "succeeded",
                },
            }
            return _stream_response(status, document={"code": 0, "data": data})
        raise AssertionError(request.url.path)

    persona = load.Persona("user", 7, "customer-token")
    dataset = load.FrozenDataset(
        color_product_id=12,
        small_color_product_id=13,
        fixed_product_ids=(1,),
        color_kit_color_id=22,
        color_count=221,
        images=(),
        admin=load.Persona("admin", 1, "admin-token"),
        customers=(persona,),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        result = await load.run_write_profile(
            client,
            dataset,
            run_id="20260909t120000",
            round_number=2,
            vus=1,
            duration_seconds=0.05,
            key_scope="warmup",
            on_journey_completed=record_completion,
        )

    assert result.completed_journeys == 1
    assert completion_callbacks == 1
    assert len(result.samples) == 7
    assert len(seen_keys) == 4
    assert seen_keys[0] == seen_keys[1]
    assert seen_keys[2] == seen_keys[3]
    assert all(
        "-warmup-r2-v1-u0-j1-" in key
        for key in seen_keys
    )


@pytest.mark.asyncio
async def test_write_journey_pacing_does_not_catch_up_after_event_loop_delay() -> None:
    now = 100.0
    starts: list[float] = []
    sleep_delays: list[float] = []

    def clock() -> float:
        return now

    async def delayed_sleep(delay: float) -> None:
        nonlocal now
        sleep_delays.append(delay)
        now += delay
        if len(sleep_delays) == 1:
            # The loop resumes four seconds after its requested wake-up.
            now += 4.0

    for _ in range(3):
        starts.append(now)
        now += 1.0
        await load._pace_after_write_journey(
            journey_started_at=starts[-1],
            deadline=200.0,
            clock=clock,
            sleep=delayed_sleep,
        )

    assert starts == [100.0, 110.0, 116.0]
    assert sleep_delays == [5.0, 5.0, 5.0]
    assert all(
        later - earlier >= load.WRITE_JOURNEY_PERIOD_SECONDS
        for earlier, later in zip(starts, starts[1:])
    )


@pytest.mark.asyncio
async def test_worker_ramp_rejects_non_finite_or_longer_than_phase() -> None:
    async def worker(_: int, __: float) -> int:
        return 0

    with pytest.raises(ValueError):
        await load._run_workers(
            profile="unit",
            round_number=1,
            vus=1,
            duration_seconds=1,
            activation_ramp_seconds=float("nan"),
            worker=worker,
        )
    with pytest.raises(ValueError):
        await load._run_workers(
            profile="unit",
            round_number=1,
            vus=1,
            duration_seconds=1,
            activation_ramp_seconds=2,
            worker=worker,
        )


@pytest.mark.asyncio
async def test_cold_palette_load_visits_all_221_once_with_at_most_four_requests() -> None:
    dataset, bodies = _image_dataset()
    visits: list[str] = []
    cache_busters: list[str] = []
    active = 0
    peak_active = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        try:
            visits.append(request.url.path)
            cache_busters.append(request.url.params["performance_cold"])
            assert request.headers["accept-encoding"] == "identity"
            assert request.headers["cache-control"] == "no-cache"
            await asyncio.sleep(0.001)
            return _stream_response(
                200,
                body=bodies[request.url.path],
                headers={"Content-Type": "image/png"},
            )
        finally:
            active -= 1

    collector = load.SampleCollector()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
    ) as client:
        completed_visits = await load._run_palette_page_load(
            client,
            collector,
            profile="C-png-cold",
            images=dataset.images,
            cache_state="cold",
            validators={},
            round_number=2,
            vus=1,
            user_index=0,
            palette_load_number=3,
            deadline=time.perf_counter() + 5,
        )

    assert completed_visits == (1,) * 221
    assert len(collector) == 221
    assert Counter(visits) == Counter({path: 1 for path in bodies})
    assert len(set(cache_busters)) == 221
    assert peak_active == load.IMAGE_CONNECTIONS_PER_USER == 4
    assert active == 0


@pytest.mark.asyncio
async def test_cold_cache_buster_does_not_repeat_across_profile_executions() -> None:
    dataset, bodies = _image_dataset()
    cache_busters: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cache_busters.append(request.url.params["performance_cold"])
        return _stream_response(
            200,
            body=bodies[request.url.path],
            headers={"Content-Type": "image/png"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
    ) as client:
        for _ in range(2):
            visits = await load._run_palette_page_load(
                client,
                load.SampleCollector(),
                profile="C-png-cold",
                images=dataset.images[:1],
                cache_state="cold",
                validators={},
                round_number=1,
                vus=5,
                user_index=0,
                palette_load_number=1,
                deadline=time.perf_counter() + 5,
            )
            assert visits == (1,)

    assert len(cache_busters) == 2
    assert len(set(cache_busters)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "content_type", "body_mode"),
    (
        (304, "image/png", "correct"),
        (200, "application/octet-stream", "correct"),
        (200, "image/png", "wrong-size"),
        (200, "image/png", "wrong-sha"),
    ),
)
async def test_cold_palette_load_fails_closed_on_png_contract_changes(
    status: int,
    content_type: str,
    body_mode: str,
) -> None:
    dataset, bodies = _image_dataset()
    target = dataset.images[0]

    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies[request.url.path]
        if request.url.path == target.path:
            if body_mode == "wrong-size":
                body += b"x"
            elif body_mode == "wrong-sha":
                body = body[:-1] + bytes([body[-1] ^ 1])
            return _stream_response(
                status,
                body=body,
                headers={"Content-Type": content_type},
            )
        return _stream_response(
            200,
            body=body,
            headers={"Content-Type": "image/png"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
    ) as client:
        with pytest.raises(load.LoadProfileError):
            await load._run_palette_page_load(
                client,
                load.SampleCollector(),
                profile="C-png-cold",
                images=dataset.images,
                cache_state="cold",
                validators={},
                round_number=1,
                vus=1,
                user_index=0,
                palette_load_number=1,
                deadline=time.perf_counter() + 5,
            )


@pytest.mark.asyncio
async def test_warm_palette_load_requires_304_with_a_zero_body() -> None:
    dataset, _ = _image_dataset()
    validators = {
        image.path: {"If-None-Match": f'"etag-{index}"'}
        for index, image in enumerate(dataset.images)
    }
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.headers["if-none-match"].startswith('"etag-')
        return _stream_response(304, body=b"")

    collector = load.SampleCollector()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
    ) as client:
        completed_visits = await load._run_palette_page_load(
            client,
            collector,
            profile="C-png-warm",
            images=dataset.images,
            cache_state="warm",
            validators=validators,
            round_number=1,
            vus=1,
            user_index=0,
            palette_load_number=1,
            deadline=time.perf_counter() + 5,
        )

    assert completed_visits == (1,) * 221
    assert Counter(seen) == Counter({image.path: 1 for image in dataset.images})
    assert collector.statistics.statuses == {"304": 221}
    assert collector.statistics.wire_body_bytes == 0
    assert collector.statistics.decoded_body_bytes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "body"), ((200, b""), (304, b"body")))
async def test_warm_palette_load_rejects_non_304_or_nonempty_body(
    status: int,
    body: bytes,
) -> None:
    dataset, _ = _image_dataset()
    validators = {
        image.path: {"If-None-Match": '"etag"'}
        for image in dataset.images
    }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: _stream_response(status, body=body)
        ),
        base_url="http://test",
    ) as client:
        with pytest.raises(load.LoadProfileError):
            await load._run_palette_page_load(
                client,
                load.SampleCollector(),
                profile="C-png-warm",
                images=dataset.images,
                cache_state="warm",
                validators=validators,
                round_number=1,
                vus=1,
                user_index=0,
                palette_load_number=1,
                deadline=time.perf_counter() + 5,
            )


@pytest.mark.asyncio
async def test_palette_schedule_never_starts_more_than_once_per_six_seconds() -> None:
    now = 100.0
    starts: list[float] = []
    sleep_delays: list[float] = []
    execution_times = iter((1.0, 8.0, 0.5, 1.0))

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        sleep_delays.append(delay)
        now += delay

    async def execute(number: int, deadline: float) -> bool:
        nonlocal now
        assert number == len(starts) + 1
        assert deadline == 122.0
        starts.append(now)
        now += next(execution_times)
        return True

    completed = await load._run_palette_user_schedule(
        start_deadline=122.0,
        completion_deadline=122.0,
        execute_palette_load=execute,
        clock=clock,
        sleep=sleep,
    )

    assert completed == 4
    assert starts == [100.0, 106.0, 114.0, 120.0]
    assert sleep_delays == [5.0, 5.5, 1.0]
    assert now == 122.0
    assert all(
        later - earlier >= load.IMAGE_JOURNEY_PERIOD_SECONDS
        for earlier, later in zip(starts, starts[1:])
    )
    assert load.IMAGE_JOURNEY_PERIOD_SECONDS == 6.0


@pytest.mark.asyncio
async def test_palette_schedule_does_not_pad_incomplete_error_or_cancellation() -> None:
    sleep_delays: list[float] = []

    async def sleep(delay: float) -> None:
        sleep_delays.append(delay)

    async def incomplete(_: int, __: float) -> bool:
        return False

    completed = await load._run_palette_user_schedule(
        start_deadline=160.0,
        completion_deadline=160.0,
        execute_palette_load=incomplete,
        clock=lambda: 100.0,
        sleep=sleep,
    )
    assert completed == 0
    assert sleep_delays == []

    class ExpectedFailure(Exception):
        pass

    async def fail(_: int, __: float) -> bool:
        raise ExpectedFailure

    with pytest.raises(ExpectedFailure):
        await load._run_palette_user_schedule(
            start_deadline=160.0,
            completion_deadline=160.0,
            execute_palette_load=fail,
            clock=lambda: 100.0,
            sleep=sleep,
        )
    assert sleep_delays == []

    async def cancel(_: int, __: float) -> bool:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await load._run_palette_user_schedule(
            start_deadline=160.0,
            completion_deadline=160.0,
            execute_palette_load=cancel,
            clock=lambda: 100.0,
            sleep=sleep,
        )
    assert sleep_delays == []


@pytest.mark.asyncio
async def test_palette_schedule_drains_without_starting_after_start_deadline() -> None:
    now = 118.0
    starts: list[float] = []
    sleep_delays: list[float] = []

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        sleep_delays.append(delay)
        now += delay

    async def execute(_: int, completion_deadline: float) -> bool:
        nonlocal now
        assert completion_deadline == 126.0
        starts.append(now)
        now += 4
        return True

    completed = await load._run_palette_user_schedule(
        start_deadline=120.0,
        completion_deadline=126.0,
        execute_palette_load=execute,
        clock=clock,
        sleep=sleep,
    )

    assert completed == 1
    assert starts == [118.0]
    assert sleep_delays == [4.0]
    assert now == 126.0


@pytest.mark.asyncio
async def test_image_profile_normal_path_keeps_full_measured_duration() -> None:
    dataset, bodies = _image_dataset()

    def handler(request: httpx.Request) -> httpx.Response:
        return _stream_response(
            200,
            body=bodies[request.url.path],
            headers={"Content-Type": "image/png"},
        )

    configured_duration = 0.3
    started = time.perf_counter()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
    ) as client:
        result = await load.run_image_profile(
            client,
            dataset,
            cache_state="cold",
            round_number=1,
            vus=1,
            duration_seconds=configured_duration,
        )
    elapsed = time.perf_counter() - started

    assert elapsed >= configured_duration - 0.005
    assert result.measured_duration_seconds >= configured_duration - 0.005
    assert result.setup["completed_palette_loads"] == 1
    assert result.setup["incomplete_palette_loads"] == 0
    assert result.setup["completion_drain_seconds"] == 0
    assert result.setup["palette_start_window_seconds"] == configured_duration
    assert result.setup["total_observation_seconds"] == configured_duration
    assert result.setup["completed_palette_loads_during_drain"] == 0
    assert result.setup["completed_palette_loads_during_drain_by_vu"] == [0]
    assert result.setup["request_rate_denominator"] == (
        "total observation including completion drain"
    )


@pytest.mark.asyncio
async def test_image_profile_records_page_completed_during_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, _ = _image_dataset()

    async def complete_in_drain(*_: object, **__: object) -> tuple[int, ...]:
        await asyncio.sleep(0.07)
        return (1,) * len(dataset.images)

    monkeypatch.setattr(load, "_run_palette_page_load", complete_in_drain)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("no HTTP expected"))
        ),
        base_url="http://test",
    ) as client:
        result = await load.run_image_profile(
            client,
            dataset,
            cache_state="cold",
            round_number=1,
            vus=1,
            duration_seconds=0.12,
            completion_drain_seconds=0.06,
        )

    assert result.setup["palette_start_window_seconds"] == 0.06
    assert result.setup["total_observation_seconds"] == 0.12
    assert result.setup["completed_palette_loads"] == 1
    assert result.setup["completed_palette_loads_during_drain"] == 1
    assert result.setup["completed_palette_loads_during_drain_by_vu"] == [1]
    assert result.setup["incomplete_palette_loads"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("completion_drain", (-1.0, float("nan"), 5.0))
async def test_image_profile_rejects_invalid_completion_drain(
    completion_drain: float,
) -> None:
    dataset, _ = _image_dataset()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("no HTTP expected"))
        ),
        base_url="http://test",
    ) as client:
        with pytest.raises(ValueError, match="completion drain"):
            await load.run_image_profile(
                client,
                dataset,
                cache_state="cold",
                round_number=1,
                vus=1,
                duration_seconds=5,
                completion_drain_seconds=completion_drain,
            )


@pytest.mark.asyncio
async def test_image_profile_accepts_ramp_equal_to_palette_start_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, _ = _image_dataset()

    async def skip_workers(**kwargs: object) -> tuple[float, int]:
        assert kwargs["duration_seconds"] == 10
        assert kwargs["activation_ramp_seconds"] == 4
        return 10.0, 0

    monkeypatch.setattr(load, "_run_workers", skip_workers)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("no HTTP expected"))
        ),
        base_url="http://test",
    ) as client:
        result = await load.run_image_profile(
            client,
            dataset,
            cache_state="cold",
            round_number=1,
            vus=10,
            duration_seconds=10,
            activation_ramp_seconds=4,
            completion_drain_seconds=6,
        )

    assert result.setup["palette_start_window_seconds"] == 4
    assert result.setup["activation_ramp_seconds"] == 4


@pytest.mark.asyncio
async def test_image_profile_rejects_ramp_beyond_palette_start_window() -> None:
    dataset, _ = _image_dataset()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("no HTTP expected"))
        ),
        base_url="http://test",
    ) as client:
        with pytest.raises(ValueError, match="activation ramp"):
            await load.run_image_profile(
                client,
                dataset,
                cache_state="cold",
                round_number=1,
                vus=10,
                duration_seconds=10,
                activation_ramp_seconds=4.001,
                completion_drain_seconds=6,
            )


@pytest.mark.asyncio
async def test_palette_deadline_cancels_and_awaits_all_image_tasks() -> None:
    dataset, _ = _image_dataset()
    active = 0
    all_connections_started = asyncio.Event()
    never_release = asyncio.Event()

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active
        active += 1
        if active == load.IMAGE_CONNECTIONS_PER_USER:
            all_connections_started.set()
        try:
            await never_release.wait()
            raise AssertionError("deadline must cancel the pending request")
        finally:
            active -= 1

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
    ) as client:
        outcome = await load._run_palette_page_load(
            client,
            load.SampleCollector(),
            profile="C-png-cold",
            images=dataset.images,
            cache_state="cold",
            validators={},
            round_number=1,
            vus=1,
            user_index=0,
            palette_load_number=1,
            deadline=time.perf_counter() + 0.05,
        )

    assert all_connections_started.is_set()
    assert outcome is None
    assert active == 0


@pytest.mark.asyncio
async def test_palette_external_cancellation_awaits_all_image_tasks() -> None:
    dataset, _ = _image_dataset()
    active = 0
    all_connections_started = asyncio.Event()
    never_release = asyncio.Event()

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active
        active += 1
        if active == load.IMAGE_CONNECTIONS_PER_USER:
            all_connections_started.set()
        try:
            await never_release.wait()
            raise AssertionError("cancellation must stop the pending request")
        finally:
            active -= 1

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
    ) as client:
        task = asyncio.create_task(
            load._run_palette_page_load(
                client,
                load.SampleCollector(),
                profile="C-png-cold",
                images=dataset.images,
                cache_state="cold",
                validators={},
                round_number=1,
                vus=1,
                user_index=0,
                palette_load_number=1,
                deadline=time.perf_counter() + 5,
            )
        )
        await asyncio.wait_for(all_connections_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("termination", ("deadline", "external_cancellation"))
async def test_palette_cleanup_retrieves_group_future_exception(
    termination: str,
) -> None:
    dataset, _ = _image_dataset()
    active = 0
    all_connections_started = asyncio.Event()
    never_release = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous_exception_handler = loop.get_exception_handler()
    loop_exception_contexts: list[dict[str, object]] = []

    def capture_loop_exception(
        _: asyncio.AbstractEventLoop,
        context: dict[str, object],
    ) -> None:
        loop_exception_contexts.append(dict(context))

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active
        active += 1
        if active == load.IMAGE_CONNECTIONS_PER_USER:
            all_connections_started.set()
        try:
            await never_release.wait()
            raise AssertionError("cleanup must cancel the pending request")
        finally:
            active -= 1

    loop.set_exception_handler(capture_loop_exception)
    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://test",
        ) as client:
            page_load = asyncio.create_task(
                load._run_palette_page_load(
                    client,
                    load.SampleCollector(),
                    profile="C-png-cold",
                    images=dataset.images,
                    cache_state="cold",
                    validators={},
                    round_number=1,
                    vus=1,
                    user_index=0,
                    palette_load_number=1,
                    deadline=time.perf_counter()
                    + (0.1 if termination == "deadline" else 5),
                )
            )
            await asyncio.wait_for(all_connections_started.wait(), timeout=1)
            if termination == "external_cancellation":
                page_load.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await page_load
            else:
                assert await page_load is None

        del page_load
        for _ in range(3):
            gc.collect()
            await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_exception_handler)

    assert active == 0
    assert [
        context
        for context in loop_exception_contexts
        if "exception was never retrieved"
        in str(context.get("message", "")).lower()
    ] == []


@pytest.mark.asyncio
async def test_image_profile_fails_closed_when_a_started_palette_load_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, _ = _image_dataset()

    async def expired_palette_load(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(
        load,
        "_run_palette_page_load",
        expired_palette_load,
    )
    started = time.perf_counter()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("no HTTP expected"))
        ),
        base_url="http://test",
    ) as client:
        with pytest.raises(load.ProfileExecutionError) as captured:
            await load.run_image_profile(
                client,
                dataset,
                cache_state="cold",
                round_number=1,
                vus=1,
                duration_seconds=5,
            )
    elapsed = time.perf_counter() - started

    setup = captured.value.result.setup
    assert elapsed < 1
    assert captured.value.__cause__.__class__ is load.LoadProfileError
    assert setup["started_palette_loads"] == 1
    assert setup["completed_palette_loads"] == 0
    assert setup["incomplete_palette_loads"] == 1
    assert setup["incomplete_palette_loads_by_vu"] == [1]


@pytest.mark.asyncio
async def test_warm_profile_excludes_prime_and_reports_palette_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, bodies = _image_dataset()
    prime_calls = 0
    measured_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal prime_calls, measured_calls
        if "if-none-match" not in request.headers:
            prime_calls += 1
            return _stream_response(
                200,
                body=bodies[request.url.path],
                headers={"Content-Type": "image/png", "ETag": '"fixture"'},
            )
        measured_calls += 1
        return _stream_response(304, body=b"")

    async def one_palette_load(
        *,
        start_deadline: float,
        completion_deadline: float,
        execute_palette_load: object,
        **_: object,
    ) -> int:
        assert start_deadline == completion_deadline
        assert callable(execute_palette_load)
        completed = await execute_palette_load(  # type: ignore[misc]
            1,
            completion_deadline,
        )
        return int(completed)

    monkeypatch.setattr(load, "_run_palette_user_schedule", one_palette_load)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://test",
    ) as client:
        result = await load.run_image_profile(
            client,
            dataset,
            cache_state="warm",
            round_number=1,
            vus=1,
            duration_seconds=5,
        )

    summary = result.summary()
    setup = summary["setup"]
    coverage = setup["coverage"]
    assert prime_calls == 221
    assert measured_calls == 221
    assert summary["completed_requests"] == 221
    assert summary["completed_journeys"] == 0
    assert setup["model_version"] == "palette-page-load-v3"
    assert setup["model"] == "per-vu-fixed-period-palette-page-load"
    assert setup["palette_load_period_seconds_per_vu"] == 6.0
    assert setup["completed_palette_loads"] == 1
    assert setup["completed_palette_loads_by_vu"] == [1]
    assert setup["incomplete_palette_loads"] == 0
    assert setup["incomplete_palette_loads_by_vu"] == [0]
    assert setup["prime_requests_excluded_from_measurement"] is True
    assert coverage == {
        "manifest_image_count": 221,
        "measured_image_requests": 221,
        "image_requests_in_completed_palette_loads": 221,
        "image_requests_outside_completed_palette_loads": 0,
        "distinct_manifest_images_in_completed_palette_loads": 221,
        "completed_palette_load_visits_per_image_min": 1,
        "completed_palette_load_visits_per_image_max": 1,
        "exactly_once_per_completed_palette_load": True,
    }
    assert "/uploads/" not in json.dumps(setup)
