"""Own, run, measure and precisely destroy one local capacity-test stack."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import stat
import statistics
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

import httpx

from scripts.performance.config import (
    COMPOSE_FILE,
    ARTIFACT_ROOT,
    MAX_WRITE_JOURNEYS_PER_RUN,
    PROJECT_PREFIX,
    REPOSITORY_ROOT,
    SECRET_NAMES,
    WORKSPACE_ROOT,
    PerformanceConfigError,
    PerformanceRunConfig,
    config_for_run,
    content_digest,
    port_is_available,
    write_private,
)
from scripts.performance.load import (
    FrozenDataset,
    IMAGE_JOURNEY_PERIOD_SECONDS,
    LoadProfileError,
    MAX_FAILURE_EVIDENCE_SAMPLES,
    MAX_SUCCESS_EVIDENCE_SAMPLES,
    ProfileExecutionError,
    ProfileResult,
    WRITE_JOURNEY_PERIOD_SECONDS,
    build_client,
    discover_dataset,
    prime_image_validators,
    run_browse_profile,
    run_color_profile,
    run_image_profile,
    run_write_profile,
    summarize_numbers,
)


STEADY_SERVICES = ("mysql", "redis", "app", "edge", "shaper")
OPERATION_SERVICES = ("image-init", "migrate", "mard", "seed")
ALL_SCENARIOS = ("A", "B", "C", "D")
IMAGE_PHASE_COMPLETION_DRAIN_SECONDS = IMAGE_JOURNEY_PERIOD_SECONDS
EXPECTED_PROFILE_OPERATIONS = {
    "A": {"color_detail_221"},
    "B": {
        "product_list", "typical_kit_detail", "color_detail_221",
        "order_list", "wallet_summary", "user_me",
    },
    "C": {"compatibility_png"},
    "D": {
        "create_color_order_for_cancel", "cancel_color_order",
        "create_color_order_for_wallet", "wallet_payment_first",
        "wallet_payment_replay", "assisted_order_first", "assisted_order_replay",
    },
}
SERVICE_MEMORY_LIMIT_MIB = {
    "mysql": 2240,
    "redis": 384,
    "app": 1280,
    "edge": 128,
    "shaper": 64,
}
STACK_MEMORY_BYTES = 4 * 1024**3
PROFILE_MEMORY_GATE_BYTES = int(STACK_MEMORY_BYTES * 0.80)
GIB = 1024**3
MIN_PREFLIGHT_DISK_FREE_BYTES = 4 * GIB
MIN_RUNTIME_DISK_FREE_BYTES = 2 * GIB
MIN_PREFLIGHT_HOST_MEMORY_AVAILABLE_BYTES = 2 * GIB
MIN_RUNTIME_HOST_MEMORY_AVAILABLE_BYTES = 1 * GIB
LOAD_GENERATOR_RSS_GATE_BYTES = 1 * GIB
TBF_RATE_BYTES_PER_SECOND = 5_000_000 // 8
TBF_BURST_BYTES = 128_000 // 8
TBF_LATENCY_MICROSECONDS = 400_000
TBF_LATENCY_MILLISECONDS = 400.0
TBF_LATENCY_TOLERANCE_MILLISECONDS = 1.0
QDISC_CUMULATIVE_COUNTERS = (
    "bytes",
    "packets",
    "drops",
    "overlimits",
    "requeues",
)
QDISC_GAUGE_COUNTERS = ("backlog",)
MAX_JSONL_RECORD_BYTES = 128 * 1024
ESTIMATED_REQUEST_SAMPLE_BYTES = 1_024
MAX_RECONCILIATION_ROWS_PER_JOURNEY = 22
ESTIMATED_DATABASE_BYTES_PER_BUSINESS_ROW = 4_096
DEFAULT_SAMPLE_INTERVAL_SECONDS = 1.0
DEFAULT_HEALTH_INTERVAL_SECONDS = 5.0
COOLDOWN_MAX_ATTEMPTS = 5
COOLDOWN_RETRY_INTERVAL_SECONDS = 1.0
COOLDOWN_REQUIRED_CONSECUTIVE_IDLE_SAMPLES = 2
COOLDOWN_MAX_THREADS_RUNNING = 2
ACCESS_TOKEN_SECONDS = 28_800
TOKEN_SAFETY_MARGIN_SECONDS = 3_600
GLOBAL_LOCK_NAME = ".owner.lock"
MANIFEST_PATH = (
    REPOSITORY_ROOT / "app" / "tasks" / "manifests" / "mard_221.json"
)
SOURCE_IDENTITY_PATHS = (
    REPOSITORY_ROOT / "app",
    REPOSITORY_ROOT / "migrations",
    REPOSITORY_ROOT / "requirements.txt",
    REPOSITORY_ROOT / "pyproject.toml",
    REPOSITORY_ROOT / "deploy" / "runtime",
    REPOSITORY_ROOT / "deploy" / "performance",
    REPOSITORY_ROOT / "scripts" / "performance",
)


class HarnessError(RuntimeError):
    """A sanitized orchestration, measurement or cleanup failure."""


class ProfileRunFailure(HarnessError):
    """Retain the number of fully completed D journeys across fail-fast."""

    def __init__(self, message: str, completed_journeys: int = 0) -> None:
        super().__init__(message)
        self.completed_journeys = completed_journeys


CONTINUABLE_CAPACITY_FAILURES = frozenset(
    {
        "aggregate_5mbps_not_demonstrated",
        "average_cpu_gate",
        "json_latency_gate",
        "normal_network_above_85_percent",
        "normal_network_sustained_above_90_percent",
        "per_operation_json_tail_gate",
        "per_operation_read_p95_gate",
        "per_operation_write_p95_gate",
        "qdisc_drop",
        "qdisc_overlimits_not_increasing",
        "read_p95_gate",
        "sustained_cpu_gate",
        "write_p95_gate",
    }
)
PROFILE_DISPOSITION_PASS = "pass"
PROFILE_DISPOSITION_CONTINUE = "continue_after_capacity_failure"
PROFILE_DISPOSITION_ABORT = "abort"


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _tbf_configuration_is_expected(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    latency = value.get("latency_milliseconds")
    latency_microseconds = value.get("latency_microseconds")
    return (
        value.get("rate_bytes_per_second") == TBF_RATE_BYTES_PER_SECOND
        and value.get("burst_bytes") == TBF_BURST_BYTES
        and _nonnegative_integer(latency_microseconds)
        and _finite_number(latency)
        and math.isclose(
            float(latency),
            TBF_LATENCY_MILLISECONDS,
            rel_tol=0,
            abs_tol=TBF_LATENCY_TOLERANCE_MILLISECONDS,
        )
    )


def _qdisc_snapshot_is_complete(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and all(
            _nonnegative_integer(value.get(key))
            for key in (*QDISC_CUMULATIVE_COUNTERS, *QDISC_GAUGE_COUNTERS)
        )
        and _tbf_configuration_is_expected(value.get("configuration"))
    )


def _qdisc_samples_are_monotonic(
    samples: Sequence[Mapping[str, object]],
) -> bool:
    previous: Mapping[str, object] | None = None
    configuration: object = None
    sample_count = 0
    for sample in samples:
        current = sample.get("qdisc")
        if not _qdisc_snapshot_is_complete(current):
            return False
        assert isinstance(current, Mapping)
        if configuration is None:
            configuration = current["configuration"]
        elif current["configuration"] != configuration:
            return False
        if previous is not None and any(
            int(current[key]) < int(previous[key])
            for key in QDISC_CUMULATIVE_COUNTERS
        ):
            return False
        previous = current
        sample_count += 1
    return sample_count >= 2


def _qdisc_window_is_complete(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    start = value.get("start")
    end = value.get("end")
    if (
        not _qdisc_snapshot_is_complete(start)
        or not _qdisc_snapshot_is_complete(end)
    ):
        return False
    assert isinstance(start, Mapping)
    assert isinstance(end, Mapping)
    if (
        start["configuration"] != end["configuration"]
        or value.get("configuration") != end["configuration"]
        or value.get("configuration_unchanged") is not True
        or value.get("sampled_counters_monotonic") is not True
    ):
        return False
    for counter, delta_name in (
        ("bytes", "bytes_delta"),
        ("overlimits", "overlimits_delta"),
        ("drops", "drops_delta"),
    ):
        delta = value.get(delta_name)
        if (
            not _nonnegative_integer(delta)
            or int(end[counter]) - int(start[counter]) != int(delta)
        ):
            return False
    if any(
        int(end[counter]) < int(start[counter])
        for counter in QDISC_CUMULATIVE_COUNTERS
    ):
        return False
    average_mbps = value.get("average_mbps")
    sustained_seconds = value.get("continuous_seconds_above_4_5_mbps")
    return (
        int(value["bytes_delta"]) > 0
        and _finite_number(average_mbps)
        and float(average_mbps) > 0
        and _finite_number(sustained_seconds)
        and float(sustained_seconds) >= 0
    )


def _dependency_window_is_complete(
    value: object,
    *,
    counter_keys: Sequence[str],
    gauge_keys: Sequence[str] = (),
) -> bool:
    if not isinstance(value, Mapping):
        return False
    start = value.get("start")
    end = value.get("end")
    deltas = value.get("deltas")
    if not all(isinstance(row, Mapping) for row in (start, end, deltas)):
        return False
    assert isinstance(start, Mapping)
    assert isinstance(end, Mapping)
    assert isinstance(deltas, Mapping)
    for key in counter_keys:
        before = start.get(key)
        after = end.get(key)
        delta = deltas.get(key)
        if (
            not _nonnegative_integer(before)
            or not _nonnegative_integer(after)
            or not _nonnegative_integer(delta)
            or int(after) - int(before) != int(delta)
        ):
            return False
    return all(
        _nonnegative_integer(start.get(key))
        and _nonnegative_integer(end.get(key))
        for key in gauge_keys
    )


def _profile_evidence_is_complete(
    load: Mapping[str, object] | None,
    monitor: Mapping[str, object] | None,
) -> bool:
    """Require the frozen load, monitor and dependency evidence for any verdict."""

    if not isinstance(load, Mapping) or not isinstance(monitor, Mapping):
        return False
    profile = str(load.get("profile", ""))
    scenario_key = profile[0] if profile and profile[0] in ALL_SCENARIOS else ""
    if (
        not isinstance(load.get("completed_requests"), int)
        or int(load["completed_requests"]) <= 0
    ):
        return False
    latency_keys = ["p95"]
    if profile == "B-authenticated-browse" and load.get("vus") == 10:
        latency_keys.extend(("p99", "max"))
    latency = load.get("latency_ms")
    operations = load.get("operations")
    if (
        not isinstance(latency, Mapping)
        or any(not _finite_number(latency.get(key)) for key in latency_keys)
        or not isinstance(operations, Mapping)
        or set(operations) != EXPECTED_PROFILE_OPERATIONS.get(scenario_key, set())
    ):
        return False
    for operation in operations.values():
        operation_latency = (
            operation.get("latency_ms")
            if isinstance(operation, Mapping)
            else None
        )
        if not isinstance(operation_latency, Mapping) or any(
            not _finite_number(operation_latency.get(key))
            for key in latency_keys
        ):
            return False

    qdisc = monitor.get("qdisc")
    cpu = monitor.get("cpu")
    memory = monitor.get("memory")
    load_generator = monitor.get("load_generator")
    host_safety = monitor.get("host_safety")
    sampling = monitor.get("sampling")
    mysql = monitor.get("mysql")
    redis = monitor.get("redis")
    if (
        not _nonnegative_integer(monitor.get("sample_count"))
        or int(monitor["sample_count"]) < 2
        or monitor.get("sample_errors") != []
        or monitor.get("readiness_failures") != 0
        or not _qdisc_window_is_complete(qdisc)
        or not isinstance(cpu, Mapping)
        or any(
            not _finite_number(cpu.get(key))
            for key in (
                "average_percent_of_two_cores",
                "continuous_seconds_above_85",
            )
        )
        or not isinstance(memory, Mapping)
        or not _finite_number(memory.get("peak_bytes"))
        or not _finite_number(memory.get("swap_peak_bytes"))
        or not isinstance(load_generator, Mapping)
        or not _finite_number(
            load_generator.get("process_cpu_percent_of_one_core")
        )
        or not _finite_number(load_generator.get("rss_peak_bytes"))
        or not isinstance(host_safety, Mapping)
        or not _finite_number(host_safety.get("available_memory_min_bytes"))
        or not _finite_number(host_safety.get("disk_free_min_bytes"))
        or not isinstance(sampling, Mapping)
        or not _finite_number(sampling.get("maximum_interval_seconds"))
        or float(sampling["maximum_interval_seconds"]) < 0
        or not isinstance(mysql, Mapping)
        or not isinstance(redis, Mapping)
    ):
        return False
    return (
        _dependency_window_is_complete(
            mysql,
            counter_keys=("Innodb_deadlocks", "Slow_queries"),
            gauge_keys=("Innodb_row_lock_current_waits",),
        )
        and _dependency_window_is_complete(
            redis,
            counter_keys=("evicted_keys", "rejected_connections"),
        )
        and _state_is_healthy(
            monitor.get("state_start"), monitor.get("state_end")
        )
    )


def classify_profile_failure(
    verdict: Mapping[str, object],
    *,
    load: Mapping[str, object] | None,
    monitor: Mapping[str, object] | None,
    result_complete: bool,
    profile_error_present: bool,
) -> dict[str, object]:
    """Classify a recorded Profile without weakening any frozen gate.

    A complete, otherwise-correct Profile may continue only when every failure is
    an explicitly enumerated observational capacity outcome.  Unknown failures
    are terminal by default.  Continuing only collects the remaining matrix; it
    never changes the failed Profile or the final run verdict to PASS.
    """

    raw_failures = verdict.get("failures")
    failures = (
        sorted(
            {
                failure
                for failure in raw_failures
                if isinstance(failure, str)
            }
        )
        if isinstance(raw_failures, (list, tuple, set, frozenset))
        else []
    )
    continuable = sorted(
        failure for failure in failures
        if failure in CONTINUABLE_CAPACITY_FAILURES
    )
    terminal = sorted(
        failure for failure in failures
        if failure not in CONTINUABLE_CAPACITY_FAILURES
    )
    # An A Profile below 4.75 Mbps is a valid observation that the service could
    # not fill the frozen 5 Mbps pipe.  An A Profile above 5.05 Mbps instead means
    # the shaping evidence is invalid and must terminate rather than be treated as
    # ordinary capacity exhaustion.  The overlimit counter follows the same rule.
    conditional_network_failures = {
        "aggregate_5mbps_not_demonstrated",
        "qdisc_overlimits_not_increasing",
    }.intersection(continuable)
    if conditional_network_failures:
        qdisc = monitor.get("qdisc") if isinstance(monitor, Mapping) else None
        average_mbps = (
            qdisc.get("average_mbps") if isinstance(qdisc, Mapping) else None
        )
        if (
            not isinstance(average_mbps, (int, float))
            or not math.isfinite(float(average_mbps))
            or not 0 < float(average_mbps) < 4.75
        ):
            continuable = sorted(
                set(continuable) - conditional_network_failures
            )
            terminal = sorted(set(terminal) | conditional_network_failures)
    verdict_passed = verdict.get("passed") is True
    zero_failed_requests = (
        isinstance(load, Mapping) and load.get("failed_requests") == 0
    )
    profile_evidence_complete = _profile_evidence_is_complete(
        load, monitor
    )
    if not profile_evidence_complete:
        terminal = sorted(set(terminal) | {"profile_evidence_incomplete"})
    if (
        verdict_passed
        and not failures
        and result_complete
        and not profile_error_present
        and zero_failed_requests
        and profile_evidence_complete
    ):
        disposition = PROFILE_DISPOSITION_PASS
    elif (
        not verdict_passed
        and failures
        and len(continuable) == len(failures)
        and result_complete
        and not profile_error_present
        and zero_failed_requests
        and profile_evidence_complete
    ):
        disposition = PROFILE_DISPOSITION_CONTINUE
    else:
        disposition = PROFILE_DISPOSITION_ABORT
    return {
        "disposition": disposition,
        "result_complete": result_complete,
        "profile_error_present": profile_error_present,
        "zero_failed_requests": zero_failed_requests,
        "profile_evidence_complete": profile_evidence_complete,
        # Kept as a compatibility alias for existing evidence consumers.
        "continuation_evidence_complete": profile_evidence_complete,
        "continuable_capacity_failures": continuable,
        "terminal_failures": terminal,
    }


def _safe_failure_reason(error: BaseException | None) -> str | None:
    """Return only messages from error types whose text is controlled internally."""

    if not isinstance(error, (HarnessError, LoadProfileError)):
        return None
    return str(error) or type(error).__name__


def _verdict_after_cleanup_failure(current: object) -> str:
    """Cleanup uncertainty must not erase an already-proven run failure."""

    return "FAIL" if current == "FAIL" else "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class CompletedCommand:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    """Small injectable subprocess boundary; command arguments never carry Secrets."""

    def __init__(self, *, cwd: Path = REPOSITORY_ROOT) -> None:
        self.cwd = cwd

    def run(
        self,
        args: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
        timeout: float = 180.0,
        check: bool = True,
    ) -> CompletedCommand:
        try:
            process = subprocess.run(
                list(args),
                cwd=self.cwd,
                env=(dict(environment) if environment is not None else None),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise HarnessError(f"command unavailable or timed out: {args[0]}") from error
        result = CompletedCommand(
            tuple(args), process.returncode, process.stdout, process.stderr
        )
        if check and process.returncode != 0:
            raise HarnessError(
                f"command failed: executable={args[0]} returncode={process.returncode}"
            )
        return result


class GlobalRunLock:
    """Serialize all local performance envelopes without owning other runs."""

    def __init__(self, config: PerformanceRunConfig) -> None:
        self.config = config
        self.descriptor: int | None = None

    def acquire(self) -> None:
        _ensure_private_root(WORKSPACE_ROOT)
        path = WORKSPACE_ROOT / GLOBAL_LOCK_NAME
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            os.close(descriptor)
            raise HarnessError("global performance owner lock is unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise HarnessError("another local performance run owns the envelope") from error
        owner = json.dumps(
            {"pid": os.getpid(), "run_id": self.config.run_id}, sort_keys=True
        ).encode("utf-8")
        os.ftruncate(descriptor, 0)
        os.write(descriptor, owner)
        os.fsync(descriptor)
        self.descriptor = descriptor

    def release(self) -> None:
        if self.descriptor is None:
            return
        descriptor = self.descriptor
        path = WORKSPACE_ROOT / GLOBAL_LOCK_NAME
        descriptor_metadata = os.fstat(descriptor)
        try:
            path_metadata = path.lstat()
        except FileNotFoundError:
            path_metadata = None
        if (
            path_metadata is not None
            and path_metadata.st_dev == descriptor_metadata.st_dev
            and path_metadata.st_ino == descriptor_metadata.st_ino
        ):
            # Unlink while still holding the inode lock. A new owner may then
            # create a fresh inode, but this run has already completed cleanup.
            path.unlink()
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        self.descriptor = None
        try:
            WORKSPACE_ROOT.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            # A concurrent new owner or an interrupted-run workspace makes the
            # shared root non-empty; neither belongs to this completed run.
            if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                raise HarnessError("global performance lock root cleanup failed") from error


def _performance_projects(runner: CommandRunner) -> list[str]:
    """Find every Compose project using the reserved performance prefix."""

    projects: set[str] = set()
    label_template = '{{.Label "com.docker.compose.project"}}'
    for arguments in (
        ("docker", "ps", "--all", "--format", label_template),
        ("docker", "network", "ls", "--format", label_template),
        ("docker", "volume", "ls", "--format", label_template),
    ):
        output = runner.run(arguments, timeout=30).stdout
        projects.update(
            line.strip()
            for line in output.splitlines()
            if line.strip().startswith(PROJECT_PREFIX)
        )
    return sorted(projects)


def _profile_count(options: HarnessOptions) -> int:
    variants = sum(
        count
        for scenario, count in (("A", 2), ("B", 1), ("C", 2), ("D", 1))
        if scenario in options.scenarios
    )
    return options.rounds * len(options.vus) * variants


def _estimated_profile_matrix_seconds(options: HarnessOptions) -> float:
    """Estimate configured sequential Profile time, excluding setup extensions."""

    per_profile = (
        options.ramp_seconds
        + options.warmup_seconds
        + options.duration_seconds
        + options.cooldown_seconds
    )
    total = _profile_count(options) * per_profile
    if "C" in options.scenarios:
        image_profile_count = options.rounds * len(options.vus) * 2
        drained_phases = 1 + int(options.ramp_seconds > 0) + int(
            options.warmup_seconds > 0
        )
        total += (
            image_profile_count
            * drained_phases
            * IMAGE_PHASE_COMPLETION_DRAIN_SECONDS
        )
    return total


def _estimated_evidence_bytes(options: HarnessOptions) -> int:
    """Conservative bound for retained raw HTTP samples plus report overhead."""

    raw_records = _profile_count(options) * (
        MAX_SUCCESS_EVIDENCE_SAMPLES + MAX_FAILURE_EVIDENCE_SAMPLES
    )
    return raw_records * ESTIMATED_REQUEST_SAMPLE_BYTES + 64 * 1024**2


def _estimated_run_storage_bytes(options: HarnessOptions) -> int:
    return _estimated_evidence_bytes(options) + (
        _maximum_write_journeys(options)
        * MAX_RECONCILIATION_ROWS_PER_JOURNEY
        * ESTIMATED_DATABASE_BYTES_PER_BUSINESS_ROW
    )


def _maximum_write_journeys(options: HarnessOptions) -> int:
    if "D" not in options.scenarios:
        return 0
    phase_durations = (
        options.ramp_seconds,
        options.warmup_seconds,
        options.duration_seconds,
    )
    per_vu = sum(
        math.ceil(duration / WRITE_JOURNEY_PERIOD_SECONDS)
        for duration in phase_durations
        if duration > 0
    )
    return options.rounds * sum(options.vus) * per_vu


def _parse_available_memory(system: str, output: str) -> int | None:
    if system == "Linux":
        match = re.search(r"^MemAvailable:\s+(\d+)\s+kB$", output, re.MULTILINE)
        return int(match.group(1)) * 1024 if match else None
    if system == "Darwin":
        page_match = re.search(r"page size of (\d+) bytes", output)
        if page_match is None:
            return None
        pages = 0
        for name in ("free", "inactive", "speculative"):
            match = re.search(
                rf"^Pages {name}:\s+(\d+)\.$", output, re.MULTILINE
            )
            if match:
                pages += int(match.group(1))
        return pages * int(page_match.group(1)) if pages else None
    return None


def _host_available_memory_bytes(runner: CommandRunner) -> int | None:
    system = platform.system()
    if system == "Darwin":
        result = runner.run(["vm_stat"], check=False, timeout=10)
        return (
            _parse_available_memory(system, result.stdout)
            if result.returncode == 0
            else None
        )
    if system == "Linux":
        try:
            return _parse_available_memory(
                system, Path("/proc/meminfo").read_text(encoding="utf-8")
            )
        except OSError:
            return None
    return None


class EvidenceWriter:
    """Write bounded, secret-free evidence using private permissions."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _require_disk_headroom(self) -> None:
        probe = self.root if self.root.exists() else self.root.parent
        if shutil.disk_usage(probe).free < MIN_RUNTIME_DISK_FREE_BYTES:
            raise HarnessError("performance evidence filesystem is below its safety floor")

    def prepare(self) -> None:
        _ensure_private_root(self.root.parent)
        self._require_disk_headroom()
        self.root.mkdir(parents=True, mode=0o700, exist_ok=False)
        os.chmod(self.root, 0o700)

    def write_json(self, name: str, value: object) -> None:
        self._require_disk_headroom()
        write_private(
            self.root / name,
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        )

    def write_text(self, name: str, value: str) -> None:
        self._require_disk_headroom()
        write_private(self.root / name, value)

    def append_jsonl(self, name: str, records: Iterable[Mapping[str, object]]) -> None:
        self._require_disk_headroom()
        path = self.root / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            os.close(descriptor)
            raise HarnessError("performance evidence file is unsafe")
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            for index, record in enumerate(records):
                if index % 128 == 0:
                    self._require_disk_headroom()
                encoded = json.dumps(record, ensure_ascii=False, sort_keys=True)
                if len(encoded.encode("utf-8")) > MAX_JSONL_RECORD_BYTES:
                    raise HarnessError("performance JSONL record exceeds its safety bound")
                stream.write(encoded)
                stream.write("\n")


@dataclass(frozen=True, slots=True)
class HarnessOptions:
    evidence_level: str
    duration_seconds: float
    rounds: int
    vus: tuple[int, ...]
    scenarios: tuple[str, ...]
    think_time_min: float
    think_time_max: float
    cooldown_seconds: float
    warmup_seconds: float
    ramp_seconds: float
    random_seed: int

    def validate(self) -> None:
        if self.evidence_level == "candidate":
            raise HarnessError(
                "this same-host Docker envelope cannot produce candidate evidence; "
                "use candidate-pre or a dedicated 2vCPU/4GiB host workflow"
            )
        if self.evidence_level not in ("exploratory", "candidate-pre"):
            raise HarnessError(
                "evidence level must be exploratory or candidate-pre"
            )
        numeric_values = (
            self.duration_seconds,
            self.think_time_min,
            self.think_time_max,
            self.cooldown_seconds,
            self.warmup_seconds,
            self.ramp_seconds,
        )
        if not all(math.isfinite(value) for value in numeric_values):
            raise HarnessError("all duration and think-time values must be finite")
        minimum_duration = 300 if self.evidence_level == "candidate-pre" else 30
        if not minimum_duration <= self.duration_seconds <= 3600:
            raise HarnessError(
                f"{self.evidence_level} steady duration must be between "
                f"{minimum_duration} and 3600 seconds"
            )
        if not 1 <= self.rounds <= 5:
            raise HarnessError("round count must be between one and five")
        if tuple(sorted(set(self.vus))) != tuple(sorted(self.vus)):
            raise HarnessError("VU values must be unique")
        if any(value not in (5, 10) for value in self.vus):
            raise HarnessError("this profile supports only 5 and 10 VUs")
        if (
            set(self.scenarios) - set(ALL_SCENARIOS)
            or not self.scenarios
            or len(set(self.scenarios)) != len(self.scenarios)
        ):
            raise HarnessError("scenario list must be a non-empty subset of A/B/C/D")
        if not 0 <= self.think_time_min <= self.think_time_max:
            raise HarnessError("browse think-time range is invalid")
        if (
            self.cooldown_seconds < 0
            or self.warmup_seconds < 0
            or self.ramp_seconds < 0
        ):
            raise HarnessError("ramp, warm-up and cooldown cannot be negative")
        if (
            self.think_time_max > 60
            or self.cooldown_seconds > 300
            or self.warmup_seconds > 600
            or self.ramp_seconds > 30
        ):
            raise HarnessError(
                "ramp, warm-up, cooldown or think time exceeds safety limits"
            )
        if not 0 <= self.random_seed <= 2**63 - 1:
            raise HarnessError("random seed is outside the supported range")
        if self.evidence_level == "candidate-pre":
            if (
                self.rounds != 3
                or self.vus != (5, 10)
                or self.scenarios != ALL_SCENARIOS
            ):
                raise HarnessError(
                    "candidate-pre requires full A/B/C/D, exactly three rounds and 5/10 VUs"
                )
            if (
                not 10 <= self.ramp_seconds <= 30
                or self.warmup_seconds < 60
                or self.cooldown_seconds < 30
            ):
                raise HarnessError(
                    "candidate-pre requires a 10-30s ramp, 60s warm-up and 30s cooldown"
                )
        estimated_authenticated_seconds = _estimated_profile_matrix_seconds(self)
        if (
            {"B", "D"}.intersection(self.scenarios)
            and estimated_authenticated_seconds
            > ACCESS_TOKEN_SECONDS - TOKEN_SAFETY_MARGIN_SECONDS
        ):
            raise HarnessError(
                "estimated profile matrix exceeds the fixed access-token safety window"
            )
        if _maximum_write_journeys(self) > MAX_WRITE_JOURNEYS_PER_RUN:
            raise HarnessError(
                "write matrix exceeds the bounded final-reconciliation capacity"
            )


@dataclass(slots=True)
class ProfileMonitorResult:
    profile: str
    samples: list[dict[str, object]]
    qdisc_start: dict[str, object]
    qdisc_end: dict[str, object]
    qdisc_mbps: float
    readiness_failures: int
    state_start: dict[str, object]
    state_end: dict[str, object]
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        cpu_samples = [
            float(row["stack_cpu_percent_of_two_cores"])
            for row in self.samples
            if row.get("stack_cpu_percent_of_two_cores") is not None
        ]
        memory_samples = [
            int(row["stack_memory_bytes"])
            for row in self.samples
            if row.get("stack_memory_bytes") is not None
        ]
        swap_samples = [
            int(row["stack_swap_bytes"])
            for row in self.samples
            if row.get("stack_swap_bytes") is not None
        ]
        mysql_samples = [
            row["mysql"] for row in self.samples if isinstance(row.get("mysql"), dict)
        ]
        redis_samples = [
            row["redis"] for row in self.samples if isinstance(row.get("redis"), dict)
        ]
        process_cpu_samples = [
            (float(row["captured_at_epoch"]), float(row["load_generator_cpu_seconds"]))
            for row in self.samples
            if isinstance(row.get("captured_at_epoch"), (int, float))
            and isinstance(row.get("load_generator_cpu_seconds"), (int, float))
        ]
        load_generator_rss = [
            int(row["load_generator_rss_bytes"])
            for row in self.samples
            if isinstance(row.get("load_generator_rss_bytes"), int)
        ]
        host_available_memory = [
            int(row["host_available_memory_bytes"])
            for row in self.samples
            if isinstance(row.get("host_available_memory_bytes"), int)
        ]
        host_disk_free = [
            int(row["host_disk_free_bytes"])
            for row in self.samples
            if isinstance(row.get("host_disk_free_bytes"), int)
        ]
        timestamps = [
            float(row["captured_at_epoch"])
            for row in self.samples
            if isinstance(row.get("captured_at_epoch"), (int, float))
        ]
        intervals = [
            after - before for before, after in zip(timestamps, timestamps[1:])
            if after >= before
        ]
        process_cpu_percent: float | None = None
        if len(process_cpu_samples) >= 2:
            wall = process_cpu_samples[-1][0] - process_cpu_samples[0][0]
            cpu_time = process_cpu_samples[-1][1] - process_cpu_samples[0][1]
            if wall > 0 and cpu_time >= 0:
                process_cpu_percent = round(cpu_time / wall * 100, 6)
        mysql_window = _dependency_window(mysql_samples)
        mysql_window["peaks"] = {
            key: max(
                (
                    int(sample[key])
                    for sample in mysql_samples
                    if isinstance(sample.get(key), int)
                ),
                default=None,
            )
            for key in ("Threads_connected", "Threads_running")
        }
        redis_window = _dependency_window(redis_samples)
        redis_window["peaks"] = {
            key: max(
                (
                    int(sample[key])
                    for sample in redis_samples
                    if isinstance(sample.get(key), int)
                ),
                default=None,
            )
            for key in ("connected_clients", "used_memory", "used_memory_peak")
        }
        return {
            "profile": self.profile,
            "sample_count": len(self.samples),
            "sample_errors": list(self.errors),
            "readiness_failures": self.readiness_failures,
            "qdisc": {
                "start": self.qdisc_start,
                "end": self.qdisc_end,
                "bytes_delta": self.qdisc_end.get("bytes", 0)
                - self.qdisc_start.get("bytes", 0),
                "overlimits_delta": self.qdisc_end.get("overlimits", 0)
                - self.qdisc_start.get("overlimits", 0),
                "drops_delta": self.qdisc_end.get("drops", 0)
                - self.qdisc_start.get("drops", 0),
                "average_mbps": round(self.qdisc_mbps, 6),
                "configuration": self.qdisc_end.get("configuration"),
                "configuration_unchanged": (
                    self.qdisc_start.get("configuration")
                    == self.qdisc_end.get("configuration")
                ),
                "sampled_counters_monotonic": (
                    _qdisc_samples_are_monotonic(self.samples)
                ),
                "continuous_seconds_above_4_5_mbps": _longest_network_duration(
                    self.samples, 4.5
                ),
            },
            "cpu": {
                "average_percent_of_two_cores": (
                    round(sum(cpu_samples) / len(cpu_samples), 6)
                    if cpu_samples
                    else None
                ),
                "max_percent_of_two_cores": max(cpu_samples) if cpu_samples else None,
                "continuous_seconds_above_85": _longest_duration(
                    self.samples, 85.0
                ),
            },
            "memory": {
                "peak_bytes": max(memory_samples) if memory_samples else None,
                "gate_bytes": PROFILE_MEMORY_GATE_BYTES,
                "second_half_growth_ratio": _half_growth(memory_samples),
                "swap_peak_bytes": max(swap_samples) if swap_samples else None,
                "source": "sum of per-container cgroup memory.current in one sampling cycle",
            },
            "load_generator": {
                "process_cpu_percent_of_one_core": process_cpu_percent,
                "cpu_source": (
                    "entire Python runner process, including in-process load "
                    "generation and monitoring/orchestration; child process CPU excluded"
                ),
                "rss_peak_bytes": max(load_generator_rss) if load_generator_rss else None,
                "rss_gate_bytes": LOAD_GENERATOR_RSS_GATE_BYTES,
                "configured_connection_pool_max": 96,
            },
            "host_safety": {
                "available_memory_min_bytes": (
                    min(host_available_memory) if host_available_memory else None
                ),
                "available_memory_floor_bytes": (
                    MIN_RUNTIME_HOST_MEMORY_AVAILABLE_BYTES
                ),
                "disk_free_min_bytes": min(host_disk_free) if host_disk_free else None,
                "disk_free_floor_bytes": MIN_RUNTIME_DISK_FREE_BYTES,
            },
            "sampling": {
                "target_interval_seconds": DEFAULT_SAMPLE_INTERVAL_SECONDS,
                "observed_interval_seconds": summarize_numbers(intervals),
                "maximum_interval_seconds": max(intervals) if intervals else None,
                "boundary_samples_included": True,
            },
            "mysql": mysql_window,
            "redis": redis_window,
            "state_start": self.state_start,
            "state_end": self.state_end,
        }


class ComposeStack:
    def __init__(
        self,
        config: PerformanceRunConfig,
        runner: CommandRunner,
    ) -> None:
        self.config = config
        self.runner = runner
        self.started = False
        self.images_built = False

    def environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(self.config.compose_environment())
        return environment

    def command(self, *arguments: str, profile: str | None = None) -> list[str]:
        command = [
            "docker",
            "compose",
            "--project-name",
            self.config.project,
            "--env-file",
            str(self.config.compose_env_path),
            "--file",
            str(COMPOSE_FILE),
        ]
        if profile:
            command.extend(("--profile", profile))
        command.extend(arguments)
        return command

    def run(
        self,
        *arguments: str,
        profile: str | None = None,
        timeout: float = 180.0,
        check: bool = True,
    ) -> CompletedCommand:
        return self.runner.run(
            self.command(*arguments, profile=profile),
            environment=self.environment(),
            timeout=timeout,
            check=check,
        )

    def service_container_ids(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for service in STEADY_SERVICES:
            command = self.run("ps", "--quiet", service, timeout=20)
            identifier = command.stdout.strip()
            if not identifier:
                raise HarnessError(f"steady service has no container: {service}")
            result[service] = identifier
        return result


def _parse_json_line(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise HarnessError("operation produced no JSON result")


def _docker_object_ids(
    runner: CommandRunner,
    kind: str,
    project: str,
) -> list[str]:
    if kind == "container":
        args = [
            "docker", "ps", "--all", "--quiet", "--filter",
            f"label=com.docker.compose.project={project}",
        ]
    elif kind in ("network", "volume"):
        args = [
            "docker", kind, "ls", "--quiet", "--filter",
            f"label=com.docker.compose.project={project}",
        ]
    else:
        raise ValueError("unsupported Docker object kind")
    result = runner.run(args, timeout=20)
    return [line for line in result.stdout.splitlines() if line]


def preflight(
    config: PerformanceRunConfig,
    options: HarnessOptions,
    runner: CommandRunner,
) -> dict[str, object]:
    """Run read-only collision, identity and local-capability checks."""

    options.validate()
    if not COMPOSE_FILE.is_file() or not MANIFEST_PATH.is_file():
        raise HarnessError("performance Compose or manifest is unavailable")
    if config.workspace.exists() or config.artifact_dir.exists():
        raise HarnessError("run ID already owns a workspace or artifact")
    residual_workspaces = sorted(
        entry.name
        for entry in WORKSPACE_ROOT.iterdir()
        if entry.name != GLOBAL_LOCK_NAME
    ) if WORKSPACE_ROOT.exists() else []
    if residual_workspaces:
        raise HarnessError(
            "another or interrupted performance workspace exists; inventory and "
            "clean it by exact run ID before starting"
        )
    if not port_is_available(config.http_port):
        raise HarnessError("performance loopback port is already in use")
    cpu_count = os.cpu_count() or 0
    start_cpu, end_cpu = (int(value) for value in config.cpuset.split("-"))
    if end_cpu != start_cpu + 1 or end_cpu >= cpu_count:
        raise HarnessError("requested two-CPU set is unavailable on this host")

    docker_version = runner.run(
        ["docker", "version", "--format", "{{json .}}"], timeout=30
    ).stdout.strip()
    compose_version = runner.run(
        ["docker", "compose", "version", "--short"], timeout=30
    ).stdout.strip()
    active_projects = _performance_projects(runner)
    if active_projects:
        raise HarnessError(
            "another or interrupted performance Compose project exists; refuse "
            "to share the CPU/memory envelope"
        )
    for kind in ("container", "network", "volume"):
        if _docker_object_ids(runner, kind, config.project):
            raise HarnessError(f"run ID collides with an existing Docker {kind}")
    for image in (config.app_image, config.shaper_image):
        existing = runner.run(
            ["docker", "image", "inspect", image], check=False, timeout=20
        )
        if existing.returncode == 0:
            raise HarnessError("run ID collides with an existing image tag")

    git_sha = runner.run(["git", "rev-parse", "HEAD"], timeout=20).stdout.strip()
    status = runner.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        timeout=20,
    ).stdout
    if options.evidence_level == "candidate-pre" and status.strip():
        raise HarnessError("candidate-pre requires a clean working tree")
    try:
        docker_document = json.loads(docker_version)
    except json.JSONDecodeError as error:
        raise HarnessError("Docker version metadata is not JSON") from error
    if not isinstance(docker_document, dict):
        raise HarnessError("Docker version metadata has an unexpected shape")
    docker_summary: dict[str, object] = {}
    for side in ("Client", "Server"):
        source = docker_document.get(side)
        if isinstance(source, dict):
            docker_summary[side.lower()] = {
                key: source.get(key)
                for key in (
                    "Version", "ApiVersion", "Os", "Arch", "KernelVersion",
                    "Context",
                )
                if source.get(key) is not None
            }
    buildx = runner.run(
        ["docker", "buildx", "version"], check=False, timeout=30
    )
    process_inventory = runner.run(
        ["ps", "-axo", "pid=,ppid=,comm="], check=False, timeout=20
    )
    physical_memory: int | None = None
    if platform.system() == "Darwin":
        memory = runner.run(["sysctl", "-n", "hw.memsize"], check=False, timeout=10)
        if memory.returncode == 0 and memory.stdout.strip().isdigit():
            physical_memory = int(memory.stdout.strip())
    elif hasattr(os, "sysconf"):
        try:
            physical_memory = int(os.sysconf("SC_PAGE_SIZE")) * int(
                os.sysconf("SC_PHYS_PAGES")
            )
        except (OSError, ValueError):
            physical_memory = None
    available_memory = _host_available_memory_bytes(runner)
    if (
        available_memory is None
        or available_memory < MIN_PREFLIGHT_HOST_MEMORY_AVAILABLE_BYTES
    ):
        raise HarnessError("host available memory is below the performance safety floor")
    disk = shutil.disk_usage(REPOSITORY_ROOT)
    estimated_evidence_bytes = _estimated_evidence_bytes(options)
    estimated_run_storage_bytes = _estimated_run_storage_bytes(options)
    required_disk_bytes = max(
        MIN_PREFLIGHT_DISK_FREE_BYTES,
        estimated_run_storage_bytes * 4,
    )
    if disk.free < required_disk_bytes:
        raise HarnessError("host free disk is below the performance safety floor")
    docker_disk = runner.run(
        ["docker", "system", "df", "--format", "{{json .}}"],
        check=False,
        timeout=30,
    )
    return {
        "git_sha": git_sha,
        "git_dirty": bool(status.strip()),
        "git_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
        "source_tree_sha256": content_digest(SOURCE_IDENTITY_PATHS),
        "docker_version_sha256": hashlib.sha256(docker_version.encode()).hexdigest(),
        "docker": docker_summary,
        "compose_version": compose_version,
        "buildx_version": buildx.stdout.strip() if buildx.returncode == 0 else None,
        "load_generator": {
            "python": platform.python_version(),
            "httpx": httpx.__version__,
            "runner": "scripts.performance.load closed-loop asyncio/httpx",
            "connection_pool_max": 96,
            "process_cpu_and_rss_sampled_during_each_profile": True,
        },
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "logical_cpu_count": cpu_count,
            "physical_memory_bytes": physical_memory,
            "available_memory_bytes": available_memory,
            "available_memory_floor_bytes": MIN_PREFLIGHT_HOST_MEMORY_AVAILABLE_BYTES,
            "disk_total_bytes": disk.total,
            "disk_used_bytes": disk.used,
            "disk_free_bytes": disk.free,
            "disk_required_bytes": required_disk_bytes,
            "estimated_max_evidence_bytes": estimated_evidence_bytes,
            "estimated_max_run_storage_bytes": estimated_run_storage_bytes,
            "docker_system_df_available": docker_disk.returncode == 0,
            "docker_system_df_sha256": (
                hashlib.sha256(docker_disk.stdout.encode()).hexdigest()
                if docker_disk.returncode == 0
                else None
            ),
            "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
            "background_process_count": len(process_inventory.stdout.splitlines()),
            "background_process_inventory_sha256": hashlib.sha256(
                process_inventory.stdout.encode()
            ).hexdigest(),
        },
        "global_envelope_owner_lock": str(WORKSPACE_ROOT / GLOBAL_LOCK_NAME),
        "existing_developer_resources": (
            "not acquired; ports 3306/6379/8000 and unrelated Compose projects "
            "are outside lifecycle ownership"
        ),
    }


def _prepare_private_workspace(config: PerformanceRunConfig) -> None:
    _ensure_private_root(WORKSPACE_ROOT)
    _ensure_private_root(ARTIFACT_ROOT)
    if config.workspace.is_symlink() or config.workspace.exists():
        raise HarnessError("performance workspace must be absent and not a symlink")
    config.workspace.mkdir(mode=0o700, exist_ok=False)
    config.secret_dir.mkdir(mode=0o700)
    for name in SECRET_NAMES:
        length = 48 if name == "jwt_secret" else 32
        write_private(config.secret_dir / name, secrets.token_urlsafe(length))
    lines = [
        f"{key}={value}"
        for key, value in sorted(config.compose_environment().items())
    ]
    write_private(config.compose_env_path, "\n".join(lines))


def _ensure_private_root(path: Path) -> None:
    """Create or validate an owned 0700 directory below a trusted parent."""

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        path.mkdir(parents=True, mode=0o700, exist_ok=False)
        metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise HarnessError(
            "performance private root must be a real owned mode-0700 directory"
        )


def _validated_owned_workspace(config: PerformanceRunConfig) -> Path | None:
    """Resolve one exact run directory while tolerating macOS' /tmp symlink."""

    try:
        metadata = config.workspace.lstat()
    except FileNotFoundError:
        return None
    expected = WORKSPACE_ROOT.resolve() / config.run_id
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
        or config.workspace.name != config.run_id
        or config.workspace.resolve() != expected
        or expected.parent != WORKSPACE_ROOT.resolve()
    ):
        raise HarnessError("performance workspace ownership or identity is unsafe")
    return config.workspace


def _app_build_source_is_allowed(relative: Path) -> bool:
    text = relative.as_posix()
    return (
        text in {
            "requirements.txt",
            "pyproject.toml",
            "deploy/runtime/app-entrypoint.sh",
        }
        or text.startswith("app/")
        or text.startswith("migrations/")
    )


def _tree_digest(root: Path) -> tuple[str, int]:
    """Digest a private staged context and reject links or special files."""

    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise HarnessError("app build context contains a link or special file")
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(f"{metadata.st_mode & 0o777:o}".encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65_536), b""):
                digest.update(chunk)
        digest.update(b"\0")
        count += 1
    return digest.hexdigest(), count


def _prepare_app_build_context(
    config: PerformanceRunConfig,
    runner: CommandRunner,
) -> tuple[Path, dict[str, object]]:
    """Stage only Git-visible files named by the App Dockerfile COPY contract."""

    context = config.workspace / "app-build-context"
    context.mkdir(mode=0o700, exist_ok=False)
    listing = runner.run(
        [
            "git", "ls-files", "--cached",
            "-z", "--", "app", "migrations", "requirements.txt",
            "pyproject.toml", "deploy/runtime/app-entrypoint.sh",
        ],
        timeout=60,
    ).stdout
    relative_paths = [Path(value) for value in listing.split("\0") if value]
    required = {
        Path("requirements.txt"),
        Path("pyproject.toml"),
        Path("deploy/runtime/app-entrypoint.sh"),
    }
    if not required.issubset(relative_paths):
        raise HarnessError("app build context is missing a required tracked source")
    for relative in sorted(relative_paths):
        if relative.is_absolute() or ".." in relative.parts or not _app_build_source_is_allowed(relative):
            raise HarnessError("app build source escaped its allowlist")
        source = REPOSITORY_ROOT / relative
        metadata = source.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise HarnessError("app build source must be a regular file")
        destination = context / relative
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
    for source, destination_name in (
        (
            REPOSITORY_ROOT / "deploy" / "performance" / "Dockerfile.app",
            "Dockerfile",
        ),
        (
            REPOSITORY_ROOT
            / "deploy"
            / "performance"
            / "Dockerfile.app.dockerignore",
            ".dockerignore",
        ),
    ):
        metadata = source.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise HarnessError("performance Docker build contract is unavailable")
        shutil.copy2(source, context / destination_name, follow_symlinks=False)
    digest, file_count = _tree_digest(context)
    return context, {
        "sha256": digest,
        "file_count": file_count,
        "source_policy": (
            "Git-indexed files under exact Docker COPY paths; "
            "symlinks/special files rejected"
        ),
    }


def _build_images(stack: ComposeStack) -> dict[str, object]:
    app_context, app_context_identity = _prepare_app_build_context(
        stack.config, stack.runner
    )
    try:
        stack.runner.run(
            [
                "docker", "build", "--tag", stack.config.app_image,
                "--file", str(app_context / "Dockerfile"), str(app_context),
            ],
            timeout=1800,
        )
    finally:
        shutil.rmtree(app_context)
    stack.runner.run(
        [
            "docker", "build", "--tag", stack.config.shaper_image,
            "--file", str(REPOSITORY_ROOT / "deploy" / "performance" / "Dockerfile.shaper"),
            str(REPOSITORY_ROOT / "deploy" / "performance"),
        ],
        timeout=600,
    )
    stack.images_built = True
    result: dict[str, object] = {
        "app_build_context": app_context_identity,
    }
    for name, tag in (("app", stack.config.app_image), ("shaper", stack.config.shaper_image)):
        inspected = stack.runner.run(
            [
                "docker", "image", "inspect", tag, "--format",
                "{{json .Id}} {{json .Architecture}} {{json .Os}}",
            ],
            timeout=30,
        ).stdout.strip()
        parts = inspected.split(maxsplit=2)
        if len(parts) != 3:
            raise HarnessError("built image identity is unavailable")
        result[name] = {
            "id": json.loads(parts[0]),
            "architecture": json.loads(parts[1]),
            "os": json.loads(parts[2]),
        }
    return result


def _run_data_task(
    stack: ComposeStack,
    *arguments: str,
    timeout: float = 300,
) -> dict[str, Any]:
    result = stack.run(
        "run", "--rm", "--no-deps", "seed",
        "python", "-m", "scripts.performance.seed", *arguments,
        profile="operations",
        timeout=timeout,
    )
    return _parse_json_line(result.stdout)


def _prepare_stack(stack: ComposeStack) -> dict[str, object]:
    stack.run(
        "up", "--detach", "--wait", "--wait-timeout", "180", "mysql", "redis",
        timeout=240,
    )
    stack.started = True
    stack.run(
        "run", "--rm", "--no-deps", "migrate",
        profile="operations", timeout=600,
    )
    stack.run(
        "run", "--rm", "--no-deps", "image-init",
        profile="operations", timeout=120,
    )
    preview = stack.run(
        "run", "--rm", "--no-deps", "mard",
        profile="operations", timeout=300,
    )
    preview_result = _parse_json_line(preview.stdout)
    manifest_sha = preview_result.get("manifest_sha256")
    local_sha = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    if manifest_sha != local_sha:
        raise HarnessError("MARD preview is not bound to the local manifest")
    applied = stack.run(
        "run", "--rm", "--no-deps", "mard",
        "python", "-m", "app.tasks.gatea_mard_publish",
        "--apply", "--confirm-manifest-sha256", local_sha,
        profile="operations", timeout=300,
    )
    apply_result = _parse_json_line(applied.stdout)
    if apply_result.get("manifest_sha256") != local_sha:
        raise HarnessError("MARD apply did not preserve the preview identity")
    replayed = stack.run(
        "run", "--rm", "--no-deps", "mard",
        profile="operations", timeout=300,
    )
    replay_result = _parse_json_line(replayed.stdout)
    if (
        replay_result.get("manifest_sha256") != local_sha
        or replay_result.get("already_current") is not True
        or replay_result.get("database_changes") != 0
        or replay_result.get("images_to_create") != 0
        or replay_result.get("images_reused") != 221
    ):
        raise HarnessError("MARD post-apply replay is not an exact no-op")
    seed = stack.run(
        "run", "--rm", "--no-deps", "seed",
        profile="operations", timeout=600,
    )
    seed_result = _parse_json_line(seed.stdout)
    if seed_result.get("bead_colors") != 221 or seed_result.get("users") != 11:
        raise HarnessError("synthetic seed result differs from the frozen profile")
    stack.run(
        "up", "--detach", "--wait", "--wait-timeout", "180",
        "app", "edge", "shaper", timeout=300,
    )
    runtime_envelope = _verify_runtime_envelope(stack)
    runtime_images = _runtime_image_identity(stack)
    return {
        "mard_preview": preview_result,
        "mard_apply": apply_result,
        "mard_replay_preview": replay_result,
        "seed": seed_result,
        "runtime_envelope": runtime_envelope,
        "runtime_images": runtime_images,
        "operations_measurement_policy": (
            "one-off image-init/migrate/mard/seed tasks run only outside formal "
            "profile windows; snapshot/verify seed tasks may briefly coexist with "
            "steady services outside measurement. Their 128/1280MiB limits are "
            "excluded from the five-service measured 4096MiB envelope"
        ),
    }


def _verify_runtime_envelope(stack: ComposeStack) -> dict[str, object]:
    """Fail closed if Docker did not apply the exact two-core/4GiB limits."""

    result: dict[str, object] = {}
    for service, identifier in stack.service_container_ids().items():
        command = stack.runner.run(
            [
                "docker", "inspect", identifier, "--format",
                "{{json .HostConfig}}",
            ],
            timeout=20,
        )
        host_config = json.loads(command.stdout)
        cgroup = stack.runner.run(
            [
                "docker", "exec", identifier, "/bin/sh", "-ec",
                "test -r /sys/fs/cgroup/cpuset.cpus.effective; "
                "test -r /sys/fs/cgroup/cpu.max; "
                "test -r /sys/fs/cgroup/memory.max; "
                "test -r /sys/fs/cgroup/memory.swap.max; "
                "printf 'cpuset_effective='; "
                "cat /sys/fs/cgroup/cpuset.cpus.effective; "
                "printf 'cpu_max='; cat /sys/fs/cgroup/cpu.max; "
                "printf 'memory_max='; cat /sys/fs/cgroup/memory.max; "
                "printf 'memory_swap_max='; cat /sys/fs/cgroup/memory.swap.max",
            ],
            timeout=20,
        )
        cgroup_lines = dict(
            line.split("=", 1)
            for line in cgroup.stdout.splitlines()
            if "=" in line
        )
        cpu_max_parts = cgroup_lines.get("cpu_max", "").split()
        expected_memory = SERVICE_MEMORY_LIMIT_MIB[service] * 1024**2
        observed = {
            "cpuset_cpus": host_config.get("CpusetCpus"),
            "memory_bytes": host_config.get("Memory"),
            "memory_swap_bytes": host_config.get("MemorySwap"),
            "nano_cpus": host_config.get("NanoCpus"),
            "cpuset_cpus_effective": cgroup_lines.get("cpuset_effective"),
            "cpu_max": cgroup_lines.get("cpu_max"),
            "memory_max_bytes": cgroup_lines.get("memory_max"),
            "memory_swap_max_bytes": cgroup_lines.get("memory_swap_max"),
        }
        if (
            observed["cpuset_cpus"] != stack.config.cpuset
            or observed["memory_bytes"] != expected_memory
            or observed["memory_swap_bytes"] != expected_memory
            or observed["nano_cpus"] != 0
            or observed["cpuset_cpus_effective"] != stack.config.cpuset
            or len(cpu_max_parts) != 2
            or cpu_max_parts[0] != "max"
            or not cpu_max_parts[1].isdigit()
            or observed["memory_max_bytes"] != str(expected_memory)
            or observed["memory_swap_max_bytes"] != "0"
        ):
            raise HarnessError(
                f"Docker runtime resource envelope differs for service={service}"
            )
        result[service] = observed
    return result


def _runtime_image_identity(stack: ComposeStack) -> dict[str, object]:
    """Record actual container image IDs and available immutable RepoDigests."""

    expected_tags = {
        "mysql": "mysql:8.0.46",
        "redis": "redis:8.0.1-alpine",
        "app": stack.config.app_image,
        "edge": "nginx:1.27.5-alpine",
        "shaper": stack.config.shaper_image,
    }
    engine_architecture = stack.runner.run(
        ["docker", "info", "--format", "{{.Architecture}}"], timeout=30
    ).stdout.strip().lower()
    architecture_aliases = {"x86_64": "amd64", "aarch64": "arm64"}
    engine_architecture = architecture_aliases.get(
        engine_architecture, engine_architecture
    )
    result: dict[str, object] = {
        "docker_server_architecture": engine_architecture,
        "cross_architecture_emulation": False,
    }
    for service, identifier in stack.service_container_ids().items():
        container = stack.runner.run(
            [
                "docker", "inspect", identifier, "--format",
                "{{json .Image}}|{{json .Config.Image}}",
            ],
            timeout=20,
        ).stdout.strip()
        image_id_raw, configured_tag_raw = container.split("|", 1)
        image_id = json.loads(image_id_raw)
        configured_tag = json.loads(configured_tag_raw)
        if configured_tag != expected_tags[service]:
            raise HarnessError(f"runtime image tag differs for service={service}")
        image = stack.runner.run(
            [
                "docker", "image", "inspect", image_id, "--format",
                "{{json .Id}}|{{json .RepoDigests}}|{{json .Architecture}}|{{json .Os}}",
            ],
            timeout=20,
        ).stdout.strip()
        parts = image.split("|", 3)
        if len(parts) != 4 or json.loads(parts[0]) != image_id:
            raise HarnessError(f"runtime image identity is unavailable: {service}")
        architecture = str(json.loads(parts[2])).lower()
        architecture = architecture_aliases.get(architecture, architecture)
        if architecture != engine_architecture:
            raise HarnessError(
                f"runtime image uses cross-architecture emulation: service={service}"
            )
        result[service] = {
            "configured_tag": configured_tag,
            "image_id": image_id,
            "repo_digests": json.loads(parts[1]),
            "architecture": architecture,
            "os": json.loads(parts[3]),
        }
    return result


def _parse_size(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?i?B)\s*", value)
    if match is None:
        raise ValueError("unrecognized Docker size")
    number = float(match.group(1))
    factors = {
        "B": 1,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "TiB": 1024**4,
    }
    return int(number * factors[match.group(2)])


def _parse_docker_stats(output: str) -> tuple[dict[str, object], float, int]:
    services: dict[str, object] = {}
    total_cpu = 0.0
    total_memory = 0
    for line in output.splitlines():
        if not line.strip():
            continue
        document = json.loads(line)
        name = str(document.get("Name", ""))
        cpu = float(str(document["CPUPerc"]).rstrip("%"))
        used = str(document["MemUsage"]).split("/")[0].strip()
        memory = _parse_size(used)
        services[name] = {
            "cpu_single_core_percent": cpu,
            "memory_bytes": memory,
            "memory_percent_of_limit": document.get("MemPerc"),
            "net_io": document.get("NetIO"),
            "block_io": document.get("BlockIO"),
            "pids": document.get("PIDs"),
        }
        total_cpu += cpu
        total_memory += memory
    # docker stats treats one core as 100%; the shared envelope has two cores.
    return services, total_cpu / 2.0, total_memory


def _qdisc_counters(output: str) -> dict[str, object]:
    try:
        document = json.loads(output)
    except json.JSONDecodeError as error:
        raise HarnessError("qdisc output is not JSON") from error
    if not isinstance(document, list):
        raise HarnessError("qdisc output has an unexpected shape")
    tbf = next(
        (item for item in document if isinstance(item, dict) and item.get("kind") == "tbf"),
        None,
    )
    if tbf is None:
        raise HarnessError("client-facing TBF qdisc is absent")

    def find(name: str, value: object) -> int | None:
        if isinstance(value, dict):
            candidate = value.get(name)
            if (
                isinstance(candidate, (int, float))
                and not isinstance(candidate, bool)
                and math.isfinite(float(candidate))
                and float(candidate).is_integer()
                and candidate >= 0
            ):
                return int(candidate)
            for nested in value.values():
                found = find(name, nested)
                if found is not None:
                    return found
        if isinstance(value, list):
            for nested in value:
                found = find(name, nested)
                if found is not None:
                    return found
        return None

    counters = {
        name: find(name, tbf)
        for name in (
            "bytes", "packets", "drops", "overlimits", "requeues", "backlog"
        )
    }
    if any(value is None for value in counters.values()):
        raise HarnessError("client-facing TBF counters are incomplete")
    options = tbf.get("options")
    if not isinstance(options, dict):
        raise HarnessError("client-facing TBF configuration is unavailable")

    def option(name: str) -> int:
        value = options.get(name)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or not float(value).is_integer()
            or value <= 0
        ):
            raise HarnessError("client-facing TBF configuration is malformed")
        return int(value)

    rate = option("rate")
    burst = option("burst")
    latency_microseconds = option("lat")
    configuration = {
        "rate_bytes_per_second": rate,
        "burst_bytes": burst,
        "latency_microseconds": latency_microseconds,
        "latency_milliseconds": round(latency_microseconds / 1000, 6),
    }
    if not _tbf_configuration_is_expected(configuration):
        raise HarnessError("client-facing TBF configuration differs from the frozen envelope")

    return {
        **counters,
        "configuration": configuration,
    }


def _parse_key_value_lines(output: str) -> dict[str, int | str]:
    result: dict[str, int | str] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        if "\t" in line:
            key, value = line.split("\t", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        value = value.strip().rstrip("\r")
        try:
            result[key.strip()] = int(value)
        except ValueError:
            result[key.strip()] = value
    return result


def _parse_cgroup_memory(output: str) -> dict[str, object]:
    values: dict[str, object] = {"available": False}
    for line in output.splitlines():
        normalized = line.strip()
        if normalized == "available=1":
            values["available"] = True
            continue
        if normalized == "available=0":
            values["available"] = False
            continue
        if "=" in normalized:
            key, raw = normalized.split("=", 1)
        elif " " in normalized:
            key, raw = normalized.split(None, 1)
        else:
            continue
        try:
            values[key] = int(raw)
        except ValueError:
            continue
    return values


class ProfileMonitor:
    """One-second out-of-envelope Docker/qdisc/dependency sampler."""

    MYSQL_QUERY = (
        "SHOW GLOBAL STATUS WHERE Variable_name IN "
        "('Questions','Threads_connected','Threads_running','Slow_queries',"
        "'Innodb_row_lock_current_waits','Innodb_row_lock_time',"
        "'Innodb_row_lock_waits'); "
        "SELECT 'Innodb_deadlocks', COUNT FROM information_schema.INNODB_METRICS "
        "WHERE NAME = 'lock_deadlocks'"
    )

    def __init__(
        self,
        stack: ComposeStack,
        client: httpx.AsyncClient,
        *,
        profile: str,
        sample_interval: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
    ) -> None:
        self.stack = stack
        self.client = client
        self.profile = profile
        self.sample_interval = sample_interval
        self.container_ids = stack.service_container_ids()
        self.samples: list[dict[str, object]] = []
        self.errors: list[str] = []
        self.readiness_failures = 0
        self._last_health = 0.0
        self.fatal_event = asyncio.Event()
        self.fatal_reason: str | None = None

    def qdisc(self) -> dict[str, object]:
        result = self.stack.runner.run(
            [
                "docker", "exec", self.container_ids["shaper"], "/bin/sh", "-ec",
                'iface="$(cat /run/performance-client-interface)"; '
                'exec tc -s -j qdisc show dev "$iface"',
            ],
            timeout=20,
        )
        return _qdisc_counters(result.stdout)

    def state(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for service, identifier in self.container_ids.items():
            inspected = self.stack.runner.run(
                [
                    "docker", "inspect", identifier, "--format",
                    "{{json .State}}|{{.RestartCount}}",
                ],
                timeout=20,
            ).stdout.strip()
            state_raw, restart_raw = inspected.rsplit("|", 1)
            state = json.loads(state_raw)
            cgroup = self.stack.runner.run(
                [
                    "docker", "exec", identifier, "/bin/sh", "-ec",
                    "if test -r /sys/fs/cgroup/memory.events && "
                    "test -r /sys/fs/cgroup/memory.swap.current; then "
                    "printf 'available=1\\n'; cat /sys/fs/cgroup/memory.events; "
                    "printf 'swap_current='; cat /sys/fs/cgroup/memory.swap.current; "
                    "else printf 'available=0\\n'; fi",
                ],
                check=False,
                timeout=20,
            )
            cgroup_values = _parse_cgroup_memory(cgroup.stdout)
            result[service] = {
                "running": state.get("Running"),
                "status": state.get("Status"),
                "oom_killed": state.get("OOMKilled"),
                "exit_code": state.get("ExitCode"),
                "restart_count": int(restart_raw),
                "memory_cgroup": cgroup_values,
            }
        return result

    def route_identity(self) -> dict[str, object]:
        result = self.stack.runner.run(
            [
                "docker", "exec", self.container_ids["shaper"], "/bin/sh", "-ec",
                'iface="$(cat /run/performance-client-interface)"; '
                'printf "%s\\n" "$iface"; ip -j route show default',
            ],
            timeout=20,
        )
        lines = result.stdout.splitlines()
        if len(lines) < 2:
            raise HarnessError("client-facing route identity is unavailable")
        route = json.loads("\n".join(lines[1:]))
        if not isinstance(route, list) or len(route) != 1:
            raise HarnessError("client-facing default route is not unique")
        if route[0].get("dev") != lines[0].strip():
            raise HarnessError("shaped interface differs from the default route")
        return {"interface": lines[0].strip(), "default_route": route[0]}

    def _sample_sync(self) -> dict[str, object]:
        ids = list(self.container_ids.values())
        stats = self.stack.runner.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],
            timeout=30,
        )
        services, cpu, docker_stats_memory = _parse_docker_stats(stats.stdout)
        cgroup_memory: dict[str, dict[str, int]] = {}
        memory = 0
        swap = 0
        for service, identifier in self.container_ids.items():
            current = self.stack.runner.run(
                [
                    "docker", "exec", identifier, "/bin/sh", "-ec",
                    "test -r /sys/fs/cgroup/memory.current; "
                    "printf 'memory_current='; cat /sys/fs/cgroup/memory.current; "
                    "printf 'swap_current='; cat /sys/fs/cgroup/memory.swap.current",
                ],
                timeout=20,
            )
            parsed = _parse_cgroup_memory(current.stdout)
            if not isinstance(parsed.get("memory_current"), int) or not isinstance(
                parsed.get("swap_current"), int
            ):
                raise HarnessError("cgroup memory.current sample is unavailable")
            cgroup_memory[service] = {
                "memory_current": int(parsed["memory_current"]),
                "swap_current": int(parsed["swap_current"]),
            }
            memory += int(parsed["memory_current"])
            swap += int(parsed["swap_current"])
        qdisc = self.qdisc()
        mysql = self.stack.runner.run(
            [
                "docker", "exec", self.container_ids["mysql"], "/bin/sh", "-ec",
                'MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"; '
                "export MYSQL_PWD; "
                f'exec mysql --batch --skip-column-names --user=root '
                f'--execute="{self.MYSQL_QUERY}"',
            ],
            timeout=20,
        )
        redis = self.stack.runner.run(
            [
                "docker", "exec", self.container_ids["redis"], "/bin/sh", "-ec",
                'REDISCLI_AUTH="$(cat /run/secrets/redis_password)"; '
                "export REDISCLI_AUTH; exec redis-cli --no-auth-warning INFO",
            ],
            timeout=20,
        )
        process_rss = self.stack.runner.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            check=False,
            timeout=10,
        )
        rss_text = process_rss.stdout.strip()
        rss_bytes = (
            int(rss_text) * 1024
            if process_rss.returncode == 0 and rss_text.isdigit()
            else None
        )
        host_available_memory = _host_available_memory_bytes(self.stack.runner)
        host_disk_free = shutil.disk_usage(self.stack.config.artifact_dir).free
        return {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "captured_at_epoch": time.time(),
            "profile": self.profile,
            "services": services,
            "cgroup_memory": cgroup_memory,
            "stack_cpu_percent_of_two_cores": round(cpu, 6),
            "stack_memory_bytes": memory,
            "stack_swap_bytes": swap,
            "docker_stats_stack_memory_bytes": docker_stats_memory,
            "qdisc": qdisc,
            "load_generator_cpu_seconds": time.process_time(),
            "load_generator_rss_bytes": rss_bytes,
            "host_available_memory_bytes": host_available_memory,
            "host_disk_free_bytes": host_disk_free,
            "mysql": _parse_key_value_lines(mysql.stdout),
            "redis": {
                key: value
                for key, value in _parse_key_value_lines(redis.stdout).items()
                if key
                in {
                    "connected_clients", "used_memory", "used_memory_peak",
                    "evicted_keys", "instantaneous_ops_per_sec", "rejected_connections",
                }
            },
        }

    def _host_guard_failure(self, sample: Mapping[str, object]) -> str | None:
        available = sample.get("host_available_memory_bytes")
        disk_free = sample.get("host_disk_free_bytes")
        rss = sample.get("load_generator_rss_bytes")
        if not isinstance(available, int):
            return "host_memory_evidence_unavailable"
        if available < MIN_RUNTIME_HOST_MEMORY_AVAILABLE_BYTES:
            return "host_memory_safety_floor"
        if not isinstance(disk_free, int):
            return "host_disk_evidence_unavailable"
        if disk_free < MIN_RUNTIME_DISK_FREE_BYTES:
            return "host_disk_safety_floor"
        if not isinstance(rss, int):
            return "load_generator_rss_unavailable"
        if rss >= LOAD_GENERATOR_RSS_GATE_BYTES:
            return "load_generator_rss_gate"
        return None

    async def _health(self) -> None:
        try:
            response = await self.client.get(
                "/api/v1/health/ready",
                headers={"Accept-Encoding": "identity"},
            )
            if response.status_code != 200:
                self.readiness_failures += 1
        except httpx.HTTPError:
            self.readiness_failures += 1

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            started = time.monotonic()
            try:
                sample = await asyncio.to_thread(self._sample_sync)
                self.samples.append(sample)
                guard_failure = self._host_guard_failure(sample)
                if guard_failure is not None:
                    self.errors.append(guard_failure)
                    self.fatal_reason = guard_failure
                    self.fatal_event.set()
                    return
                if started - self._last_health >= DEFAULT_HEALTH_INTERVAL_SECONDS:
                    await self._health()
                    self._last_health = started
                    if self.readiness_failures:
                        self.fatal_reason = "readiness_failure"
                        self.fatal_event.set()
                        return
                delay = max(
                    0.0, self.sample_interval - (time.monotonic() - started)
                )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
            except Exception as error:
                # Only the exception type is persisted. Command output and exception
                # messages can contain credentials or request context.
                self.errors.append(type(error).__name__)
                self.fatal_reason = "metric_sample_failure"
                self.fatal_event.set()
                return


def _longest_duration(
    samples: Sequence[Mapping[str, object]],
    threshold: float,
) -> float:
    longest = 0.0
    run_started: float | None = None
    previous: float | None = None
    for sample in samples:
        captured = sample.get("captured_at_epoch")
        cpu = sample.get("stack_cpu_percent_of_two_cores")
        if not isinstance(captured, (int, float)) or not isinstance(cpu, (int, float)):
            continue
        timestamp = float(captured)
        if float(cpu) > threshold:
            if run_started is None:
                run_started = timestamp
            previous = timestamp
            longest = max(
                longest,
                timestamp - run_started + DEFAULT_SAMPLE_INTERVAL_SECONDS,
            )
        else:
            run_started = None
            previous = None
    if run_started is not None and previous is not None:
        longest = max(
            longest,
            previous - run_started + DEFAULT_SAMPLE_INTERVAL_SECONDS,
        )
    return round(longest, 6)


def _half_growth(values: Sequence[int]) -> float | None:
    if len(values) < 4:
        return None
    midpoint = len(values) // 2
    first = sum(values[:midpoint]) / midpoint
    second_values = values[midpoint:]
    second = sum(second_values) / len(second_values)
    if first == 0:
        return None
    return round((second - first) / first, 6)


def _dependency_window(
    samples: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if not samples:
        return {"start": {}, "end": {}, "deltas": {}}
    start = dict(samples[0])
    end = dict(samples[-1])
    deltas: dict[str, int] = {}
    for key, end_value in end.items():
        start_value = start.get(key)
        if isinstance(start_value, int) and isinstance(end_value, int):
            deltas[key] = end_value - start_value
    return {"start": start, "end": end, "deltas": deltas}


def _longest_network_duration(
    samples: Sequence[Mapping[str, object]],
    threshold_mbps: float,
) -> float:
    longest = 0.0
    current = 0.0
    previous: Mapping[str, object] | None = None
    for sample in samples:
        if previous is None:
            previous = sample
            continue
        before_time = previous.get("captured_at_epoch")
        after_time = sample.get("captured_at_epoch")
        before_qdisc = previous.get("qdisc")
        after_qdisc = sample.get("qdisc")
        if (
            not isinstance(before_time, (int, float))
            or not isinstance(after_time, (int, float))
            or not isinstance(before_qdisc, dict)
            or not isinstance(after_qdisc, dict)
        ):
            current = 0.0
            previous = sample
            continue
        elapsed = float(after_time) - float(before_time)
        byte_delta = int(after_qdisc.get("bytes", 0)) - int(
            before_qdisc.get("bytes", 0)
        )
        mbps = byte_delta * 8 / elapsed / 1_000_000 if elapsed > 0 else 0.0
        if mbps > threshold_mbps:
            current += elapsed
            longest = max(longest, current)
        else:
            current = 0.0
        previous = sample
    return round(longest, 6)


def _state_is_healthy(start: object, end: object) -> bool:
    if not isinstance(start, dict) or not isinstance(end, dict):
        return False
    for service in STEADY_SERVICES:
        before = start.get(service)
        after = end.get(service)
        if not isinstance(before, dict) or not isinstance(after, dict):
            return False
        if (
            after.get("running") is not True
            or after.get("oom_killed") is not False
            or after.get("restart_count") != before.get("restart_count")
        ):
            return False
        before_cgroup = before.get("memory_cgroup")
        after_cgroup = after.get("memory_cgroup")
        if not isinstance(before_cgroup, dict) or not isinstance(after_cgroup, dict):
            return False
        swap_current = after_cgroup.get("swap_current")
        if (
            before_cgroup.get("available") is not True
            or after_cgroup.get("available") is not True
            or not isinstance(swap_current, int)
            or swap_current != 0
        ):
            return False
        for counter in ("high", "max", "oom", "oom_kill"):
            before_value = before_cgroup.get(counter)
            after_value = after_cgroup.get(counter)
            if (
                not isinstance(before_value, int)
                or not isinstance(after_value, int)
                or after_value != before_value
            ):
                return False
    return True


def evaluate_profile(
    load: Mapping[str, object],
    monitor: Mapping[str, object],
) -> dict[str, object]:
    """Apply the pre-frozen Runbook gates without retroactive relaxation."""

    profile = str(load["profile"])
    failures: list[str] = []
    if not _profile_evidence_is_complete(load, monitor):
        failures.append("profile_evidence_incomplete")
    if load.get("failed_requests") != 0:
        failures.append("unexpected_request_failure")
    if monitor.get("sample_errors"):
        failures.append("metric_sample_failure")
    if monitor.get("readiness_failures") != 0:
        failures.append("readiness_failure")
    if not _state_is_healthy(monitor.get("state_start"), monitor.get("state_end")):
        failures.append("container_restart_exit_or_oom")
    qdisc = monitor.get("qdisc")
    if not isinstance(qdisc, dict):
        failures.append("qdisc_evidence_missing")
    else:
        if int(qdisc.get("bytes_delta", 0)) <= 0:
            failures.append("qdisc_bytes_not_increasing")
        if int(qdisc.get("drops_delta", 0)) != 0:
            failures.append("qdisc_drop")
        if profile.startswith("A-"):
            mbps = float(qdisc.get("average_mbps", 0))
            if int(qdisc.get("overlimits_delta", 0)) <= 0:
                failures.append("qdisc_overlimits_not_increasing")
            if not 4.75 <= mbps <= 5.05:
                failures.append("aggregate_5mbps_not_demonstrated")
        if profile == "B-authenticated-browse" and float(
            qdisc.get("average_mbps", 0)
        ) >= 4.25:
            failures.append("normal_network_above_85_percent")
        if profile == "B-authenticated-browse" and float(
            qdisc.get("continuous_seconds_above_4_5_mbps", 0)
        ) >= 30:
            failures.append("normal_network_sustained_above_90_percent")

    cpu = monitor.get("cpu")
    if not isinstance(cpu, dict) or cpu.get("average_percent_of_two_cores") is None:
        failures.append("cpu_evidence_missing")
    else:
        if float(cpu["average_percent_of_two_cores"]) >= 70:
            failures.append("average_cpu_gate")
        if int(cpu.get("continuous_seconds_above_85", 0)) >= 30:
            failures.append("sustained_cpu_gate")
    memory = monitor.get("memory")
    if not isinstance(memory, dict) or memory.get("peak_bytes") is None:
        failures.append("memory_evidence_missing")
    else:
        if int(memory["peak_bytes"]) >= PROFILE_MEMORY_GATE_BYTES:
            failures.append("memory_peak_gate")
        growth = memory.get("second_half_growth_ratio")
        if growth is not None and float(growth) > 0.10:
            failures.append("memory_growth_gate")
        if memory.get("swap_peak_bytes") is None or int(
            memory["swap_peak_bytes"]
        ) != 0:
            failures.append("swap_usage_gate")

    load_generator = monitor.get("load_generator")
    if not isinstance(load_generator, dict):
        failures.append("load_generator_evidence_missing")
    else:
        loader_cpu = load_generator.get("process_cpu_percent_of_one_core")
        loader_rss = load_generator.get("rss_peak_bytes")
        if loader_cpu is None or float(loader_cpu) >= 70:
            failures.append("load_generator_cpu_gate")
        if loader_rss is None or int(loader_rss) >= LOAD_GENERATOR_RSS_GATE_BYTES:
            failures.append("load_generator_rss_gate")
    host_safety = monitor.get("host_safety")
    if not isinstance(host_safety, dict):
        failures.append("host_safety_evidence_missing")
    else:
        available = host_safety.get("available_memory_min_bytes")
        disk_free = host_safety.get("disk_free_min_bytes")
        if (
            available is None
            or int(available) < MIN_RUNTIME_HOST_MEMORY_AVAILABLE_BYTES
        ):
            failures.append("host_memory_safety_gate")
        if disk_free is None or int(disk_free) < MIN_RUNTIME_DISK_FREE_BYTES:
            failures.append("host_disk_safety_gate")
    sampling = monitor.get("sampling")
    if not isinstance(sampling, dict):
        failures.append("metric_sampling_evidence_missing")
    else:
        maximum_interval = sampling.get("maximum_interval_seconds")
        if not _finite_number(maximum_interval) or float(maximum_interval) < 0:
            failures.append("metric_sampling_evidence_missing")
        elif float(maximum_interval) > 5:
            failures.append("metric_sampling_gap_gate")

    mysql = monitor.get("mysql")
    if not _dependency_window_is_complete(
        mysql,
        counter_keys=("Innodb_deadlocks", "Slow_queries"),
        gauge_keys=("Innodb_row_lock_current_waits",),
    ):
        failures.append("mysql_evidence_missing")
    else:
        assert isinstance(mysql, Mapping)
        mysql_end = mysql["end"]
        mysql_deltas = mysql["deltas"]
        assert isinstance(mysql_end, Mapping)
        assert isinstance(mysql_deltas, Mapping)
        if int(mysql_end["Innodb_row_lock_current_waits"]) != 0:
            failures.append("mysql_lock_wait_not_drained")
        if int(mysql_deltas["Innodb_deadlocks"]) != 0:
            failures.append("mysql_deadlock")
        if int(mysql_deltas["Slow_queries"]) != 0:
            failures.append("mysql_slow_query")
    redis = monitor.get("redis")
    if not _dependency_window_is_complete(
        redis,
        counter_keys=("evicted_keys", "rejected_connections"),
    ):
        failures.append("redis_evidence_missing")
    else:
        assert isinstance(redis, Mapping)
        redis_deltas = redis["deltas"]
        assert isinstance(redis_deltas, Mapping)
        if (
            int(redis_deltas["evicted_keys"]) != 0
            or int(redis_deltas["rejected_connections"]) != 0
        ):
            failures.append("redis_eviction_or_rejection")

    latency = load.get("latency_ms")
    operations = load.get("operations")
    if not isinstance(operations, dict) or not operations:
        failures.append("per_operation_latency_missing")
    else:
        scenario_key = profile[0] if profile and profile[0] in ALL_SCENARIOS else ""
        if set(operations) != EXPECTED_PROFILE_OPERATIONS.get(scenario_key, set()):
            failures.append("profile_operation_coverage")
        for operation_summary in operations.values():
            if not isinstance(operation_summary, dict):
                failures.append("per_operation_latency_missing")
                continue
            operation_latency = operation_summary.get("latency_ms")
            if not isinstance(operation_latency, dict):
                failures.append("per_operation_latency_missing")
                continue
            if profile.startswith(("A-", "B-", "C-")) and (
                operation_latency.get("p95") is None
                or float(operation_latency["p95"]) >= 1000
            ):
                failures.append("per_operation_read_p95_gate")
            if profile.startswith("D-") and (
                operation_latency.get("p95") is None
                or float(operation_latency["p95"]) >= 2000
            ):
                failures.append("per_operation_write_p95_gate")
            if profile == "B-authenticated-browse" and int(load.get("vus", 0)) == 10:
                if (
                    operation_latency.get("p95") is None
                    or float(operation_latency["p95"]) > 800
                    or
                    operation_latency.get("p99") is None
                    or float(operation_latency["p99"]) > 2000
                    or operation_latency.get("max") is None
                    or float(operation_latency["max"]) >= 5000
                ):
                    failures.append("per_operation_json_tail_gate")
    if isinstance(latency, dict):
        if profile.startswith(("A-", "B-", "C-")) and (
            latency.get("p95") is None or float(latency["p95"]) >= 1000
        ):
            failures.append("read_p95_gate")
        if profile == "B-authenticated-browse" and int(load.get("vus", 0)) == 10:
            if (
                latency.get("p95") is None
                or float(latency["p95"]) > 800
                or latency.get("p99") is None
                or float(latency["p99"]) > 2000
                or latency.get("max") is None
                or float(latency["max"]) >= 5000
            ):
                failures.append("json_latency_gate")
        if profile.startswith("D-") and (
            latency.get("p95") is None or float(latency["p95"]) >= 2000
        ):
            failures.append("write_p95_gate")
    return {"passed": not failures, "failures": sorted(set(failures))}


async def _measure(
    stack: ComposeStack,
    client: httpx.AsyncClient,
    evidence: EvidenceWriter,
    *,
    profile_factory: Callable[[], Any],
    profile_label: str,
) -> tuple[dict[str, object], int]:
    monitor = ProfileMonitor(stack, client, profile=profile_label)
    route = monitor.route_identity()
    state_start = monitor.state()
    boundary_start = await asyncio.to_thread(monitor._sample_sync)
    boundary_guard = monitor._host_guard_failure(boundary_start)
    if boundary_guard is not None:
        raise HarnessError(f"profile boundary failed host guard: {boundary_guard}")
    monitor.samples.append(boundary_start)
    qdisc_start = dict(boundary_start["qdisc"])
    stop = asyncio.Event()
    monitor_task = asyncio.create_task(monitor.run(stop))
    profile_task = asyncio.create_task(profile_factory())
    fatal_task = asyncio.create_task(monitor.fatal_event.wait())
    started = time.monotonic()
    result: ProfileResult | None = None
    profile_error: BaseException | None = None
    try:
        done, _ = await asyncio.wait(
            (profile_task, fatal_task, monitor_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        monitor_stopped_early = monitor_task in done
        if (
            monitor_stopped_early
            or (fatal_task in done and monitor.fatal_event.is_set())
        ):
            if not profile_task.done():
                profile_task.cancel()
            try:
                result = await profile_task
            except ProfileExecutionError as error:
                result = error.result
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException:
                pass
            profile_error = HarnessError(
                "profile monitor stopped the run: "
                f"{monitor.fatal_reason or 'metric_monitor_stopped'}"
            )
        else:
            try:
                result = profile_task.result()
            except ProfileExecutionError as error:
                result = error.result
                profile_error = error
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as error:
                profile_error = error
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit) as error:
        profile_error = error
    finally:
        if not profile_task.done():
            profile_task.cancel()
        outcome = (await asyncio.gather(profile_task, return_exceptions=True))[0]
        if result is None and isinstance(outcome, ProfileExecutionError):
            result = outcome.result
        stop.set()
        fatal_task.cancel()
        await asyncio.gather(fatal_task, return_exceptions=True)
        await monitor_task
    elapsed = time.monotonic() - started
    boundary_end = await asyncio.to_thread(monitor._sample_sync)
    monitor.samples.append(boundary_end)
    boundary_guard = monitor._host_guard_failure(boundary_end)
    if boundary_guard is not None and profile_error is None:
        profile_error = HarnessError(
            f"profile end boundary failed host guard: {boundary_guard}"
        )
    qdisc_end = dict(boundary_end["qdisc"])
    state_end = monitor.state()
    byte_delta = qdisc_end.get("bytes", 0) - qdisc_start.get("bytes", 0)
    monitor_result = ProfileMonitorResult(
        profile=profile_label,
        samples=monitor.samples,
        qdisc_start=qdisc_start,
        qdisc_end=qdisc_end,
        qdisc_mbps=byte_delta * 8 / max(elapsed, 0.001) / 1_000_000,
        readiness_failures=monitor.readiness_failures,
        state_start=state_start,
        state_end=state_end,
        errors=monitor.errors,
    )
    load_summary = (
        result.summary()
        if result is not None
        else {
            "profile": profile_label,
            "round": None,
            "vus": None,
            "completed_requests": 0,
            "failed_requests": 1,
            "completed_journeys": 0,
            "rps": 0,
            "latency_ms": {},
            "failure_type": type(profile_error).__name__ if profile_error else "unknown",
        }
    )
    monitor_summary = monitor_result.summary()
    verdict = evaluate_profile(load_summary, monitor_summary)
    safe_id = re.sub(r"[^a-z0-9-]+", "-", profile_label.lower()).strip("-")
    if result is not None:
        assert hasattr(result.samples, "evidence_records")
        evidence.append_jsonl(
            "request-samples.jsonl",
            result.samples.evidence_records(),
        )
    evidence.append_jsonl("metric-samples.jsonl", monitor.samples)
    failure_handling = classify_profile_failure(
        verdict,
        load=load_summary,
        monitor=monitor_summary,
        result_complete=result is not None,
        profile_error_present=profile_error is not None,
    )
    combined = {
        "load": load_summary,
        "monitor": monitor_summary,
        "route_identity": route,
        "verdict": verdict,
        "failure_handling": failure_handling,
    }
    evidence.write_json(f"profile-{safe_id}.json", combined)
    completed_journeys = result.completed_journeys if result is not None else 0
    if isinstance(
        profile_error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
    ):
        raise profile_error
    if profile_error is not None:
        raise ProfileRunFailure(
            f"profile aborted after recording evidence: {profile_label}",
            completed_journeys,
        ) from profile_error
    if failure_handling["disposition"] == PROFILE_DISPOSITION_ABORT:
        raise ProfileRunFailure(
            f"profile failed its frozen gates: {profile_label}",
            completed_journeys,
        )
    assert result is not None
    return combined, result.completed_journeys


SETUP_ONLY_IGNORED_GATES = {
    "aggregate_5mbps_not_demonstrated",
    "average_cpu_gate",
    "json_latency_gate",
    "normal_network_above_85_percent",
    "normal_network_sustained_above_90_percent",
    "memory_growth_gate",
    "per_operation_json_tail_gate",
    "per_operation_read_p95_gate",
    "per_operation_write_p95_gate",
    "qdisc_overlimits_not_increasing",
    "read_p95_gate",
    "sustained_cpu_gate",
    "write_p95_gate",
}


async def _unmeasured_phase(
    stack: ComposeStack,
    client: httpx.AsyncClient,
    factory: Callable[[], Any],
    evidence: EvidenceWriter,
    *,
    phase_label: str,
) -> int:
    """Run ramp/warm-up with the same fail-fast host and service sentinel."""

    monitor = ProfileMonitor(stack, client, profile=phase_label)
    state_start = monitor.state()
    boundary_start = await asyncio.to_thread(monitor._sample_sync)
    guard = monitor._host_guard_failure(boundary_start)
    if guard is not None:
        raise ProfileRunFailure(f"unmeasured phase host guard failed: {guard}")
    monitor.samples.append(boundary_start)
    qdisc_start = dict(boundary_start["qdisc"])
    stop = asyncio.Event()
    monitor_task = asyncio.create_task(monitor.run(stop))
    profile_task = asyncio.create_task(factory())
    fatal_task = asyncio.create_task(monitor.fatal_event.wait())
    result: ProfileResult | None = None
    profile_error: BaseException | None = None
    started = time.monotonic()
    try:
        done, _ = await asyncio.wait(
            (profile_task, fatal_task, monitor_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        monitor_stopped_early = monitor_task in done
        if (
            monitor_stopped_early
            or (fatal_task in done and monitor.fatal_event.is_set())
        ):
            if not profile_task.done():
                profile_task.cancel()
            try:
                result = await profile_task
            except ProfileExecutionError as error:
                result = error.result
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException:
                pass
            profile_error = HarnessError(
                "setup monitor stopped the load: "
                f"{monitor.fatal_reason or 'metric_monitor_stopped'}"
            )
        else:
            try:
                result = profile_task.result()
            except ProfileExecutionError as error:
                result = error.result
                profile_error = error
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as error:
                profile_error = error
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit) as error:
        profile_error = error
    finally:
        if not profile_task.done():
            profile_task.cancel()
        outcome = (await asyncio.gather(profile_task, return_exceptions=True))[0]
        if result is None and isinstance(outcome, ProfileExecutionError):
            result = outcome.result
        stop.set()
        fatal_task.cancel()
        await asyncio.gather(fatal_task, return_exceptions=True)
        await monitor_task
    elapsed = time.monotonic() - started
    boundary_end = await asyncio.to_thread(monitor._sample_sync)
    monitor.samples.append(boundary_end)
    guard = monitor._host_guard_failure(boundary_end)
    if guard is not None and profile_error is None:
        profile_error = HarnessError(f"setup end host guard failed: {guard}")
    qdisc_end = dict(boundary_end["qdisc"])
    state_end = monitor.state()
    byte_delta = qdisc_end.get("bytes", 0) - qdisc_start.get("bytes", 0)
    monitor_summary = ProfileMonitorResult(
        profile=phase_label,
        samples=monitor.samples,
        qdisc_start=qdisc_start,
        qdisc_end=qdisc_end,
        qdisc_mbps=byte_delta * 8 / max(elapsed, 0.001) / 1_000_000,
        readiness_failures=monitor.readiness_failures,
        state_start=state_start,
        state_end=state_end,
        errors=monitor.errors,
    ).summary()
    load_summary = (
        result.summary()
        if result is not None
        else {
            "profile": phase_label.removeprefix("ramp-").removeprefix("warmup-"),
            "round": None,
            "vus": None,
            "failed_requests": 1,
            "latency_ms": {},
            "operations": {},
        }
    )
    full_verdict = evaluate_profile(load_summary, monitor_summary)
    failures = [
        failure
        for failure in full_verdict["failures"]
        if failure not in SETUP_ONLY_IGNORED_GATES
    ]
    passed = profile_error is None and not failures
    evidence.append_jsonl("setup-metric-samples.jsonl", monitor.samples)
    if result is not None and not passed:
        assert hasattr(result.samples, "evidence_records")
        evidence.append_jsonl(
            "setup-failure-request-samples.jsonl",
            result.samples.evidence_records(),
        )
    evidence.append_jsonl(
        "setup-phase-summaries.jsonl",
        [{
            "phase": phase_label,
            "passed": passed,
            "load": load_summary,
            "monitor": monitor_summary,
            "failures": failures,
            "profile_error_type": (
                type(profile_error).__name__ if profile_error is not None else None
            ),
        }],
    )
    completed_journeys = result.completed_journeys if result is not None else 0
    if isinstance(
        profile_error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
    ):
        raise profile_error
    if not passed:
        raise ProfileRunFailure(
            f"unmeasured phase failed: {phase_label}", completed_journeys
        ) from profile_error
    return completed_journeys


def _profile_sequence(
    options: HarnessOptions,
    round_number: int,
) -> list[tuple[str, int, str]]:
    vus_order = list(options.vus)
    if round_number % 2 == 0:
        vus_order.reverse()
    sequence: list[tuple[str, int, str]] = []
    for vus in vus_order:
        if "A" in options.scenarios:
            sequence.extend((("A-identity", vus, "identity"), ("A-gzip", vus, "gzip")))
        if "B" in options.scenarios:
            sequence.append(("B", vus, ""))
        if "C" in options.scenarios:
            sequence.extend((("C-cold", vus, "cold"), ("C-warm", vus, "warm")))
        if "D" in options.scenarios:
            sequence.append(("D", vus, ""))
    return sequence


def _scheduled_profiles(
    options: HarnessOptions,
) -> list[tuple[int, tuple[str, int, str]]]:
    """Keep every read repetition on the frozen fixture before any D writes."""

    return [
        (round_number, profile)
        for write_phase in (False, True)
        for round_number in range(1, options.rounds + 1)
        for profile in _profile_sequence(options, round_number)
        if (profile[0] == "D") is write_phase
    ]


def _profile_execution_summary(
    results: Sequence[Mapping[str, object]],
    options: HarnessOptions,
    *,
    execution_completed: bool,
) -> dict[str, object]:
    capacity_failed_profiles: list[dict[str, object]] = []
    for result in results:
        handling = result.get("failure_handling")
        continuation = result.get("continuation")
        load = result.get("load")
        verdict = result.get("verdict")
        if (
            not isinstance(handling, Mapping)
            or handling.get("disposition") != PROFILE_DISPOSITION_CONTINUE
            or not isinstance(load, Mapping)
            or not isinstance(verdict, Mapping)
        ):
            continue
        capacity_failed_profiles.append({
            "profile": load.get("profile"),
            "round": load.get("round"),
            "vus": load.get("vus"),
            "failures": list(verdict.get("failures", [])),
            "cooldown_passed": (
                isinstance(continuation, Mapping)
                and continuation.get("cooldown_passed") is True
            ),
            "continued_to_later_profile": (
                isinstance(continuation, Mapping)
                and continuation.get("continued_to_later_profile") is True
            ),
        })
    scheduled_profile_count = _profile_count(options)
    recorded_profile_count = len(results)
    return {
        "scheduled_profile_count": scheduled_profile_count,
        "recorded_profile_count": recorded_profile_count,
        "execution_completed": execution_completed,
        "matrix_complete": (
            execution_completed
            and recorded_profile_count == scheduled_profile_count
        ),
        "capacity_failed_profile_count": len(capacity_failed_profiles),
        "cooldown_passed_capacity_failure_count": sum(
            row["cooldown_passed"] is True
            for row in capacity_failed_profiles
        ),
        "continued_to_later_profile_count": sum(
            row["continued_to_later_profile"] is True
            for row in capacity_failed_profiles
        ),
        "capacity_failed_profiles": capacity_failed_profiles,
    }


def _factory(
    kind: str,
    variant: str,
    *,
    client: httpx.AsyncClient,
    dataset: FrozenDataset,
    config: PerformanceRunConfig,
    options: HarnessOptions,
    round_number: int,
    vus: int,
    duration: float,
    image_validators: Mapping[str, Mapping[str, str]] | None,
    key_scope: str,
    activation_ramp_seconds: float = 0,
    completion_drain_seconds: float = 0,
    on_write_journey_completed: Callable[[], None] | None = None,
) -> Callable[[], Any]:
    if kind.startswith("A-"):
        return lambda: run_color_profile(
            client, dataset, encoding=variant, round_number=round_number,
            vus=vus, duration_seconds=duration,
            activation_ramp_seconds=activation_ramp_seconds,
        )
    if kind == "B":
        return lambda: run_browse_profile(
            client, dataset, run_seed=options.random_seed,
            round_number=round_number, vus=vus, duration_seconds=duration,
            think_time_min=options.think_time_min,
            think_time_max=options.think_time_max,
            activation_ramp_seconds=activation_ramp_seconds,
        )
    if kind.startswith("C-"):
        return lambda: run_image_profile(
            client, dataset, cache_state=variant, round_number=round_number,
            vus=vus, duration_seconds=duration, validators=image_validators,
            activation_ramp_seconds=activation_ramp_seconds,
            completion_drain_seconds=completion_drain_seconds,
        )
    if kind == "D":
        return lambda: run_write_profile(
            client, dataset, run_id=config.run_id, round_number=round_number,
            vus=vus, duration_seconds=duration, key_scope=key_scope,
            activation_ramp_seconds=activation_ramp_seconds,
            on_journey_completed=on_write_journey_completed,
        )
    raise HarnessError("unknown performance profile")


def _run_continuation_checkpoint(
    stack: ComposeStack,
    evidence: EvidenceWriter,
    *,
    profile_label: str,
    round_number: int,
    vus: int,
    expected_write_journeys: int,
    fixture_digest: str,
) -> dict[str, object]:
    """Prove data and cumulative service correctness before a soft continuation."""

    reconciliation = _run_data_task(
        stack,
        "verify",
        "--expected-write-journeys",
        str(expected_write_journeys),
        "--expected-static-fixture-sha256",
        fixture_digest,
        timeout=600,
    )
    if reconciliation.get("passed") is not True:
        raise HarnessError("continuation reconciliation did not pass")
    checkpoint_logs = _log_summary(stack)
    checkpoint_statements = _statement_summary(stack)
    log_failure = _service_log_error_detected(checkpoint_logs)
    statement_error_count = _statement_error_count(checkpoint_statements)
    passed = not log_failure and statement_error_count == 0
    result = {
        "strict_reconciliation_passed": True,
        "service_error_check_passed": passed,
    }
    evidence.append_jsonl(
        "capacity-failure-checkpoints.jsonl",
        [{
            "profile": profile_label,
            "round": round_number,
            "vus": vus,
            "expected_write_journeys": expected_write_journeys,
            **result,
            "log_failure_detected": log_failure,
            "statement_error_count": statement_error_count,
        }],
    )
    if not passed:
        raise HarnessError("continuation service or statement error check failed")
    return result


async def _execute_profiles(
    stack: ComposeStack,
    evidence: EvidenceWriter,
    options: HarnessOptions,
    journey_progress: dict[str, int],
    completed_profiles: list[dict[str, object]] | None = None,
) -> tuple[list[dict[str, object]], int, FrozenDataset]:
    results = completed_profiles if completed_profiles is not None else []
    expected_write_journeys = 0
    password = (stack.config.secret_dir / "persona_password").read_text(
        encoding="utf-8"
    ).strip()
    async with build_client(stack.config.base_url, max_connections=96) as client:
        dataset = await discover_dataset(client, password=password)
        evidence.write_json("dataset.json", dataset.safe_summary())
        # Login is setup, never part of steady HTTP percentiles.  It creates exactly
        # eleven LOGIN audit rows that the final verifier treats as a fixed baseline.
        login_snapshot = _run_data_task(stack, "snapshot")
        if login_snapshot.get("audit_logs") != 11:
            raise HarnessError("persona login audit baseline is not exactly eleven")

        def record_completed_write_journey() -> None:
            journey_progress["completed"] += 1

        scheduled_profiles = _scheduled_profiles(options)
        for profile_index, (round_number, (kind, vus, variant)) in enumerate(
            scheduled_profiles
        ):
                image_validators = None
                if kind == "C-warm":
                    # Cache priming intentionally precedes qdisc/resource snapshots.
                    image_validators = await prime_image_validators(client, dataset.images)
                profile_stem = (
                    f"{kind}-{variant}-r{round_number}-v{vus}"
                    if variant
                    else f"{kind}-r{round_number}-v{vus}"
                )
                if options.ramp_seconds:
                    image_completion_drain = (
                        IMAGE_PHASE_COMPLETION_DRAIN_SECONDS
                        if kind.startswith("C-")
                        else 0
                    )
                    ramp_factory = _factory(
                        kind, variant, client=client, dataset=dataset,
                        config=stack.config, options=options,
                        round_number=round_number, vus=vus,
                        duration=options.ramp_seconds + image_completion_drain,
                        image_validators=image_validators,
                        key_scope="ramp",
                        activation_ramp_seconds=options.ramp_seconds,
                        completion_drain_seconds=image_completion_drain,
                        on_write_journey_completed=record_completed_write_journey,
                    )
                    journeys = await _unmeasured_phase(
                        stack,
                        client,
                        ramp_factory,
                        evidence,
                        phase_label=f"ramp-{profile_stem}",
                    )
                    expected_write_journeys += journeys
                warmup_completion_drain = (
                    IMAGE_PHASE_COMPLETION_DRAIN_SECONDS
                    if kind.startswith("C-") and options.warmup_seconds
                    else 0
                )
                warmup_factory = _factory(
                    kind, variant, client=client, dataset=dataset,
                    config=stack.config, options=options, round_number=round_number,
                    vus=vus,
                    duration=options.warmup_seconds + warmup_completion_drain,
                    image_validators=image_validators,
                    key_scope="warmup",
                    completion_drain_seconds=warmup_completion_drain,
                    on_write_journey_completed=record_completed_write_journey,
                )
                if options.warmup_seconds:
                    journeys = await _unmeasured_phase(
                        stack,
                        client,
                        warmup_factory,
                        evidence,
                        phase_label=f"warmup-{profile_stem}",
                    )
                    expected_write_journeys += journeys
                profile_label = profile_stem
                measured_completion_drain = (
                    IMAGE_PHASE_COMPLETION_DRAIN_SECONDS
                    if kind.startswith("C-")
                    else 0
                )
                measured_factory = _factory(
                    kind, variant, client=client, dataset=dataset,
                    config=stack.config, options=options, round_number=round_number,
                    vus=vus,
                    duration=options.duration_seconds + measured_completion_drain,
                    image_validators=image_validators,
                    key_scope="measured",
                    completion_drain_seconds=measured_completion_drain,
                    on_write_journey_completed=record_completed_write_journey,
                )
                result, journeys = await _measure(
                    stack, client, evidence,
                    profile_factory=measured_factory,
                    profile_label=profile_label,
                )
                results.append(result)
                expected_write_journeys += journeys
                failure_handling = result.get("failure_handling")
                capacity_failure = (
                    isinstance(failure_handling, dict)
                    and failure_handling.get("disposition")
                    == PROFILE_DISPOSITION_CONTINUE
                )
                if capacity_failure:
                    if expected_write_journeys != journey_progress["completed"]:
                        raise HarnessError(
                            "write journey progress diverged before continuation"
                        )
                    fixture_digest = login_snapshot.get("static_fixture_sha256")
                    if (
                        not isinstance(fixture_digest, str)
                        or re.fullmatch(r"[0-9a-f]{64}", fixture_digest) is None
                    ):
                        raise HarnessError(
                            "continuation reconciliation fixture digest is unavailable"
                        )
                    checkpoint = _run_continuation_checkpoint(
                        stack,
                        evidence,
                        profile_label=profile_label,
                        round_number=round_number,
                        vus=vus,
                        expected_write_journeys=expected_write_journeys,
                        fixture_digest=fixture_digest,
                    )
                    result["continuation"] = {
                        **checkpoint,
                        "cooldown_passed": False,
                        "continued_to_later_profile": False,
                        "remaining_profile_count": (
                            len(scheduled_profiles) - profile_index - 1
                        ),
                    }
                if options.cooldown_seconds:
                    await asyncio.sleep(options.cooldown_seconds)
                if options.cooldown_seconds or capacity_failure:
                    await _confirm_cooldown(
                        stack,
                        client,
                        evidence,
                        profile_label=profile_label,
                        state_start=result.get("monitor", {}).get("state_end"),
                        redis_start=result.get("monitor", {}).get("redis", {}).get(
                            "end"
                        ),
                    )
                if capacity_failure:
                    remaining_profile_count = (
                        len(scheduled_profiles) - profile_index - 1
                    )
                    continuation = result["continuation"]
                    assert isinstance(continuation, dict)
                    continuation["cooldown_passed"] = True
                    continuation["continued_to_later_profile"] = (
                        remaining_profile_count > 0
                    )
                    evidence.append_jsonl(
                        "capacity-failure-continuations.jsonl",
                        [{
                            "profile": profile_label,
                            "round": round_number,
                            "vus": vus,
                            "failures": list(result["verdict"]["failures"]),
                            "cooldown_passed": True,
                            "continued_to_later_profile": (
                                remaining_profile_count > 0
                            ),
                            "remaining_profile_count": remaining_profile_count,
                        }],
                    )
        if expected_write_journeys != journey_progress["completed"]:
            raise HarnessError("write journey progress counter diverged")
        return results, expected_write_journeys, dataset


async def _confirm_cooldown(
    stack: ComposeStack,
    client: httpx.AsyncClient,
    evidence: EvidenceWriter,
    *,
    profile_label: str,
    state_start: Mapping[str, object] | None = None,
    redis_start: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Require two consecutive safe, healthy idle samples before continuing."""

    consecutive_idle_samples = 0
    maximum_threads_running: int | None = None
    final_reasons: list[str] = []
    baseline_state: Mapping[str, object] | None = state_start
    baseline_redis: Mapping[str, object] | None = redis_start
    for attempt in range(1, COOLDOWN_MAX_ATTEMPTS + 1):
        monitor = ProfileMonitor(
            stack, client, profile=f"cooldown-after-{profile_label}"
        )
        sample: Mapping[str, object] = {}
        current_state: Mapping[str, object] = {}
        sample_error_type: str | None = None
        host_guard_failure: str | None = None
        try:
            sample = await asyncio.to_thread(monitor._sample_sync)
            current_state = monitor.state()
            if baseline_state is None:
                baseline_state = current_state
            host_guard_failure = monitor._host_guard_failure(sample)
            await monitor._health()
        except Exception as error:
            # Ordinary sampler/parser failures still need a bounded, sanitized
            # attempt record. Cancellation and process interrupts inherit from
            # BaseException and intentionally keep their normal control flow.
            sample_error_type = type(error).__name__

        qdisc = sample.get("qdisc")
        mysql = sample.get("mysql")
        redis = sample.get("redis")
        qdisc_backlog = (
            qdisc.get("backlog")
            if isinstance(qdisc, Mapping)
            and isinstance(qdisc.get("backlog"), int)
            else None
        )
        mysql_threads_connected = (
            mysql.get("Threads_connected")
            if isinstance(mysql, Mapping)
            and isinstance(mysql.get("Threads_connected"), int)
            else None
        )
        mysql_threads_running = (
            mysql.get("Threads_running")
            if isinstance(mysql, Mapping)
            and isinstance(mysql.get("Threads_running"), int)
            else None
        )
        mysql_current_lock_waits = (
            mysql.get("Innodb_row_lock_current_waits")
            if isinstance(mysql, Mapping)
            and isinstance(mysql.get("Innodb_row_lock_current_waits"), int)
            else None
        )
        if isinstance(mysql_threads_running, int):
            maximum_threads_running = max(
                maximum_threads_running or mysql_threads_running,
                mysql_threads_running,
            )

        reasons: list[str] = []
        if sample_error_type is not None:
            reasons.append("metric_sample_failure")
        if host_guard_failure is not None:
            reasons.append(host_guard_failure)
        if monitor.readiness_failures:
            reasons.append("readiness_failure")
        state_healthy = (
            baseline_state is not None
            and _state_is_healthy(baseline_state, current_state)
        )
        if not state_healthy:
            reasons.append("container_restart_exit_or_oom")
        redis_evicted_keys = (
            redis.get("evicted_keys")
            if isinstance(redis, Mapping)
            and isinstance(redis.get("evicted_keys"), int)
            else None
        )
        redis_rejected_connections = (
            redis.get("rejected_connections")
            if isinstance(redis, Mapping)
            and isinstance(redis.get("rejected_connections"), int)
            else None
        )
        if baseline_redis is None and isinstance(redis, Mapping):
            baseline_redis = redis
        baseline_evicted_keys = (
            baseline_redis.get("evicted_keys")
            if isinstance(baseline_redis, Mapping)
            and isinstance(baseline_redis.get("evicted_keys"), int)
            else None
        )
        baseline_rejected_connections = (
            baseline_redis.get("rejected_connections")
            if isinstance(baseline_redis, Mapping)
            and isinstance(baseline_redis.get("rejected_connections"), int)
            else None
        )
        if (
            redis_evicted_keys is None
            or redis_rejected_connections is None
            or baseline_evicted_keys is None
            or baseline_rejected_connections is None
        ):
            reasons.append("redis_evidence_missing")
        elif (
            redis_evicted_keys != baseline_evicted_keys
            or redis_rejected_connections != baseline_rejected_connections
        ):
            reasons.append("redis_eviction_or_rejection")
        if qdisc_backlog is None:
            reasons.append("qdisc_backlog_unavailable")
        elif qdisc_backlog != 0:
            reasons.append("qdisc_backlog_not_zero")
        if mysql_threads_running is None:
            reasons.append("mysql_threads_running_unavailable")
        elif mysql_threads_running > COOLDOWN_MAX_THREADS_RUNNING:
            reasons.append("mysql_threads_running_above_idle_limit")
        if mysql_current_lock_waits is None:
            reasons.append("mysql_lock_waits_unavailable")
        elif mysql_current_lock_waits != 0:
            reasons.append("mysql_lock_waits_not_zero")

        sample_passed = not reasons
        consecutive_idle_samples = (
            consecutive_idle_samples + 1 if sample_passed else 0
        )
        passed = (
            consecutive_idle_samples
            >= COOLDOWN_REQUIRED_CONSECUTIVE_IDLE_SAMPLES
        )
        record_reasons = list(reasons)
        if sample_passed and not passed:
            record_reasons.append("consecutive_idle_confirmation_pending")
        final_reasons = record_reasons
        record = {
            "profile": profile_label,
            "stage": "cooldown",
            "attempt": attempt,
            "maximum_attempts": COOLDOWN_MAX_ATTEMPTS,
            "captured_at_utc": sample.get(
                "captured_at_utc", datetime.now(timezone.utc).isoformat()
            ),
            "qdisc_backlog": qdisc_backlog,
            "mysql_threads_connected": mysql_threads_connected,
            "mysql_threads_running": mysql_threads_running,
            "mysql_threads_running_idle_limit": COOLDOWN_MAX_THREADS_RUNNING,
            "maximum_mysql_threads_running_observed": maximum_threads_running,
            "mysql_current_lock_waits": mysql_current_lock_waits,
            "readiness_failures": monitor.readiness_failures,
            "host_guard_failure": host_guard_failure,
            "state_healthy": state_healthy,
            "redis_evicted_keys": redis_evicted_keys,
            "redis_rejected_connections": redis_rejected_connections,
            "baseline_redis_evicted_keys": baseline_evicted_keys,
            "baseline_redis_rejected_connections": (
                baseline_rejected_connections
            ),
            "sample_error_type": sample_error_type,
            "sample_passed": sample_passed,
            "consecutive_idle_samples": consecutive_idle_samples,
            "required_consecutive_idle_samples": (
                COOLDOWN_REQUIRED_CONSECUTIVE_IDLE_SAMPLES
            ),
            "reasons": record_reasons,
            "passed": passed,
        }
        # Persist every attempt before returning or raising so a cooldown failure
        # never destroys the only explanation for the fail-closed decision.
        evidence.append_jsonl("cooldown-samples.jsonl", [record])
        if passed:
            return record
        if attempt < COOLDOWN_MAX_ATTEMPTS:
            await asyncio.sleep(COOLDOWN_RETRY_INTERVAL_SECONDS)

    raise HarnessError(
        "cooldown failed after finite retries: "
        f"profile={profile_label} reasons={','.join(final_reasons)}"
    )


def _log_summary(stack: ComposeStack) -> dict[str, object]:
    result: dict[str, object] = {}
    for service in STEADY_SERVICES:
        logs = stack.run("logs", "--no-color", service, timeout=60)
        combined = logs.stdout + logs.stderr
        result[service] = {
            "collection_succeeded": True,
            "sha256": hashlib.sha256(combined.encode()).hexdigest(),
            "bytes": len(combined.encode()),
            "traceback_count": combined.count("Traceback"),
            "fatal_count": len(re.findall(r"\bFATAL\b", combined, flags=re.IGNORECASE)),
            "mysql_1205_count": len(re.findall(r"error_code=1205\b", combined)),
            "mysql_1213_count": len(re.findall(r"error_code=1213\b", combined)),
        }
    return result


def _service_log_error_detected(summary: object) -> bool:
    if not isinstance(summary, Mapping) or set(summary) != set(STEADY_SERVICES):
        raise HarnessError("service log evidence is incomplete")
    counters = (
        "traceback_count",
        "fatal_count",
        "mysql_1205_count",
        "mysql_1213_count",
    )
    detected = False
    for service in STEADY_SERVICES:
        row = summary.get(service)
        if (
            not isinstance(row, Mapping)
            or row.get("collection_succeeded") is not True
            or any(not _nonnegative_integer(row.get(key)) for key in counters)
        ):
            raise HarnessError("service log evidence is incomplete")
        detected = detected or any(int(row[key]) > 0 for key in counters)
    return detected


def aggregate_profiles(
    results: Sequence[Mapping[str, object]],
    options: HarnessOptions,
) -> dict[str, object]:
    """Compute deterministic three-round median/worst and B 5→10 scaling."""

    grouped: dict[tuple[str, int], list[Mapping[str, object]]] = {}
    browse_by_round: dict[int, dict[int, Mapping[str, object]]] = {}
    color_by_round: dict[int, dict[int, dict[str, Mapping[str, object]]]] = {}
    profile_gates_passed = True
    for result in results:
        load = result.get("load")
        if not isinstance(load, dict):
            profile_gates_passed = False
            continue
        verdict = result.get("verdict")
        if not isinstance(verdict, dict) or verdict.get("passed") is not True:
            profile_gates_passed = False
        profile = str(load.get("profile"))
        vus = int(load.get("vus", 0))
        grouped.setdefault((profile, vus), []).append(result)
        if profile == "B-authenticated-browse":
            browse_by_round.setdefault(int(load.get("round", 0)), {})[vus] = result
        if profile in ("A-color-identity", "A-color-gzip"):
            encoding = profile.rsplit("-", 1)[1]
            color_by_round.setdefault(int(load.get("round", 0)), {}).setdefault(
                vus, {}
            )[encoding] = result

    groups: list[dict[str, object]] = []
    repetition_passed = True
    for (profile, vus), members in sorted(grouped.items()):
        rps_values: list[float] = []
        p95_values: list[float] = []
        p99_values: list[float] = []
        failed_values: list[int] = []
        cpu_average_values: list[float] = []
        cpu_peak_values: list[float] = []
        memory_peak_values: list[int] = []
        qdisc_mbps_values: list[float] = []
        wire_per_response_values: list[float] = []
        decoded_per_response_values: list[float] = []
        rounds_seen: list[int] = []
        for member in members:
            load = member["load"]
            assert isinstance(load, dict)
            latency = load.get("latency_ms", {})
            if not isinstance(latency, dict):
                continue
            rounds_seen.append(int(load.get("round", 0)))
            rps_values.append(float(load.get("rps", 0)))
            failed_values.append(int(load.get("failed_requests", 0)))
            successful = int(load.get("successful_requests", 0))
            if successful:
                wire_per_response_values.append(
                    int(load.get("wire_body_bytes", 0)) / successful
                )
                decoded_per_response_values.append(
                    int(load.get("decoded_body_bytes", 0)) / successful
                )
            if latency.get("p95") is not None:
                p95_values.append(float(latency["p95"]))
            if latency.get("p99") is not None:
                p99_values.append(float(latency["p99"]))
            monitor = member.get("monitor")
            if isinstance(monitor, dict):
                cpu = monitor.get("cpu")
                memory = monitor.get("memory")
                qdisc = monitor.get("qdisc")
                if isinstance(cpu, dict):
                    if cpu.get("average_percent_of_two_cores") is not None:
                        cpu_average_values.append(
                            float(cpu["average_percent_of_two_cores"])
                        )
                    if cpu.get("max_percent_of_two_cores") is not None:
                        cpu_peak_values.append(float(cpu["max_percent_of_two_cores"]))
                if isinstance(memory, dict) and memory.get("peak_bytes") is not None:
                    memory_peak_values.append(int(memory["peak_bytes"]))
                if isinstance(qdisc, dict) and qdisc.get("average_mbps") is not None:
                    qdisc_mbps_values.append(float(qdisc["average_mbps"]))
        complete = sorted(rounds_seen) == list(range(1, options.rounds + 1))
        repetition_passed = repetition_passed and complete
        groups.append(
            {
                "profile": profile,
                "vus": vus,
                "rounds": sorted(rounds_seen),
                "complete": complete,
                "rps_median": statistics.median(rps_values) if rps_values else None,
                "rps_worst": min(rps_values) if rps_values else None,
                "p95_median_ms": statistics.median(p95_values) if p95_values else None,
                "p95_worst_ms": max(p95_values) if p95_values else None,
                "p99_median_ms": statistics.median(p99_values) if p99_values else None,
                "p99_worst_ms": max(p99_values) if p99_values else None,
                "failed_requests_worst": max(failed_values) if failed_values else None,
                "cpu_average_worst_percent_of_two_cores": (
                    max(cpu_average_values) if cpu_average_values else None
                ),
                "cpu_peak_worst_percent_of_two_cores": (
                    max(cpu_peak_values) if cpu_peak_values else None
                ),
                "memory_peak_worst_bytes": (
                    max(memory_peak_values) if memory_peak_values else None
                ),
                "qdisc_mbps_median": (
                    statistics.median(qdisc_mbps_values)
                    if qdisc_mbps_values else None
                ),
                "qdisc_mbps_worst_high": (
                    max(qdisc_mbps_values) if qdisc_mbps_values else None
                ),
                "wire_body_bytes_per_response_median": (
                    statistics.median(wire_per_response_values)
                    if wire_per_response_values else None
                ),
                "decoded_body_bytes_per_response_median": (
                    statistics.median(decoded_per_response_values)
                    if decoded_per_response_values else None
                ),
            }
        )

    scaling: list[dict[str, object]] = []
    scaling_passed = True
    if "B" in options.scenarios:
        for round_number in range(1, options.rounds + 1):
            pair = browse_by_round.get(round_number, {})
            if set(pair) != {5, 10}:
                scaling_passed = False
                scaling.append(
                    {"round": round_number, "passed": False, "reason": "missing 5/10 pair"}
                )
                continue
            load5 = pair[5]["load"]
            load10 = pair[10]["load"]
            assert isinstance(load5, dict) and isinstance(load10, dict)
            latency5 = load5.get("latency_ms", {})
            latency10 = load10.get("latency_ms", {})
            assert isinstance(latency5, dict) and isinstance(latency10, dict)
            rps5 = float(load5.get("rps", 0))
            rps10 = float(load10.get("rps", 0))
            p95_5 = float(latency5.get("p95") or 0)
            p95_10 = float(latency10.get("p95") or 0)
            passed = (
                rps5 > 0
                and rps10 >= 1.7 * rps5
                and p95_5 > 0
                and p95_10 <= 2 * p95_5
            )
            scaling_passed = scaling_passed and passed
            scaling.append(
                {
                    "round": round_number,
                    "rps_5": rps5,
                    "rps_10": rps10,
                    "throughput_ratio": round(rps10 / rps5, 6) if rps5 else None,
                    "p95_5_ms": p95_5,
                    "p95_10_ms": p95_10,
                    "p95_ratio": round(p95_10 / p95_5, 6) if p95_5 else None,
                    "resource_change": _profile_resource_comparison(pair[5], pair[10]),
                    "passed": passed,
                }
            )

    compression: list[dict[str, object]] = []
    compression_passed = True
    if "A" in options.scenarios:
        for round_number in range(1, options.rounds + 1):
            for vus in options.vus:
                pair = color_by_round.get(round_number, {}).get(vus, {})
                if set(pair) != {"identity", "gzip"}:
                    compression_passed = False
                    compression.append(
                        {
                            "round": round_number,
                            "vus": vus,
                            "passed": False,
                            "reason": "missing identity/gzip pair",
                        }
                    )
                    continue
                identity = _wire_bytes_per_success(pair["identity"])
                gzip_bytes = _wire_bytes_per_success(pair["gzip"])
                passed = identity is not None and gzip_bytes is not None and gzip_bytes < identity
                compression_passed = compression_passed and passed
                compression.append(
                    {
                        "round": round_number,
                        "vus": vus,
                        "identity_wire_bytes_per_response": identity,
                        "gzip_wire_bytes_per_response": gzip_bytes,
                        "gzip_to_identity_ratio": (
                            round(gzip_bytes / identity, 6)
                            if identity and gzip_bytes is not None else None
                        ),
                        "wire_reduction_percent": (
                            round((1 - gzip_bytes / identity) * 100, 3)
                            if identity and gzip_bytes is not None else None
                        ),
                        "passed": passed,
                    }
                )

    enforced = options.evidence_level == "candidate-pre"
    passed = (
        profile_gates_passed
        and repetition_passed
        and compression_passed
        and scaling_passed
    )
    return {
        "enforced": enforced,
        "profile_gates_passed": profile_gates_passed,
        "repetition_passed": repetition_passed,
        "browse_scaling_passed": scaling_passed,
        "color_compression_passed": compression_passed,
        "passed": passed,
        "groups": groups,
        "browse_5_to_10": scaling,
        "color_identity_to_gzip": compression,
        "representative_rule": "median across rounds; worst round retained",
    }


def _wire_bytes_per_success(result: Mapping[str, object]) -> float | None:
    load = result.get("load")
    if not isinstance(load, dict):
        return None
    successful = int(load.get("successful_requests", 0))
    if successful <= 0:
        return None
    return round(int(load.get("wire_body_bytes", 0)) / successful, 3)


def _profile_resource_comparison(
    five: Mapping[str, object],
    ten: Mapping[str, object],
) -> dict[str, object]:
    """Expose resource movement alongside each B throughput scaling pair."""

    def values(result: Mapping[str, object]) -> dict[str, object]:
        monitor = result.get("monitor")
        if not isinstance(monitor, dict):
            return {}
        cpu = monitor.get("cpu") if isinstance(monitor.get("cpu"), dict) else {}
        memory = (
            monitor.get("memory") if isinstance(monitor.get("memory"), dict) else {}
        )
        qdisc = (
            monitor.get("qdisc") if isinstance(monitor.get("qdisc"), dict) else {}
        )
        return {
            "cpu_average_percent_of_two_cores": cpu.get(
                "average_percent_of_two_cores"
            ),
            "cpu_peak_percent_of_two_cores": cpu.get("max_percent_of_two_cores"),
            "memory_peak_bytes": memory.get("peak_bytes"),
            "network_average_mbps": qdisc.get("average_mbps"),
        }

    return {"vus_5": values(five), "vus_10": values(ten)}


def _statement_summary(stack: ComposeStack) -> list[dict[str, object]]:
    ids = stack.service_container_ids()
    query = (
        "SELECT '__schema_total__', '', COALESCE(SUM(COUNT_STAR),0), "
        "COALESCE(SUM(SUM_ERRORS),0), "
        "ROUND(COALESCE(SUM(SUM_TIMER_WAIT),0)/1000000000000,6) "
        "FROM performance_schema.events_statements_summary_by_digest "
        "WHERE SCHEMA_NAME = 'pinkdoohub_performance'; "
        "SELECT COALESCE(DIGEST,''), LEFT(COALESCE(DIGEST_TEXT,''),300), "
        "COUNT_STAR, SUM_ERRORS, ROUND(SUM_TIMER_WAIT/1000000000000,6) "
        "FROM performance_schema.events_statements_summary_by_digest "
        "WHERE SCHEMA_NAME = 'pinkdoohub_performance' "
        "ORDER BY SUM_TIMER_WAIT DESC LIMIT 20"
    )
    command = stack.runner.run(
        [
            "docker", "exec", ids["mysql"], "/bin/sh", "-ec",
            'MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"; '
            "export MYSQL_PWD; "
            f'exec mysql --batch --skip-column-names --user=root --execute="{query}"',
        ],
        timeout=30,
    )
    rows: list[dict[str, object]] = []
    try:
        for line in command.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 5:
                raise ValueError("unexpected statement column count")
            rows.append(
                {
                    "scope": (
                        "schema_total"
                        if parts[0] == "__schema_total__"
                        else "top_statement"
                    ),
                    "digest": parts[0],
                    "digest_text": parts[1],
                    "count": int(parts[2]),
                    "errors": int(parts[3]),
                    "total_seconds": float(parts[4]),
                }
            )
    except (TypeError, ValueError) as error:
        raise HarnessError("MySQL statement evidence is malformed") from error
    _statement_error_count(rows)
    return rows


def _statement_error_count(summary: object) -> int:
    if not isinstance(summary, list):
        raise HarnessError("MySQL statement evidence is unavailable")
    totals = [
        row
        for row in summary
        if isinstance(row, Mapping) and row.get("scope") == "schema_total"
    ]
    if len(totals) != 1:
        raise HarnessError("MySQL statement evidence is unavailable")
    total = totals[0]
    if (
        not _nonnegative_integer(total.get("count"))
        or int(total["count"]) == 0
        or not _nonnegative_integer(total.get("errors"))
        or not _finite_number(total.get("total_seconds"))
        or float(total["total_seconds"]) < 0
    ):
        raise HarnessError("MySQL statement evidence is unavailable or malformed")
    return int(total["errors"])


def cleanup(stack: ComposeStack) -> dict[str, object]:
    """Remove only names derived from this run ID, then verify absence."""

    attempts: list[dict[str, object]] = []
    cleanup_errors: list[str] = []

    def record_command(
        action: str,
        arguments: Sequence[str],
        *,
        timeout: float,
        targets: Sequence[str] = (),
    ) -> CompletedCommand | None:
        try:
            result = stack.runner.run(
                arguments, check=False, timeout=timeout
            )
        except HarnessError as error:
            cleanup_errors.append(f"{action}:{type(error).__name__}")
            attempts.append({
                "action": action,
                "targets": list(targets),
                "returncode": None,
                "failure_type": type(error).__name__,
            })
            return None
        attempts.append({
            "action": action,
            "targets": list(targets),
            "returncode": result.returncode,
        })
        if result.returncode != 0:
            cleanup_errors.append(f"{action}:returncode-{result.returncode}")
        return result

    def exact_ids(kind: str, *, final: bool = False) -> list[str] | None:
        try:
            return _docker_object_ids(
                stack.runner, kind, stack.config.project
            )
        except HarnessError as error:
            phase = "final_inventory" if final else "cleanup_inventory"
            cleanup_errors.append(f"{phase}_{kind}:{type(error).__name__}")
            return None

    if stack.config.compose_env_path.is_file():
        try:
            result = stack.run(
                "down", "--volumes", "--remove-orphans", "--timeout", "20",
                check=False, timeout=180,
            )
        except HarnessError as error:
            cleanup_errors.append(f"compose_down:{type(error).__name__}")
            attempts.append({
                "action": "compose_down",
                "returncode": None,
                "failure_type": type(error).__name__,
            })
        else:
            attempts.append({
                "action": "compose_down", "returncode": result.returncode
            })
            if result.returncode != 0:
                cleanup_errors.append(
                    f"compose_down:returncode-{result.returncode}"
                )
    # Compose may be interrupted or its env file may be missing after a host crash.
    # The fallback resolves only objects carrying this exact unique project label.
    containers = exact_ids("container")
    if containers:
        record_command(
            "stop_exact_labeled_containers",
            ["docker", "container", "stop", "--time", "20", *containers],
            timeout=120,
            targets=containers,
        )
        # Force is a precise fallback for the same exact label-derived IDs if
        # graceful stop timed out or returned non-zero.
        record_command(
            "force_remove_exact_labeled_containers",
            ["docker", "container", "rm", "--force", *containers],
            timeout=120,
            targets=containers,
        )
    for kind in ("network", "volume"):
        identifiers = exact_ids(kind)
        if identifiers:
            record_command(
                f"remove_exact_labeled_{kind}s",
                ["docker", kind, "rm", *identifiers],
                timeout=120,
                targets=identifiers,
            )
    for image in (stack.config.app_image, stack.config.shaper_image):
        record_command(
            "remove_unique_image_tag",
            ["docker", "image", "rm", image],
            timeout=120,
            targets=(image,),
        )
    try:
        workspace = _validated_owned_workspace(stack.config)
        if workspace is not None:
            shutil.rmtree(workspace)
            attempts.append({"action": "remove_private_workspace", "returncode": 0})
    except (HarnessError, OSError) as error:
        cleanup_errors.append(f"remove_private_workspace:{type(error).__name__}")
        attempts.append({
            "action": "remove_private_workspace",
            "returncode": None,
            "failure_type": type(error).__name__,
        })

    residual = {
        kind: exact_ids(kind, final=True)
        for kind in ("container", "network", "volume")
    }
    image_residual: list[str] | None = []
    for image in (stack.config.app_image, stack.config.shaper_image):
        try:
            inspected = stack.runner.run(
                ["docker", "image", "inspect", image], check=False, timeout=20
            )
        except HarnessError as error:
            cleanup_errors.append(f"final_inventory_image:{type(error).__name__}")
            image_residual = None
            break
        if inspected.returncode == 0:
            assert image_residual is not None
            image_residual.append(image)
    workspace_absent = not (
        stack.config.workspace.exists() or stack.config.workspace.is_symlink()
    )
    port_released = port_is_available(stack.config.http_port)
    verified = (
        all(values == [] for values in residual.values())
        and image_residual == []
        and workspace_absent
        and port_released
    )
    return {
        "attempts": attempts,
        "cleanup_errors": cleanup_errors,
        "verified": verified,
        "residual_docker_objects": residual,
        "residual_image_tags": image_residual,
        "workspace_absent": workspace_absent,
        "loopback_port_released": port_released,
        "artifact_retained": str(stack.config.artifact_dir),
        "unrelated_resources_touched": False,
    }


def recovery_inventory(
    config: PerformanceRunConfig,
    runner: CommandRunner,
) -> dict[str, object]:
    """Read exact task-owned residuals without changing them."""

    docker_objects = {
        kind: _docker_object_ids(runner, kind, config.project)
        for kind in ("container", "network", "volume")
    }
    images: dict[str, bool] = {}
    for tag in (config.app_image, config.shaper_image):
        images[tag] = runner.run(
            ["docker", "image", "inspect", tag], check=False, timeout=20
        ).returncode == 0
    workspace_present = config.workspace.exists() or config.workspace.is_symlink()
    return {
        "mode": "read-only-recovery-inventory",
        "run_id": config.run_id,
        "project": config.project,
        "docker_objects_by_exact_project_label": docker_objects,
        "unique_image_tags": images,
        "workspace": {
            "path": str(config.workspace),
            "present": workspace_present,
            "is_symlink": config.workspace.is_symlink(),
        },
        "loopback_port": {
            "port": config.http_port,
            "available": port_is_available(config.http_port),
        },
        "artifact_preserved": str(config.artifact_dir),
        "apply_gate": (
            "use cleanup --apply with the same --run-id and --confirm-run-id; "
            "only these exact labels/tags/path are eligible"
        ),
    }


def _validate_recovery_workspace(config: PerformanceRunConfig) -> None:
    workspace = _validated_owned_workspace(config)
    if workspace is None:
        return
    if config.compose_env_path.exists():
        env_metadata = config.compose_env_path.lstat()
        if (
            not stat.S_ISREG(env_metadata.st_mode)
            or env_metadata.st_uid != os.geteuid()
            or env_metadata.st_mode & 0o077
        ):
            raise HarnessError("recovery Compose env file is unsafe")


def _render_report(summary: Mapping[str, object]) -> str:
    configuration = summary["configuration"]
    assert isinstance(configuration, dict)
    results = summary.get("profiles", [])
    profile_execution = summary.get("profile_execution", {})
    if not isinstance(profile_execution, Mapping):
        profile_execution = {}
    continuation_policy = summary.get("continuation_policy", {})
    if not isinstance(continuation_policy, Mapping):
        continuation_policy = {}
    options_summary = summary.get("options", {})
    if not isinstance(options_summary, Mapping):
        options_summary = {}
    safety_bounds = summary.get("safety_bounds", {})
    estimated_matrix_seconds = (
        safety_bounds.get("estimated_configured_profile_matrix_seconds", "?")
        if isinstance(safety_bounds, dict)
        else "?"
    )
    image_phase_completion_drain_seconds = (
        safety_bounds.get("image_phase_completion_drain_seconds", "?")
        if isinstance(safety_bounds, dict)
        else "?"
    )
    failure_details: list[str] = []
    if isinstance(summary.get("failure_type"), str):
        failure_details.append(f"- 失败类型：`{summary['failure_type']}`")
    if isinstance(summary.get("failure_reason"), str):
        failure_details.append(f"- 失败原因：`{summary['failure_reason']}`")
    lines = [
        f"# 本地 2 核 / 4GiB / 共享 5Mbps 压测 — {configuration['run_id']}",
        "",
        f"- 证据级别：`{summary.get('evidence_level')}`",
        f"- 总结论：`{summary.get('verdict')}`",
        *failure_details,
        f"- Git SHA：`{summary.get('source_identity', {}).get('git_sha', 'unknown')}`",
        f"- 工作树：`{'dirty' if summary.get('source_identity', {}).get('git_dirty') else 'clean'}`",
        f"- 未运行场景：`{summary.get('not_run_scenarios', [])}`（非空且没有已确认失败时整体为 INCONCLUSIVE；已确认失败仍为 FAIL）",
        "- Profile 执行：记录 `{recorded}` / 计划 `{scheduled}`；"
        "`matrix_complete={complete}`；容量失败 `{failed}` 个。".format(
            recorded=profile_execution.get("recorded_profile_count", "?"),
            scheduled=profile_execution.get("scheduled_profile_count", "?"),
            complete=profile_execution.get("matrix_complete", "?"),
            failed=profile_execution.get("capacity_failed_profile_count", "?"),
        ),
        "- 失败继续策略：`{version}`；继续采集只扩充诊断覆盖，不会把失败 Profile 或整轮改成 PASS。".format(
            version=continuation_policy.get("version", "未记录"),
        ),
        "- 稳态资源：MySQL 2240MiB + Redis 384MiB + App 1280MiB + Nginx 128MiB + Shaper 64MiB = 4096MiB，共享同一双 CPU cpuset。",
        "- 网络：单一 client-facing TBF，十进制 5,000,000 bit/s；本地 HTTP，无 TLS/公网 RTT，不能外推为真实 VPS 或微信终端体验。",
        "- One-off：image-init/migrate/MARD/seed 只在正式 Profile 窗口外运行；snapshot/verify 会在窗口外短时与长期服务共存，未计入五服务 4096MiB 测量包络。",
        "- C v3 options 启动窗口：ramp=`{ramp}` 秒、warm-up=`{warmup}` 秒、measured=`{measured}` 秒；每个实际存在阶段另有 `{drain}` 秒 completion drain，drain 不从启动窗口扣除。".format(
            ramp=options_summary.get("ramp_seconds", "?"),
            warmup=options_summary.get("warmup_seconds", "?"),
            measured=options_summary.get("duration_seconds", "?"),
            drain=image_phase_completion_drain_seconds,
        ),
        f"- 配置内 Profile 矩阵时长下界：`{estimated_matrix_seconds}` 秒；已对 C 的每个实际存在 ramp/warm-up/measured 阶段计入 `{image_phase_completion_drain_seconds}` 秒完成 drain，不含构建/迁移/prime/最终对账及冷却扩展时间。",
        "",
        "| Profile | VU | 请求 | 完整旅程/页面加载 | RPS | P95(ms) | qdisc Mbps | 结论 | 执行处置 | 失败 gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            load = result.get("load", {})
            monitor = result.get("monitor", {})
            verdict = result.get("verdict", {})
            failure_handling = result.get("failure_handling", {})
            latency = load.get("latency_ms", {}) if isinstance(load, dict) else {}
            qdisc = monitor.get("qdisc", {}) if isinstance(monitor, dict) else {}
            disposition = (
                failure_handling.get("disposition", "未记录")
                if isinstance(failure_handling, Mapping)
                else "未记录"
            )
            failures = verdict.get("failures", []) if isinstance(verdict, dict) else []
            failed_gates = (
                ", ".join(str(failure) for failure in failures)
                if isinstance(failures, list) and failures
                else "—"
            )
            activity_count: object = "—"
            if isinstance(load, dict):
                profile = str(load.get("profile", ""))
                if profile.startswith("C-"):
                    setup = load.get("setup", {})
                    activity_count = (
                        setup.get("completed_palette_loads", "?")
                        if isinstance(setup, dict)
                        else "?"
                    )
                elif profile.startswith("D-"):
                    activity_count = load.get("completed_journeys", "?")
            lines.append(
                "| {profile} | {vus} | {count} | {journeys} | {rps} | {p95} | {mbps} | {status} | {disposition} | {failures} |".format(
                    profile=load.get("profile", "?"), vus=load.get("vus", "?"),
                    count=load.get("completed_requests", "?"),
                    journeys=activity_count, rps=load.get("rps", "?"),
                    p95=latency.get("p95", "?") if isinstance(latency, dict) else "?",
                    mbps=qdisc.get("average_mbps", "?") if isinstance(qdisc, dict) else "?",
                    status="PASS" if verdict.get("passed") else "FAIL",
                    disposition=disposition,
                    failures=failed_gates,
                )
            )
    lines.extend((
        "",
        "## C v3 启动窗口、drain 与总阶段时长",
        "",
        "| Profile | Round | VU | Options measured 启动窗口(s) | Setup 启动窗口(s) | Completion drain(s) | 配置总阶段(s) | 实测总阶段(s) | Started | Completed | Incomplete |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ))
    c_result_count = 0
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, Mapping):
                continue
            load = result.get("load")
            if not isinstance(load, Mapping) or not str(
                load.get("profile", "")
            ).startswith("C-"):
                continue
            setup = load.get("setup")
            if not isinstance(setup, Mapping):
                setup = {}
            c_result_count += 1
            lines.append(
                "| {profile} | {round} | {vus} | {option_window} | {setup_window} | {drain} | {configured} | {measured} | {started} | {completed} | {incomplete} |".format(
                    profile=load.get("profile", "?"),
                    round=load.get("round", "?"),
                    vus=load.get("vus", "?"),
                    option_window=options_summary.get("duration_seconds", "?"),
                    setup_window=setup.get("palette_start_window_seconds", "?"),
                    drain=setup.get("completion_drain_seconds", "?"),
                    configured=load.get("configured_duration_seconds", "?"),
                    measured=load.get("measured_duration_seconds", "?"),
                    started=setup.get("started_palette_loads", "?"),
                    completed=setup.get("completed_palette_loads", "?"),
                    incomplete=setup.get("incomplete_palette_loads", "?"),
                )
            )
    if c_result_count == 0:
        lines.append("| — | — | — | — | — | — | — | — | — | — | — |")
    lines.extend(
        (
            "",
            "## 失败处置与矩阵完整性",
            "",
            "继续采集不等于通过；`matrix_complete` 只表示计划 Profile 已采齐。任何已记录的容量门槛失败仍使整轮为 `FAIL`。",
            "",
            f"- Profile 执行：`{json.dumps(profile_execution, ensure_ascii=False, sort_keys=True)}`",
            f"- Test Card continuation policy：`{json.dumps(continuation_policy, ensure_ascii=False, sort_keys=True)}`",
            "",
            "## 跨轮聚合与 5→10 扩展性",
            "",
            f"`{json.dumps(summary.get('aggregate', {}), ensure_ascii=False, sort_keys=True)}`",
            "",
            "## 正确性与限制",
            "",
            "- A 同时验证 identity/gzip wire bytes，并逐次核对冻结的 221 色 slot/code/name/HEX/兼容 URL。",
            "- B 是闭环认证浏览；购物车仍为小程序本地状态，不虚构服务端购物车 API。",
            "- C v3（palette-page-load-v3）是旧客户端兼容 PNG 页面加载旅程：每 VU 每 6 秒最多启动一次，严格遍历 221 图，每 VU 最多 4 个连接，因此 5/10 VU 的最大在途请求分别是 20/40；warm 是条件重验证 304 且 prime 不计入测量。options 保留完整启动窗口，每个实际存在的 C 阶段再增加 completion drain；窗口截止后不启动新旅程，drain 截止仍 incomplete 会 terminal FAIL。A 独立承担聚合 5Mbps 饱和证明。",
            "- D 使用可销毁 MySQL 8，真实执行颜色订单取消、钱包支付、代客下单及同 key 重放；外部支付 Provider 始终关闭。",
            "- `load_generator.process_cpu_percent_of_one_core` 是整个 Runner Python 进程的单核口径，包含进程内负载与采样/编排开销，不是只计 HTTP 负载协程；子进程 CPU 不在该值中。",
            "- 纯色 PNG 只有数百字节，不能替代未来 100–500KiB 真实商品 WebP 冷缓存容量测试。",
            "- Docker 容器上限合计只是服务包络近似，不包含宿主内核、Docker 守护进程、页缓存和 Runner Python 主进程。",
            "",
            "## 资源回收",
            "",
            f"`{json.dumps(summary.get('cleanup', {}), ensure_ascii=False, sort_keys=True)}`",
            "",
        )
    )
    return "\n".join(lines)


async def execute(
    config: PerformanceRunConfig,
    options: HarnessOptions,
    runner: CommandRunner,
) -> dict[str, object]:
    """Hold the single-host envelope lock through preflight, run and cleanup."""

    owner_lock = GlobalRunLock(config)
    owner_lock.acquire()
    try:
        return await _execute_locked(config, options, runner)
    finally:
        owner_lock.release()


async def _execute_locked(
    config: PerformanceRunConfig,
    options: HarnessOptions,
    runner: CommandRunner,
) -> dict[str, object]:
    """Execute only after the caller supplied the explicit --apply gate."""

    source_identity = preflight(config, options, runner)
    evidence = EvidenceWriter(config.artifact_dir)
    evidence.prepare()
    stack = ComposeStack(config, runner)
    completed_profiles: list[dict[str, object]] = []
    summary: dict[str, object] = {
        "schema_version": 1,
        "run_started_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_level": options.evidence_level,
        "configuration": config.safe_summary(),
        "options": asdict(options),
        "source_identity": source_identity,
        "steady_memory_limits_mib": SERVICE_MEMORY_LIMIT_MIB,
        "steady_memory_limit_total_mib": sum(SERVICE_MEMORY_LIMIT_MIB.values()),
        "safety_bounds": {
            "maximum_retained_success_samples_per_profile": (
                MAX_SUCCESS_EVIDENCE_SAMPLES
            ),
            "maximum_retained_failure_samples_per_profile": (
                MAX_FAILURE_EVIDENCE_SAMPLES
            ),
            "estimated_max_evidence_bytes": _estimated_evidence_bytes(options),
            "estimated_max_run_storage_bytes": _estimated_run_storage_bytes(options),
            "estimated_configured_profile_matrix_seconds": (
                _estimated_profile_matrix_seconds(options)
            ),
            "image_phase_completion_drain_seconds": (
                IMAGE_PHASE_COMPLETION_DRAIN_SECONDS
            ),
            "maximum_write_journeys": _maximum_write_journeys(options),
            "maximum_write_journeys_hard_limit": MAX_WRITE_JOURNEYS_PER_RUN,
            "maximum_reconciliation_business_rows": (
                _maximum_write_journeys(options)
                * MAX_RECONCILIATION_ROWS_PER_JOURNEY
            ),
            "write_journey_period_seconds_per_vu": (
                WRITE_JOURNEY_PERIOD_SECONDS
            ),
        },
        "profiles": completed_profiles,
        "continuation_policy": {
            "version": "observational-capacity-v1",
            "continuable_capacity_failures": sorted(
                CONTINUABLE_CAPACITY_FAILURES
            ),
            "conditional_a_network_failures_require_average_mbps_below": 4.75,
            "conditional_a_network_failure_rule": {
                "requires_positive_bytes_delta": True,
                "requires_finite_average_mbps": True,
                "average_mbps_minimum_exclusive": 0,
                "average_mbps_maximum_exclusive": 4.75,
            },
            "continue_requires_complete_result": True,
            "continue_requires_no_profile_error": True,
            "continue_requires_zero_failed_requests": True,
            "continue_requires_strict_reconciliation": True,
            "continue_requires_zero_service_or_statement_errors": True,
            "continue_requires_cooldown": True,
            "terminal_by_default": True,
            "overall_failure_preserved": True,
        },
        "profile_execution": _profile_execution_summary(
            completed_profiles,
            options,
            execution_completed=False,
        ),
        "not_run_scenarios": sorted(set(ALL_SCENARIOS) - set(options.scenarios)),
        "verdict": "INCONCLUSIVE",
    }
    evidence.write_json("test-card.json", summary)
    primary_error: BaseException | None = None
    journey_progress = {"completed": 0}
    profile_execution_completed = False
    try:
        _prepare_private_workspace(config)
        summary["images"] = _build_images(stack)
        summary["preparation"] = _prepare_stack(stack)
        pre_load = _run_data_task(stack, "snapshot")
        profiles, expected_journeys, dataset = await _execute_profiles(
            stack, evidence, options, journey_progress, completed_profiles
        )
        profile_execution_completed = True
        if profiles is not completed_profiles:
            completed_profiles[:] = profiles
        summary["aggregate"] = aggregate_profiles(profiles, options)
        summary["profile_execution"] = _profile_execution_summary(
            profiles,
            options,
            execution_completed=True,
        )
        summary["dataset"] = dataset.safe_summary()
        summary["pre_load_snapshot"] = pre_load
        summary["expected_write_journeys"] = expected_journeys
        fixture_digest = pre_load.get("static_fixture_sha256")
        if (
            not isinstance(fixture_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", fixture_digest) is None
        ):
            raise HarnessError("pre-load static fixture digest is unavailable")
        summary["reconciliation"] = _run_data_task(
            stack,
            "verify", "--expected-write-journeys", str(expected_journeys),
            "--expected-static-fixture-sha256", fixture_digest,
            timeout=600,
        )
        summary["mysql_statement_summary"] = _statement_summary(stack)
        summary["logs"] = _log_summary(stack)
        post_git_sha = runner.run(
            ["git", "rev-parse", "HEAD"], timeout=20
        ).stdout.strip()
        post_status = runner.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            timeout=20,
        ).stdout
        summary["post_run_source_identity"] = {
            "git_sha": post_git_sha,
            "git_dirty": bool(post_status.strip()),
            "git_status_sha256": hashlib.sha256(post_status.encode()).hexdigest(),
            "source_tree_sha256": content_digest(SOURCE_IDENTITY_PATHS),
        }
        if (
            post_git_sha != source_identity["git_sha"]
            or summary["post_run_source_identity"]["source_tree_sha256"]
            != source_identity["source_tree_sha256"]
            or (
                options.evidence_level == "candidate-pre"
                and post_status.strip()
            )
        ):
            raise HarnessError("source identity changed during the performance run")
        log_failure = _service_log_error_detected(summary["logs"])
        statement_error_count = _statement_error_count(
            summary["mysql_statement_summary"]
        )
        if log_failure or statement_error_count:
            raise HarnessError("service logs or MySQL statement metrics contain errors")
        if summary["profile_execution"]["capacity_failed_profile_count"]:
            raise HarnessError(
                "frozen capacity gates failed after the complete profile matrix"
            )
        if not summary["aggregate"]["passed"]:
            raise HarnessError("repetition, compression or 5-to-10 browse scaling failed")
        if summary["not_run_scenarios"]:
            summary["verdict"] = "INCONCLUSIVE"
            summary["inconclusive_reason"] = "scenario subset; full matrix not run"
        else:
            summary["verdict"] = "PASS"
    except BaseException as error:
        primary_error = error
        summary["verdict"] = "FAIL" if isinstance(
            error, (HarnessError, LoadProfileError)
        ) else "INCONCLUSIVE"
        summary["failure_type"] = type(error).__name__
        failure_reason = _safe_failure_reason(error)
        if failure_reason is not None:
            summary["failure_reason"] = failure_reason
        summary["completed_write_journeys_before_failure"] = journey_progress[
            "completed"
        ]
        forensic_memory = _host_available_memory_bytes(runner)
        forensic_disk = shutil.disk_usage(REPOSITORY_ROOT).free
        if (
            stack.started
            and forensic_memory is not None
            and forensic_memory >= MIN_PREFLIGHT_HOST_MEMORY_AVAILABLE_BYTES
            and forensic_disk >= MIN_PREFLIGHT_DISK_FREE_BYTES
        ):
            try:
                forensic = _run_data_task(
                    stack,
                    "forensic",
                    "--expected-write-journeys",
                    str(journey_progress["completed"]),
                    timeout=600,
                )
                summary["failure_forensics"] = forensic
                evidence.write_json("failure-forensics.json", forensic)
            except BaseException as forensic_error:
                summary["failure_forensics"] = {
                    "available": False,
                    "failure_type": type(forensic_error).__name__,
                    "expected_completed_write_journeys": journey_progress[
                        "completed"
                    ],
                }
        elif stack.started:
            summary["failure_forensics"] = {
                "available": False,
                "skipped_due_to_safety_floor": True,
                "host_available_memory_bytes": forensic_memory,
                "host_disk_free_bytes": forensic_disk,
                "required_memory_bytes": MIN_PREFLIGHT_HOST_MEMORY_AVAILABLE_BYTES,
                "required_disk_bytes": MIN_PREFLIGHT_DISK_FREE_BYTES,
                "expected_completed_write_journeys": journey_progress[
                    "completed"
                ],
            }
    finally:
        summary["profile_execution"] = _profile_execution_summary(
            completed_profiles,
            options,
            execution_completed=profile_execution_completed,
        )
        try:
            summary["cleanup"] = cleanup(stack)
            if not summary["cleanup"]["verified"]:
                summary["verdict"] = _verdict_after_cleanup_failure(
                    summary.get("verdict")
                )
                summary["cleanup_failure"] = True
                if primary_error is None:
                    primary_error = HarnessError(
                        "performance resource cleanup could not be verified"
                    )
        except BaseException as cleanup_error:
            summary["cleanup"] = {
                "verified": False,
                "failure_type": type(cleanup_error).__name__,
                "artifact_retained": str(config.artifact_dir),
            }
            summary["verdict"] = _verdict_after_cleanup_failure(
                summary.get("verdict")
            )
            if primary_error is None:
                primary_error = cleanup_error
        failure_reason = _safe_failure_reason(primary_error)
        if failure_reason is not None:
            summary["failure_reason"] = failure_reason
        summary["run_finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        evidence.write_json("summary.json", summary)
        evidence.write_text("report.md", _render_report(summary))
    if isinstance(
        primary_error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)
    ):
        raise primary_error
    if primary_error is not None:
        raise HarnessError(
            f"performance run did not pass; evidence={config.artifact_dir} "
            f"failure_type={type(primary_error).__name__}"
        ) from primary_error
    return summary


def plan(config: PerformanceRunConfig, options: HarnessOptions) -> dict[str, object]:
    options.validate()
    return {
        "mode": "read-only-plan",
        "configuration": config.safe_summary(),
        "options": asdict(options),
        "profiles_per_round": len(_profile_sequence(options, 1)),
        "steady_services": list(STEADY_SERVICES),
        "steady_memory_limits_mib": SERVICE_MEMORY_LIMIT_MIB,
        "steady_memory_limit_total_mib": sum(SERVICE_MEMORY_LIMIT_MIB.values()),
        "safety_bounds": {
            "maximum_retained_success_samples_per_profile": (
                MAX_SUCCESS_EVIDENCE_SAMPLES
            ),
            "maximum_retained_failure_samples_per_profile": (
                MAX_FAILURE_EVIDENCE_SAMPLES
            ),
            "estimated_max_evidence_bytes": _estimated_evidence_bytes(options),
            "estimated_max_run_storage_bytes": _estimated_run_storage_bytes(options),
            "estimated_configured_profile_matrix_seconds": (
                _estimated_profile_matrix_seconds(options)
            ),
            "image_phase_completion_drain_seconds": (
                IMAGE_PHASE_COMPLETION_DRAIN_SECONDS
            ),
            "minimum_preflight_disk_free_bytes": MIN_PREFLIGHT_DISK_FREE_BYTES,
            "minimum_runtime_disk_free_bytes": MIN_RUNTIME_DISK_FREE_BYTES,
            "minimum_runtime_host_available_memory_bytes": (
                MIN_RUNTIME_HOST_MEMORY_AVAILABLE_BYTES
            ),
            "maximum_write_journeys": _maximum_write_journeys(options),
            "maximum_write_journeys_hard_limit": MAX_WRITE_JOURNEYS_PER_RUN,
            "maximum_reconciliation_business_rows": (
                _maximum_write_journeys(options)
                * MAX_RECONCILIATION_ROWS_PER_JOURNEY
            ),
            "write_journey_period_seconds_per_vu": (
                WRITE_JOURNEY_PERIOD_SECONDS
            ),
        },
        "operation_services": list(OPERATION_SERVICES),
        "mutations_if_run_with_apply": [
            "create exact private workspace and Secret files",
            "build two run-ID-scoped images",
            "create one run-ID-scoped Compose project/volumes/networks",
            "write only synthetic data inside the disposable MySQL instance",
            "apply TBF only inside the disposable edge network namespace",
            "retain sanitized evidence under the ignored backups/performance path",
            "destroy exact project, volumes, images and private workspace in finally",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--run-id", required=True)
        target.add_argument("--http-port", type=int, default=18083)
        target.add_argument("--cpuset", default="0-1")
        target.add_argument(
            "--evidence-level",
            choices=("exploratory", "candidate-pre"),
            default="exploratory",
        )
        target.add_argument("--duration-seconds", type=float, default=60)
        target.add_argument("--rounds", type=int, default=1)
        target.add_argument("--vus", type=int, nargs="+", default=(5, 10))
        target.add_argument("--scenarios", nargs="+", default=ALL_SCENARIOS)
        target.add_argument("--think-time-min", type=float, default=0.4)
        target.add_argument("--think-time-max", type=float, default=0.6)
        target.add_argument("--cooldown-seconds", type=float, default=5)
        target.add_argument("--warmup-seconds", type=float, default=0)
        target.add_argument("--ramp-seconds", type=float, default=0)
        target.add_argument("--random-seed", type=int, default=20260909)

    plan_parser = subparsers.add_parser("plan")
    add_common(plan_parser)
    run_parser = subparsers.add_parser("run")
    add_common(run_parser)
    run_parser.add_argument("--apply", action="store_true")
    cleanup_parser = subparsers.add_parser("cleanup-plan")
    cleanup_parser.add_argument("--run-id", required=True)
    cleanup_parser.add_argument("--http-port", type=int, default=18083)
    cleanup_parser.add_argument("--cpuset", default="0-1")
    recovery_parser = subparsers.add_parser("cleanup")
    recovery_parser.add_argument("--run-id", required=True)
    recovery_parser.add_argument("--http-port", type=int, default=18083)
    recovery_parser.add_argument("--cpuset", default="0-1")
    recovery_parser.add_argument("--apply", action="store_true")
    recovery_parser.add_argument("--confirm-run-id", required=True)
    return parser


def _options(arguments: argparse.Namespace) -> HarnessOptions:
    return HarnessOptions(
        evidence_level=arguments.evidence_level,
        duration_seconds=arguments.duration_seconds,
        rounds=arguments.rounds,
        vus=tuple(arguments.vus),
        scenarios=tuple(arguments.scenarios),
        think_time_min=arguments.think_time_min,
        think_time_max=arguments.think_time_max,
        cooldown_seconds=arguments.cooldown_seconds,
        warmup_seconds=arguments.warmup_seconds,
        ramp_seconds=arguments.ramp_seconds,
        random_seed=arguments.random_seed,
    )


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        config = config_for_run(
            arguments.run_id,
            http_port=arguments.http_port,
            cpuset=arguments.cpuset,
        )
        if arguments.command == "cleanup-plan":
            print(json.dumps(
                recovery_inventory(config, CommandRunner()),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ))
            return 0
        if arguments.command == "cleanup":
            if not arguments.apply:
                raise HarnessError("cleanup requires explicit --apply")
            if arguments.confirm_run_id != config.run_id:
                raise HarnessError("cleanup confirmation does not match the run ID")
            owner_lock = GlobalRunLock(config)
            owner_lock.acquire()
            try:
                _validate_recovery_workspace(config)
                result = cleanup(ComposeStack(config, CommandRunner()))
            finally:
                owner_lock.release()
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if result["verified"] else 2
        options = _options(arguments)
        if arguments.command == "plan":
            print(json.dumps(plan(config, options), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if not arguments.apply:
            raise HarnessError("run requires explicit --apply")
        summary = asyncio.run(execute(config, options, CommandRunner()))
        print(
            json.dumps(
                {
                    "run_id": config.run_id,
                    "verdict": summary["verdict"],
                    "artifact": str(config.artifact_dir),
                    "cleanup_verified": summary["cleanup"]["verified"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (PerformanceConfigError, HarnessError, LoadProfileError) as error:
        print(f"Performance harness refused or failed safely: {error}", file=sys.stderr)
        return 2
    except (asyncio.CancelledError, KeyboardInterrupt):
        print("Performance harness interrupted; finally cleanup was requested", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
