"""Gate A 非空 M2→M8 升级编排的授权、顺序、证据与失败语义。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.tasks.gatea_migrate_step import APPROVED_MIGRATIONS
from scripts.release import gatea_operations as gatea
from scripts.release import gatea_upgrade as upgrade


SOURCE_SHA = "a" * 40
TARGET_SHA = "b" * 40
BACKUP_ID = "20260907t120000z"
MANIFEST_SHA = "c" * 64


def test_upgrade_module_imports_with_standard_library_only() -> None:
    result = subprocess.run(
        [sys.executable, "-S", "-c", "import scripts.release.gatea_upgrade"],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def _values(backup_root: Path) -> dict[str, str]:
    return {
        "GATEA_APP_IMAGE": f"pinkdoohub-gatea:{TARGET_SHA}",
        "GATEA_BACKUP_ROOT": str(backup_root),
    }


def _source_backup_snapshot() -> dict[str, object]:
    return {
        "aerich_versions": ",".join(APPROVED_MIGRATIONS[:3]),
        "tables": 10,
        "columns": 100,
        "statistics": 20,
        "constraints": 15,
        "users": 0,
        "products": 0,
        "experience_options": 0,
        "product_images": 0,
        "product_kits": 0,
        "kit_stock": 0,
        "orders": 0,
        "order_items": 0,
        "order_total": "0.00",
        "inventory_transactions": 0,
        "inventory_change": 0,
        "audit_logs": 0,
    }


def _source_status() -> dict[str, object]:
    return _source_backup_snapshot() | {
        "aerich_versions": list(APPROVED_MIGRATIONS[:3]),
        "columns_sha256": "1" * 64,
        "statistics_sha256": "2" * 64,
        "constraints_sha256": "3" * 64,
    }


def _final_snapshot() -> dict[str, object]:
    return _source_backup_snapshot() | {
        "aerich_versions": list(APPROVED_MIGRATIONS),
        "tables": 24,
        "columns": 240,
        "statistics": 60,
        "constraints": 45,
        "columns_sha256": "4" * 64,
        "statistics_sha256": "5" * 64,
        "constraints_sha256": "6" * 64,
        "external_identities": 0,
        "eligible_wallet_users": 0,
        "wallet_accounts": 0,
        "ineligible_wallet_accounts": 0,
        "wallet_balance": "0.00",
        "wallet_transactions": 0,
        "recharge_orders": 0,
        "payments": 0,
        "payment_settlements": 0,
        "refunds": 0,
        "store_business_days": 0,
        "reservations": 0,
        "bead_colors": 221,
        "bead_color_slots": 221,
        "bead_color_min_slot": 1,
        "bead_color_max_slot": 221,
        "configured_bead_colors": 221,
        "distinct_bead_color_hex": 221,
        "active_bead_colors": 221,
        "product_kit_colors": 0,
        "reservation_settings": 1,
        "reservation_settings_invalid": 0,
        "reservation_settings_check": 1,
        "reservation_settings_unique": 1,
    }


def _backup_record() -> dict[str, object]:
    return {
        "candidate_sha": SOURCE_SHA,
        "image_id": "sha256:source-image",
        "database_snapshot": _source_backup_snapshot(),
        "image_manifest": [],
    }


def _common_arguments(tmp_path: Path, *, apply: bool) -> dict[str, object]:
    return {
        "config_file": Path("/config.env"),
        "secret_dir": Path("/secrets"),
        "mode": "loopback",
        "source_candidate_sha": SOURCE_SHA,
        "backup_id": BACKUP_ID,
        "backup_root": tmp_path / "backups",
        "backup_record_dir": tmp_path / "backup-records",
        "restore_record_dir": tmp_path / "restore-records",
        "release_record_dir": tmp_path,
        "apply": apply,
        "confirm_target_sha": TARGET_SHA if apply else None,
        "confirm_source_sha": SOURCE_SHA if apply else None,
        "confirm_backup_id": BACKUP_ID if apply else None,
        "confirm_manifest_sha256": MANIFEST_SHA if apply else None,
    }


def _patch_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: _values(tmp_path / "backups"),
    )
    monkeypatch.setattr(
        upgrade,
        "_plan",
        lambda **kwargs: (
            TARGET_SHA,
            "sha256:target-image",
            _backup_record(),
            _source_status(),
            MANIFEST_SHA,
        ),
    )
    monkeypatch.setattr(
        upgrade,
        "_run_runtime_preflight",
        lambda **kwargs: {
            "app_env": "production",
            "db_engine": "mysql",
            "jwt_algorithm": "HS256",
            "validated": True,
        },
    )


def test_plan_is_read_only_and_rejects_apply_confirmations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_plan(monkeypatch, tmp_path)

    result = upgrade.upgrade_existing_database(**_common_arguments(tmp_path, apply=False))

    assert result == {
        "already_current": False,
        "backup_id": BACKUP_ID,
        "candidate_sha": TARGET_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "mode": "plan",
        "restore_verified": True,
        "source_candidate_sha": SOURCE_SHA,
        "source_version": 2,
        "target_version": 8,
    }
    assert not list(tmp_path.glob("*.json"))

    arguments = _common_arguments(tmp_path, apply=False)
    arguments["confirm_target_sha"] = TARGET_SHA
    with pytest.raises(upgrade.GateAUpgradeError, match="does not accept"):
        upgrade.upgrade_existing_database(**arguments)


def test_apply_requires_all_four_exact_confirmations_before_stopping(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_plan(monkeypatch, tmp_path)
    stopped = False

    def unexpected_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal stopped
        stopped = True
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(gatea, "_run_compose", unexpected_compose)
    arguments = _common_arguments(tmp_path, apply=True)
    arguments["confirm_backup_id"] = "wrong"

    with pytest.raises(upgrade.GateAUpgradeError, match="confirmations"):
        upgrade.upgrade_existing_database(**arguments)

    assert stopped is False
    assert not list(tmp_path.glob("*.json"))


def test_runtime_preflight_failure_happens_before_stopping_or_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_plan(monkeypatch, tmp_path)
    stopped = False

    def fail_preflight(**kwargs: object) -> dict[str, object]:
        raise upgrade.GateAUpgradeError("runtime configuration preflight failed")

    def unexpected_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal stopped
        stopped = True
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(upgrade, "_run_runtime_preflight", fail_preflight)
    monkeypatch.setattr(gatea, "_run_compose", unexpected_compose)

    with pytest.raises(upgrade.GateAUpgradeError, match="runtime configuration"):
        upgrade.upgrade_existing_database(**_common_arguments(tmp_path, apply=True))

    assert stopped is False
    assert not list(tmp_path.glob("*.json"))


def test_apply_runs_exact_sequence_writes_record_and_keeps_app_stopped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_plan(monkeypatch, tmp_path)
    compose_commands: list[tuple[str, ...]] = []
    task_names: list[str] = []
    current_version = 2
    image_manifest_calls = 0

    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: compose_commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess([], 0),
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {
                "Service": service,
                "State": "running" if service in {"mysql", "redis"} else "exited",
                "Health": "healthy" if service in {"mysql", "redis"} else "",
            }
            for service in ("mysql", "redis", "app", "nginx")
        ],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_snapshot",
        lambda *args: _source_backup_snapshot(),
    )

    def fake_image_manifest(*args: object) -> list[str]:
        nonlocal image_manifest_calls
        image_manifest_calls += 1
        if image_manifest_calls == 1:
            return []
        return [f"{'0' * 64} mard-{index:03d}.png" for index in range(221)]

    monkeypatch.setattr(upgrade.backup, "_source_image_manifest", fake_image_manifest)

    def fake_task(**kwargs: object) -> dict[str, object]:
        nonlocal current_version
        description = str(kwargs["description"])
        task_names.append(description)
        if description.startswith("migrate-m"):
            current_version = int(description.removeprefix("migrate-m"))
            return {
                "aerich_versions": list(APPROVED_MIGRATIONS[: current_version + 1]),
                "applied": True,
                "migration": APPROVED_MIGRATIONS[current_version],
                "target_version": current_version,
            }
        if description == "wallet-prepare":
            return {
                "wallet_accounts": {"replay_would_create": 0},
                "legacy_settlements": {
                    "replay_would_create": 0,
                    "blocked": 0,
                },
                "reconciliation": {
                    "scanned": 0,
                    "mismatches": 0,
                    "violations": 0,
                }
            }
        if description == "mard-preview":
            return {
                "already_current": False,
                "colors": 221,
                "database_changes": 221,
                "images_to_create": 221,
                "manifest_sha256": MANIFEST_SHA,
                "mode": "preview",
            }
        if description == "mard-apply":
            return {
                "colors": 221,
                "manifest_sha256": MANIFEST_SHA,
                "mode": "apply",
            }
        return {
            "already_current": True,
            "colors": 221,
            "database_changes": 0,
            "images_to_create": 0,
            "manifest_sha256": MANIFEST_SHA,
            "mode": "preview",
        }

    monkeypatch.setattr(upgrade, "_run_task", fake_task)
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: _source_status()
        | {"aerich_versions": list(APPROVED_MIGRATIONS[: current_version + 1])},
    )
    monkeypatch.setattr(upgrade, "_read_final_snapshot", lambda **kwargs: _final_snapshot())

    result = upgrade.upgrade_existing_database(**_common_arguments(tmp_path, apply=True))

    assert compose_commands == [("stop", "--timeout", "30", "nginx", "app")]
    assert task_names == [
        "migrate-m3",
        "migrate-m4",
        "wallet-prepare",
        "migrate-m5",
        "migrate-m6",
        "migrate-m7",
        "migrate-m8",
        "mard-preview",
        "mard-apply",
        "mard-replay-preview",
    ]
    assert result["application_stopped"] is True
    success_path = gatea._upgrade_marker(tmp_path, TARGET_SHA)
    evidence_path = tmp_path / (
        f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    success = json.loads(success_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert success["passed"] is True
    assert success["backup_id"] == BACKUP_ID
    assert success["source_candidate_sha"] == SOURCE_SHA
    assert success["source_image_id"] == "sha256:source-image"
    assert success["target_aerich_versions"] == list(APPROVED_MIGRATIONS)
    assert success["evidence_sha256"] == upgrade._sha256(evidence_path)
    assert evidence["status"] == "succeeded"
    assert [step["name"] for step in evidence["steps"]] == [
        "migrate-m3",
        "migrate-m4",
        "wallet-prepare",
        "migrate-m5",
        "migrate-m6",
        "migrate-m7",
        "migrate-m8",
        "mard-publish",
    ]
    assert not any(command[:2] == ("up", "--detach") for command in compose_commands)


def test_failure_preserves_evidence_and_does_not_restart_business_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_plan(monkeypatch, tmp_path)
    compose_commands: list[tuple[str, ...]] = []
    current_version = 2

    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: compose_commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess([], 0),
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {
                "Service": service,
                "State": "running" if service in {"mysql", "redis"} else "exited",
                "Health": "healthy" if service in {"mysql", "redis"} else "",
            }
            for service in ("mysql", "redis", "app", "nginx")
        ],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_snapshot",
        lambda *args: _source_backup_snapshot(),
    )
    monkeypatch.setattr(upgrade.backup, "_source_image_manifest", lambda *args: [])

    def fail_m4(**kwargs: object) -> dict[str, object]:
        nonlocal current_version
        if kwargs["description"] == "migrate-m4":
            raise upgrade.GateAUpgradeError("controlled failure")
        current_version = 3
        return {
            "aerich_versions": list(APPROVED_MIGRATIONS[:4]),
            "applied": True,
            "migration": APPROVED_MIGRATIONS[3],
            "target_version": 3,
        }

    monkeypatch.setattr(upgrade, "_run_task", fail_m4)
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: _source_status()
        | {"aerich_versions": list(APPROVED_MIGRATIONS[: current_version + 1])},
    )

    with pytest.raises(upgrade.GateAUpgradeError, match="controlled failure"):
        upgrade.upgrade_existing_database(**_common_arguments(tmp_path, apply=True))

    evidence_path = tmp_path / (
        f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "failed"
    assert evidence["business_entry_stopped"] is True
    assert evidence["error_type"] == "GateAUpgradeError"
    assert [step["name"] for step in evidence["steps"]] == ["migrate-m3"]
    assert not gatea._upgrade_marker(tmp_path, TARGET_SHA).exists()
    assert compose_commands == [("stop", "--timeout", "30", "nginx", "app")]


def test_prior_evidence_blocks_blind_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _values(tmp_path / "backups")
    evidence_path = tmp_path / (
        f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    evidence_path.write_text('{"status":"failed"}\n', encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:target")

    with pytest.raises(upgrade.GateAUpgradeError, match="manual review"):
        upgrade._plan(
            values=values,
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            source_candidate_sha=SOURCE_SHA,
            backup_id=BACKUP_ID,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            release_record_dir=tmp_path,
        )


def test_plan_rejects_unapproved_database_start_before_loading_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _values(tmp_path / "backups")
    loaded_backup = False
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:target")
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in ("mysql", "redis", "app", "nginx")
        ],
    )
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: _source_status()
        | {"aerich_versions": list(APPROVED_MIGRATIONS[:4])},
    )

    def unexpected_backup(**kwargs: object) -> dict[str, object]:
        nonlocal loaded_backup
        loaded_backup = True
        return _backup_record()

    monkeypatch.setattr(upgrade, "_load_verified_backup", unexpected_backup)

    with pytest.raises(upgrade.GateAUpgradeError, match="approved M2"):
        upgrade._plan(
            values=values,
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            source_candidate_sha=SOURCE_SHA,
            backup_id=BACKUP_ID,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            release_record_dir=tmp_path,
        )

    assert loaded_backup is False


def test_verified_backup_must_be_fresh_and_have_exact_restore_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root = tmp_path / "backups"
    backup_records = tmp_path / "backup-records"
    restore_records = tmp_path / "restore-records"
    restore_records.mkdir()
    completed = datetime.now(timezone.utc) - timedelta(hours=25)
    payload = {
        "candidate_sha": SOURCE_SHA,
        "image_id": "sha256:source-image",
        "completed_at": completed.isoformat(),
        "consistency": "nginx-and-app-stopped",
        "application_restarted": True,
        "passed": True,
        "database_snapshot": _source_backup_snapshot(),
        "image_manifest": [],
    }
    monkeypatch.setattr(upgrade.backup, "_validate_backup_directories", lambda **kwargs: None)
    monkeypatch.setattr(
        upgrade.backup,
        "_load_backup_record",
        lambda **kwargs: (payload, Path("/db.sql"), Path("/images.tar")),
    )

    with pytest.raises(upgrade.GateAUpgradeError, match="within 24 hours"):
        upgrade._load_verified_backup(
            values=_values(backup_root),
            backup_id=BACKUP_ID,
            source_candidate_sha=SOURCE_SHA,
            backup_root=backup_root,
            backup_record_dir=backup_records,
            restore_record_dir=restore_records,
        )

    payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    with pytest.raises(upgrade.GateAUpgradeError, match="restore PASS record"):
        upgrade._load_verified_backup(
            values=_values(backup_root),
            backup_id=BACKUP_ID,
            source_candidate_sha=SOURCE_SHA,
            backup_root=backup_root,
            backup_record_dir=backup_records,
            restore_record_dir=restore_records,
        )


def test_final_snapshot_rejects_core_drift_wallet_or_mard_gap() -> None:
    source = _source_backup_snapshot()
    final = _final_snapshot()
    upgrade._validate_final_snapshot(source, final)

    for key, value, message in (
        ("orders", 1, "core invariant"),
        ("wallet_accounts", 1, "Wallet owner"),
        ("active_bead_colors", 220, "MARD invariant"),
        ("distinct_bead_color_hex", 220, "MARD invariant"),
        ("reservation_settings_unique", 0, "ReservationSettings"),
    ):
        changed = final | {key: value}
        with pytest.raises(upgrade.GateAUpgradeError, match=message):
            upgrade._validate_final_snapshot(source, changed)


def test_task_failure_does_not_echo_raw_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess(
            [], 1, stdout="must-not-appear", stderr="secret-must-not-appear"
        ),
    )

    with pytest.raises(upgrade.GateAUpgradeError, match="task failed") as captured:
        upgrade._run_task(
            values={},
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            service="migrate",
            module="app.tasks.gatea_migrate_step",
            description="migration",
        )

    assert "must-not-appear" not in str(captured.value)


def test_runtime_tasks_keep_the_image_entrypoint_for_secret_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(
            [],
            0,
            stdout='{"applied": true}',
            stderr="",
        )

    monkeypatch.setattr(gatea, "_run_compose", fake_compose)

    result = upgrade._run_task(
        values={},
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
        service="migrate",
        module="app.tasks.gatea_migrate_step",
        arguments=("--target-version", "3"),
        operations_profile=True,
        description="migration",
    )

    assert result == {"applied": True}
    assert calls[0]["arguments"] == (
        "run",
        "--rm",
        "--no-deps",
        "migrate",
        "python",
        "-m",
        "app.tasks.gatea_migrate_step",
        "--target-version",
        "3",
    )
    assert "--entrypoint" not in calls[0]["arguments"]


def test_runtime_preflight_uses_entrypoint_and_rejects_raw_failure_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                '{"app_env":"production","db_engine":"mysql",'
                '"jwt_algorithm":"HS256","validated":true}'
            ),
            stderr="",
        )

    monkeypatch.setattr(gatea, "_run_compose", fake_compose)

    result = upgrade._run_runtime_preflight(
        values={},
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
    )

    assert result["validated"] is True
    assert calls[0]["arguments"][:6] == (
        "run",
        "--rm",
        "--no-deps",
        "migrate",
        "python",
        "-c",
    )
    assert "--entrypoint" not in calls[0]["arguments"]

    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess(
            [], 1, stdout="must-not-appear", stderr="secret-must-not-appear"
        ),
    )
    with pytest.raises(upgrade.GateAUpgradeError) as captured:
        upgrade._run_runtime_preflight(
            values={},
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
        )
    assert "must-not-appear" not in str(captured.value)


def test_invalid_backup_id_is_rejected_before_reading_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    validated = False

    def unexpected_inputs(**kwargs: object) -> dict[str, str]:
        nonlocal validated
        validated = True
        return {}

    monkeypatch.setattr(gatea, "_validated_inputs", unexpected_inputs)
    arguments = _common_arguments(tmp_path, apply=False)
    arguments["backup_id"] = "../escape"

    with pytest.raises(gatea.GateAError, match="YYYYMMDD"):
        upgrade.upgrade_existing_database(**arguments)

    assert validated is False


def test_deployment_record_accepts_upgrade_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    path = gatea._upgrade_marker(tmp_path, TARGET_SHA)
    payload = {
        "schema_version": 1,
        "record_type": "existing-database-upgrade",
        "candidate_sha": TARGET_SHA,
        "image_id": "sha256:target",
        "passed": True,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "backup_id": BACKUP_ID,
        "manifest_sha256": MANIFEST_SHA,
        "source_candidate_sha": SOURCE_SHA,
        "source_image_id": "sha256:source",
        "source_aerich_versions": list(APPROVED_MIGRATIONS[:3]),
        "target_aerich_versions": list(APPROVED_MIGRATIONS),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert tuple(APPROVED_MIGRATIONS) == gatea.APPROVED_TARGET_M8_CHAIN
    loaded = gatea._require_deployment_record(
        record_dir=tmp_path,
        candidate_sha=TARGET_SHA,
        image_id="sha256:target",
    )
    assert loaded == payload

    payload["passed"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(gatea.GateAError, match="does not match"):
        gatea._require_deployment_record(
            record_dir=tmp_path,
            candidate_sha=TARGET_SHA,
            image_id="sha256:target",
        )

    payload["passed"] = True
    payload["source_candidate_sha"] = TARGET_SHA
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(gatea.GateAError, match="does not match"):
        gatea._require_deployment_record(
            record_dir=tmp_path,
            candidate_sha=TARGET_SHA,
            image_id="sha256:target",
        )
