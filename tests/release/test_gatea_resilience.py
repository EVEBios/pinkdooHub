"""Gate A 持久依赖故障、重启和日志观察边界。"""

import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts.release import gatea_operations as gatea
from scripts.release import gatea_resilience as resilience


def _values() -> dict[str, str]:
    return {
        "GATEA_APP_IMAGE": "pinkdoohub-gatea:" + "a" * 40,
        "GATEA_LOOPBACK_PORT": "18080",
    }


def _secret_dir(tmp_path: Path) -> Path:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    for index, name in enumerate(gatea.EXPECTED_SECRET_FILES):
        (secret_dir / name).write_text(
            f"test-only-secret-{index}-abcdefghijklmnopqrstuvwxyz",
            encoding="utf-8",
        )
    return secret_dir


def test_dependency_drill_stops_observes_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    http_waits = iter(((503, 1.25), (200, 2.5)))
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess([], 0, stdout=""),
    )
    monkeypatch.setattr(
        resilience, "_wait_http", lambda **kwargs: next(http_waits)
    )
    monkeypatch.setattr(resilience, "_http_status", lambda *args: 200)
    monkeypatch.setattr(resilience, "_wait_services", lambda **kwargs: 3.5)

    result = resilience._dependency_drill(
        service="mysql",
        values=_values(),
        config_file=Path("/config"),
        secret_dir=Path("/secrets"),
        port=18080,
        timeout=180,
    )

    assert commands == [
        ("stop", "--timeout", "30", "mysql"),
        ("start", "mysql"),
    ]
    assert result["outage_readiness_status"] == 503
    assert result["outage_liveness_status"] == 200
    assert result["recovered_readiness_status"] == 200
    assert result["passed"] is True


def test_dependency_drill_requires_liveness_during_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess([], 0, stdout=""),
    )
    monkeypatch.setattr(resilience, "_wait_http", lambda **kwargs: (503, 1.0))
    monkeypatch.setattr(resilience, "_http_status", lambda *args: 500)

    with pytest.raises(resilience.ResilienceError, match="liveness"):
        resilience._dependency_drill(
            service="redis",
            values=_values(),
            config_file=Path("/config"),
            secret_dir=Path("/secrets"),
            port=18080,
            timeout=180,
        )


def test_log_rotation_requires_exact_bounded_json_file_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resilience,
        "_service_container_id",
        lambda **kwargs: "a" * 64,
    )
    payload = {"Type": "json-file", "Config": {"max-file": "5", "max-size": "10m"}}
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout=json.dumps(payload)
        ),
    )

    result = resilience._log_rotation_contract(
        values=_values(),
        config_file=Path("/config"),
        secret_dir=Path("/secrets"),
    )
    assert set(result) == set(resilience.SERVICES)
    assert result["app"] == {
        "driver": "json-file",
        "max_file": "5",
        "max_size": "10m",
    }

    payload["Config"]["max-size"] = "unbounded"
    with pytest.raises(resilience.ResilienceError, match="rotation contract"):
        resilience._log_rotation_contract(
            values=_values(),
            config_file=Path("/config"),
            secret_dir=Path("/secrets"),
        )


def test_restore_all_services_reuses_existing_loopback_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _values()
    commands: list[tuple[str, ...]] = []
    publisher_checks: list[int] = []
    rows = [
        {"Service": name, "State": "running", "Health": "healthy"}
        for name in resilience.SERVICES
    ]
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess([], 0, stdout=""),
    )
    monkeypatch.setattr(gatea, "_compose_ps", lambda **kwargs: rows)
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_validate_loopback_publishers",
        lambda actual_rows, port: publisher_checks.append(port),
    )
    monkeypatch.setattr(
        gatea,
        "app_up",
        lambda **kwargs: pytest.fail("first-start app_up must not run during recovery"),
    )

    resilience._restore_all_services(
        values=values,
        config_file=Path("/config"),
        secret_dir=Path("/secrets"),
        timeout=180,
    )

    assert commands == [
        (
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "180",
            "mysql",
            "redis",
            "app",
            "nginx",
        )
    ]
    assert publisher_checks == [18080]


def test_log_scan_records_only_aggregates_and_no_raw_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_dir = _secret_dir(tmp_path)
    logs = (
        'nginx | "GET /api/v1/health/ready HTTP/1.1" 200 10 '
        "request_time=0.010 request_id=safe\n"
        'nginx | "GET /api/v1/products HTTP/1.1" 404 10 '
        "request_time=0.250 request_id=safe\n"
    )
    monkeypatch.setattr(resilience, "_compose_logs", lambda **kwargs: logs)

    result = resilience._scan_logs(
        values=_values(),
        config_file=Path("/config"),
        secret_dir=secret_dir,
    )

    assert result["nginx_request_count"] == 2
    assert result["nginx_4xx_count"] == 1
    assert result["nginx_5xx_count"] == 0
    assert result["request_time_seconds"]["max"] == 0.25
    assert result["raw_log_content_recorded"] is False
    assert "GET" not in json.dumps(result)


@pytest.mark.parametrize(
    "unsafe_log",
    (
        "Authorization: Bearer signed.token.value",
        "redis://service:credential@redis:6379/0",
        "-----BEGIN " + "PRIVATE KEY-----",
    ),
)
def test_log_scan_rejects_sensitive_patterns_without_echoing_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    unsafe_log: str,
) -> None:
    secret_dir = _secret_dir(tmp_path)
    monkeypatch.setattr(resilience, "_compose_logs", lambda **kwargs: unsafe_log)

    with pytest.raises(resilience.ResilienceError) as captured:
        resilience._scan_logs(
            values=_values(),
            config_file=Path("/config"),
            secret_dir=secret_dir,
        )
    assert unsafe_log not in str(captured.value)


def test_log_scan_rejects_exact_secret_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_dir = _secret_dir(tmp_path)
    secret = (secret_dir / gatea.EXPECTED_SECRET_FILES[0]).read_text().strip()
    monkeypatch.setattr(resilience, "_compose_logs", lambda **kwargs: secret)

    with pytest.raises(resilience.ResilienceError) as captured:
        resilience._scan_logs(
            values=_values(),
            config_file=Path("/config"),
            secret_dir=secret_dir,
        )
    assert secret not in str(captured.value)


def test_representative_record_must_be_safe_and_bound_to_runtime(
    tmp_path: Path,
) -> None:
    record = tmp_path / "representative.json"
    payload = {
        "schema_version": 1,
        "candidate_sha": "a" * 40,
        "image_id": "sha256:image",
        "synthetic_user_disabled": True,
        "synthetic_session_revoked": True,
        "super_admin_session_revoked": True,
        "pii_recorded": False,
        "secret_values_recorded": False,
        "passed": True,
    }
    record.write_text(json.dumps(payload), encoding="utf-8")

    assert resilience._load_representative_record(
        record, "a" * 40, "sha256:image"
    ) == payload

    payload["secret_values_recorded"] = True
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(resilience.ResilienceError, match="record is invalid"):
        resilience._load_representative_record(
            record, "a" * 40, "sha256:image"
        )


def test_execute_recovers_services_even_when_dependency_drill_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _values()
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    representative = tmp_path / "representative.json"
    representative.write_text("{}", encoding="utf-8")
    recovered: list[bool] = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:image")
    monkeypatch.setattr(gatea, "_require_migration_record", lambda **kwargs: None)
    monkeypatch.setattr(resilience, "_load_representative_record", lambda *args: {})
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in resilience.SERVICES
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(gatea, "_validate_loopback_publishers", lambda *args: None)
    monkeypatch.setattr(
        resilience.gatea_backup, "_source_snapshot", lambda *args: {"users": 2}
    )
    monkeypatch.setattr(
        resilience.gatea_backup,
        "_source_image_manifest",
        lambda *args: ["fixture.png"],
    )
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: (_ for _ in ()).throw(
            resilience.ResilienceError("safe failure")
        ),
    )
    monkeypatch.setattr(
        resilience,
        "_restore_all_services",
        lambda **kwargs: recovered.append(True),
    )

    with pytest.raises(resilience.ResilienceError, match="safe failure"):
        resilience.execute(
            config_file=tmp_path / "config",
            secret_dir=tmp_path / "secrets",
            release_record_dir=tmp_path / "releases",
            representative_record=representative,
            record_dir=record_dir,
            wait_timeout=180,
        )

    assert recovered == [True]
    assert not (record_dir / resilience.RECORD_NAME).exists()
