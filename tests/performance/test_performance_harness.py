"""压测编排参数、指标解析、门槛与跨轮聚合单元测试。"""

import json
import asyncio
import os
from pathlib import Path
import socket

import pytest

from scripts.performance import config as config_module
from scripts.performance import harness
from scripts.performance import load as load_module
from scripts.performance.config import PerformanceRunConfig


def _options(**overrides: object) -> harness.HarnessOptions:
    values: dict[str, object] = {
        "evidence_level": "exploratory",
        "duration_seconds": 60,
        "rounds": 1,
        "vus": (5, 10),
        "scenarios": harness.ALL_SCENARIOS,
        "think_time_min": 0.4,
        "think_time_max": 0.6,
        "cooldown_seconds": 5,
        "warmup_seconds": 0,
        "ramp_seconds": 0,
        "random_seed": 20260909,
    }
    values.update(overrides)
    return harness.HarnessOptions(**values)  # type: ignore[arg-type]


def _state() -> dict[str, object]:
    return {
        service: {
            "running": True,
            "oom_killed": False,
            "restart_count": 0,
            "memory_cgroup": {
                "available": True,
                "swap_current": 0,
                "high": 0,
                "max": 0,
                "oom": 0,
                "oom_kill": 0,
            },
        }
        for service in harness.STEADY_SERVICES
    }


def _monitor(*, mbps: float = 1.0) -> dict[str, object]:
    state = _state()
    configuration = {
        "rate_bytes_per_second": harness.TBF_RATE_BYTES_PER_SECOND,
        "burst_bytes": harness.TBF_BURST_BYTES,
        "latency_microseconds": harness.TBF_LATENCY_MICROSECONDS,
        "latency_milliseconds": harness.TBF_LATENCY_MILLISECONDS,
    }
    return {
        "sample_count": 2,
        "sample_errors": [],
        "readiness_failures": 0,
        "qdisc": {
            "start": {
                "bytes": 100,
                "packets": 10,
                "drops": 0,
                "overlimits": 0,
                "requeues": 0,
                "backlog": 0,
                "configuration": dict(configuration),
            },
            "end": {
                "bytes": 200,
                "packets": 20,
                "drops": 0,
                "overlimits": 1,
                "requeues": 0,
                "backlog": 0,
                "configuration": dict(configuration),
            },
            "bytes_delta": 100,
            "overlimits_delta": 1,
            "drops_delta": 0,
            "average_mbps": mbps,
            "configuration": configuration,
            "configuration_unchanged": True,
            "sampled_counters_monotonic": True,
            "continuous_seconds_above_4_5_mbps": 0,
        },
        "cpu": {
            "average_percent_of_two_cores": 20,
            "max_percent_of_two_cores": 30,
            "continuous_seconds_above_85": 0,
        },
        "memory": {
            "peak_bytes": 1024,
            "second_half_growth_ratio": 0,
            "swap_peak_bytes": 0,
        },
        "load_generator": {
            "process_cpu_percent_of_one_core": 10,
            "rss_peak_bytes": 64 * 1024**2,
        },
        "host_safety": {
            "available_memory_min_bytes": 4 * 1024**3,
            "disk_free_min_bytes": 10 * 1024**3,
        },
        "sampling": {"maximum_interval_seconds": 1.1},
        "mysql": {
            "start": {
                "Innodb_row_lock_current_waits": 0,
                "Innodb_deadlocks": 0,
                "Slow_queries": 0,
            },
            "end": {
                "Innodb_row_lock_current_waits": 0,
                "Innodb_deadlocks": 0,
                "Slow_queries": 0,
            },
            "deltas": {"Innodb_deadlocks": 0, "Slow_queries": 0},
        },
        "redis": {
            "start": {"evicted_keys": 0, "rejected_connections": 0},
            "end": {"evicted_keys": 0, "rejected_connections": 0},
            "deltas": {"evicted_keys": 0, "rejected_connections": 0},
        },
        "state_start": state,
        "state_end": json.loads(json.dumps(state)),
    }


def _load(
    profile: str,
    vus: int,
    operations: set[str],
    *,
    p95: float = 100,
    p99: float = 150,
    maximum: float = 200,
) -> dict[str, object]:
    latency = {"p95": p95, "p99": p99, "max": maximum}
    return {
        "profile": profile,
        "round": 1,
        "vus": vus,
        "completed_requests": 10,
        "failed_requests": 0,
        "latency_ms": latency,
        "operations": {
            operation: {"latency_ms": dict(latency)} for operation in operations
        },
    }


def _log_evidence(*, traceback_count: int = 0) -> dict[str, object]:
    return {
        service: {
            "collection_succeeded": True,
            "traceback_count": traceback_count,
            "fatal_count": 0,
            "mysql_1205_count": 0,
            "mysql_1213_count": 0,
        }
        for service in harness.STEADY_SERVICES
    }


def _statement_evidence(
    *, errors: int = 0, count: int = 1
) -> list[dict[str, object]]:
    return [{
        "scope": "schema_total",
        "digest": "__schema_total__",
        "digest_text": "",
        "count": count,
        "errors": errors,
        "total_seconds": 0.001,
    }]


def test_candidate_pre_contract_requires_exact_matrix_ramp_and_token_window() -> None:
    candidate_options = _options(
        evidence_level="candidate-pre",
        duration_seconds=300,
        rounds=3,
        warmup_seconds=60,
        cooldown_seconds=30,
        ramp_seconds=20,
    )
    candidate_options.validate()
    assert harness._estimated_profile_matrix_seconds(candidate_options) == 14_976
    candidate_plan = harness.plan(
        PerformanceRunConfig("20260909t120000"), candidate_options
    )
    assert (
        candidate_plan["safety_bounds"][  # type: ignore[index]
            "estimated_configured_profile_matrix_seconds"
        ]
        == 14_976
    )
    assert (
        candidate_plan["safety_bounds"][  # type: ignore[index]
            "image_phase_completion_drain_seconds"
        ]
        == 6
    )
    assert harness._estimated_profile_matrix_seconds(_options()) == 804

    with pytest.raises(harness.HarnessError, match="cannot produce candidate"):
        _options(evidence_level="candidate").validate()

    with pytest.raises(harness.HarnessError, match="10-30s ramp"):
        _options(
            evidence_level="candidate-pre",
            duration_seconds=300,
            rounds=3,
            warmup_seconds=60,
            cooldown_seconds=30,
        ).validate()
    with pytest.raises(harness.HarnessError, match="exactly three"):
        _options(
            evidence_level="candidate-pre",
            duration_seconds=300,
            rounds=4,
            warmup_seconds=60,
            cooldown_seconds=30,
            ramp_seconds=20,
        ).validate()
    with pytest.raises(harness.HarnessError, match="access-token"):
        _options(
            evidence_level="candidate-pre",
            duration_seconds=900,
            rounds=3,
            warmup_seconds=60,
            cooldown_seconds=30,
            ramp_seconds=20,
        ).validate()
    assert harness._maximum_write_journeys(_options(
        evidence_level="candidate-pre",
        duration_seconds=300,
        rounds=3,
        warmup_seconds=60,
        cooldown_seconds=30,
        ramp_seconds=20,
    )) == 2880
    with pytest.raises(harness.HarnessError, match="final-reconciliation"):
        _options(
            scenarios=("D",),
            duration_seconds=1201,
            vus=(5, 10),
        ).validate()


@pytest.mark.parametrize(
    "change",
    (
        {"duration_seconds": float("nan")},
        {"duration_seconds": float("inf")},
        {"vus": (5, 5)},
        {"scenarios": ("A", "A")},
    ),
)
def test_unsafe_or_ambiguous_profile_parameters_are_rejected(
    change: dict[str, object],
) -> None:
    with pytest.raises(harness.HarnessError):
        _options(**change).validate()


def test_metric_parsers_keep_qdisc_cgroup_and_two_core_cpu_semantics() -> None:
    qdisc = harness._qdisc_counters(json.dumps([
        {
            "kind": "tbf",
            "options": {"rate": 625_000, "burst": 16_000, "lat": 400_000},
            "stats": {
                "bytes": 123,
                "packets": 4,
                "drops": 0,
                "overlimits": 9,
                "requeues": 0,
                "backlog": 0,
            },
        }
    ]))
    assert qdisc == {
        "bytes": 123,
        "packets": 4,
        "drops": 0,
        "overlimits": 9,
        "requeues": 0,
        "backlog": 0,
        "configuration": {
            "rate_bytes_per_second": 625_000,
            "burst_bytes": 16_000,
            "latency_microseconds": 400_000,
            "latency_milliseconds": 400.0,
        },
    }
    cgroup = harness._parse_cgroup_memory(
        "available=1\nhigh 0\nmax 0\noom 0\noom_kill 0\n"
        "memory_current=2048\nswap_current=0\n"
    )
    assert cgroup["available"] is True
    assert cgroup["memory_current"] == 2048
    services, cpu, memory = harness._parse_docker_stats(
        '{"Name":"app","CPUPerc":"120.0%","MemUsage":"1MiB / 2MiB"}\n'
        '{"Name":"mysql","CPUPerc":"40.0%","MemUsage":"2MiB / 3MiB"}\n'
    )
    assert set(services) == {"app", "mysql"}
    assert cpu == 80
    assert memory == 3 * 1024**2


@pytest.mark.parametrize(
    "options",
    (
        {"rate": 624_999, "burst": 16_000, "lat": 400_000},
        {"rate": 625_000, "burst": 16_001, "lat": 400_000},
        {"rate": 625_000, "burst": 16_000, "lat": 398_000},
    ),
)
def test_qdisc_parser_rejects_configuration_outside_frozen_tbf(
    options: dict[str, int],
) -> None:
    with pytest.raises(harness.HarnessError, match="frozen envelope"):
        harness._qdisc_counters(json.dumps([{
            "kind": "tbf",
            "options": options,
            "bytes": 1,
            "packets": 1,
            "drops": 0,
            "overlimits": 0,
            "requeues": 0,
            "backlog": 0,
        }]))


def test_qdisc_parser_requires_counters_and_configuration() -> None:
    with pytest.raises(harness.HarnessError, match="configuration is unavailable"):
        harness._qdisc_counters(json.dumps([{
            "kind": "tbf",
            "bytes": 1,
            "packets": 1,
            "drops": 0,
            "overlimits": 0,
            "requeues": 0,
            "backlog": 0,
        }]))
    with pytest.raises(harness.HarnessError, match="counters are incomplete"):
        harness._qdisc_counters(json.dumps([{
            "kind": "tbf",
            "options": {"rate": 625_000, "burst": 16_000, "lat": 400_000},
            "bytes": 1,
        }]))


@pytest.mark.asyncio
async def test_monitor_sanitizes_any_non_cancelled_sampler_exception() -> None:
    class FailingMonitor(harness.ProfileMonitor):
        def __init__(self) -> None:
            self.sample_interval = 0
            self.samples = []
            self.errors = []
            self.readiness_failures = 0
            self._last_health = 0.0
            self.fatal_event = asyncio.Event()
            self.fatal_reason = None

        def _sample_sync(self) -> dict[str, object]:
            raise KeyError("Authorization: Bearer TEST_SECRET")

    monitor = FailingMonitor()
    await monitor.run(asyncio.Event())

    assert monitor.fatal_event.is_set()
    assert monitor.fatal_reason == "metric_sample_failure"
    assert monitor.errors == ["KeyError"]
    assert "TEST_SECRET" not in json.dumps(monitor.errors)


def test_host_available_memory_parsers_are_explicit() -> None:
    assert harness._parse_available_memory(
        "Linux", "MemTotal: 100 kB\nMemAvailable: 4096 kB\n"
    ) == 4096 * 1024
    assert harness._parse_available_memory(
        "Darwin",
        "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
        "Pages free: 10.\nPages inactive: 20.\nPages speculative: 2.\n",
    ) == 32 * 16384


def test_failure_reason_only_accepts_controlled_error_types() -> None:
    assert harness._safe_failure_reason(
        harness.HarnessError("controlled reason")
    ) == "controlled reason"
    assert harness._safe_failure_reason(
        load_module.LoadProfileError("controlled load reason")
    ) == "controlled load reason"
    assert harness._safe_failure_reason(
        RuntimeError("Authorization: Bearer TEST_SECRET")
    ) is None


def test_monitor_summary_uses_linear_first_to_last_loader_cpu_evidence() -> None:
    samples = [
        {
            "captured_at_epoch": float(index),
            "stack_cpu_percent_of_two_cores": 20,
            "stack_memory_bytes": 1024,
            "stack_swap_bytes": 0,
            "load_generator_cpu_seconds": index * 0.5,
            "load_generator_rss_bytes": 64 * 1024**2,
            "host_available_memory_bytes": 4 * 1024**3,
            "host_disk_free_bytes": 10 * 1024**3,
            "qdisc": {"bytes": index * 100},
            "mysql": {"Threads_connected": 2, "Threads_running": 1},
            "redis": {"connected_clients": 2},
        }
        for index in range(1000)
    ]
    summary = harness.ProfileMonitorResult(
        profile="unit",
        samples=samples,
        qdisc_start={"bytes": 0, "overlimits": 0, "drops": 0},
        qdisc_end={"bytes": 100, "overlimits": 1, "drops": 0},
        qdisc_mbps=1,
        readiness_failures=0,
        state_start=_state(),
        state_end=_state(),
    ).summary()

    assert summary["sample_count"] == 1000
    assert summary["load_generator"]["process_cpu_percent_of_one_core"] == 50
    assert summary["load_generator"]["cpu_source"].startswith(
        "entire Python runner process"
    )
    assert summary["sampling"]["maximum_interval_seconds"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ("measured", "setup"))
async def test_interrupt_cancels_and_awaits_load_before_monitor_stops(
    phase: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    started = asyncio.Event()

    class FakeMonitor:
        def __init__(self, *_: object, profile: str, **__: object) -> None:
            self.profile = profile
            self.samples: list[dict[str, object]] = []
            self.errors: list[str] = []
            self.readiness_failures = 0
            self.fatal_event = asyncio.Event()
            self.fatal_reason = None

        def route_identity(self) -> dict[str, object]:
            return {"interface": "eth0"}

        def state(self) -> dict[str, object]:
            return _state()

        def _sample_sync(self) -> dict[str, object]:
            index = len(self.samples)
            return {
                "captured_at_epoch": float(index),
                "captured_at_utc": "2026-09-09T00:00:00+00:00",
                "stack_cpu_percent_of_two_cores": 1,
                "stack_memory_bytes": 1024,
                "stack_swap_bytes": 0,
                "load_generator_cpu_seconds": float(index) / 10,
                "load_generator_rss_bytes": 1024,
                "host_available_memory_bytes": 4 * 1024**3,
                "host_disk_free_bytes": 10 * 1024**3,
                "qdisc": {
                    "bytes": index + 1,
                    "overlimits": 0,
                    "drops": 0,
                },
                "mysql": {"Threads_connected": 1, "Threads_running": 1},
                "redis": {"connected_clients": 1},
            }

        def _host_guard_failure(self, _: object) -> None:
            return None

        async def run(self, stop: asyncio.Event) -> None:
            await stop.wait()
            order.append("monitor_stopped")

    class FakeEvidence:
        def append_jsonl(self, *_: object, **__: object) -> None:
            pass

        def write_json(self, *_: object, **__: object) -> None:
            pass

    async def load_forever() -> None:
        started.set()
        try:
            await asyncio.Future()
        finally:
            order.append("load_stopped")

    monkeypatch.setattr(harness, "ProfileMonitor", FakeMonitor)
    monkeypatch.setattr(
        harness,
        "evaluate_profile",
        lambda *_: {"passed": True, "failures": []},
    )
    if phase == "measured":
        coroutine = harness._measure(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            FakeEvidence(),  # type: ignore[arg-type]
            profile_factory=load_forever,
            profile_label="unit",
        )
    else:
        coroutine = harness._unmeasured_phase(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            load_forever,
            FakeEvidence(),  # type: ignore[arg-type]
            phase_label="warmup-unit",
        )
    task = asyncio.create_task(coroutine)
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert order == ["load_stopped", "monitor_stopped"]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ("measured", "setup"))
async def test_monitor_early_exit_is_terminal_and_cancels_load(
    phase: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_cancelled = asyncio.Event()

    class FakeMonitor:
        def __init__(self, *_: object, profile: str, **__: object) -> None:
            self.profile = profile
            self.samples: list[dict[str, object]] = []
            self.errors: list[str] = []
            self.readiness_failures = 0
            self.fatal_event = asyncio.Event()
            self.fatal_reason = None

        def route_identity(self) -> dict[str, object]:
            return {"interface": "eth0"}

        def state(self) -> dict[str, object]:
            return _state()

        def _sample_sync(self) -> dict[str, object]:
            index = len(self.samples)
            return {
                "captured_at_epoch": float(index),
                "stack_cpu_percent_of_two_cores": 1,
                "stack_memory_bytes": 1024,
                "stack_swap_bytes": 0,
                "load_generator_cpu_seconds": float(index),
                "load_generator_rss_bytes": 1024,
                "host_available_memory_bytes": 4 * 1024**3,
                "host_disk_free_bytes": 10 * 1024**3,
                "qdisc": {
                    "bytes": index + 1,
                    "overlimits": 0,
                    "drops": 0,
                    "configuration": _monitor()["qdisc"]["configuration"],  # type: ignore[index]
                },
                "mysql": {},
                "redis": {},
            }

        def _host_guard_failure(self, _: object) -> None:
            return None

        async def run(self, _: asyncio.Event) -> None:
            return

    class FakeEvidence:
        def append_jsonl(self, *_: object, **__: object) -> None:
            pass

        def write_json(self, *_: object, **__: object) -> None:
            pass

    async def load_forever() -> None:
        try:
            await asyncio.Future()
        finally:
            load_cancelled.set()

    monkeypatch.setattr(harness, "ProfileMonitor", FakeMonitor)
    monkeypatch.setattr(
        harness,
        "evaluate_profile",
        lambda *_: {"passed": True, "failures": []},
    )
    if phase == "measured":
        coroutine = harness._measure(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            FakeEvidence(),  # type: ignore[arg-type]
            profile_factory=load_forever,
            profile_label="unit",
        )
    else:
        coroutine = harness._unmeasured_phase(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            load_forever,
            FakeEvidence(),  # type: ignore[arg-type]
            phase_label="warmup-unit",
        )

    with pytest.raises(harness.ProfileRunFailure, match="aborted|unmeasured"):
        await asyncio.wait_for(coroutine, timeout=1)
    assert load_cancelled.is_set()


def _cooldown_sample(
    *,
    threads_running: int = 2,
    backlog: int = 0,
    lock_waits: int = 0,
    readiness_failures: int = 0,
    host_guard_failure: str | None = None,
    redis_evicted_keys: int = 0,
    redis_rejected_connections: int = 0,
    restart_count: int = 0,
    cgroup_high: int = 0,
) -> dict[str, object]:
    return {
        "captured_at_utc": "2026-09-09T00:00:00+00:00",
        "host_available_memory_bytes": 4 * 1024**3,
        "host_disk_free_bytes": 10 * 1024**3,
        "load_generator_rss_bytes": 64 * 1024**2,
        "host_guard_failure": host_guard_failure,
        "restart_count": restart_count,
        "cgroup_high": cgroup_high,
        "qdisc": {"backlog": backlog},
        "mysql": {
            "Threads_connected": 4,
            "Threads_running": threads_running,
            "Innodb_row_lock_current_waits": lock_waits,
        },
        "redis": {
            "evicted_keys": redis_evicted_keys,
            "rejected_connections": redis_rejected_connections,
        },
        "readiness_failures": readiness_failures,
    }


@pytest.mark.asyncio
async def test_cooldown_requires_two_consecutive_idle_samples_and_keeps_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = iter([
        _cooldown_sample(threads_running=3),
        _cooldown_sample(threads_running=2),
        _cooldown_sample(threads_running=2),
    ])
    records: list[dict[str, object]] = []
    sleeps: list[float] = []

    class FakeMonitor:
        def __init__(self, *_: object, **__: object) -> None:
            self.sample = next(samples)
            self.readiness_failures = 0

        def _sample_sync(self) -> dict[str, object]:
            return self.sample

        def state(self) -> dict[str, object]:
            state = _state()
            for service in harness.STEADY_SERVICES:
                service_state = state[service]
                service_state["restart_count"] = self.sample["restart_count"]  # type: ignore[index]
                service_state["memory_cgroup"]["high"] = self.sample["cgroup_high"]  # type: ignore[index]
            return state

        def _host_guard_failure(self, _: object) -> str | None:
            return self.sample["host_guard_failure"]  # type: ignore[return-value]

        async def _health(self) -> None:
            self.readiness_failures = int(self.sample["readiness_failures"])

    class FakeEvidence:
        def append_jsonl(self, name: str, values: object) -> None:
            assert name == "cooldown-samples.jsonl"
            records.extend(list(values))  # type: ignore[arg-type]

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(harness, "ProfileMonitor", FakeMonitor)
    monkeypatch.setattr(harness.asyncio, "sleep", fake_sleep)

    result = await harness._confirm_cooldown(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        FakeEvidence(),  # type: ignore[arg-type]
        profile_label="A-identity-identity-r1-v5",
        state_start=_state(),
        redis_start={"evicted_keys": 0, "rejected_connections": 0},
    )

    assert [record["attempt"] for record in records] == [1, 2, 3]
    assert [record["passed"] for record in records] == [False, False, True]
    assert records[0]["reasons"] == [
        "mysql_threads_running_above_idle_limit"
    ]
    assert records[1]["reasons"] == [
        "consecutive_idle_confirmation_pending"
    ]
    assert records[2]["reasons"] == []
    assert result["maximum_mysql_threads_running_observed"] == 3
    assert result["mysql_threads_running_idle_limit"] == 2
    assert sleeps == [
        harness.COOLDOWN_RETRY_INTERVAL_SECONDS,
        harness.COOLDOWN_RETRY_INTERVAL_SECONDS,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "expected_reason"),
    (
        ({"threads_running": 3}, "mysql_threads_running_above_idle_limit"),
        ({"backlog": 1}, "qdisc_backlog_not_zero"),
        ({"lock_waits": 1}, "mysql_lock_waits_not_zero"),
        ({"readiness_failures": 1}, "readiness_failure"),
        ({"host_guard_failure": "host_memory_safety_floor"}, "host_memory_safety_floor"),
        ({"redis_evicted_keys": 1}, "redis_eviction_or_rejection"),
        ({"restart_count": 1}, "container_restart_exit_or_oom"),
        ({"cgroup_high": 1}, "container_restart_exit_or_oom"),
    ),
)
async def test_cooldown_strict_failures_are_bounded_and_final_attempt_is_recorded(
    change: dict[str, int],
    expected_reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[dict[str, object]] = []
    sleeps: list[float] = []

    class FakeMonitor:
        def __init__(self, *_: object, **__: object) -> None:
            self.sample = _cooldown_sample(**change)
            self.readiness_failures = 0

        def _sample_sync(self) -> dict[str, object]:
            return self.sample

        def state(self) -> dict[str, object]:
            state = _state()
            for service in harness.STEADY_SERVICES:
                service_state = state[service]
                service_state["restart_count"] = self.sample["restart_count"]  # type: ignore[index]
                service_state["memory_cgroup"]["high"] = self.sample["cgroup_high"]  # type: ignore[index]
            return state

        def _host_guard_failure(self, _: object) -> str | None:
            return self.sample["host_guard_failure"]  # type: ignore[return-value]

        async def _health(self) -> None:
            self.readiness_failures = int(self.sample["readiness_failures"])

    class FakeEvidence:
        def append_jsonl(self, _: str, values: object) -> None:
            records.extend(list(values))  # type: ignore[arg-type]

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(harness, "ProfileMonitor", FakeMonitor)
    monkeypatch.setattr(harness.asyncio, "sleep", fake_sleep)

    with pytest.raises(harness.HarnessError, match="finite retries"):
        await harness._confirm_cooldown(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            FakeEvidence(),  # type: ignore[arg-type]
            profile_label="unit",
            state_start=_state(),
            redis_start={"evicted_keys": 0, "rejected_connections": 0},
        )

    assert len(records) == harness.COOLDOWN_MAX_ATTEMPTS
    assert [record["attempt"] for record in records] == list(
        range(1, harness.COOLDOWN_MAX_ATTEMPTS + 1)
    )
    assert all(record["passed"] is False for record in records)
    assert expected_reason in records[-1]["reasons"]
    assert len(sleeps) == harness.COOLDOWN_MAX_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_cooldown_sampler_exception_is_sanitized_and_recorded_before_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[dict[str, object]] = []

    class FakeMonitor:
        def __init__(self, *_: object, **__: object) -> None:
            self.readiness_failures = 0

        def _sample_sync(self) -> dict[str, object]:
            raise KeyError("Authorization: Bearer TEST_SECRET")

        async def _health(self) -> None:
            raise AssertionError("health must not run after sampler failure")

    class FakeEvidence:
        def append_jsonl(self, _: str, values: object) -> None:
            records.extend(list(values))  # type: ignore[arg-type]

    async def fake_sleep(_: float) -> None:
        pass

    monkeypatch.setattr(harness, "ProfileMonitor", FakeMonitor)
    monkeypatch.setattr(harness.asyncio, "sleep", fake_sleep)

    with pytest.raises(harness.HarnessError, match="finite retries"):
        await harness._confirm_cooldown(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            FakeEvidence(),  # type: ignore[arg-type]
            profile_label="unit",
            state_start=_state(),
            redis_start={"evicted_keys": 0, "rejected_connections": 0},
        )

    assert len(records) == harness.COOLDOWN_MAX_ATTEMPTS
    assert all(record["sample_error_type"] == "KeyError" for record in records)
    assert all("metric_sample_failure" in record["reasons"] for record in records)
    assert "TEST_SECRET" not in json.dumps(records)


def test_read_latency_boundary_and_operation_coverage_are_fail_closed() -> None:
    operations = harness.EXPECTED_PROFILE_OPERATIONS["B"]
    passing = _load(
        "B-authenticated-browse", 10, operations,
        p95=800, p99=2000, maximum=4999,
    )
    assert harness.evaluate_profile(passing, _monitor())["passed"] is True

    slow = _load(
        "B-authenticated-browse", 10, operations,
        p95=800.1, p99=2000, maximum=4999,
    )
    assert "json_latency_gate" in harness.evaluate_profile(
        slow, _monitor()
    )["failures"]
    missing = _load("B-authenticated-browse", 10, {"product_list"})
    assert "profile_operation_coverage" in harness.evaluate_profile(
        missing, _monitor()
    )["failures"]


def test_runner_process_cpu_gate_keeps_strict_seventy_percent_boundary() -> None:
    load = _load(
        "B-authenticated-browse", 10, harness.EXPECTED_PROFILE_OPERATIONS["B"]
    )
    passing_monitor = _monitor()
    passing_monitor["load_generator"][  # type: ignore[index]
        "process_cpu_percent_of_one_core"
    ] = 69.999
    assert harness.evaluate_profile(load, passing_monitor)["passed"] is True

    failing_monitor = _monitor()
    failing_monitor["load_generator"][  # type: ignore[index]
        "process_cpu_percent_of_one_core"
    ] = 70.0
    verdict = harness.evaluate_profile(load, failing_monitor)
    assert verdict["passed"] is False
    assert "load_generator_cpu_gate" in verdict["failures"]


@pytest.mark.parametrize(
    "failure",
    (
        "qdisc_drop",
        "read_p95_gate",
        "per_operation_read_p95_gate",
        "write_p95_gate",
        "per_operation_write_p95_gate",
        "average_cpu_gate",
        "sustained_cpu_gate",
    ),
)
def test_complete_observational_capacity_failure_is_continuable(
    failure: str,
) -> None:
    handling = harness.classify_profile_failure(
        {"passed": False, "failures": [failure]},
        load=_load(
            "B-authenticated-browse",
            5,
            harness.EXPECTED_PROFILE_OPERATIONS["B"],
        ),
        monitor=_monitor(mbps=1),
        result_complete=True,
        profile_error_present=False,
    )

    assert handling["disposition"] == harness.PROFILE_DISPOSITION_CONTINUE
    assert handling["continuable_capacity_failures"] == [failure]
    assert handling["terminal_failures"] == []


def test_passing_profile_still_requires_complete_dependency_evidence() -> None:
    monitor = _monitor(mbps=4.99)
    del monitor["mysql"]["deltas"]["Innodb_deadlocks"]  # type: ignore[index]

    handling = harness.classify_profile_failure(
        {"passed": True, "failures": []},
        load=_load(
            "A-color-identity", 5, harness.EXPECTED_PROFILE_OPERATIONS["A"]
        ),
        monitor=monitor,
        result_complete=True,
        profile_error_present=False,
    )

    assert handling["profile_evidence_complete"] is False
    assert handling["continuation_evidence_complete"] is False
    assert handling["terminal_failures"] == ["profile_evidence_incomplete"]
    assert handling["disposition"] == harness.PROFILE_DISPOSITION_ABORT


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("sample_count", 0),
        ("sample_errors", ["KeyError"]),
        ("readiness_failures", 1),
    ),
)
def test_passing_profile_requires_clean_complete_sampling_evidence(
    field: str,
    value: object,
) -> None:
    monitor = _monitor()
    monitor[field] = value

    handling = harness.classify_profile_failure(
        {"passed": True, "failures": []},
        load=_load(
            "B-authenticated-browse",
            5,
            harness.EXPECTED_PROFILE_OPERATIONS["B"],
        ),
        monitor=monitor,
        result_complete=True,
        profile_error_present=False,
    )

    assert handling["profile_evidence_complete"] is False
    assert handling["terminal_failures"] == ["profile_evidence_incomplete"]
    assert handling["disposition"] == harness.PROFILE_DISPOSITION_ABORT


def test_passing_profile_rejects_negative_sampling_interval() -> None:
    monitor = _monitor()
    monitor["sampling"]["maximum_interval_seconds"] = -1  # type: ignore[index]

    handling = harness.classify_profile_failure(
        {"passed": True, "failures": []},
        load=_load(
            "B-authenticated-browse",
            5,
            harness.EXPECTED_PROFILE_OPERATIONS["B"],
        ),
        monitor=monitor,
        result_complete=True,
        profile_error_present=False,
    )

    assert handling["profile_evidence_complete"] is False
    assert handling["disposition"] == harness.PROFILE_DISPOSITION_ABORT


@pytest.mark.parametrize(
    "invalid_evidence",
    (
        "missing_raw_counter",
        "mismatched_delta",
        "counter_rollback",
        "sampled_counter_rollback",
    ),
)
def test_passing_profile_requires_complete_monotonic_qdisc_evidence(
    invalid_evidence: str,
) -> None:
    monitor = _monitor()
    qdisc = monitor["qdisc"]
    assert isinstance(qdisc, dict)
    if invalid_evidence == "missing_raw_counter":
        del qdisc["start"]["packets"]  # type: ignore[index]
    elif invalid_evidence == "mismatched_delta":
        qdisc["bytes_delta"] = 99
    elif invalid_evidence == "counter_rollback":
        qdisc["start"]["requeues"] = 1  # type: ignore[index]
    else:
        qdisc["sampled_counters_monotonic"] = False

    handling = harness.classify_profile_failure(
        {"passed": True, "failures": []},
        load=_load(
            "B-authenticated-browse",
            5,
            harness.EXPECTED_PROFILE_OPERATIONS["B"],
        ),
        monitor=monitor,
        result_complete=True,
        profile_error_present=False,
    )

    assert handling["profile_evidence_complete"] is False
    assert handling["terminal_failures"] == ["profile_evidence_incomplete"]
    assert handling["disposition"] == harness.PROFILE_DISPOSITION_ABORT


def test_qdisc_summary_detects_mid_profile_counter_reset_after_recovery() -> None:
    configuration = _monitor()["qdisc"]["configuration"]  # type: ignore[index]

    def qdisc_snapshot(byte_count: int) -> dict[str, object]:
        return {
            "bytes": byte_count,
            "packets": byte_count,
            "drops": 0,
            "overlimits": 0,
            "requeues": 0,
            "backlog": 0,
            "configuration": dict(configuration),  # type: ignore[arg-type]
        }

    start = qdisc_snapshot(100)
    end = qdisc_snapshot(200)
    summary = harness.ProfileMonitorResult(
        profile="unit",
        samples=[
            {"qdisc": start},
            {"qdisc": qdisc_snapshot(50)},
            {"qdisc": end},
        ],
        qdisc_start=start,
        qdisc_end=end,
        qdisc_mbps=1,
        readiness_failures=0,
        state_start=_state(),
        state_end=_state(),
    ).summary()

    assert summary["qdisc"]["sampled_counters_monotonic"] is False  # type: ignore[index]


@pytest.mark.parametrize(
    ("section", "group", "key", "expected_failure"),
    (
        ("mysql", "deltas", "Innodb_deadlocks", "mysql_evidence_missing"),
        ("mysql", "deltas", "Slow_queries", "mysql_evidence_missing"),
        (
            "mysql",
            "end",
            "Innodb_row_lock_current_waits",
            "mysql_evidence_missing",
        ),
        ("redis", "deltas", "evicted_keys", "redis_evidence_missing"),
        (
            "redis",
            "deltas",
            "rejected_connections",
            "redis_evidence_missing",
        ),
    ),
)
def test_profile_verdict_fails_closed_when_dependency_key_is_missing(
    section: str,
    group: str,
    key: str,
    expected_failure: str,
) -> None:
    monitor = _monitor()
    del monitor[section][group][key]  # type: ignore[index]
    verdict = harness.evaluate_profile(
        _load(
            "B-authenticated-browse",
            5,
            harness.EXPECTED_PROFILE_OPERATIONS["B"],
        ),
        monitor,
    )

    assert verdict["passed"] is False
    assert expected_failure in verdict["failures"]
    assert "profile_evidence_incomplete" in verdict["failures"]


def test_profile_verdict_fails_closed_when_sampling_evidence_is_missing() -> None:
    monitor = _monitor()
    del monitor["sampling"]["maximum_interval_seconds"]  # type: ignore[index]

    verdict = harness.evaluate_profile(
        _load(
            "B-authenticated-browse",
            5,
            harness.EXPECTED_PROFILE_OPERATIONS["B"],
        ),
        monitor,
    )

    assert verdict["passed"] is False
    assert "metric_sampling_evidence_missing" in verdict["failures"]
    assert "profile_evidence_incomplete" in verdict["failures"]


def test_mysql_sampler_reads_deadlocks_from_innodb_metrics() -> None:
    assert "'Innodb_deadlocks', COUNT" in harness.ProfileMonitor.MYSQL_QUERY
    assert "information_schema.INNODB_METRICS" in harness.ProfileMonitor.MYSQL_QUERY
    assert "NAME = 'lock_deadlocks'" in harness.ProfileMonitor.MYSQL_QUERY


@pytest.mark.parametrize(
    "terminal_failure",
    (
        "unexpected_request_failure",
        "readiness_failure",
        "container_restart_exit_or_oom",
        "metric_sample_failure",
        "metric_sampling_gap_gate",
        "memory_peak_gate",
        "swap_usage_gate",
        "load_generator_rss_gate",
        "load_generator_cpu_gate",
        "host_memory_safety_gate",
        "mysql_slow_query",
        "mysql_deadlock",
        "redis_eviction_or_rejection",
        "profile_operation_coverage",
    ),
)
def test_correctness_safety_and_unknown_failures_are_terminal(
    terminal_failure: str,
) -> None:
    handling = harness.classify_profile_failure(
        {"passed": False, "failures": ["qdisc_drop", terminal_failure]},
        load=_load(
            "B-authenticated-browse",
            5,
            harness.EXPECTED_PROFILE_OPERATIONS["B"],
        ),
        monitor=_monitor(mbps=1),
        result_complete=True,
        profile_error_present=False,
    )

    assert handling["disposition"] == harness.PROFILE_DISPOSITION_ABORT
    assert handling["terminal_failures"] == [terminal_failure]


@pytest.mark.parametrize(
    ("average_mbps", "expected_disposition"),
    (
        (4.74, harness.PROFILE_DISPOSITION_CONTINUE),
        (5.051, harness.PROFILE_DISPOSITION_ABORT),
        (float("nan"), harness.PROFILE_DISPOSITION_ABORT),
        (0.0, harness.PROFILE_DISPOSITION_ABORT),
    ),
)
def test_a_shaping_failure_continues_only_when_pipe_was_not_filled(
    average_mbps: float,
    expected_disposition: str,
) -> None:
    handling = harness.classify_profile_failure(
        {
            "passed": False,
            "failures": [
                "aggregate_5mbps_not_demonstrated",
                "qdisc_overlimits_not_increasing",
            ],
        },
        load=_load(
            "A-color-identity", 5, harness.EXPECTED_PROFILE_OPERATIONS["A"]
        ),
        monitor=_monitor(mbps=average_mbps),
        result_complete=True,
        profile_error_present=False,
    )

    assert handling["disposition"] == expected_disposition


@pytest.mark.parametrize(
    ("result_complete", "profile_error_present"),
    ((False, False), (True, True), (False, True)),
)
def test_incomplete_or_errored_profile_is_terminal_even_for_capacity_gate(
    result_complete: bool,
    profile_error_present: bool,
) -> None:
    handling = harness.classify_profile_failure(
        {"passed": False, "failures": ["read_p95_gate"]},
        load=_load(
            "B-authenticated-browse",
            5,
            harness.EXPECTED_PROFILE_OPERATIONS["B"],
        ),
        monitor=_monitor(),
        result_complete=result_complete,
        profile_error_present=profile_error_present,
    )

    assert handling["disposition"] == harness.PROFILE_DISPOSITION_ABORT


def test_request_failure_cannot_continue_even_with_only_capacity_gate_in_verdict() -> None:
    failed_load = _load(
        "B-authenticated-browse",
        5,
        harness.EXPECTED_PROFILE_OPERATIONS["B"],
    )
    failed_load["failed_requests"] = 1
    handling = harness.classify_profile_failure(
        {"passed": False, "failures": ["read_p95_gate"]},
        load=failed_load,
        monitor=_monitor(),
        result_complete=True,
        profile_error_present=False,
    )

    assert handling["zero_failed_requests"] is False
    assert handling["disposition"] == harness.PROFILE_DISPOSITION_ABORT


def test_missing_latency_evidence_cannot_be_treated_as_capacity_failure() -> None:
    incomplete_load = _load(
        "B-authenticated-browse",
        5,
        harness.EXPECTED_PROFILE_OPERATIONS["B"],
    )
    incomplete_load["latency_ms"] = {"p95": None}
    handling = harness.classify_profile_failure(
        {"passed": False, "failures": ["read_p95_gate"]},
        load=incomplete_load,
        monitor=_monitor(),
        result_complete=True,
        profile_error_present=False,
    )

    assert handling["continuation_evidence_complete"] is False
    assert "profile_evidence_incomplete" in handling["terminal_failures"]
    assert handling["disposition"] == harness.PROFILE_DISPOSITION_ABORT


def test_render_report_uses_profile_specific_completed_activity_counts() -> None:
    def result(
        profile: str,
        *,
        completed_journeys: int | None = None,
        completed_palette_loads: int | None = None,
    ) -> dict[str, object]:
        load: dict[str, object] = {
            "profile": profile,
            "vus": 5,
            "completed_requests": 10,
            "rps": 1.5,
            "latency_ms": {"p95": 100},
        }
        if completed_journeys is not None:
            load["completed_journeys"] = completed_journeys
        if completed_palette_loads is not None:
            load["setup"] = {
                "palette_start_window_seconds": 60,
                "completion_drain_seconds": 6,
                "started_palette_loads": completed_palette_loads,
                "completed_palette_loads": completed_palette_loads,
                "incomplete_palette_loads": 0,
            }
            load["configured_duration_seconds"] = 66
            load["measured_duration_seconds"] = 65.9
        return {
            "load": load,
            "monitor": {"qdisc": {"average_mbps": 1.0}},
            "verdict": {"passed": True},
        }

    report = harness._render_report({
        "configuration": {"run_id": "unit-report"},
        "evidence_level": "exploratory",
        "verdict": "PASS",
        "source_identity": {"git_sha": "abc", "git_dirty": False},
        "options": {
            "ramp_seconds": 0,
            "warmup_seconds": 0,
            "duration_seconds": 60,
        },
        "safety_bounds": {
            "estimated_configured_profile_matrix_seconds": 123,
            "image_phase_completion_drain_seconds": 6,
        },
        "profiles": [
            result("A-color-gzip"),
            result("B-authenticated-browse"),
            result("C-png-warm", completed_palette_loads=7),
            result("D-color-order-wallet-write", completed_journeys=3),
        ],
        "aggregate": {},
        "cleanup": {"verified": True},
    })

    assert "| Profile | VU | 请求 | 完整旅程/页面加载 |" in report
    assert "| A-color-gzip | 5 | 10 | — |" in report
    assert "| B-authenticated-browse | 5 | 10 | — |" in report
    assert "| C-png-warm | 5 | 10 | 7 |" in report
    assert "| D-color-order-wallet-write | 5 | 10 | 3 |" in report
    assert "`123` 秒" in report
    assert "每个实际存在 ramp/warm-up/measured 阶段计入 `6` 秒" in report
    assert "C v3（palette-page-load-v3）是旧客户端兼容 PNG 页面加载旅程" in report
    assert "ramp=`0` 秒、warm-up=`0` 秒、measured=`60` 秒" in report
    assert "| C-png-warm | ? | 5 | 60 | 60 | 6 | 66 | 65.9 | 7 | 7 | 0 |" in report


def test_render_report_separates_failed_verdict_from_continued_collection() -> None:
    report = harness._render_report({
        "configuration": {"run_id": "continued-capacity-failure"},
        "evidence_level": "exploratory",
        "verdict": "FAIL",
        "failure_reason": "frozen capacity gates failed after the complete profile matrix",
        "source_identity": {"git_sha": "abc", "git_dirty": False},
        "safety_bounds": {
            "estimated_configured_profile_matrix_seconds": 123
        },
        "profiles": [{
            "load": {
                "profile": "C-png-warm",
                "vus": 5,
                "completed_requests": 50650,
                "rps": 840,
                "latency_ms": {"p95": 1250},
                "setup": {"completed_palette_loads": 230},
            },
            "monitor": {"qdisc": {"average_mbps": 1.25}},
            "verdict": {
                "passed": False,
                "failures": ["read_p95_gate"],
            },
            "failure_handling": {
                "disposition": "continue_after_capacity_failure",
            },
            "continuation": {
                "strict_reconciliation_passed": True,
                "service_error_check_passed": True,
                "cooldown_passed": True,
                "continued_to_later_profile": True,
                "remaining_profile_count": 6,
            },
        }],
        "profile_execution": {
            "scheduled_profile_count": 12,
            "recorded_profile_count": 12,
            "execution_completed": True,
            "matrix_complete": True,
            "capacity_failed_profile_count": 1,
            "cooldown_passed_capacity_failure_count": 1,
            "continued_to_later_profile_count": 1,
            "capacity_failed_profiles": [{
                "profile": "C-png-warm",
                "round": 1,
                "vus": 5,
                "failures": ["read_p95_gate"],
                "cooldown_passed": True,
                "continued_to_later_profile": True,
            }],
        },
        "continuation_policy": {
            "version": "observational-capacity-v1",
            "terminal_by_default": True,
            "overall_failure_preserved": True,
        },
        "aggregate": {"passed": True},
        "cleanup": {"verified": True},
    })

    assert "- 总结论：`FAIL`" in report
    assert "记录 `12` / 计划 `12`；`matrix_complete=True`；容量失败 `1` 个" in report
    assert "继续采集不等于通过" in report
    assert "| 结论 | 执行处置 | 失败 gate |" in report
    assert (
        "| C-png-warm | 5 | 50650 | 230 | 840 | 1250 | 1.25 | FAIL | "
        "continue_after_capacity_failure | read_p95_gate |"
    ) in report
    assert '"overall_failure_preserved": true' in report


def test_a_saturation_requires_wire_shaping_and_strict_read_p95() -> None:
    load = _load(
        "A-color-gzip", 5, harness.EXPECTED_PROFILE_OPERATIONS["A"],
        p95=999.9,
    )
    assert harness.evaluate_profile(load, _monitor(mbps=4.9))["passed"] is True
    load["latency_ms"] = {"p95": 1000, "p99": 1000, "max": 1000}
    assert "read_p95_gate" in harness.evaluate_profile(
        load, _monitor(mbps=4.9)
    )["failures"]


def _aggregate_result(
    profile: str,
    round_number: int,
    vus: int,
) -> dict[str, object]:
    rps = 18 if profile == "B-authenticated-browse" and vus == 10 else 10
    successful = 10
    wire = 250 if profile == "A-color-gzip" else 1000
    monitor = _monitor(mbps=4.9 if profile.startswith("A-") else 1.0)
    return {
        "load": {
            "profile": profile,
            "round": round_number,
            "vus": vus,
            "rps": rps,
            "successful_requests": successful,
            "failed_requests": 0,
            "wire_body_bytes": wire * successful,
            "decoded_body_bytes": 1000 * successful,
            "latency_ms": {"p95": 100, "p99": 150},
        },
        "monitor": monitor,
        "verdict": {"passed": True, "failures": []},
    }


def test_candidate_pre_aggregate_keeps_worst_resources_scaling_and_gzip_gain() -> None:
    profiles = (
        "A-color-identity",
        "A-color-gzip",
        "B-authenticated-browse",
        "C-png-cold",
        "C-png-warm",
        "D-color-order-wallet-write",
    )
    results = [
        _aggregate_result(profile, round_number, vus)
        for round_number in range(1, 4)
        for vus in (5, 10)
        for profile in profiles
    ]
    options = _options(
        evidence_level="candidate-pre",
        duration_seconds=300,
        rounds=3,
        warmup_seconds=60,
        cooldown_seconds=30,
        ramp_seconds=20,
    )

    aggregate = harness.aggregate_profiles(results, options)

    assert aggregate["passed"] is True
    assert aggregate["profile_gates_passed"] is True
    assert aggregate["browse_scaling_passed"] is True
    assert aggregate["color_compression_passed"] is True
    assert aggregate["browse_5_to_10"][0]["throughput_ratio"] == 1.8
    assert "resource_change" in aggregate["browse_5_to_10"][0]
    assert aggregate["color_identity_to_gzip"][0]["wire_reduction_percent"] == 75
    assert all(group["failed_requests_worst"] == 0 for group in aggregate["groups"])


def test_exploratory_browse_scaling_failure_cannot_be_reported_as_pass() -> None:
    five = _aggregate_result("B-authenticated-browse", 1, 5)
    ten = _aggregate_result("B-authenticated-browse", 1, 10)
    ten["load"]["rps"] = 12  # type: ignore[index]

    aggregate = harness.aggregate_profiles(
        [five, ten], _options(scenarios=("B",))
    )

    assert aggregate["browse_scaling_passed"] is False
    assert aggregate["passed"] is False


def test_aggregate_cannot_pass_when_a_recorded_profile_failed() -> None:
    identity = _aggregate_result("A-color-identity", 1, 5)
    gzip = _aggregate_result("A-color-gzip", 1, 5)
    identity["verdict"] = {"passed": False, "failures": ["qdisc_drop"]}

    aggregate = harness.aggregate_profiles(
        [identity, gzip],
        _options(scenarios=("A",), vus=(5,)),
    )

    assert aggregate["repetition_passed"] is True
    assert aggregate["color_compression_passed"] is True
    assert aggregate["profile_gates_passed"] is False
    assert aggregate["passed"] is False


def test_setup_phase_ignores_steady_growth_but_keeps_hard_safety_gates() -> None:
    assert "memory_growth_gate" in harness.SETUP_ONLY_IGNORED_GATES
    assert "average_cpu_gate" in harness.SETUP_ONLY_IGNORED_GATES
    assert "memory_peak_gate" not in harness.SETUP_ONLY_IGNORED_GATES
    assert "container_restart_exit_or_oom" not in harness.SETUP_ONLY_IGNORED_GATES


def test_all_read_rounds_are_scheduled_before_any_write_profile() -> None:
    options = _options(rounds=3)
    scheduled = harness._scheduled_profiles(options)
    write_flags = [profile[0] == "D" for _, profile in scheduled]

    first_write = write_flags.index(True)
    assert all(not value for value in write_flags[:first_write])
    assert all(write_flags[first_write:])
    assert {round_number for round_number, _ in scheduled[:first_write]} == {1, 2, 3}


@pytest.mark.asyncio
async def test_each_c_phase_preserves_its_start_window_then_drains_for_six_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "persona_password").write_text(
        "performance-only-password", encoding="utf-8"
    )
    dataset = load_module.FrozenDataset(
        color_product_id=1,
        small_color_product_id=2,
        fixed_product_ids=(3,),
        color_kit_color_id=4,
        color_count=221,
        images=(),
        admin=load_module.Persona("admin", 1, "token"),
        customers=(load_module.Persona("user", 2, "token"),),
    )
    factory_calls: list[tuple[str, dict[str, object]]] = []

    class FakeConfig:
        secret_dir = tmp_path
        base_url = "http://127.0.0.1:18083"

    class FakeStack:
        config = FakeConfig()

    class FakeClientContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeEvidence:
        def write_json(self, *_: object) -> None:
            pass

    async def fake_discover(*_: object, **__: object) -> load_module.FrozenDataset:
        return dataset

    def fake_factory(
        kind: str, _variant: str, **kwargs: object
    ) -> object:
        factory_calls.append((kind, kwargs))
        return lambda: None

    async def fake_unmeasured(*_: object, **__: object) -> int:
        return 0

    async def fake_measure(*_: object, **__: object) -> tuple[dict[str, object], int]:
        return {"load": {"profile": "unit"}}, 0

    async def fake_cooldown(*_: object, **__: object) -> dict[str, object]:
        return {}

    async def fake_sleep(_: float) -> None:
        pass

    monkeypatch.setattr(
        harness, "build_client", lambda *_args, **_kwargs: FakeClientContext()
    )
    monkeypatch.setattr(harness, "discover_dataset", fake_discover)
    monkeypatch.setattr(harness, "_run_data_task", lambda *_: {"audit_logs": 11})
    monkeypatch.setattr(
        harness,
        "_scheduled_profiles",
        lambda *_: [
            (1, ("C-cold", 5, "cold")),
            (1, ("B", 5, "")),
        ],
    )
    monkeypatch.setattr(harness, "_factory", fake_factory)
    monkeypatch.setattr(harness, "_unmeasured_phase", fake_unmeasured)
    monkeypatch.setattr(harness, "_measure", fake_measure)
    monkeypatch.setattr(harness, "_confirm_cooldown", fake_cooldown)
    monkeypatch.setattr(harness.asyncio, "sleep", fake_sleep)

    await harness._execute_profiles(
        FakeStack(),  # type: ignore[arg-type]
        FakeEvidence(),  # type: ignore[arg-type]
        _options(
            evidence_level="candidate-pre",
            duration_seconds=300,
            rounds=3,
            ramp_seconds=20,
            warmup_seconds=60,
            cooldown_seconds=30,
        ),
        {"completed": 0},
    )

    assert len(factory_calls) == 6
    c_ramp, c_warmup, c_measured, b_ramp, b_warmup, b_measured = factory_calls
    assert c_ramp[0] == "C-cold"
    assert c_ramp[1]["duration"] == 26
    assert c_ramp[1]["activation_ramp_seconds"] == 20
    assert c_ramp[1]["completion_drain_seconds"] == 6
    assert c_warmup[1]["duration"] == 66
    assert c_warmup[1]["completion_drain_seconds"] == 6
    assert c_measured[1]["duration"] == 306
    assert c_measured[1]["completion_drain_seconds"] == 6
    assert b_ramp[0] == "B"
    assert b_ramp[1]["duration"] == 20
    assert b_ramp[1]["completion_drain_seconds"] == 0
    assert b_warmup[1]["duration"] == 60
    assert b_measured[1]["duration"] == 300


@pytest.mark.asyncio
async def test_image_factory_forwards_completion_drain_to_load_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    dataset = load_module.FrozenDataset(
        color_product_id=1,
        small_color_product_id=2,
        fixed_product_ids=(3,),
        color_kit_color_id=4,
        color_count=221,
        images=(),
        admin=load_module.Persona("admin", 1, "token"),
        customers=(load_module.Persona("user", 2, "token"),),
    )

    async def fake_image_profile(*_: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(harness, "run_image_profile", fake_image_profile)
    factory = harness._factory(
        "C-cold",
        "cold",
        client=object(),  # type: ignore[arg-type]
        dataset=dataset,
        config=PerformanceRunConfig("20260909t120000"),
        options=_options(),
        round_number=1,
        vus=10,
        duration=26,
        image_validators=None,
        key_scope="ramp",
        activation_ramp_seconds=20,
        completion_drain_seconds=6,
    )

    await factory()

    assert captured["duration_seconds"] == 26
    assert captured["activation_ramp_seconds"] == 20
    assert captured["completion_drain_seconds"] == 6


@pytest.mark.asyncio
async def test_capacity_failure_is_reconciled_cooled_and_next_profile_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "persona_password").write_text(
        "performance-only-password", encoding="utf-8"
    )
    dataset = load_module.FrozenDataset(
        color_product_id=1,
        small_color_product_id=2,
        fixed_product_ids=(3,),
        color_kit_color_id=4,
        color_count=221,
        images=(),
        admin=load_module.Persona("admin", 1, "token"),
        customers=(load_module.Persona("user", 2, "token"),),
    )
    capacity_verdict = {"passed": False, "failures": ["qdisc_drop"]}
    capacity_load = _load(
        "A-color-identity", 5, harness.EXPECTED_PROFILE_OPERATIONS["A"]
    )
    capacity_result = {
        "load": capacity_load,
        "monitor": {
            "state_end": _state(),
            "redis": {
                "end": {"evicted_keys": 0, "rejected_connections": 0}
            },
        },
        "verdict": capacity_verdict,
        "failure_handling": harness.classify_profile_failure(
            capacity_verdict,
            load=capacity_load,
            monitor=_monitor(mbps=4.9),
            result_complete=True,
            profile_error_present=False,
        ),
    }
    passing_result = {
        "load": {"profile": "A-color-gzip", "round": 1, "vus": 5},
        "monitor": {
            "state_end": _state(),
            "redis": {
                "end": {"evicted_keys": 0, "rejected_connections": 0}
            },
        },
        "verdict": {"passed": True, "failures": []},
        "failure_handling": {
            "disposition": harness.PROFILE_DISPOSITION_PASS,
        },
    }
    measured = iter((capacity_result, passing_result))
    measured_profiles: list[str] = []
    cooldown_profiles: list[str] = []
    data_tasks: list[tuple[object, ...]] = []
    evidence_names: list[str] = []

    class FakeConfig:
        secret_dir = tmp_path
        base_url = "http://127.0.0.1:18083"

    class FakeStack:
        config = FakeConfig()

    class FakeClientContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeEvidence:
        def write_json(self, *_: object) -> None:
            pass

        def append_jsonl(self, name: str, _: object) -> None:
            evidence_names.append(name)

    async def fake_discover(*_: object, **__: object) -> load_module.FrozenDataset:
        return dataset

    async def fake_measure(
        *_: object,
        profile_label: str,
        **__: object,
    ) -> tuple[dict[str, object], int]:
        measured_profiles.append(profile_label)
        return next(measured), 0

    async def fake_cooldown(
        *_: object,
        profile_label: str,
        **__: object,
    ) -> dict[str, object]:
        cooldown_profiles.append(profile_label)
        return {"passed": True}

    def fake_data_task(_: object, *args: object, **__: object) -> dict[str, object]:
        data_tasks.append(args)
        if args == ("snapshot",):
            return {"audit_logs": 11, "static_fixture_sha256": "a" * 64}
        assert args[0] == "verify"
        return {"passed": True}

    monkeypatch.setattr(
        harness, "build_client", lambda *_args, **_kwargs: FakeClientContext()
    )
    monkeypatch.setattr(harness, "discover_dataset", fake_discover)
    monkeypatch.setattr(harness, "_run_data_task", fake_data_task)
    monkeypatch.setattr(
        harness,
        "_scheduled_profiles",
        lambda *_: [
            (1, ("A-identity", 5, "identity")),
            (1, ("A-gzip", 5, "gzip")),
        ],
    )
    monkeypatch.setattr(harness, "_factory", lambda *_args, **_kwargs: lambda: None)
    monkeypatch.setattr(harness, "_measure", fake_measure)
    monkeypatch.setattr(harness, "_confirm_cooldown", fake_cooldown)
    monkeypatch.setattr(
        harness,
        "_log_summary",
        lambda *_: _log_evidence(),
    )
    monkeypatch.setattr(harness, "_statement_summary", lambda *_: _statement_evidence())

    results, journeys, returned_dataset = await harness._execute_profiles(
        FakeStack(),  # type: ignore[arg-type]
        FakeEvidence(),  # type: ignore[arg-type]
        _options(scenarios=("A",), vus=(5,), cooldown_seconds=0),
        {"completed": 0},
    )

    assert measured_profiles == [
        "A-identity-identity-r1-v5",
        "A-gzip-gzip-r1-v5",
    ]
    assert cooldown_profiles == ["A-identity-identity-r1-v5"]
    assert any(task[0] == "verify" for task in data_tasks)
    assert results[0]["verdict"]["passed"] is False  # type: ignore[index]
    continuation = results[0]["continuation"]
    assert continuation["cooldown_passed"] is True  # type: ignore[index]
    assert continuation["continued_to_later_profile"] is True  # type: ignore[index]
    assert "capacity-failure-checkpoints.jsonl" in evidence_names
    assert "capacity-failure-continuations.jsonl" in evidence_names
    assert journeys == 0
    assert returned_dataset is dataset


@pytest.mark.parametrize("failure_source", ("log", "statement"))
def test_continuation_checkpoint_records_service_error_before_aborting(
    failure_source: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[dict[str, object]] = []

    class FakeEvidence:
        def append_jsonl(self, name: str, values: object) -> None:
            assert name == "capacity-failure-checkpoints.jsonl"
            records.extend(values)  # type: ignore[arg-type]

    monkeypatch.setattr(
        harness,
        "_run_data_task",
        lambda *_args, **_kwargs: {"passed": True},
    )
    monkeypatch.setattr(
        harness,
        "_log_summary",
        lambda *_: _log_evidence(
            traceback_count=int(failure_source == "log")
        ),
    )
    monkeypatch.setattr(
        harness,
        "_statement_summary",
        lambda *_: _statement_evidence(
            errors=int(failure_source == "statement")
        ),
    )

    with pytest.raises(harness.HarnessError, match="service or statement"):
        harness._run_continuation_checkpoint(
            object(),  # type: ignore[arg-type]
            FakeEvidence(),  # type: ignore[arg-type]
            profile_label="A-identity-identity-r1-v5",
            round_number=1,
            vus=5,
            expected_write_journeys=0,
            fixture_digest="a" * 64,
        )

    assert len(records) == 1
    assert records[0]["strict_reconciliation_passed"] is True
    assert records[0]["service_error_check_passed"] is False
    assert records[0]["log_failure_detected"] is (failure_source == "log")
    assert records[0]["statement_error_count"] == int(
        failure_source == "statement"
    )


def test_log_collection_and_statement_evidence_fail_closed() -> None:
    class FailingLogStack:
        def run(self, *_: object, **kwargs: object) -> object:
            assert kwargs.get("check", True) is True
            raise harness.HarnessError("command failed")

    with pytest.raises(harness.HarnessError, match="command failed"):
        harness._log_summary(FailingLogStack())  # type: ignore[arg-type]
    with pytest.raises(harness.HarnessError, match="log evidence is incomplete"):
        harness._service_log_error_detected({})
    with pytest.raises(harness.HarnessError, match="statement evidence is unavailable"):
        harness._statement_error_count([])
    with pytest.raises(harness.HarnessError, match="statement evidence is unavailable"):
        harness._statement_error_count(_statement_evidence(count=0))
    assert harness._statement_error_count(_statement_evidence(errors=3)) == 3


def test_cleanup_uncertainty_never_overwrites_proven_failure() -> None:
    assert harness._verdict_after_cleanup_failure("FAIL") == "FAIL"
    assert harness._verdict_after_cleanup_failure("PASS") == "INCONCLUSIVE"
    assert harness._verdict_after_cleanup_failure("INCONCLUSIVE") == "INCONCLUSIVE"


@pytest.mark.asyncio
async def test_write_capacity_failure_stops_when_strict_checkpoint_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "persona_password").write_text("password", encoding="utf-8")
    dataset = load_module.FrozenDataset(
        color_product_id=1,
        small_color_product_id=2,
        fixed_product_ids=(3,),
        color_kit_color_id=4,
        color_count=221,
        images=(),
        admin=load_module.Persona("admin", 1, "token"),
        customers=(load_module.Persona("user", 2, "token"),),
    )
    verdict = {"passed": False, "failures": ["write_p95_gate"]}
    failed_load = _load(
        "D-color-order-wallet-write",
        5,
        harness.EXPECTED_PROFILE_OPERATIONS["D"],
    )
    failed_result = {
        "load": failed_load,
        "monitor": {"state_end": _state(), "redis": {"end": {}}},
        "verdict": verdict,
        "failure_handling": harness.classify_profile_failure(
            verdict,
            load=failed_load,
            monitor=_monitor(),
            result_complete=True,
            profile_error_present=False,
        ),
    }
    measured_profiles: list[str] = []
    verify_arguments: list[object] = []
    completed_profiles: list[dict[str, object]] = []

    class FakeConfig:
        secret_dir = tmp_path
        base_url = "http://127.0.0.1:18083"

    class FakeStack:
        config = FakeConfig()

    class FakeClientContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeEvidence:
        def write_json(self, *_: object) -> None:
            pass

        def append_jsonl(self, *_: object) -> None:
            pass

    async def fake_measure(
        *_: object,
        profile_label: str,
        **__: object,
    ) -> tuple[dict[str, object], int]:
        measured_profiles.append(profile_label)
        if len(measured_profiles) > 1:
            raise AssertionError("next Profile must not run")
        return failed_result, 2

    async def fake_discover(*_: object, **__: object) -> load_module.FrozenDataset:
        return dataset

    def fake_data_task(_: object, *args: object, **__: object) -> dict[str, object]:
        if args == ("snapshot",):
            return {"audit_logs": 11, "static_fixture_sha256": "a" * 64}
        verify_arguments.extend(args)
        raise harness.HarnessError("strict checkpoint failed")

    monkeypatch.setattr(
        harness, "build_client", lambda *_args, **_kwargs: FakeClientContext()
    )
    monkeypatch.setattr(harness, "discover_dataset", fake_discover)
    monkeypatch.setattr(harness, "_run_data_task", fake_data_task)
    monkeypatch.setattr(
        harness,
        "_scheduled_profiles",
        lambda *_: [
            (1, ("D", 5, "")),
            (1, ("D", 10, "")),
        ],
    )
    monkeypatch.setattr(harness, "_factory", lambda *_args, **_kwargs: lambda: None)
    monkeypatch.setattr(harness, "_measure", fake_measure)

    with pytest.raises(harness.HarnessError, match="strict checkpoint failed"):
        await harness._execute_profiles(
            FakeStack(),  # type: ignore[arg-type]
            FakeEvidence(),  # type: ignore[arg-type]
            _options(scenarios=("D",)),
            {"completed": 2},
            completed_profiles,
        )

    assert measured_profiles == ["D-r1-v5"]
    assert completed_profiles == [failed_result]
    assert "--expected-write-journeys" in verify_arguments
    journey_index = verify_arguments.index("--expected-write-journeys") + 1
    assert verify_arguments[journey_index] == "2"


@pytest.mark.asyncio
async def test_completed_profile_sink_survives_following_cooldown_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "persona_password").write_text(
        "performance-only-password", encoding="utf-8"
    )
    dataset = load_module.FrozenDataset(
        color_product_id=1,
        small_color_product_id=2,
        fixed_product_ids=(3,),
        color_kit_color_id=4,
        color_count=221,
        images=(),
        admin=load_module.Persona("admin", 1, "token"),
        customers=(load_module.Persona("user", 2, "token"),),
    )
    completed_result = {"load": {"profile": "A-color-identity"}}
    completed_profiles: list[dict[str, object]] = []

    class FakeConfig:
        secret_dir = tmp_path
        base_url = "http://127.0.0.1:18083"

    class FakeStack:
        config = FakeConfig()

    class FakeClientContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeEvidence:
        def write_json(self, *_: object) -> None:
            pass

    async def fake_discover(*_: object, **__: object) -> load_module.FrozenDataset:
        return dataset

    async def fake_measure(*_: object, **__: object) -> tuple[dict[str, object], int]:
        return completed_result, 0

    async def fake_cooldown(*_: object, **__: object) -> dict[str, object]:
        raise harness.HarnessError("controlled cooldown failure")

    async def fake_sleep(_: float) -> None:
        pass

    monkeypatch.setattr(harness, "build_client", lambda *_args, **_kwargs: FakeClientContext())
    monkeypatch.setattr(harness, "discover_dataset", fake_discover)
    monkeypatch.setattr(harness, "_run_data_task", lambda *_: {"audit_logs": 11})
    monkeypatch.setattr(
        harness,
        "_scheduled_profiles",
        lambda *_: [(1, ("A-identity", 5, "identity"))],
    )
    monkeypatch.setattr(harness, "_factory", lambda *_args, **_kwargs: lambda: None)
    monkeypatch.setattr(harness, "_measure", fake_measure)
    monkeypatch.setattr(harness, "_confirm_cooldown", fake_cooldown)
    monkeypatch.setattr(harness.asyncio, "sleep", fake_sleep)

    with pytest.raises(harness.HarnessError, match="controlled cooldown"):
        await harness._execute_profiles(
            FakeStack(),  # type: ignore[arg-type]
            FakeEvidence(),  # type: ignore[arg-type]
            _options(),
            {"completed": 0},
            completed_profiles,
        )

    assert completed_profiles == [completed_result]


def test_private_root_and_global_lock_reject_symlinks_and_second_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private"
    monkeypatch.setattr(harness, "WORKSPACE_ROOT", root)
    first = harness.GlobalRunLock(PerformanceRunConfig("20260909t120000"))
    second = harness.GlobalRunLock(PerformanceRunConfig("20260909t120001"))
    first.acquire()
    try:
        assert root.stat().st_mode & 0o777 == 0o700
        assert (root / harness.GLOBAL_LOCK_NAME).stat().st_mode & 0o777 == 0o600
        with pytest.raises(harness.HarnessError, match="another local"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()
    assert not root.exists()

    unsafe_target = tmp_path / "unsafe-target"
    unsafe_target.mkdir()
    unsafe_link = tmp_path / "unsafe-link"
    os.symlink(unsafe_target, unsafe_link)
    with pytest.raises(harness.HarnessError):
        harness._ensure_private_root(unsafe_link)


def test_workspace_guard_accepts_macos_style_resolved_parent_but_not_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspaces"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(harness, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(config_module, "WORKSPACE_ROOT", root)
    config = PerformanceRunConfig("20260909t120000")
    config.workspace.mkdir(mode=0o700)
    assert harness._validated_owned_workspace(config) == config.workspace
    config.workspace.rmdir()
    target = tmp_path / "outside"
    target.mkdir()
    os.symlink(target, config.workspace)
    with pytest.raises(harness.HarnessError):
        harness._validated_owned_workspace(config)


def test_cleanup_cli_has_read_only_inventory_and_explicit_double_gate() -> None:
    parser = harness.build_parser()
    inventory = parser.parse_args(
        ["cleanup-plan", "--run-id", "20260909t120000"]
    )
    cleanup = parser.parse_args([
        "cleanup", "--run-id", "20260909t120000",
        "--confirm-run-id", "20260909t120000", "--apply",
    ])

    assert inventory.command == "cleanup-plan"
    assert cleanup.command == "cleanup"
    assert cleanup.apply is True
    assert cleanup.confirm_run_id == cleanup.run_id


def test_cleanup_removes_only_exact_labeled_objects_and_preserves_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspaces"
    artifact_root = tmp_path / "artifacts"
    workspace_root.mkdir(mode=0o700)
    artifact_root.mkdir(mode=0o700)
    monkeypatch.setattr(harness, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(harness, "ARTIFACT_ROOT", artifact_root)
    monkeypatch.setattr(config_module, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(config_module, "ARTIFACT_ROOT", artifact_root)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    config = PerformanceRunConfig("20260909t120000", http_port=port)
    config.workspace.mkdir(mode=0o700)
    config.artifact_dir.mkdir(mode=0o700)
    (config.artifact_dir / "keep").write_text("evidence", encoding="utf-8")

    class FakeRunner:
        def __init__(self) -> None:
            self.objects = {
                "container": ["container-exact"],
                "network": ["network-exact"],
                "volume": ["volume-exact"],
            }
            self.commands: list[tuple[str, ...]] = []

        def run(
            self,
            args: object,
            **_: object,
        ) -> harness.CompletedCommand:
            command = tuple(args)  # type: ignore[arg-type]
            self.commands.append(command)
            if command[:3] == ("docker", "ps", "--all"):
                output = "\n".join(self.objects["container"])
            elif command[:3] == ("docker", "network", "ls"):
                output = "\n".join(self.objects["network"])
            elif command[:3] == ("docker", "volume", "ls"):
                output = "\n".join(self.objects["volume"])
            elif command[:3] == ("docker", "container", "stop"):
                raise harness.HarnessError("simulated cleanup timeout")
            elif command[:3] == ("docker", "container", "rm"):
                self.objects["container"] = []
                output = ""
            elif command[:3] == ("docker", "network", "rm"):
                self.objects["network"] = []
                output = ""
            elif command[:3] == ("docker", "volume", "rm"):
                self.objects["volume"] = []
                output = ""
            elif command[:3] == ("docker", "image", "inspect"):
                return harness.CompletedCommand(command, 1, "", "not found")
            else:
                output = ""
            return harness.CompletedCommand(command, 0, output, "")

    runner = FakeRunner()
    result = harness.cleanup(harness.ComposeStack(config, runner))  # type: ignore[arg-type]

    assert result["verified"] is True
    assert not config.workspace.exists()
    assert (config.artifact_dir / "keep").read_text(encoding="utf-8") == "evidence"
    flattened = " ".join(" ".join(command) for command in runner.commands)
    assert "container-exact" in flattened
    assert "network-exact" in flattened
    assert "volume-exact" in flattened
    assert "--force" in flattened
    assert any("stop_exact_labeled" in item for item in result["cleanup_errors"])
    assert "prune" not in flattened


@pytest.mark.asyncio
async def test_execute_locked_persists_partial_profiles_and_safe_failure_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_identity = {
        "git_sha": "abc",
        "git_dirty": True,
        "source_tree_sha256": "source",
    }
    completed_result = {"load": {"profile": "A-color-identity", "vus": 5}}
    written_json: dict[str, object] = {}
    written_text: dict[str, str] = {}

    class FakeEvidence:
        def __init__(self, _: Path) -> None:
            pass

        def prepare(self) -> None:
            pass

        def write_json(self, name: str, value: object) -> None:
            written_json[name] = json.loads(json.dumps(value))

        def write_text(self, name: str, value: str) -> None:
            written_text[name] = value

    class FakeRunner:
        pass

    async def fake_profiles(
        _stack: object,
        _evidence: object,
        _options_value: object,
        _journey_progress: object,
        completed_profiles: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], int, object]:
        completed_profiles.append(completed_result)
        try:
            raise RuntimeError("Authorization: Bearer TEST_SECRET")
        except RuntimeError as secret_error:
            raise harness.ProfileRunFailure(
                "controlled cooldown failure", 0
            ) from secret_error

    monkeypatch.setattr(harness, "preflight", lambda *_: source_identity)
    monkeypatch.setattr(harness, "EvidenceWriter", FakeEvidence)
    monkeypatch.setattr(harness, "_prepare_private_workspace", lambda *_: None)
    monkeypatch.setattr(harness, "_build_images", lambda *_: {})
    monkeypatch.setattr(harness, "_prepare_stack", lambda *_: {})
    monkeypatch.setattr(harness, "_run_data_task", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(harness, "_execute_profiles", fake_profiles)
    monkeypatch.setattr(
        harness, "_host_available_memory_bytes", lambda *_: 4 * 1024**3
    )
    monkeypatch.setattr(
        harness,
        "cleanup",
        lambda *_: {"verified": True, "residual_docker_objects": {}},
    )

    with pytest.raises(harness.HarnessError, match="did not pass"):
        await harness._execute_locked(
            PerformanceRunConfig("20260909t120000"),
            _options(),
            FakeRunner(),  # type: ignore[arg-type]
        )

    summary = written_json["summary.json"]
    assert isinstance(summary, dict)
    assert summary["profiles"] == [completed_result]
    assert summary["verdict"] == "FAIL"
    assert summary["failure_type"] == "ProfileRunFailure"
    assert summary["failure_reason"] == "controlled cooldown failure"
    persisted = json.dumps(summary) + written_text["report.md"]
    assert "TEST_SECRET" not in persisted
    assert "Authorization" not in persisted


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_verified", (True, False))
async def test_complete_matrix_with_capacity_failure_reconciles_cleans_and_fails(
    cleanup_verified: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_identity = {
        "git_sha": "abc",
        "git_dirty": True,
        "source_tree_sha256": "source",
    }
    dataset = load_module.FrozenDataset(
        color_product_id=1,
        small_color_product_id=2,
        fixed_product_ids=(3,),
        color_kit_color_id=4,
        color_count=221,
        images=(),
        admin=load_module.Persona("admin", 1, "token"),
        customers=(load_module.Persona("user", 2, "token"),),
    )
    failed_profile = {
        "load": {"profile": "A-color-identity", "round": 1, "vus": 5},
        "monitor": {},
        "verdict": {"passed": False, "failures": ["qdisc_drop"]},
        "failure_handling": {
            "disposition": harness.PROFILE_DISPOSITION_CONTINUE,
        },
        "continuation": {
            "cooldown_passed": True,
            "continued_to_later_profile": True,
        },
    }
    passing_profile = {
        "load": {"profile": "A-color-gzip", "round": 1, "vus": 5},
        "monitor": {},
        "verdict": {"passed": True, "failures": []},
        "failure_handling": {
            "disposition": harness.PROFILE_DISPOSITION_PASS,
        },
    }
    written_json: dict[str, object] = {}
    written_text: dict[str, str] = {}
    data_tasks: list[tuple[object, ...]] = []

    class FakeEvidence:
        def __init__(self, _: Path) -> None:
            pass

        def prepare(self) -> None:
            pass

        def write_json(self, name: str, value: object) -> None:
            written_json[name] = json.loads(json.dumps(value))

        def write_text(self, name: str, value: str) -> None:
            written_text[name] = value

    class FakeRunner:
        def run(self, args: object, **_: object) -> harness.CompletedCommand:
            command = tuple(args)  # type: ignore[arg-type]
            if command[:3] == ("git", "rev-parse", "HEAD"):
                output = "abc\n"
            elif command[:2] == ("git", "status"):
                output = ""
            else:
                raise AssertionError(command)
            return harness.CompletedCommand(command, 0, output, "")

    async def fake_profiles(
        _stack: object,
        _evidence: object,
        _options_value: object,
        _journey_progress: object,
        completed_profiles: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], int, load_module.FrozenDataset]:
        completed_profiles.extend((failed_profile, passing_profile))
        return completed_profiles, 0, dataset

    def fake_data_task(_: object, *args: object, **__: object) -> dict[str, object]:
        data_tasks.append(args)
        if args == ("snapshot",):
            return {"static_fixture_sha256": "a" * 64}
        if args[0] == "verify":
            return {"passed": True, "expected_write_journeys": 0}
        assert args[0] == "forensic"
        return {"available": True, "fully_reconciled": True}

    monkeypatch.setattr(harness, "preflight", lambda *_: source_identity)
    monkeypatch.setattr(harness, "EvidenceWriter", FakeEvidence)
    monkeypatch.setattr(harness, "_prepare_private_workspace", lambda *_: None)
    monkeypatch.setattr(harness, "_build_images", lambda *_: {})
    monkeypatch.setattr(harness, "_prepare_stack", lambda *_: {})
    monkeypatch.setattr(harness, "_run_data_task", fake_data_task)
    monkeypatch.setattr(harness, "_execute_profiles", fake_profiles)
    monkeypatch.setattr(
        harness,
        "aggregate_profiles",
        lambda *_: {"passed": False, "profile_gates_passed": False},
    )
    monkeypatch.setattr(harness, "_statement_summary", lambda *_: _statement_evidence())
    monkeypatch.setattr(
        harness,
        "_log_summary",
        lambda *_: _log_evidence(),
    )
    monkeypatch.setattr(harness, "content_digest", lambda *_: "source")
    monkeypatch.setattr(
        harness,
        "_host_available_memory_bytes",
        lambda *_: 4 * 1024**3,
    )
    monkeypatch.setattr(
        harness,
        "cleanup",
        lambda *_: {
            "verified": cleanup_verified,
            "residual_docker_objects": {},
        },
    )

    with pytest.raises(harness.HarnessError, match="did not pass"):
        await harness._execute_locked(
            PerformanceRunConfig("20260909t120000"),
            _options(scenarios=("A",), vus=(5,)),
            FakeRunner(),  # type: ignore[arg-type]
        )

    summary = written_json["summary.json"]
    assert isinstance(summary, dict)
    assert summary["verdict"] == "FAIL"
    assert summary["failure_reason"] == (
        "frozen capacity gates failed after the complete profile matrix"
    )
    assert summary["reconciliation"] == {
        "passed": True,
        "expected_write_journeys": 0,
    }
    assert summary["cleanup"]["verified"] is cleanup_verified  # type: ignore[index]
    execution = summary["profile_execution"]
    assert execution["matrix_complete"] is True  # type: ignore[index]
    assert execution["capacity_failed_profile_count"] == 1  # type: ignore[index]
    assert execution["recorded_profile_count"] == 2  # type: ignore[index]
    assert summary["profiles"][0]["verdict"]["passed"] is False  # type: ignore[index]
    assert any(task[0] == "verify" for task in data_tasks)


@pytest.mark.asyncio
async def test_successful_body_with_unverified_cleanup_still_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_identity = {"git_sha": "abc", "source_tree_sha256": "source"}
    dataset = load_module.FrozenDataset(
        color_product_id=1,
        small_color_product_id=2,
        fixed_product_ids=(3,),
        color_kit_color_id=4,
        color_count=221,
        images=(),
        admin=load_module.Persona("admin", 1, "token"),
        customers=(load_module.Persona("user", 2, "token"),),
    )

    class FakeEvidence:
        def __init__(self, _: Path) -> None:
            pass

        def prepare(self) -> None:
            pass

        def write_json(self, *_: object) -> None:
            pass

        def write_text(self, *_: object) -> None:
            pass

    class FakeRunner:
        def run(self, args: object, **_: object) -> harness.CompletedCommand:
            command = tuple(args)  # type: ignore[arg-type]
            if command[:3] == ("git", "rev-parse", "HEAD"):
                output = "abc\n"
            elif command[:2] == ("git", "status"):
                output = ""
            else:
                raise AssertionError(command)
            return harness.CompletedCommand(command, 0, output, "")

    async def fake_profiles(*_: object) -> tuple[list[dict[str, object]], int, object]:
        return [], 0, dataset

    monkeypatch.setattr(harness, "preflight", lambda *_: source_identity)
    monkeypatch.setattr(harness, "EvidenceWriter", FakeEvidence)
    monkeypatch.setattr(harness, "_prepare_private_workspace", lambda *_: None)
    monkeypatch.setattr(harness, "_build_images", lambda *_: {})
    monkeypatch.setattr(harness, "_prepare_stack", lambda *_: {})
    monkeypatch.setattr(
        harness,
        "_run_data_task",
        lambda *args, **_: (
            {"static_fixture_sha256": "a" * 64}
            if "snapshot" in args
            else {"passed": True}
        ),
    )
    monkeypatch.setattr(harness, "_execute_profiles", fake_profiles)
    monkeypatch.setattr(harness, "aggregate_profiles", lambda *_: {"passed": True})
    monkeypatch.setattr(harness, "_statement_summary", lambda *_: _statement_evidence())
    monkeypatch.setattr(
        harness,
        "_log_summary",
        lambda *_: _log_evidence(),
    )
    monkeypatch.setattr(harness, "content_digest", lambda *_: "source")
    monkeypatch.setattr(
        harness,
        "cleanup",
        lambda *_: {"verified": False, "residual_docker_objects": {}},
    )
    monkeypatch.setattr(harness, "_render_report", lambda *_: "report")

    with pytest.raises(harness.HarnessError, match="did not pass") as error:
        await harness._execute_locked(
            PerformanceRunConfig("20260909t120000"),
            _options(),
            FakeRunner(),  # type: ignore[arg-type]
        )
    assert isinstance(error.value.__cause__, harness.HarnessError)
    assert "cleanup" in str(error.value.__cause__)


def test_actual_staged_app_context_excludes_nested_gitignored_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    files = {
        "requirements.txt": "httpx\n",
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "app/main.py": "value = 1\n",
        "migrations/models/0_1.py": "value = 1\n",
        "deploy/runtime/app-entrypoint.sh": "#!/bin/sh\nexec \"$@\"\n",
        "deploy/performance/Dockerfile.app": "FROM scratch\n",
        "deploy/performance/Dockerfile.app.dockerignore": "**\n!app/**\n",
        ".gitignore": ".env\n*.env\n*.pem\n*credentials*.json\n__pycache__/\n*.pyc\n",
    }
    for relative, value in files.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    hidden = {
        "app/.env": "secret",
        "app/nested/local.env": "secret",
        "app/nested/private.pem": "secret",
        "app/nested/service-credentials.json": "secret",
        "app/__pycache__/main.pyc": "secret",
        "app/local_token.txt": "untracked secret-like local file",
    }
    for relative, value in hidden.items():
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    runner = harness.CommandRunner(cwd=repository)
    runner.run(["git", "init", "--quiet"])
    runner.run([
        "git", "add", ".gitignore", "requirements.txt", "pyproject.toml",
        "app/main.py", "migrations/models/0_1.py",
        "deploy/runtime/app-entrypoint.sh",
    ])
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir(mode=0o700)
    monkeypatch.setattr(harness, "REPOSITORY_ROOT", repository)
    monkeypatch.setattr(harness, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(config_module, "WORKSPACE_ROOT", workspace_root)
    config = PerformanceRunConfig("20260909t120000")
    config.workspace.mkdir(mode=0o700)

    context, identity = harness._prepare_app_build_context(config, runner)

    assert (context / "app/main.py").is_file()
    assert (context / "migrations/models/0_1.py").is_file()
    assert (context / "Dockerfile").is_file()
    assert identity["file_count"] == 7
    for relative in hidden:
        assert not (context / relative).exists()
