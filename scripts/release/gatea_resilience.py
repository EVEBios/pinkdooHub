#!/usr/bin/env python3
"""执行 Gate A 持久依赖故障、应用重启与日志可观测性演练。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

from scripts.release import gatea_backup
from scripts.release import gatea_operations as gatea


DEFAULT_REPRESENTATIVE_RECORD = Path(
    "/srv/pinkdoohub/gatea/records/representative-data/"
    "gatea-representative-data.json"
)
DEFAULT_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/resilience")
RECORD_NAME = "gatea-resilience.json"
SERVICES = ("mysql", "redis", "app", "nginx")
FORBIDDEN_LOG_PATTERNS = (
    re.compile(r"authorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(r"(?:access|refresh)_token[\"'=:\s]+[A-Za-z0-9_.-]{12,}", re.IGNORECASE),
    re.compile(r"(?:redis|rediss|mysql(?:\+\w+)?)://[^\s/@]+:[^\s/@]+@", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
NGINX_METRIC_PATTERN = re.compile(
    r'"[A-Z]+ [^\"]+ HTTP/[^\"]+"\s+(?P<status>\d{3})\s+\d+\s+'
    r"request_time=(?P<duration>\d+(?:\.\d+)?)"
)


class ResilienceError(RuntimeError):
    """不包含日志正文、Secret、连接串或用户身份的安全演练错误。"""


def _http_status(port: int, path: str) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", path, headers={"Connection": "close"})
        response = connection.getresponse()
        response.read()
        return response.status
    except OSError:
        return 0
    finally:
        connection.close()


def _wait_http(
    *,
    port: int,
    path: str,
    expected: set[int],
    timeout: int,
) -> tuple[int, float]:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        status = _http_status(port, path)
        if status in expected:
            return status, round(time.monotonic() - started, 3)
        time.sleep(1)
    raise ResilienceError("Gate A health transition did not reach the expected state")


def _wait_services(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    services: Sequence[str],
    timeout: int,
) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        rows = gatea._compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            services=services,
        )
        try:
            gatea._ensure_services_healthy(rows, *services)
            return round(time.monotonic() - started, 3)
        except gatea.GateAError:
            time.sleep(1)
    raise ResilienceError("Gate A services did not recover before the timeout")


def _restore_all_services(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    release_record_dir: Path,
    timeout: int,
) -> None:
    gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=(
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            str(timeout),
            "mysql",
            "redis",
        ),
    )
    gatea.app_up(
        config_file=config_file,
        secret_dir=secret_dir,
        record_dir=release_record_dir,
        mode="loopback",
        wait_timeout=timeout,
    )


def _dependency_drill(
    *,
    service: str,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    port: int,
    timeout: int,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("stop", "--timeout", "30", service),
    )
    readiness_status, failure_seconds = _wait_http(
        port=port,
        path="/api/v1/health/ready",
        expected={503},
        timeout=45,
    )
    liveness_status = _http_status(port, "/api/v1/health/live")
    if liveness_status != 200:
        raise ResilienceError("Gate A liveness failed during a dependency outage")
    gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("start", service),
    )
    service_recovery_seconds = _wait_services(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=(service,),
        timeout=timeout,
    )
    recovered_status, readiness_recovery_seconds = _wait_http(
        port=port,
        path="/api/v1/health/ready",
        expected={200},
        timeout=timeout,
    )
    return {
        "service": service,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "outage_readiness_status": readiness_status,
        "outage_liveness_status": liveness_status,
        "failure_detection_seconds": failure_seconds,
        "service_recovery_seconds": service_recovery_seconds,
        "readiness_recovery_seconds": readiness_recovery_seconds,
        "recovered_readiness_status": recovered_status,
        "passed": True,
    }


def _app_restart_drill(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    port: int,
    timeout: int,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("restart", "--timeout", "30", "app"),
    )
    service_recovery_seconds = _wait_services(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=("app",),
        timeout=timeout,
    )
    readiness_status, readiness_recovery_seconds = _wait_http(
        port=port,
        path="/api/v1/health/ready",
        expected={200},
        timeout=timeout,
    )
    return {
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "total_seconds": round(time.monotonic() - started, 3),
        "service_recovery_seconds": service_recovery_seconds,
        "readiness_recovery_seconds": readiness_recovery_seconds,
        "readiness_status": readiness_status,
        "passed": True,
    }


def _service_container_id(
    *,
    service: str,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> str:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("ps", "--quiet", service),
        capture_output=True,
    )
    container_id = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        raise ResilienceError("Gate A service container identity is invalid")
    return container_id


def _log_rotation_contract(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for service in SERVICES:
        container_id = _service_container_id(
            service=service,
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
        )
        inspected = subprocess.run(
            (
                "docker",
                "inspect",
                "--format",
                "{{json .HostConfig.LogConfig}}",
                container_id,
            ),
            check=True,
            text=True,
            capture_output=True,
        )
        try:
            payload = json.loads(inspected.stdout)
        except json.JSONDecodeError as error:
            raise ResilienceError("Gate A Docker log metadata is invalid") from error
        if payload != {
            "Type": "json-file",
            "Config": {"max-file": "5", "max-size": "10m"},
        }:
            raise ResilienceError("Gate A Docker log rotation contract does not match")
        result[service] = {
            "driver": "json-file",
            "max_file": "5",
            "max_size": "10m",
        }
    return result


def _compose_logs(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    services: Sequence[str],
) -> str:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("logs", "--no-color", "--since", "24h", *services),
        capture_output=True,
    )
    return (result.stdout or "") + (result.stderr or "")


def _scan_logs(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> dict[str, Any]:
    logs = _compose_logs(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=SERVICES,
    )
    secret_values: list[str] = []
    for secret_name in gatea.EXPECTED_SECRET_FILES:
        value = (secret_dir / secret_name).read_text(encoding="utf-8").strip()
        if len(value) < 12:
            raise ResilienceError("Gate A Secret does not meet the log scan length floor")
        secret_values.append(value)
    if any(secret in logs for secret in secret_values):
        raise ResilienceError("Gate A logs contain an exact Secret value")
    if any(pattern.search(logs) for pattern in FORBIDDEN_LOG_PATTERNS):
        raise ResilienceError("Gate A logs contain a forbidden sensitive pattern")

    nginx_logs = _compose_logs(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=("nginx",),
    )
    statuses: list[int] = []
    durations: list[float] = []
    for match in NGINX_METRIC_PATTERN.finditer(nginx_logs):
        statuses.append(int(match.group("status")))
        durations.append(float(match.group("duration")))
    if not statuses or not durations:
        raise ResilienceError("Gate A Nginx logs have no queryable request metrics")
    ordered = sorted(durations)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "window": "24h",
        "combined_line_count": len(logs.splitlines()),
        "nginx_request_count": len(statuses),
        "nginx_4xx_count": sum(400 <= status < 500 for status in statuses),
        "nginx_5xx_count": sum(status >= 500 for status in statuses),
        "request_time_seconds": {
            "median": round(statistics.median(durations), 6),
            "p95": round(ordered[p95_index], 6),
            "max": round(max(durations), 6),
        },
        "exact_secret_matches": 0,
        "forbidden_pattern_matches": 0,
        "raw_log_content_recorded": False,
        "passed": True,
    }


def _load_representative_record(
    path: Path, candidate_sha: str, image_id: str
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("schema_version") != 1
            or payload.get("candidate_sha") != candidate_sha
            or payload.get("image_id") != image_id
            or payload.get("passed") is not True
            or payload.get("synthetic_user_disabled") is not True
            or payload.get("synthetic_session_revoked") is not True
            or payload.get("super_admin_session_revoked") is not True
            or payload.get("pii_recorded") is not False
            or payload.get("secret_values_recorded") is not False
        ):
            raise ValueError
    except (FileNotFoundError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ResilienceError("Gate A representative data record is invalid") from error
    return payload


def execute(
    *,
    config_file: Path,
    secret_dir: Path,
    release_record_dir: Path,
    representative_record: Path,
    record_dir: Path,
    wait_timeout: int,
) -> dict[str, Any]:
    """执行两次依赖故障、应用重启、数据保持与日志安全验证。"""

    if os.geteuid() != 0:
        raise ResilienceError("Gate A resilience drill must run as root")
    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        require_available_port=False,
    )
    gatea._validate_root_directory(
        record_dir, 0o755, "Gate A resilience record directory"
    )
    record_path = record_dir / RECORD_NAME
    if record_path.exists():
        raise ResilienceError("Gate A resilience drill is already recorded")
    image_id = gatea.validate_app_image(values)
    candidate_sha = gatea._candidate_sha(values)
    gatea._require_migration_record(
        record_dir=release_record_dir,
        candidate_sha=candidate_sha,
        image_id=image_id,
    )
    _load_representative_record(representative_record, candidate_sha, image_id)
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=SERVICES,
    )
    gatea._ensure_services_healthy(rows, *SERVICES)
    gatea._validate_loopback_publishers(
        rows, int(values.get("GATEA_LOOPBACK_PORT", "18080"))
    )
    before_snapshot = gatea_backup._source_snapshot(
        values, config_file, secret_dir, "loopback"
    )
    before_images = gatea_backup._source_image_manifest(
        values, config_file, secret_dir, "loopback"
    )
    port = int(values.get("GATEA_LOOPBACK_PORT", "18080"))
    started_at = datetime.now(timezone.utc).isoformat()
    drills: list[dict[str, Any]] = []
    operation_error: BaseException | None = None
    try:
        for service in ("mysql", "redis"):
            drills.append(
                _dependency_drill(
                    service=service,
                    values=values,
                    config_file=config_file,
                    secret_dir=secret_dir,
                    port=port,
                    timeout=wait_timeout,
                )
            )
        app_restart = _app_restart_drill(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            port=port,
            timeout=wait_timeout,
        )
    except BaseException as error:
        operation_error = error
        app_restart = {}

    recovery_error: BaseException | None = None
    try:
        _restore_all_services(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            release_record_dir=release_record_dir,
            timeout=wait_timeout,
        )
    except BaseException as error:
        recovery_error = error
    if recovery_error is not None:
        raise ResilienceError("Gate A resilience recovery failed") from recovery_error
    if operation_error is not None:
        if isinstance(operation_error, ResilienceError):
            raise operation_error
        raise ResilienceError("Gate A resilience drill failed safely") from operation_error

    after_snapshot = gatea_backup._source_snapshot(
        values, config_file, secret_dir, "loopback"
    )
    after_images = gatea_backup._source_image_manifest(
        values, config_file, secret_dir, "loopback"
    )
    if after_snapshot != before_snapshot:
        raise ResilienceError("Gate A data changed during the resilience drill")
    if after_images != before_images:
        raise ResilienceError("Gate A images changed during the resilience drill")
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=SERVICES,
    )
    gatea._ensure_services_healthy(rows, *SERVICES)
    gatea._validate_loopback_publishers(rows, port)
    log_rotation = _log_rotation_contract(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
    )
    log_observability = _scan_logs(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
    )
    payload = {
        "schema_version": 1,
        "candidate_sha": candidate_sha,
        "image_id": image_id,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "dependency_drills": drills,
        "app_restart": app_restart,
        "database_snapshot_unchanged": True,
        "image_manifest_unchanged": True,
        "image_file_count": len(after_images),
        "source_services_healthy": True,
        "loopback_only": True,
        "log_rotation": log_rotation,
        "log_observability": log_observability,
        "pii_recorded": False,
        "secret_values_recorded": False,
        "passed": True,
    }
    gatea_backup._write_json_atomic(record_path, payload, 0o644)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--config-file", type=Path, default=gatea.DEFAULT_CONFIG_FILE)
    parser.add_argument("--secret-dir", type=Path, default=gatea.DEFAULT_SECRET_DIR)
    parser.add_argument(
        "--release-record-dir", type=Path, default=gatea.DEFAULT_RECORD_DIR
    )
    parser.add_argument(
        "--representative-record",
        type=Path,
        default=DEFAULT_REPRESENTATIVE_RECORD,
    )
    parser.add_argument("--record-dir", type=Path, default=DEFAULT_RECORD_DIR)
    parser.add_argument("--wait-timeout", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if not arguments.apply:
            raise ResilienceError("Gate A resilience drill requires --apply")
        if not 60 <= arguments.wait_timeout <= 600:
            raise ResilienceError("Gate A resilience wait timeout is invalid")
        execute(
            config_file=arguments.config_file,
            secret_dir=arguments.secret_dir,
            release_record_dir=arguments.release_record_dir,
            representative_record=arguments.representative_record,
            record_dir=arguments.record_dir,
            wait_timeout=arguments.wait_timeout,
        )
    except (
        ResilienceError,
        gatea.GateAError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Gate A resilience drill failed: {error}", file=sys.stderr)
        return 1
    print("Gate A dependency, restart, data, and log resilience drill passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
