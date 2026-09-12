"""Gate A 持久依赖故障、重启和日志观察边界。"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
from typing import Iterator

import pytest

from scripts.release import gatea_backup
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


def _content_snapshots(*, include_m9: bool = True) -> dict[str, dict[str, object]]:
    snapshots: dict[str, dict[str, object]] = {
        "m7_preserved_business": {
            "schema_version": 1,
            "profile": gatea_backup.M7_CONTENT_SNAPSHOT_PROFILE,
            "content_sha256": "b" * 64,
        }
    }
    if include_m9:
        snapshots["m8_swatch_content"] = {
            "schema_version": 1,
            "profile": gatea_backup.M8_SWATCH_CONTENT_SNAPSHOT_PROFILE,
            "content_sha256": "8" * 64,
        }
        snapshots["m9_table_business"] = {
            "schema_version": 1,
            "profile": gatea_backup.M9_TABLE_CONTENT_SNAPSHOT_PROFILE,
            "content_sha256": "c" * 64,
        }
    return snapshots


def _m7_representative_payload(credentials_file: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "gatea-m7-representative-data",
        "candidate_sha": "b" * 40,
        "image_id": "sha256:source-image",
        "operations_sha": "c" * 40,
        "backup_id": "20260908t120000z",
        "started_at": "2026-09-08T12:00:00+00:00",
        "completed_at": "2026-09-08T12:05:00+00:00",
        "before_snapshot": {"users": 2},
        "after_snapshot": {"users": 5},
        "representative_details": {"orders": 6},
        "synthetic_user_ids": [11, 12, 13],
        "color_product_id": 21,
        "color_ids": [31, 32, 33],
        "order_ids": [41, 42, 43, 44, 45, 46],
        "reservation_ids": [51, 52, 53, 54, 55, 56],
        "before_image_file_count": 225,
        "after_image_file_count": 226,
        "request_count": 100,
        "synthetic_sessions_revoked": True,
        "super_admin_session_revoked": True,
        "credentials_file": str(credentials_file),
        "credentials_file_mode": "0600",
        "credentials_sha256": "d" * 64,
        "super_admin_credentials_recorded": False,
        "request_or_response_bodies_recorded": False,
        "loopback_only": True,
        "passed": True,
    }


def _stub_execute_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[dict[str, str], Path, Path]:
    """隔离 execute 的只读边界，让专项测试只观察演练与恢复次序。"""

    values = _values()
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    representative = tmp_path / "representative.json"
    representative.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        gatea,
        "reject_unresolved_candidate_transition_journals",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        gatea,
        "reject_unresolved_m9_acceptance_sidecars",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "_validate_root_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:image")
    monkeypatch.setattr(
        gatea,
        "_require_deployment_record",
        lambda **kwargs: {"schema_version": 1},
    )
    monkeypatch.setattr(
        resilience,
        "_load_representative_record",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        resilience,
        "_validate_representative_record_file",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in resilience.M9_SERVICES
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(gatea, "_validate_loopback_publishers", lambda *args: None)
    monkeypatch.setattr(
        resilience.gatea_backup,
        "_source_snapshot",
        lambda *args: {
            "aerich_versions": ",".join(gatea.APPROVED_TARGET_M9_CHAIN),
            "users": 2,
        },
    )
    monkeypatch.setattr(
        resilience.gatea_backup,
        "_source_image_manifest",
        lambda *args: ["fixture.png"],
    )
    monkeypatch.setattr(
        resilience,
        "_database_content_snapshots",
        lambda **kwargs: _content_snapshots(),
    )
    acceptance_path = (
        tmp_path
        / f"gatea-m9-runtime-acceptance-{'a' * 40}.json"
    )
    acceptance_path.write_text("{}\n", encoding="utf-8")
    acceptance_path.chmod(0o644)
    acceptance_evidence = resilience._RuntimeAcceptanceEvidence(
        path=acceptance_path,
        record_sha256="1" * 64,
        attempt_id_sha256="2" * 64,
        completed_at="2026-09-10T00:00:00+00:00",
        payload={"passed": True},
        file_identity=(1,),
    )
    monkeypatch.setattr(
        resilience,
        "_validate_runtime_acceptance_record",
        lambda **kwargs: acceptance_evidence,
    )
    return values, record_dir, representative


def _execute_with_stub_paths(
    *,
    tmp_path: Path,
    record_dir: Path,
    representative: Path,
) -> dict[str, object]:
    return resilience.execute(
        config_file=tmp_path / "config",
        secret_dir=tmp_path / "secrets",
        release_record_dir=tmp_path / "releases",
        representative_record=representative,
        record_dir=record_dir,
        wait_timeout=180,
        runtime_acceptance_record=(
            tmp_path / f"gatea-m9-runtime-acceptance-{'a' * 40}.json"
        ),
        confirm_runtime_acceptance_record_sha256="1" * 64,
    )


def _runtime_acceptance_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, str, dict[str, object], dict[str, object], list[object]]:
    """构造只关注 resilience 强绑定字段的 M9 final acceptance。"""

    from scripts.release import gatea_m9_acceptance as acceptance

    candidate_sha = "a" * 40
    source_candidate_sha = "b" * 40
    image_id = "sha256:" + "c" * 64
    release_record_dir = tmp_path / "release-records"
    release_record_dir.mkdir()
    upgrade_record_path = gatea._upgrade_marker(release_record_dir, candidate_sha)
    plan_replay_path = gatea._upgrade_replay_marker(
        release_record_dir,
        candidate_sha,
    )
    upgrade_record_path.write_text('{"upgrade":true}\n', encoding="utf-8")
    plan_replay_path.write_text('{"replay":true}\n', encoding="utf-8")
    representative_record_sha256 = "d" * 64
    credentials_sha256 = "e" * 64
    payload: dict[str, object] = {
        "candidate_sha": candidate_sha,
        "image_id": image_id,
        "operations_sha": candidate_sha,
        "ci_run_id": "34481317426",
        "source_candidate_sha": source_candidate_sha,
        "representative_record_sha256": representative_record_sha256,
        "credentials_sha256": credentials_sha256,
        "upgrade_record_sha256": gatea._sha256(upgrade_record_path),
        "upgrade_plan_replay_record_sha256": gatea._sha256(plan_replay_path),
        "runtime_services": list(resilience.M9_SERVICES),
        "upgrade_plan_replayed": True,
        "attempt_id_sha256": "f" * 64,
        "completed_at": "2026-09-10T00:00:00+00:00",
        "passed": True,
    }
    acceptance_dir = tmp_path / "acceptance"
    acceptance_dir.mkdir(mode=0o755)
    path = acceptance_dir / (
        f"gatea-m9-runtime-acceptance-{candidate_sha}.json"
    )
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o644)
    validator_calls: list[object] = []

    def validate_success(actual: object) -> None:
        validator_calls.append(actual)

    def validate_root_file(
        actual_path: Path,
        expected_mode: int,
        description: str,
        **kwargs: object,
    ) -> None:
        del description, kwargs
        metadata = Path(actual_path).lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != expected_mode
        ):
            raise gatea.GateAError("unsafe fixture metadata")

    def validate_root_directory(
        actual_path: Path,
        expected_mode: int,
        description: str,
    ) -> None:
        del description
        metadata = Path(actual_path).lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != expected_mode
        ):
            raise gatea.GateAError("unsafe fixture directory metadata")

    monkeypatch.setattr(acceptance, "_validate_success_record", validate_success)
    monkeypatch.setattr(
        acceptance,
        "_operations_evidence",
        lambda record_dir: (candidate_sha, "34481317426"),
    )
    monkeypatch.setattr(gatea, "_validate_root_file", validate_root_file)
    monkeypatch.setattr(
        gatea,
        "_validate_root_directory",
        validate_root_directory,
    )
    arguments: dict[str, object] = {
        "candidate_sha": candidate_sha,
        "image_id": image_id,
        "deployment_record": {
            "schema_version": 1,
            "record_type": "existing-database-upgrade",
            "source_version": 7,
            "source_candidate_sha": source_candidate_sha,
            "source_aerich_versions": list(gatea.APPROVED_TARGET_M7_CHAIN),
            "target_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
        },
        "representative_payload": {
            "credentials_sha256": credentials_sha256,
        },
        "representative_record_sha256": representative_record_sha256,
        "release_record_dir": release_record_dir,
        "runtime_services": resilience.M9_SERVICES,
    }
    return path, gatea._sha256(path), arguments, payload, validator_calls


def _patch_successful_execute_drill(monkeypatch: pytest.MonkeyPatch) -> None:
    def dependency_drill(**kwargs: object) -> dict[str, object]:
        started_at = datetime.now(timezone.utc).isoformat()
        completed_at = datetime.now(timezone.utc).isoformat()
        return {
            "service": kwargs["service"],
            "started_at": started_at,
            "completed_at": completed_at,
            "outage_readiness_status": 503,
            "outage_liveness_status": 200,
            "failure_detection_seconds": 0.1,
            "service_recovery_seconds": 0.2,
            "readiness_recovery_seconds": 0.3,
            "recovered_readiness_status": 200,
            "passed": True,
        }

    def app_restart(**kwargs: object) -> dict[str, object]:
        del kwargs
        started_at = datetime.now(timezone.utc).isoformat()
        completed_at = datetime.now(timezone.utc).isoformat()
        return {
            "started_at": started_at,
            "completed_at": completed_at,
            "total_seconds": 0.4,
            "service_recovery_seconds": 0.2,
            "readiness_recovery_seconds": 0.2,
            "readiness_status": 200,
            "passed": True,
        }

    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        dependency_drill,
    )
    monkeypatch.setattr(
        resilience,
        "_app_restart_drill",
        app_restart,
    )
    monkeypatch.setattr(resilience, "_restore_all_services", lambda **kwargs: None)
    monkeypatch.setattr(
        resilience,
        "_log_rotation_contract",
        lambda **kwargs: {
            service: {
                "driver": "json-file",
                "max_file": "5",
                "max_size": "10m",
            }
            for service in kwargs["services"]
        },
    )
    monkeypatch.setattr(
        resilience,
        "_scan_logs",
        lambda **kwargs: {
            "window": "24h",
            "combined_line_count": 20,
            "nginx_request_count": 10,
            "nginx_4xx_count": 0,
            "nginx_5xx_count": 0,
            "request_time_seconds": {
                "median": 0.01,
                "p95": 0.02,
                "max": 0.03,
            },
            "exact_secret_matches": 0,
            "forbidden_pattern_matches": 0,
            "raw_log_content_recorded": False,
            "passed": True,
        },
    )


def test_runtime_acceptance_record_is_validated_and_frozen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path, digest, arguments, payload, validator_calls = (
        _runtime_acceptance_fixture(monkeypatch, tmp_path)
    )

    result = resilience._validate_runtime_acceptance_record(
        path=path,
        confirmed_sha256=digest,
        **arguments,
    )

    assert result.path == path
    assert result.record_sha256 == digest
    assert result.attempt_id_sha256 == "f" * 64
    assert result.completed_at == "2026-09-10T00:00:00+00:00"
    assert result.payload == payload
    assert validator_calls == [payload]


def test_runtime_acceptance_record_requires_candidate_scoped_basename(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path, _, arguments, _, _ = _runtime_acceptance_fixture(
        monkeypatch,
        tmp_path,
    )
    wrong_path = path.with_name("gatea-m9-runtime-acceptance-other.json")
    path.rename(wrong_path)

    with pytest.raises(resilience.ResilienceError, match="filename"):
        resilience._validate_runtime_acceptance_record(
            path=wrong_path,
            confirmed_sha256=gatea._sha256(wrong_path),
            **arguments,
        )


@pytest.mark.parametrize("confirmed_digest", ("invalid", "0" * 64))
def test_runtime_acceptance_record_rejects_invalid_or_mismatched_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    confirmed_digest: str,
) -> None:
    path, _, arguments, _, _ = _runtime_acceptance_fixture(
        monkeypatch,
        tmp_path,
    )

    with pytest.raises(resilience.ResilienceError, match="digest"):
        resilience._validate_runtime_acceptance_record(
            path=path,
            confirmed_sha256=confirmed_digest,
            **arguments,
        )


@pytest.mark.parametrize("unsafe_kind", ("symlink", "mode"))
def test_runtime_acceptance_record_requires_regular_root_0644_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    path, digest, arguments, _, _ = _runtime_acceptance_fixture(
        monkeypatch,
        tmp_path,
    )
    if unsafe_kind == "symlink":
        target = tmp_path / "acceptance-target.json"
        path.rename(target)
        path.symlink_to(target)
    else:
        path.chmod(0o600)

    with pytest.raises(resilience.ResilienceError, match="regular file|metadata"):
        resilience._validate_runtime_acceptance_record(
            path=path,
            confirmed_sha256=digest,
            **arguments,
        )


@pytest.mark.parametrize("unsafe_kind", ("symlink", "mode"))
def test_runtime_acceptance_record_requires_protected_real_parent_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    path, digest, arguments, _, _ = _runtime_acceptance_fixture(
        monkeypatch,
        tmp_path,
    )
    if unsafe_kind == "symlink":
        real_parent = path.parent.with_name("real-acceptance")
        path.parent.rename(real_parent)
        path.parent.symlink_to(real_parent, target_is_directory=True)
    else:
        path.parent.chmod(0o700)

    with pytest.raises(resilience.ResilienceError, match="directory"):
        resilience._validate_runtime_acceptance_record(
            path=path,
            confirmed_sha256=digest,
            **arguments,
        )


@pytest.mark.parametrize("sidecar_suffix", (".json.pending", ".json.complete"))
def test_runtime_acceptance_record_rejects_pending_or_complete_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sidecar_suffix: str,
) -> None:
    path, digest, arguments, _, _ = _runtime_acceptance_fixture(
        monkeypatch,
        tmp_path,
    )
    path.with_suffix(sidecar_suffix).write_text("{}\n", encoding="utf-8")

    with pytest.raises(resilience.ResilienceError, match="sidecar"):
        resilience._validate_runtime_acceptance_record(
            path=path,
            confirmed_sha256=digest,
            **arguments,
        )


@pytest.mark.parametrize(
    "scenario",
    (
        "candidate",
        "image",
        "operations",
        "ci-run",
        "source",
        "representative",
        "credentials",
        "upgrade-record",
        "plan-replay",
        "runtime-services",
        "plan-replayed",
        "passed",
        "deployment-chain",
    ),
)
def test_runtime_acceptance_record_rejects_every_critical_binding_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario: str,
) -> None:
    path, _, arguments, payload, _ = _runtime_acceptance_fixture(
        monkeypatch,
        tmp_path,
    )
    if scenario == "candidate":
        payload["candidate_sha"] = "9" * 40
    elif scenario == "image":
        payload["image_id"] = "sha256:" + "9" * 64
    elif scenario == "operations":
        payload["operations_sha"] = "9" * 40
    elif scenario == "ci-run":
        payload["ci_run_id"] = "1"
    elif scenario == "source":
        payload["source_candidate_sha"] = "9" * 40
    elif scenario == "representative":
        payload["representative_record_sha256"] = "9" * 64
    elif scenario == "credentials":
        payload["credentials_sha256"] = "9" * 64
    elif scenario == "upgrade-record":
        payload["upgrade_record_sha256"] = "9" * 64
    elif scenario == "plan-replay":
        payload["upgrade_plan_replay_record_sha256"] = "9" * 64
    elif scenario == "runtime-services":
        payload["runtime_services"] = list(resilience.LEGACY_SERVICES)
    elif scenario == "plan-replayed":
        payload["upgrade_plan_replayed"] = False
    elif scenario == "passed":
        payload["passed"] = False
    else:
        deployment = dict(arguments["deployment_record"])  # type: ignore[arg-type]
        deployment["target_aerich_versions"] = list(
            gatea.APPROVED_TARGET_M8_CHAIN
        )
        arguments["deployment_record"] = deployment
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    digest = gatea._sha256(path)

    with pytest.raises(resilience.ResilienceError, match="binding"):
        resilience._validate_runtime_acceptance_record(
            path=path,
            confirmed_sha256=digest,
            **arguments,
        )


def test_runtime_acceptance_record_detects_metadata_drift_across_drill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path, digest, arguments, _, _ = _runtime_acceptance_fixture(
        monkeypatch,
        tmp_path,
    )
    initial = resilience._validate_runtime_acceptance_record(
        path=path,
        confirmed_sha256=digest,
        **arguments,
    )
    metadata = path.stat()
    os.utime(
        path,
        ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000),
    )

    with pytest.raises(resilience.ResilienceError, match="changed during"):
        resilience._validate_runtime_acceptance_record(
            path=path,
            confirmed_sha256=digest,
            expected=initial,
            **arguments,
        )


def test_runtime_acceptance_record_rechecks_current_operations_sidecars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from scripts.release import gatea_m9_acceptance as acceptance

    path, digest, arguments, _, _ = _runtime_acceptance_fixture(
        monkeypatch,
        tmp_path,
    )
    operation_evidence = iter(
        (("a" * 40, "34481317426"), ("a" * 40, "34481317427"))
    )
    monkeypatch.setattr(
        acceptance,
        "_operations_evidence",
        lambda record_dir: next(operation_evidence),
    )
    initial = resilience._validate_runtime_acceptance_record(
        path=path,
        confirmed_sha256=digest,
        **arguments,
    )

    with pytest.raises(resilience.ResilienceError, match="binding"):
        resilience._validate_runtime_acceptance_record(
            path=path,
            confirmed_sha256=digest,
            expected=initial,
            **arguments,
        )


def test_resilience_record_path_is_scoped_to_candidate(tmp_path: Path) -> None:
    first_sha = "a" * 40
    second_sha = "b" * 40

    assert resilience._record_path(tmp_path, first_sha) == (
        tmp_path / f"gatea-resilience-{first_sha}.json"
    )
    assert resilience._record_path(tmp_path, second_sha) != resilience._record_path(
        tmp_path, first_sha
    )


@pytest.mark.parametrize("target_kind", ("file", "dangling-symlink"))
def test_resilience_record_writer_never_overwrites_an_existing_path(
    tmp_path: Path,
    target_kind: str,
) -> None:
    path = resilience._record_path(tmp_path, "a" * 40)
    if target_kind == "file":
        original = '{"owner":"first"}\n'
        path.write_text(original, encoding="utf-8")
    else:
        missing_target = tmp_path / "missing-record"
        path.symlink_to(missing_target)

    with pytest.raises(resilience.ResilienceError, match="already reserved"):
        resilience._write_resilience_record(path, {"owner": "replacement"})

    if target_kind == "file":
        assert path.read_text(encoding="utf-8") == original
    else:
        assert path.is_symlink()
        assert path.readlink() == missing_target
    assert list(tmp_path.glob(f".{path.name}.tmp-*")) == []


def test_resilience_record_writer_never_publishes_partial_json_on_enospc(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = resilience._record_path(tmp_path, "a" * 40)
    synced_directories: list[Path] = []

    def fail_after_partial_write(
        payload: object,
        stream: object,
        **kwargs: object,
    ) -> None:
        del payload, kwargs
        stream.write('{"partial":')
        raise OSError(28, "simulated ENOSPC")

    monkeypatch.setattr(resilience.gatea_backup.json, "dump", fail_after_partial_write)
    monkeypatch.setattr(
        resilience.gatea_backup,
        "_fsync_directory",
        lambda directory: synced_directories.append(directory),
    )

    with pytest.raises(OSError, match="ENOSPC"):
        resilience._write_resilience_record(path, {"passed": True})

    assert not path.exists()
    assert not path.is_symlink()
    assert list(tmp_path.glob(f".{path.name}.tmp-*")) == []
    assert synced_directories == [tmp_path]


def test_resilience_record_publish_boundary_keeps_only_complete_final_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = resilience._record_path(tmp_path, "a" * 40)
    sync_calls = 0

    def interrupt_first_directory_sync(directory: Path) -> None:
        nonlocal sync_calls
        assert directory == tmp_path
        sync_calls += 1
        if sync_calls == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(
        resilience.gatea_backup,
        "_fsync_directory",
        interrupt_first_directory_sync,
    )

    with pytest.raises(KeyboardInterrupt):
        resilience._write_resilience_record(path, {"passed": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"passed": True}
    assert list(tmp_path.glob(f".{path.name}.tmp-*")) == []
    assert sync_calls == 2


def test_execute_recovers_final_visible_after_publication_sync_failure_without_redrill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, record_dir, representative = _stub_execute_environment(monkeypatch, tmp_path)
    _patch_successful_execute_drill(monkeypatch)
    dependency_drill = resilience._dependency_drill
    app_restart_drill = resilience._app_restart_drill
    drill_calls: list[str] = []

    def count_dependency(**kwargs: object) -> dict[str, object]:
        drill_calls.append(str(kwargs["service"]))
        return dependency_drill(**kwargs)

    def count_app_restart(**kwargs: object) -> dict[str, object]:
        drill_calls.append("app")
        return app_restart_drill(**kwargs)

    monkeypatch.setattr(resilience, "_dependency_drill", count_dependency)
    monkeypatch.setattr(resilience, "_app_restart_drill", count_app_restart)
    original_fsync = gatea_backup._fsync_directory
    sync_calls = 0

    def fail_first_publication_sync(directory: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            raise KeyboardInterrupt
        original_fsync(directory)

    monkeypatch.setattr(gatea_backup, "_fsync_directory", fail_first_publication_sync)
    with pytest.raises(KeyboardInterrupt):
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )

    path = resilience._record_path(record_dir, "a" * 40)
    published = json.loads(path.read_text(encoding="utf-8"))
    assert drill_calls == ["mysql", "redis", "app"]
    assert list(record_dir.glob(f".{path.name}.tmp-*")) == []

    monkeypatch.setattr(gatea_backup, "_fsync_directory", original_fsync)
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: pytest.fail("recovery must not repeat dependency outages"),
    )
    monkeypatch.setattr(
        resilience,
        "_app_restart_drill",
        lambda **kwargs: pytest.fail("recovery must not restart the app again"),
    )

    recovered = _execute_with_stub_paths(
        tmp_path=tmp_path,
        record_dir=record_dir,
        representative=representative,
    )

    assert recovered == published
    assert path.stat().st_nlink == 1


def test_existing_resilience_final_and_temp_require_root_owned_0644_stable_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = resilience._record_path(tmp_path, "a" * 40)
    path.write_text('{"schema_version":2}\n', encoding="utf-8")
    path.chmod(0o644)
    temporary = tmp_path / f".{path.name}.tmp-recovery"
    os.link(path, temporary)
    validations: list[tuple[Path, int, str]] = []
    monkeypatch.setattr(
        gatea,
        "_validate_root_file",
        lambda file_path, mode, description: validations.append(
            (file_path, mode, description)
        ),
    )

    evidence = resilience._load_existing_resilience_record(path)

    assert evidence is not None
    assert evidence.record_sha256 == gatea._sha256(path)
    assert [item[:2] for item in validations] == [
        (path, 0o644),
        (temporary, 0o644),
    ]

    monkeypatch.setattr(gatea, "_sha256", lambda _: "0" * 64)
    with pytest.raises(resilience.ResilienceError, match="digest changed"):
        resilience._load_existing_resilience_record(path)


@pytest.mark.parametrize("cleanup_sync_failure", (False, True))
def test_execute_recovers_only_a_stable_same_inode_temporary_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cleanup_sync_failure: bool,
) -> None:
    _, record_dir, representative = _stub_execute_environment(monkeypatch, tmp_path)
    _patch_successful_execute_drill(monkeypatch)
    published = _execute_with_stub_paths(
        tmp_path=tmp_path,
        record_dir=record_dir,
        representative=representative,
    )
    path = resilience._record_path(record_dir, "a" * 40)
    temporary = record_dir / f".{path.name}.tmp-recovery"
    os.link(path, temporary)
    assert path.stat().st_nlink == 2
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: pytest.fail("recovery must not repeat dependency outages"),
    )
    monkeypatch.setattr(
        resilience,
        "_app_restart_drill",
        lambda **kwargs: pytest.fail("recovery must not restart the app again"),
    )

    original_fsync = gatea_backup._fsync_directory
    sync_calls = 0

    def fail_after_alias_unlink(directory: Path) -> None:
        nonlocal sync_calls
        sync_calls += 1
        original_fsync(directory)
        if cleanup_sync_failure and sync_calls == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(gatea_backup, "_fsync_directory", fail_after_alias_unlink)
    if cleanup_sync_failure:
        with pytest.raises(KeyboardInterrupt):
            _execute_with_stub_paths(
                tmp_path=tmp_path,
                record_dir=record_dir,
                representative=representative,
            )
        assert not temporary.exists()
        monkeypatch.setattr(gatea_backup, "_fsync_directory", original_fsync)

    recovered = _execute_with_stub_paths(
        tmp_path=tmp_path,
        record_dir=record_dir,
        representative=representative,
    )

    assert recovered == published
    assert not temporary.exists()
    assert path.stat().st_nlink == 1


@pytest.mark.parametrize(
    "artifact_kind",
    ("orphan-temp", "mismatched-temp", "unknown-sidecar", "multiple-aliases"),
)
def test_execute_rejects_unknown_or_inconsistent_resilience_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    artifact_kind: str,
) -> None:
    _, record_dir, representative = _stub_execute_environment(monkeypatch, tmp_path)
    _patch_successful_execute_drill(monkeypatch)
    path = resilience._record_path(record_dir, "a" * 40)
    if artifact_kind != "orphan-temp":
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )
    first_temporary = record_dir / f".{path.name}.tmp-first"
    if artifact_kind == "orphan-temp":
        first_temporary.write_text("{}\n", encoding="utf-8")
    elif artifact_kind == "mismatched-temp":
        first_temporary.write_text('{"passed":false}\n', encoding="utf-8")
    elif artifact_kind == "unknown-sidecar":
        first_temporary = record_dir / f"{path.name}.pending"
        first_temporary.write_text("{}\n", encoding="utf-8")
    else:
        os.link(path, first_temporary)
        os.link(path, record_dir / f".{path.name}.tmp-second")

    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: pytest.fail("unsafe artifacts must block before redrill"),
    )
    with pytest.raises(
        resilience.ResilienceError,
        match="orphan|inconsistent|unknown alias or sidecar",
    ):
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )

    assert first_temporary.exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("unknown-field", "record is invalid"),
        ("candidate", "record is invalid"),
        ("time-order", "time order is invalid"),
        ("acceptance-binding", "acceptance binding is invalid"),
    ),
)
def test_execute_recovery_revalidates_exact_schema_bindings_and_time_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    _, record_dir, representative = _stub_execute_environment(monkeypatch, tmp_path)
    _patch_successful_execute_drill(monkeypatch)
    _execute_with_stub_paths(
        tmp_path=tmp_path,
        record_dir=record_dir,
        representative=representative,
    )
    path = resilience._record_path(record_dir, "a" * 40)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "unknown-field":
        payload["unexpected"] = True
    elif mutation == "candidate":
        payload["candidate_sha"] = "b" * 40
    elif mutation == "time-order":
        payload["dependency_drills"][0]["started_at"] = (
            "2000-01-01T00:00:00+00:00"
        )
    else:
        payload["runtime_acceptance_record_sha256"] = "9" * 64
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o644)
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: pytest.fail("invalid final must block before redrill"),
    )

    with pytest.raises(resilience.ResilienceError, match=message):
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )


def test_execute_recovery_revalidates_live_content_and_image_invariants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, record_dir, representative = _stub_execute_environment(monkeypatch, tmp_path)
    _patch_successful_execute_drill(monkeypatch)
    _execute_with_stub_paths(
        tmp_path=tmp_path,
        record_dir=record_dir,
        representative=representative,
    )
    changed_snapshots = _content_snapshots()
    changed_snapshots["m9_table_business"]["content_sha256"] = "d" * 64
    monkeypatch.setattr(
        resilience,
        "_database_content_snapshots",
        lambda **kwargs: changed_snapshots,
    )
    monkeypatch.setattr(
        resilience.gatea_backup,
        "_source_image_manifest",
        lambda *args: ["fixture.png", "unexpected.png"],
    )
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: pytest.fail("live drift must block before redrill"),
    )

    with pytest.raises(resilience.ResilienceError, match="record is invalid"):
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )


def test_legacy_schema_v1_final_recovery_is_exact_and_does_not_redrill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, record_dir, representative = _stub_execute_environment(monkeypatch, tmp_path)
    _patch_successful_execute_drill(monkeypatch)
    monkeypatch.setattr(
        resilience.gatea_backup,
        "_source_snapshot",
        lambda *args: {
            "aerich_versions": ",".join(gatea.APPROVED_TARGET_M8_CHAIN),
            "users": 2,
        },
    )
    monkeypatch.setattr(
        resilience,
        "_database_content_snapshots",
        lambda **kwargs: _content_snapshots(include_m9=False),
    )
    arguments = {
        "config_file": tmp_path / "config",
        "secret_dir": tmp_path / "secrets",
        "release_record_dir": tmp_path / "releases",
        "representative_record": representative,
        "record_dir": record_dir,
        "wait_timeout": 180,
    }
    published = resilience.execute(**arguments)
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: pytest.fail("legacy final recovery must not redrill"),
    )
    monkeypatch.setattr(
        resilience,
        "_app_restart_drill",
        lambda **kwargs: pytest.fail("legacy final recovery must not restart app"),
    )

    recovered = resilience.execute(**arguments)

    assert recovered == published
    assert recovered["schema_version"] == 1
    assert set(recovered) == resilience.RESILIENCE_RECORD_BASE_KEYS


def test_execute_rejects_a_dangling_resilience_record_before_the_drill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, record_dir, representative = _stub_execute_environment(monkeypatch, tmp_path)
    path = resilience._record_path(record_dir, "a" * 40)
    path.symlink_to(tmp_path / "missing-record")
    monkeypatch.setattr(
        gatea,
        "_require_deployment_record",
        lambda **kwargs: pytest.fail("record precheck must fail before the drill"),
    )

    with pytest.raises(resilience.ResilienceError, match="must be a regular file"):
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )

    assert path.is_symlink()


@pytest.mark.parametrize(
    ("blocked_guard", "message"),
    (
        (
            "reject_unresolved_candidate_transition_journals",
            "candidate transition has an unresolved pending journal",
        ),
        (
            "reject_unresolved_m9_acceptance_sidecars",
            "M9 acceptance has an unresolved sidecar",
        ),
    ),
)
def test_execute_rejects_global_pending_before_runtime_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    blocked_guard: str,
    message: str,
) -> None:
    release_record_dir = tmp_path / "release-records"
    acceptance_record_dir = tmp_path / "acceptance-records"
    calls: list[tuple[str, Path]] = []

    monkeypatch.setattr(os, "geteuid", lambda: 0)

    def release_guard(*, record_dir: Path, **kwargs: object) -> None:
        calls.append(("release", record_dir))
        if blocked_guard == "reject_unresolved_candidate_transition_journals":
            raise gatea.GateAError(message)

    def acceptance_guard(*, record_dir: Path, **kwargs: object) -> None:
        calls.append(("acceptance", record_dir))
        if blocked_guard == "reject_unresolved_m9_acceptance_sidecars":
            raise gatea.GateAError(message)

    monkeypatch.setattr(
        gatea,
        "reject_unresolved_candidate_transition_journals",
        release_guard,
    )
    monkeypatch.setattr(
        gatea,
        "reject_unresolved_m9_acceptance_sidecars",
        acceptance_guard,
    )
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: pytest.fail(
            "global pending guards must run before runtime input validation"
        ),
    )

    with pytest.raises(gatea.GateAError, match=message):
        resilience.execute(
            config_file=tmp_path / "config.env",
            secret_dir=tmp_path / "secrets",
            release_record_dir=release_record_dir,
            representative_record=None,
            record_dir=tmp_path / "resilience-records",
            wait_timeout=180,
            acceptance_record_dir=acceptance_record_dir,
        )

    expected = [("release", release_record_dir)]
    if blocked_guard == "reject_unresolved_m9_acceptance_sidecars":
        expected.append(("acceptance", acceptance_record_dir))
    assert calls == expected


def test_execute_rejects_runtime_acceptance_outside_guarded_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Path]] = []
    guarded_dir = tmp_path / "guarded-acceptance"
    outside_record = tmp_path / "outside" / (
        f"gatea-m9-runtime-acceptance-{'a' * 40}.json"
    )

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        gatea,
        "reject_unresolved_candidate_transition_journals",
        lambda *, record_dir, **kwargs: calls.append(("release", record_dir)),
    )
    monkeypatch.setattr(
        gatea,
        "reject_unresolved_m9_acceptance_sidecars",
        lambda *, record_dir, **kwargs: calls.append(("acceptance", record_dir)),
    )
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: pytest.fail(
            "acceptance directory binding must precede runtime inputs"
        ),
    )

    with pytest.raises(
        resilience.ResilienceError,
        match="must use the guarded directory",
    ):
        resilience.execute(
            config_file=tmp_path / "config.env",
            secret_dir=tmp_path / "secrets",
            release_record_dir=tmp_path / "release-records",
            representative_record=None,
            record_dir=tmp_path / "resilience-records",
            wait_timeout=180,
            runtime_acceptance_record=outside_record,
            confirm_runtime_acceptance_record_sha256="1" * 64,
            acceptance_record_dir=guarded_dir,
        )

    assert calls == [
        ("release", tmp_path / "release-records"),
        ("acceptance", guarded_dir),
    ]


@pytest.mark.parametrize(
    ("signum", "expected_type"),
    [
        pytest.param(
            signal.SIGTERM,
            gatea.GateAOperationInterrupted,
            id="sigterm",
        ),
        pytest.param(signal.SIGINT, KeyboardInterrupt, id="sigint"),
    ],
)
def test_resilience_termination_guard_raises_once_then_defers_repeats(
    monkeypatch: pytest.MonkeyPatch,
    signum: int,
    expected_type: type[BaseException],
) -> None:
    previous = {
        signal.SIGHUP: object(),
        signal.SIGTERM: object(),
        signal.SIGINT: object(),
    }
    active_handlers: dict[int, object] = {}
    monkeypatch.setattr(
        resilience.signal,
        "getsignal",
        lambda signum: previous[signum],
    )
    monkeypatch.setattr(
        resilience.signal,
        "signal",
        lambda signum, handler: active_handlers.__setitem__(signum, handler),
    )

    with resilience._resilience_termination_guard() as termination:
        handler = active_handlers[signum]
        assert callable(handler)
        with pytest.raises(
            expected_type,
            match=f"received {signal.Signals(signum).name} and is recovering",
        ) as captured:
            handler(signum, None)

        assert captured.value is termination.interruption
        assert termination.recovering is True
        termination.begin_recovery()
        repeated_handler = active_handlers[signal.SIGHUP]
        assert callable(repeated_handler)
        assert repeated_handler(signal.SIGHUP, None) is None

    assert active_handlers == previous


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
        services=resilience.LEGACY_SERVICES,
    )
    assert set(result) == set(resilience.LEGACY_SERVICES)
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
            services=resilience.LEGACY_SERVICES,
        )


def test_restore_all_services_reuses_existing_loopback_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _values()
    commands: list[tuple[str, ...]] = []
    isolation_flags: list[bool] = []
    publisher_checks: list[int] = []
    rows = [
        {"Service": name, "State": "running", "Health": "healthy"}
        for name in resilience.M9_SERVICES
    ]
    def run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(tuple(kwargs["arguments"]))
        isolation_flags.append(bool(kwargs.get("start_new_session")))
        return subprocess.CompletedProcess([], 0, stdout="")

    monkeypatch.setattr(gatea, "_run_compose", run_compose)

    def compose_ps(**kwargs: object) -> list[dict[str, object]]:
        isolation_flags.append(bool(kwargs.get("start_new_session")))
        return rows

    monkeypatch.setattr(gatea, "_compose_ps", compose_ps)
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
        services=resilience.M9_SERVICES,
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
            "table-sweeper",
            "nginx",
        )
    ]
    assert isolation_flags == [True, True]
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
        services=resilience.M9_SERVICES,
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
            services=resilience.M9_SERVICES,
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
            services=resilience.M9_SERVICES,
        )
    assert secret not in str(captured.value)


@pytest.mark.parametrize(
    "unsafe_log",
    (
        'qr_token="AbCdEfGhIjKlMnOpQrStUvWxYz012345"',
        'GET /api/v1/table-codes/AbCdEfGhIjKlMnOpQrStUvWxYz012345 HTTP/1.1',
        "PINKDOOHUB_TABLE:v1:AbCdEfGhIjKlMnOpQrStUvWxYz012345",
    ),
)
def test_log_scan_rejects_full_table_tokens(
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
            services=resilience.M9_SERVICES,
        )

    assert "AbCdEfGhIjKlMnOpQrStUvWxYz012345" not in str(captured.value)


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


def test_representative_binding_uses_verified_upgrade_source() -> None:
    deployment_record = {
        "record_type": "existing-database-upgrade",
        "source_candidate_sha": "b" * 40,
        "source_image_id": "sha256:source-image",
    }

    assert resilience._representative_binding(
        deployment_record,
        "a" * 40,
        "sha256:target-image",
    ) == ("b" * 40, "sha256:source-image")
    assert resilience._representative_binding(
        {"schema_version": 1},
        "a" * 40,
        "sha256:target-image",
    ) == ("a" * 40, "sha256:target-image")


def test_representative_binding_uses_m7_lineage_for_m9_adoption() -> None:
    deployment_record = {
        "schema_version": 2,
        "record_type": "existing-database-upgrade",
        "transition_kind": "m9-candidate-adoption",
        "source_version": 9,
        "target_version": 9,
        "source_candidate_sha": "8" * 40,
        "source_image_id": "sha256:" + "8" * 64,
        "lineage_source_candidate_sha": "b" * 40,
        "lineage_source_image_id": "sha256:" + "c" * 64,
        "source_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
        "target_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
    }

    assert resilience._representative_binding(
        deployment_record,
        "a" * 40,
        "sha256:target-image",
    ) == ("b" * 40, "sha256:" + "c" * 64)


def test_runtime_acceptance_accepts_m9_adoption_with_m7_lineage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path, digest, arguments, payload, _ = _runtime_acceptance_fixture(
        monkeypatch,
        tmp_path,
    )
    source_candidate_sha = str(payload["source_candidate_sha"])
    arguments["deployment_record"] = {
        "schema_version": 2,
        "record_type": "existing-database-upgrade",
        "transition_kind": "m9-candidate-adoption",
        "source_version": 9,
        "target_version": 9,
        "source_candidate_sha": "8" * 40,
        "source_image_id": "sha256:" + "8" * 64,
        "lineage_source_candidate_sha": source_candidate_sha,
        "lineage_source_image_id": "sha256:" + "7" * 64,
        "source_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
        "target_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
    }

    evidence = resilience._validate_runtime_acceptance_record(
        path=path,
        confirmed_sha256=digest,
        **arguments,
    )

    assert evidence.payload["source_candidate_sha"] == source_candidate_sha


def test_m7_representative_record_uses_current_safe_shape(tmp_path: Path) -> None:
    record = tmp_path / "representative.json"
    payload = _m7_representative_payload(tmp_path / "credentials.json")
    record.write_text(json.dumps(payload), encoding="utf-8")

    assert resilience._load_representative_record(
        record,
        "b" * 40,
        "sha256:source-image",
        require_m7_record=True,
    ) == payload

    payload["request_or_response_bodies_recorded"] = True
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(resilience.ResilienceError, match="record is invalid"):
        resilience._load_representative_record(
            record,
            "b" * 40,
            "sha256:source-image",
            require_m7_record=True,
        )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("operations_sha", "not-a-sha"),
        ("backup_id", "2026-09-08"),
        ("synthetic_user_ids", [11, 12]),
        ("color_ids", [31, 31, 33]),
        ("order_ids", [41, 42, 43, 44, 45]),
        ("reservation_ids", [51, 52, 53, 54, 55, True]),
        ("after_image_file_count", 225),
        ("request_count", 0),
        ("credentials_sha256", "not-a-digest"),
        ("loopback_only", False),
    ),
)
def test_m7_representative_record_rejects_truncated_or_invalid_evidence(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    record = tmp_path / "representative.json"
    payload = _m7_representative_payload(tmp_path / "credentials.json")
    payload[field] = invalid_value
    record.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(resilience.ResilienceError, match="record is invalid"):
        resilience._load_representative_record(
            record,
            "b" * 40,
            "sha256:source-image",
            require_m7_record=True,
        )


def test_m7_representative_record_rejects_unknown_or_missing_fields(
    tmp_path: Path,
) -> None:
    record = tmp_path / "representative.json"
    payload = _m7_representative_payload(tmp_path / "credentials.json")
    payload["unexpected"] = True
    record.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(resilience.ResilienceError, match="record is invalid"):
        resilience._load_representative_record(
            record,
            "b" * 40,
            "sha256:source-image",
            require_m7_record=True,
        )

    payload.pop("unexpected")
    payload.pop("representative_details")
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(resilience.ResilienceError, match="record is invalid"):
        resilience._load_representative_record(
            record,
            "b" * 40,
            "sha256:source-image",
            require_m7_record=True,
        )


def test_representative_artifacts_require_safe_files_and_matching_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = tmp_path / "representative.json"
    credentials = tmp_path / "credentials.json"
    credentials.write_text('{"synthetic":true}\n', encoding="utf-8")
    payload = _m7_representative_payload(credentials)
    payload["credentials_sha256"] = gatea._sha256(credentials)
    record.write_text(json.dumps(payload), encoding="utf-8")
    validations: list[tuple[str, int]] = []
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_validate_root_file",
        lambda path, mode, description: validations.append((Path(path).name, mode)),
    )

    resilience._validate_representative_record_file(record)
    resilience._validate_m7_credentials_artifact(
        record_path=record,
        payload=payload,
    )

    assert validations == [
        ("representative.json", 0o644),
        ("credentials.json", 0o600),
    ]

    payload["credentials_sha256"] = "e" * 64
    with pytest.raises(resilience.ResilienceError, match="artifact is invalid"):
        resilience._validate_m7_credentials_artifact(
            record_path=record,
            payload=payload,
        )


def test_representative_record_rejects_a_symbolic_link(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "representative.json"
    link.symlink_to(target)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "_validate_root_file", lambda *args: None)

    with pytest.raises(resilience.ResilienceError, match="record is invalid"):
        resilience._validate_representative_record_file(link)


def test_m7_upgrade_rejects_a_source_bound_legacy_record(tmp_path: Path) -> None:
    record = tmp_path / "representative.json"
    record.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "candidate_sha": "b" * 40,
                "image_id": "sha256:source-image",
                "synthetic_user_disabled": True,
                "synthetic_session_revoked": True,
                "super_admin_session_revoked": True,
                "pii_recorded": False,
                "secret_values_recorded": False,
                "passed": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(resilience.ResilienceError, match="record is invalid"):
        resilience._load_representative_record(
            record,
            "b" * 40,
            "sha256:source-image",
            require_m7_record=True,
        )


def test_m7_upgrade_automatically_selects_source_representative_record() -> None:
    source_sha = "b" * 40
    deployment_record = {
        "record_type": "existing-database-upgrade",
        "source_version": 7,
    }

    assert resilience._representative_record_path(
        None,
        deployment_record,
        source_sha,
    ) == resilience.DEFAULT_REPRESENTATIVE_RECORD.parent / (
        f"gatea-m7-representative-data-{source_sha}.json"
    )
    explicit = Path("/approved/representative.json")
    assert resilience._representative_record_path(
        explicit,
        deployment_record,
        source_sha,
    ) == explicit


def test_runtime_services_are_selected_only_from_exact_approved_chain() -> None:
    assert resilience._runtime_services(
        {"aerich_versions": ",".join(gatea.APPROVED_SOURCE_M2_CHAIN)}
    ) == resilience.LEGACY_SERVICES
    assert resilience._runtime_services(
        {"aerich_versions": ",".join(gatea.APPROVED_TARGET_M7_CHAIN)}
    ) == resilience.LEGACY_SERVICES
    assert resilience._runtime_services(
        {"aerich_versions": ",".join(gatea.APPROVED_TARGET_M8_CHAIN)}
    ) == resilience.LEGACY_SERVICES
    assert resilience._runtime_services(
        {"aerich_versions": ",".join(gatea.APPROVED_TARGET_M9_CHAIN)}
    ) == resilience.M9_SERVICES
    with pytest.raises(resilience.ResilienceError, match="not approved"):
        resilience._runtime_services(
            {
                "aerich_versions": ",".join(
                    (*gatea.APPROVED_TARGET_M9_CHAIN, "10_unknown.py")
                )
            }
        )


def test_database_content_snapshots_follow_the_exact_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        resilience.gatea_backup,
        "_source_m7_content_snapshot",
        lambda *args: calls.append("m7") or {"profile": "m7"},
    )
    monkeypatch.setattr(
        resilience.gatea_backup,
        "_source_m8_swatch_content_snapshot",
        lambda *args: calls.append("m8") or {"profile": "m8"},
    )
    monkeypatch.setattr(
        resilience.gatea_backup,
        "_source_m9_table_content_snapshot",
        lambda *args: calls.append("m9") or {"profile": "m9"},
    )

    common = {
        "values": _values(),
        "config_file": Path("/config"),
        "secret_dir": Path("/secrets"),
    }
    assert resilience._database_content_snapshots(
        snapshot={
            "aerich_versions": ",".join(gatea.APPROVED_SOURCE_M2_CHAIN)
        },
        **common,
    ) == {}
    assert resilience._database_content_snapshots(
        snapshot={
            "aerich_versions": ",".join(gatea.APPROVED_TARGET_M7_CHAIN)
        },
        **common,
    ) == {"m7_preserved_business": {"profile": "m7"}}
    assert resilience._database_content_snapshots(
        snapshot={
            "aerich_versions": ",".join(gatea.APPROVED_TARGET_M9_CHAIN)
        },
        **common,
    ) == {
        "m7_preserved_business": {"profile": "m7"},
        "m8_swatch_content": {"profile": "m8"},
        "m9_table_business": {"profile": "m9"},
    }
    assert calls == ["m7", "m7", "m8", "m9"]


def test_m9_resilience_content_contract_requires_independent_swatch_evidence() -> None:
    m9_snapshot = {
        "aerich_versions": ",".join(gatea.APPROVED_TARGET_M9_CHAIN)
    }
    content = _content_snapshots()

    assert resilience._validated_record_content_snapshots(
        payload=content,
        live_snapshot=m9_snapshot,
    ) == content

    missing = dict(content)
    missing.pop("m8_swatch_content")
    with pytest.raises(resilience.ResilienceError, match="content evidence"):
        resilience._validated_record_content_snapshots(
            payload=missing,
            live_snapshot=m9_snapshot,
        )

    invalid = _content_snapshots()
    invalid["m8_swatch_content"] = {
        **invalid["m8_swatch_content"],
        "content_sha256": "invalid",
    }
    with pytest.raises(resilience.ResilienceError, match="content evidence"):
        resilience._validated_record_content_snapshots(
            payload=invalid,
            live_snapshot=m9_snapshot,
        )

    # M8 resilience remains schema-v1-compatible; only the M9 record contract
    # gains the nested swatch projection.
    legacy_m8 = _content_snapshots(include_m9=False)
    assert resilience._validated_record_content_snapshots(
        payload=legacy_m8,
        live_snapshot={
            "aerich_versions": ",".join(gatea.APPROVED_TARGET_M8_CHAIN)
        },
    ) == legacy_m8


@pytest.mark.parametrize(
    ("provide_record", "provide_digest"),
    ((False, False), (True, False), (False, True)),
)
def test_m9_execute_requires_both_runtime_acceptance_arguments_before_drill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provide_record: bool,
    provide_digest: bool,
) -> None:
    _, record_dir, representative = _stub_execute_environment(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: pytest.fail("acceptance precheck must precede drill"),
    )

    with pytest.raises(resilience.ResilienceError, match="requires.*record"):
        resilience.execute(
            config_file=tmp_path / "config",
            secret_dir=tmp_path / "secrets",
            release_record_dir=tmp_path / "releases",
            representative_record=representative,
            record_dir=record_dir,
            wait_timeout=180,
            runtime_acceptance_record=(
                tmp_path / f"gatea-m9-runtime-acceptance-{'a' * 40}.json"
                if provide_record
                else None
            ),
            confirm_runtime_acceptance_record_sha256=(
                "1" * 64 if provide_digest else None
            ),
        )

    assert not resilience._record_path(record_dir, "a" * 40).exists()


def test_m9_execute_rejects_drill_time_before_acceptance_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, record_dir, representative = _stub_execute_environment(
        monkeypatch,
        tmp_path,
    )
    acceptance_path = (
        tmp_path / f"gatea-m9-runtime-acceptance-{'a' * 40}.json"
    )
    future_acceptance = resilience._RuntimeAcceptanceEvidence(
        path=acceptance_path,
        record_sha256="1" * 64,
        attempt_id_sha256="2" * 64,
        completed_at="2999-01-01T00:00:00+00:00",
        payload={"passed": True},
        file_identity=(1,),
    )
    monkeypatch.setattr(
        resilience,
        "_validate_runtime_acceptance_record",
        lambda **kwargs: future_acceptance,
    )
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: pytest.fail("time precheck must precede drill"),
    )

    with pytest.raises(resilience.ResilienceError, match="starts before"):
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )

    assert not resilience._record_path(record_dir, "a" * 40).exists()


@pytest.mark.parametrize("scenario", ("content-drift", "sidecar"))
def test_m9_execute_does_not_publish_when_acceptance_changes_during_drill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario: str,
) -> None:
    _, record_dir, representative = _stub_execute_environment(
        monkeypatch,
        tmp_path,
    )
    _patch_successful_execute_drill(monkeypatch)
    acceptance_path = (
        tmp_path / f"gatea-m9-runtime-acceptance-{'a' * 40}.json"
    )
    initial = resilience._RuntimeAcceptanceEvidence(
        path=acceptance_path,
        record_sha256="1" * 64,
        attempt_id_sha256="2" * 64,
        completed_at="2026-09-10T00:00:00+00:00",
        payload={"passed": True},
        file_identity=(1,),
    )

    def validate_acceptance(**kwargs: object) -> object:
        if kwargs.get("expected") is None:
            return initial
        if scenario == "sidecar":
            assert acceptance_path.with_suffix(".json.pending").exists()
            raise resilience.ResilienceError(
                "Gate A M9 runtime acceptance sidecar requires manual review"
            )
        assert acceptance_path.read_text(encoding="utf-8") == '{"changed":true}\n'
        raise resilience.ResilienceError(
            "Gate A M9 runtime acceptance record changed during resilience drill"
        )

    def mutate_during_first_drill(**kwargs: object) -> dict[str, object]:
        if kwargs["service"] == "mysql":
            if scenario == "sidecar":
                acceptance_path.with_suffix(".json.pending").write_text(
                    "{}\n",
                    encoding="utf-8",
                )
            else:
                acceptance_path.write_text(
                    '{"changed":true}\n',
                    encoding="utf-8",
                )
        return {"service": kwargs["service"], "passed": True}

    monkeypatch.setattr(
        resilience,
        "_validate_runtime_acceptance_record",
        validate_acceptance,
    )
    monkeypatch.setattr(resilience, "_dependency_drill", mutate_during_first_drill)

    with pytest.raises(
        resilience.ResilienceError,
        match="sidecar|changed during",
    ):
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )

    assert not resilience._record_path(record_dir, "a" * 40).exists()


def test_m9_execute_publishes_schema_v2_with_runtime_acceptance_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, record_dir, representative = _stub_execute_environment(
        monkeypatch,
        tmp_path,
    )
    _patch_successful_execute_drill(monkeypatch)

    payload = _execute_with_stub_paths(
        tmp_path=tmp_path,
        record_dir=record_dir,
        representative=representative,
    )

    assert payload["schema_version"] == 2
    assert payload["runtime_acceptance_record_sha256"] == "1" * 64
    assert payload["runtime_acceptance_attempt_id_sha256"] == "2" * 64
    assert payload["runtime_acceptance_completed_at"] == (
        "2026-09-10T00:00:00+00:00"
    )
    published = json.loads(
        resilience._record_path(record_dir, "a" * 40).read_text(encoding="utf-8")
    )
    assert published == payload


def test_legacy_execute_keeps_exact_schema_v1_without_acceptance_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, record_dir, representative = _stub_execute_environment(
        monkeypatch,
        tmp_path,
    )
    _patch_successful_execute_drill(monkeypatch)
    monkeypatch.setattr(
        resilience.gatea_backup,
        "_source_snapshot",
        lambda *args: {
            "aerich_versions": ",".join(gatea.APPROVED_TARGET_M8_CHAIN),
            "users": 2,
        },
    )
    monkeypatch.setattr(
        resilience,
        "_database_content_snapshots",
        lambda **kwargs: _content_snapshots(include_m9=False),
    )
    monkeypatch.setattr(
        resilience,
        "_validate_runtime_acceptance_record",
        lambda **kwargs: pytest.fail("legacy chain must not require acceptance"),
    )

    payload = resilience.execute(
        config_file=tmp_path / "config",
        secret_dir=tmp_path / "secrets",
        release_record_dir=tmp_path / "releases",
        representative_record=representative,
        record_dir=record_dir,
        wait_timeout=180,
    )

    assert payload["schema_version"] == 1
    assert set(payload) == {
        "schema_version",
        "candidate_sha",
        "image_id",
        "representative_candidate_sha",
        "representative_image_id",
        "representative_record_sha256",
        "started_at",
        "completed_at",
        "dependency_drills",
        "app_restart",
        "database_snapshot_unchanged",
        "database_content_snapshots",
        "database_content_snapshots_unchanged",
        "image_manifest_unchanged",
        "image_file_count",
        "source_services_healthy",
        "runtime_services",
        "table_sweeper_included",
        "loopback_only",
        "log_rotation",
        "log_observability",
        "pii_recorded",
        "secret_values_recorded",
        "passed",
    }
    assert payload["runtime_services"] == list(resilience.LEGACY_SERVICES)
    assert payload["table_sweeper_included"] is False


def test_cli_exposes_runtime_acceptance_record_and_digest_confirmation() -> None:
    destinations = {action.dest for action in resilience._parser()._actions}

    assert "runtime_acceptance_record" in destinations
    assert "confirm_runtime_acceptance_record_sha256" in destinations
    assert "acceptance_record_dir" in destinations


@pytest.mark.parametrize(
    "drill_error",
    (
        resilience.ResilienceError("safe failure"),
        KeyboardInterrupt(),
        gatea.GateAOperationInterrupted("controlled termination"),
    ),
)
def test_execute_recovers_services_and_preserves_the_original_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drill_error: BaseException,
) -> None:
    _, record_dir, representative = _stub_execute_environment(
        monkeypatch,
        tmp_path,
    )
    recovered: list[bool] = []
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: (_ for _ in ()).throw(drill_error),
    )
    monkeypatch.setattr(
        resilience,
        "_restore_all_services",
        lambda **kwargs: recovered.append(True),
    )

    expected_error = type(drill_error)
    expected_message = (
        "safe failure"
        if isinstance(drill_error, resilience.ResilienceError)
        else None
    )
    with pytest.raises(expected_error, match=expected_message) as captured:
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )

    assert recovered == [True]
    assert captured.value is drill_error
    assert not resilience._record_path(record_dir, "a" * 40).exists()


def test_execute_restores_when_termination_hits_the_recovery_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, record_dir, representative = _stub_execute_environment(
        monkeypatch,
        tmp_path,
    )
    recovered: list[str] = []

    @contextmanager
    def boundary_guard() -> Iterator[resilience._ResilienceTermination]:
        termination = resilience._ResilienceTermination()

        def interrupt_at_boundary() -> None:
            termination.handle(signal.SIGTERM, None)

        termination.begin_recovery = interrupt_at_boundary  # type: ignore[method-assign]
        yield termination

    monkeypatch.setattr(resilience, "_resilience_termination_guard", boundary_guard)
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: {"passed": True},
    )
    monkeypatch.setattr(
        resilience,
        "_app_restart_drill",
        lambda **kwargs: {"passed": True},
    )
    monkeypatch.setattr(
        resilience,
        "_restore_all_services",
        lambda **kwargs: recovered.append("complete"),
    )

    with pytest.raises(
        gatea.GateAOperationInterrupted,
        match="received SIGTERM and is recovering",
    ):
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )

    assert recovered == ["complete"]
    assert not resilience._record_path(record_dir, "a" * 40).exists()


@pytest.mark.parametrize(
    ("signum", "expected_type"),
    [
        pytest.param(
            signal.SIGTERM,
            gatea.GateAOperationInterrupted,
            id="sigterm",
        ),
        pytest.param(signal.SIGINT, KeyboardInterrupt, id="sigint"),
    ],
)
def test_execute_defers_first_termination_until_recovery_completes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    signum: int,
    expected_type: type[BaseException],
) -> None:
    _, record_dir, representative = _stub_execute_environment(
        monkeypatch,
        tmp_path,
    )
    previous = {
        signal.SIGHUP: object(),
        signal.SIGTERM: object(),
        signal.SIGINT: object(),
    }
    active_handlers: dict[int, object] = {}
    recovery_steps: list[str] = []
    deferred: list[BaseException] = []
    monkeypatch.setattr(
        resilience.signal,
        "getsignal",
        lambda signum: previous[signum],
    )
    monkeypatch.setattr(
        resilience.signal,
        "signal",
        lambda signum, handler: active_handlers.__setitem__(signum, handler),
    )
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: {"passed": True},
    )
    monkeypatch.setattr(
        resilience,
        "_app_restart_drill",
        lambda **kwargs: {"passed": True},
    )

    def restore(**kwargs: object) -> None:
        recovery_steps.append("started")
        first_handler = active_handlers[signum]
        assert callable(first_handler)
        assert first_handler(signum, None) is None
        controller = getattr(first_handler, "__self__")
        assert isinstance(controller, resilience._ResilienceTermination)
        assert controller.interruption is not None
        deferred.append(controller.interruption)
        recovery_steps.append("after-first-signal")
        second_handler = active_handlers[signal.SIGHUP]
        assert callable(second_handler)
        assert second_handler(signal.SIGHUP, None) is None
        recovery_steps.append("complete")

    monkeypatch.setattr(resilience, "_restore_all_services", restore)

    with pytest.raises(
        expected_type,
        match=f"received {signal.Signals(signum).name} and is recovering",
    ) as caught:
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )

    assert recovery_steps == ["started", "after-first-signal", "complete"]
    assert caught.value is deferred[0]
    assert active_handlers == previous
    assert not resilience._record_path(record_dir, "a" * 40).exists()


def test_execute_preserves_drill_error_when_termination_arrives_in_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, record_dir, representative = _stub_execute_environment(
        monkeypatch,
        tmp_path,
    )
    active_handlers: dict[int, object] = {}
    original_error = resilience.ResilienceError("original drill failure")
    recovery_steps: list[str] = []
    monkeypatch.setattr(resilience.signal, "getsignal", lambda signum: object())
    monkeypatch.setattr(
        resilience.signal,
        "signal",
        lambda signum, handler: active_handlers.__setitem__(signum, handler),
    )
    monkeypatch.setattr(
        resilience,
        "_dependency_drill",
        lambda **kwargs: (_ for _ in ()).throw(original_error),
    )

    def restore(**kwargs: object) -> None:
        handler = active_handlers[signal.SIGTERM]
        assert callable(handler)
        assert handler(signal.SIGTERM, None) is None
        recovery_steps.append("complete")

    monkeypatch.setattr(resilience, "_restore_all_services", restore)

    with pytest.raises(resilience.ResilienceError) as captured:
        _execute_with_stub_paths(
            tmp_path=tmp_path,
            record_dir=record_dir,
            representative=representative,
        )

    assert captured.value is original_error
    assert recovery_steps == ["complete"]
    assert not resilience._record_path(record_dir, "a" * 40).exists()
