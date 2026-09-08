"""Gate A 非空 M2→M8 升级编排的授权、顺序、证据与失败语义。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
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
        "PRODUCT_IMAGE_BASE_URL": (
            "https://api-test.pinkdoohub.cn/uploads/products"
        ),
    }


def _source_backup_snapshot(source_version: int = 2) -> dict[str, object]:
    return {
        "aerich_versions": ",".join(APPROVED_MIGRATIONS[: source_version + 1]),
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


def _source_status(source_version: int = 2) -> dict[str, object]:
    return _source_backup_snapshot(source_version) | {
        "aerich_versions": list(APPROVED_MIGRATIONS[: source_version + 1]),
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


def _backup_record(source_version: int = 2) -> dict[str, object]:
    record: dict[str, object] = {
        "candidate_sha": SOURCE_SHA,
        "image_id": "sha256:source-image",
        "database_snapshot": _source_backup_snapshot(source_version),
        "image_manifest": _mard_image_manifest() if source_version == 7 else [],
    }
    if source_version == 7:
        record["m7_content_snapshot"] = _m7_content_snapshot()
    return record


def _m7_content_snapshot(digest: str = "7" * 64) -> dict[str, object]:
    return {
        "content_sha256": digest,
        "profile": upgrade.backup.M7_CONTENT_SNAPSHOT_PROFILE,
        "schema_version": upgrade.backup.M7_CONTENT_SNAPSHOT_SCHEMA_VERSION,
    }


def _m7_source_preflight() -> dict[str, object]:
    return {
        "catalog_rows": 221,
        "catalog_sha256": "8" * 64,
        "image_set_sha256": "9" * 64,
        "images": 221,
        "manifest_sha256": MANIFEST_SHA,
        "profile": upgrade.M7_MARD_PREFLIGHT_PROFILE,
        "swatch_hex_columns": 0,
    }


def _mard_image_manifest() -> list[str]:
    return [f"{'0' * 64} mard-{index:03d}.png" for index in range(221)]


def _m7_invariants() -> dict[str, object]:
    final = _final_snapshot()
    return {key: final[key] for key in upgrade.M7_INVARIANT_KEYS}


def _common_arguments(
    tmp_path: Path,
    *,
    apply: bool,
    source_version: int | None = None,
) -> dict[str, object]:
    arguments: dict[str, object] = {
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
    if source_version is not None:
        arguments["source_version"] = source_version
    return arguments


def _patch_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    source_version: int = 2,
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
            _backup_record(source_version),
            _source_status(source_version),
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


def _noop_mard_preview() -> dict[str, object]:
    return {
        "already_current": True,
        "colors": 221,
        "created_images": 0,
        "database_changes": 0,
        "images_reused": 221,
        "images_to_create": 0,
        "manifest_sha256": MANIFEST_SHA,
        "mode": "preview",
    }


def _stopped_replay_service_rows() -> list[dict[str, str]]:
    return [
        {
            "Service": service,
            "State": "running" if service in {"mysql", "redis"} else "exited",
            "Health": "healthy" if service in {"mysql", "redis"} else "",
        }
        for service in ("mysql", "redis", "app", "nginx")
    ]


def _patch_stopped_replay_services(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: _stopped_replay_service_rows(),
    )


def _write_replay_fixture(
    tmp_path: Path,
    *,
    source_version: int = 7,
    include_source_version: bool = True,
) -> tuple[Path, Path, dict[str, object]]:
    success_path = gatea._upgrade_marker(tmp_path, TARGET_SHA)
    evidence_path = tmp_path / (
        f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    final_snapshot = _final_snapshot()
    final_images = _manifest_summary_fixture(_mard_image_manifest())
    evidence: dict[str, object] = {
        "schema_version": 1,
        "record_type": "existing-database-upgrade-evidence",
        "candidate_sha": TARGET_SHA,
        "source_candidate_sha": SOURCE_SHA,
        "backup_id": BACKUP_ID,
        "status": "succeeded",
        "final_database_snapshot": final_snapshot,
        "final_image_manifest": final_images,
    }
    if source_version == 7:
        evidence["final_m7_content_snapshot"] = _m7_content_snapshot()
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    success: dict[str, object] = {
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
        "source_aerich_versions": list(
            APPROVED_MIGRATIONS[: source_version + 1]
        ),
        "target_aerich_versions": list(APPROVED_MIGRATIONS),
        "evidence_path": str(evidence_path),
        "evidence_sha256": upgrade._sha256(evidence_path),
        "final_database_snapshot": final_snapshot,
        "final_image_manifest": final_images,
    }
    if include_source_version:
        success["source_version"] = source_version
    if source_version == 7:
        success["final_m7_content_snapshot"] = _m7_content_snapshot()
    success_path.write_text(json.dumps(success), encoding="utf-8")
    return success_path, evidence_path, success


def _manifest_summary_fixture(lines: list[str]) -> dict[str, object]:
    return upgrade._manifest_summary(lines)


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
        "source_aerich_versions": list(APPROVED_MIGRATIONS[:3]),
        "source_candidate_sha": SOURCE_SHA,
        "source_version": 2,
        "target_aerich_versions": list(APPROVED_MIGRATIONS),
        "target_version": 8,
    }
    assert not list(tmp_path.glob("*.json"))

    arguments = _common_arguments(tmp_path, apply=False)
    arguments["confirm_target_sha"] = TARGET_SHA
    with pytest.raises(upgrade.GateAUpgradeError, match="does not accept"):
        upgrade.upgrade_existing_database(**arguments)


def test_cli_defaults_to_m2_and_requires_explicit_m7_selection() -> None:
    base_arguments = [
        "--mode",
        "loopback",
        "--source-candidate-sha",
        SOURCE_SHA,
        "--backup-id",
        BACKUP_ID,
    ]

    assert upgrade._parser().parse_args(base_arguments).source_version == 2
    assert (
        upgrade._parser()
        .parse_args([*base_arguments, "--source-version", "7"])
        .source_version
        == 7
    )
    parser = upgrade._parser()
    assert parser.description is not None
    assert "M7 requires explicit --source-version 7" in parser.description
    help_text = " ".join(parser.format_help().split())
    assert "defaults to M2 only for legacy command compatibility" in help_text


def test_m7_plan_requires_explicit_source_version_before_loading_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _values(tmp_path / "backups")
    backup_loads = 0
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
        lambda **kwargs: _source_status(7),
    )

    def load_backup(**kwargs: object) -> dict[str, object]:
        nonlocal backup_loads
        backup_loads += 1
        return _backup_record(7)

    monkeypatch.setattr(upgrade, "_load_verified_backup", load_backup)
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)
    plan_arguments = {
        "values": values,
        "config_file": Path("/config.env"),
        "secret_dir": Path("/secrets"),
        "mode": "loopback",
        "source_candidate_sha": SOURCE_SHA,
        "backup_id": BACKUP_ID,
        "backup_root": tmp_path / "backups",
        "backup_record_dir": tmp_path / "backup-records",
        "restore_record_dir": tmp_path / "restore-records",
        "release_record_dir": tmp_path,
    }

    with pytest.raises(upgrade.GateAUpgradeError, match="approved M2"):
        upgrade._plan(**plan_arguments)
    assert backup_loads == 0

    _, _, backup_record, source_status, manifest_sha = upgrade._plan(
        **plan_arguments,
        source_version=7,
    )
    assert backup_loads == 1
    assert backup_record["database_snapshot"]["aerich_versions"] == ",".join(
        APPROVED_MIGRATIONS[:8]
    )
    assert source_status["aerich_versions"] == list(APPROVED_MIGRATIONS[:8])
    assert manifest_sha == MANIFEST_SHA


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
            "created_images": 0,
            "database_changes": 0,
            "images_reused": 221,
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
    monkeypatch.setattr(
        upgrade,
        "_read_final_snapshot",
        lambda **kwargs: _final_snapshot(),
    )

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


def test_m7_apply_runs_only_m8_and_mard_and_records_exact_source_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_plan(monkeypatch, tmp_path, source_version=7)
    compose_commands: list[tuple[str, ...]] = []
    task_names: list[str] = []
    current_version = 7
    content_snapshot_calls: list[bool] = []

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
        lambda *args: _source_backup_snapshot(7),
    )

    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: _mard_image_manifest(),
    )
    monkeypatch.setattr(
        upgrade,
        "_read_m7_invariant_snapshot",
        lambda **kwargs: _m7_invariants(),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m7_content_snapshot",
        lambda *args: content_snapshot_calls.append(True)
        or _m7_content_snapshot(),
    )
    monkeypatch.setattr(
        upgrade,
        "_run_m7_source_preflight",
        lambda **kwargs: _m7_source_preflight(),
    )

    def fake_task(**kwargs: object) -> dict[str, object]:
        nonlocal current_version
        description = str(kwargs["description"])
        task_names.append(description)
        if description == "migrate-m8":
            current_version = 8
            return {
                "aerich_versions": list(APPROVED_MIGRATIONS),
                "applied": True,
                "migration": APPROVED_MIGRATIONS[8],
                "target_version": 8,
            }
        if description == "mard-preview":
            return {
                "already_current": True,
                "colors": 221,
                "created_images": 0,
                "database_changes": 0,
                "images_reused": 221,
                "images_to_create": 0,
                "manifest_sha256": MANIFEST_SHA,
                "mode": "preview",
            }
        if description == "mard-apply":
            return {
                "already_current": True,
                "colors": 221,
                "created_images": 0,
                "database_changes": 0,
                "images_reused": 221,
                "images_to_create": 0,
                "manifest_sha256": MANIFEST_SHA,
                "mode": "apply",
            }
        if description == "mard-replay-preview":
            return {
                "already_current": True,
                "colors": 221,
                "created_images": 0,
                "database_changes": 0,
                "images_reused": 221,
                "images_to_create": 0,
                "manifest_sha256": MANIFEST_SHA,
                "mode": "preview",
            }
        raise AssertionError(f"unexpected task: {description}")

    monkeypatch.setattr(upgrade, "_run_task", fake_task)
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: _source_status(7)
        | {"aerich_versions": list(APPROVED_MIGRATIONS[: current_version + 1])},
    )
    monkeypatch.setattr(
        upgrade,
        "_read_final_snapshot",
        lambda **kwargs: _final_snapshot(),
    )

    result = upgrade.upgrade_existing_database(
        **_common_arguments(tmp_path, apply=True, source_version=7)
    )

    assert compose_commands == [("stop", "--timeout", "30", "nginx", "app")]
    assert task_names == [
        "migrate-m8",
        "mard-preview",
        "mard-apply",
        "mard-replay-preview",
    ]
    assert content_snapshot_calls == [True, True]
    assert result["source_version"] == 7
    assert result["source_aerich_versions"] == list(APPROVED_MIGRATIONS[:8])
    success_path = gatea._upgrade_marker(tmp_path, TARGET_SHA)
    evidence_path = tmp_path / (
        f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    success = json.loads(success_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert success["source_version"] == 7
    assert success["source_aerich_versions"] == list(APPROVED_MIGRATIONS[:8])
    assert success["target_aerich_versions"] == list(APPROVED_MIGRATIONS)
    assert success["source_m7_content_snapshot"] == _m7_content_snapshot()
    assert success["final_m7_content_snapshot"] == _m7_content_snapshot()
    assert success["source_m7_mard_preflight"] == _m7_source_preflight()
    assert success["wallet_preparation"] == {}
    assert evidence["source_version"] == 7
    assert evidence["source_aerich_versions"] == list(APPROVED_MIGRATIONS[:8])
    assert evidence["target_aerich_versions"] == list(APPROVED_MIGRATIONS)
    assert evidence["source_m7_content_snapshot"] == _m7_content_snapshot()
    assert evidence["final_m7_content_snapshot"] == _m7_content_snapshot()
    assert evidence["source_m7_mard_preflight"] == _m7_source_preflight()
    assert [step["name"] for step in evidence["steps"]] == [
        "migrate-m8",
        "mard-publish",
    ]

    replay = upgrade.upgrade_existing_database(
        **_common_arguments(tmp_path, apply=False, source_version=7)
    )
    assert replay == {
        "already_current": True,
        "backup_id": BACKUP_ID,
        "candidate_sha": TARGET_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "mode": "plan-replay",
        "source_aerich_versions": list(APPROVED_MIGRATIONS[:8]),
        "source_version": 7,
        "target_aerich_versions": list(APPROVED_MIGRATIONS),
        "target_version": 8,
    }
    assert task_names == [
        "migrate-m8",
        "mard-preview",
        "mard-apply",
        "mard-replay-preview",
    ]


@pytest.mark.parametrize(
    "failure_message",
    (
        "Gate A M7 MARD catalog differs from the manifest",
        "Gate A M7 MARD image set differs from the manifest",
        "Gate A M7 source schema is partially upgraded",
    ),
)
def test_m7_source_preflight_failure_blocks_m8_before_any_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_message: str,
) -> None:
    _patch_plan(monkeypatch, tmp_path, source_version=7)
    compose_commands: list[tuple[str, ...]] = []
    task_names: list[str] = []

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
        lambda *args: _source_backup_snapshot(7),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: _mard_image_manifest(),
    )
    monkeypatch.setattr(
        upgrade,
        "_read_m7_invariant_snapshot",
        lambda **kwargs: _m7_invariants(),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m7_content_snapshot",
        lambda *args: _m7_content_snapshot(),
    )
    monkeypatch.setattr(
        upgrade,
        "_run_m7_source_preflight",
        lambda **kwargs: (_ for _ in ()).throw(
            upgrade.GateAUpgradeError(failure_message)
        ),
    )

    def unexpected_task(**kwargs: object) -> dict[str, object]:
        description = str(kwargs["description"])
        task_names.append(description)
        raise AssertionError(f"unexpected task: {description}")

    monkeypatch.setattr(upgrade, "_run_task", unexpected_task)
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: _source_status(7),
    )

    with pytest.raises(upgrade.GateAUpgradeError, match=re.escape(failure_message)):
        upgrade.upgrade_existing_database(
            **_common_arguments(tmp_path, apply=True, source_version=7)
        )

    evidence_path = tmp_path / (
        f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "failed"
    assert evidence["business_entry_stopped"] is True
    assert evidence["source_version"] == 7
    assert evidence["failure_database_status"]["aerich_versions"] == list(
        APPROVED_MIGRATIONS[:8]
    )
    assert evidence["steps"] == []
    assert task_names == []
    assert compose_commands == [("stop", "--timeout", "30", "nginx", "app")]
    assert not gatea._upgrade_marker(tmp_path, TARGET_SHA).exists()


def test_stopped_m7_content_drift_blocks_preflight_and_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_plan(monkeypatch, tmp_path, source_version=7)
    compose_commands: list[tuple[str, ...]] = []
    preflight_called = False
    task_names: list[str] = []

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
        lambda *args: _source_backup_snapshot(7),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: _mard_image_manifest(),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m7_content_snapshot",
        lambda *args: _m7_content_snapshot("8" * 64),
    )

    def unexpected_preflight(**kwargs: object) -> dict[str, object]:
        nonlocal preflight_called
        preflight_called = True
        return _m7_source_preflight()

    def unexpected_task(**kwargs: object) -> dict[str, object]:
        task_names.append(str(kwargs["description"]))
        raise AssertionError("migration must not run")

    monkeypatch.setattr(upgrade, "_run_m7_source_preflight", unexpected_preflight)
    monkeypatch.setattr(upgrade, "_run_task", unexpected_task)
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: _source_status(7),
    )

    with pytest.raises(upgrade.GateAUpgradeError, match="stopped M7 content"):
        upgrade.upgrade_existing_database(
            **_common_arguments(tmp_path, apply=True, source_version=7)
        )

    assert preflight_called is False
    assert task_names == []
    assert compose_commands == [("stop", "--timeout", "30", "nginx", "app")]


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


def test_m7_replay_record_must_match_explicit_source_version_and_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_replay_fixture(tmp_path)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:target")
    _patch_stopped_replay_services(monkeypatch)
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)
    monkeypatch.setattr(
        upgrade,
        "_read_final_snapshot",
        lambda **kwargs: _final_snapshot(),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: _mard_image_manifest(),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m7_content_snapshot",
        lambda *args: _m7_content_snapshot(),
    )
    monkeypatch.setattr(
        upgrade,
        "_run_task",
        lambda **kwargs: _noop_mard_preview(),
    )
    arguments = {
        "values": _values(tmp_path / "backups"),
        "config_file": Path("/config.env"),
        "secret_dir": Path("/secrets"),
        "mode": "loopback",
        "source_candidate_sha": SOURCE_SHA,
        "backup_id": BACKUP_ID,
        "backup_root": tmp_path / "backups",
        "backup_record_dir": tmp_path / "backup-records",
        "restore_record_dir": tmp_path / "restore-records",
        "release_record_dir": tmp_path,
    }

    _, _, backup_record, final_snapshot, manifest_sha = upgrade._plan(
        **arguments,
        source_version=7,
    )
    assert backup_record == {}
    assert final_snapshot["aerich_versions"] == list(APPROVED_MIGRATIONS)
    assert manifest_sha == MANIFEST_SHA

    with pytest.raises(upgrade.GateAUpgradeError, match="requested replay"):
        upgrade._plan(**arguments)


def test_legacy_m2_to_m8_replay_without_source_version_remains_compatible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_replay_fixture(
        tmp_path,
        source_version=2,
        include_source_version=False,
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:target")
    _patch_stopped_replay_services(monkeypatch)
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)
    monkeypatch.setattr(upgrade, "_read_final_snapshot", lambda **kwargs: _final_snapshot())
    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: _mard_image_manifest(),
    )
    monkeypatch.setattr(upgrade, "_run_task", lambda **kwargs: _noop_mard_preview())

    _, _, backup_record, final_snapshot, _ = upgrade._plan(
        values=_values(tmp_path / "backups"),
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
    assert backup_record == {}
    assert final_snapshot == _final_snapshot()


@pytest.mark.parametrize(
    ("scenario", "message"),
    (
        ("evidence_path", "requested replay"),
        ("evidence_digest", "evidence digest"),
        ("database", "database"),
        ("images", "image volume"),
        ("m7_content", "preserved M7 content"),
        ("mard", "exact no-op"),
    ),
)
def test_replay_revalidates_fixed_evidence_and_current_final_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario: str,
    message: str,
) -> None:
    success_path, evidence_path, success = _write_replay_fixture(tmp_path)
    final_snapshot = _final_snapshot()
    final_images = _mard_image_manifest()
    final_m7_content = _m7_content_snapshot()
    mard_preview = _noop_mard_preview()

    if scenario == "evidence_path":
        success["evidence_path"] = str(tmp_path / "attacker-selected.json")
        success_path.write_text(json.dumps(success), encoding="utf-8")
    elif scenario == "evidence_digest":
        evidence_path.write_text('{"tampered":true}\n', encoding="utf-8")
    elif scenario == "database":
        final_snapshot = final_snapshot | {"orders": 1}
    elif scenario == "images":
        final_images = final_images.copy()
        final_images[-1] = f"{'f' * 64} mard-220.png"
    elif scenario == "m7_content":
        final_m7_content = _m7_content_snapshot("8" * 64)
    elif scenario == "mard":
        mard_preview = mard_preview | {
            "already_current": False,
            "database_changes": 1,
        }

    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:target")
    _patch_stopped_replay_services(monkeypatch)
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)
    monkeypatch.setattr(
        upgrade,
        "_read_final_snapshot",
        lambda **kwargs: final_snapshot,
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: final_images,
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m7_content_snapshot",
        lambda *args: final_m7_content,
    )
    monkeypatch.setattr(
        upgrade,
        "_run_task",
        lambda **kwargs: mard_preview,
    )

    with pytest.raises(upgrade.GateAUpgradeError, match=message):
        upgrade._plan(
            values=_values(tmp_path / "backups"),
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            source_candidate_sha=SOURCE_SHA,
            backup_id=BACKUP_ID,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            release_record_dir=tmp_path,
            source_version=7,
        )


@pytest.mark.parametrize(
    ("scenario", "message"),
    (
        ("app-running-healthy", "service app did not stop"),
        ("nginx-running-healthy", "service nginx did not stop"),
        ("app-missing", "service app is unavailable"),
        ("mysql-missing", "service mysql is unavailable"),
        ("redis-unhealthy", "service redis is not healthy"),
    ),
)
def test_replay_requires_healthy_dependencies_and_stopped_business_services(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario: str,
    message: str,
) -> None:
    _write_replay_fixture(tmp_path)
    rows = _stopped_replay_service_rows()
    if scenario == "app-running-healthy":
        rows[2] = {"Service": "app", "State": "running", "Health": "healthy"}
    elif scenario == "nginx-running-healthy":
        rows[3] = {
            "Service": "nginx",
            "State": "running",
            "Health": "healthy",
        }
    elif scenario == "app-missing":
        rows = [row for row in rows if row["Service"] != "app"]
    elif scenario == "mysql-missing":
        rows = [row for row in rows if row["Service"] != "mysql"]
    elif scenario == "redis-unhealthy":
        rows[1] = {"Service": "redis", "State": "running", "Health": "unhealthy"}

    live_checks: list[str] = []
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:target")
    monkeypatch.setattr(gatea, "_compose_ps", lambda **kwargs: rows)
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)
    monkeypatch.setattr(
        upgrade,
        "_read_final_snapshot",
        lambda **kwargs: live_checks.append("database") or _final_snapshot(),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: live_checks.append("images") or _mard_image_manifest(),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m7_content_snapshot",
        lambda *args: live_checks.append("content") or _m7_content_snapshot(),
    )
    monkeypatch.setattr(
        upgrade,
        "_run_task",
        lambda **kwargs: live_checks.append("mard") or _noop_mard_preview(),
    )

    with pytest.raises(gatea.GateAError, match=message):
        upgrade._plan(
            values=_values(tmp_path / "backups"),
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            source_candidate_sha=SOURCE_SHA,
            backup_id=BACKUP_ID,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            release_record_dir=tmp_path,
            source_version=7,
        )

    assert live_checks == []


def test_replay_fails_closed_when_service_status_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_replay_fixture(tmp_path)
    live_checks: list[str] = []
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:target")
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)

    def unavailable_status(**kwargs: object) -> list[dict[str, str]]:
        raise gatea.GateAError("Gate A service status is unavailable")

    monkeypatch.setattr(gatea, "_compose_ps", unavailable_status)
    monkeypatch.setattr(
        upgrade,
        "_read_final_snapshot",
        lambda **kwargs: live_checks.append("database") or _final_snapshot(),
    )

    with pytest.raises(gatea.GateAError, match="service status is unavailable"):
        upgrade._plan(
            values=_values(tmp_path / "backups"),
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            source_candidate_sha=SOURCE_SHA,
            backup_id=BACKUP_ID,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            release_record_dir=tmp_path,
            source_version=7,
        )

    assert live_checks == []


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


def test_verified_m7_backup_requires_restore_record_with_exact_content_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root = tmp_path / "backups"
    backup_records = tmp_path / "backup-records"
    restore_records = tmp_path / "restore-records"
    restore_records.mkdir()
    completed = datetime.now(timezone.utc) - timedelta(minutes=10)
    content_snapshot = _m7_content_snapshot()
    payload = {
        "candidate_sha": SOURCE_SHA,
        "image_id": "sha256:source-image",
        "completed_at": completed.isoformat(),
        "consistency": "nginx-and-app-stopped",
        "application_restarted": True,
        "passed": True,
        "database_snapshot": _source_backup_snapshot(7),
        "m7_content_snapshot": content_snapshot,
        "image_manifest": _mard_image_manifest(),
    }
    restore_payload: dict[str, object] = {
        "schema_version": 1,
        "backup_id": BACKUP_ID,
        "candidate_sha": SOURCE_SHA,
        "restore_project": upgrade.backup.restore_project(BACKUP_ID),
        "completed_at": (completed + timedelta(minutes=1)).isoformat(),
        "host_ports_published": False,
        "m7_content_matches": True,
        "m7_content_snapshot": content_snapshot,
    }
    restore_payload.update({field: True for field in upgrade.RESTORE_TRUE_FIELDS})
    restore_path = restore_records / f"{BACKUP_ID}.json"
    restore_path.write_text(json.dumps(restore_payload), encoding="utf-8")
    monkeypatch.setattr(
        upgrade.backup,
        "_validate_backup_directories",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_load_backup_record",
        lambda **kwargs: (payload, Path("/db.sql"), Path("/images.tar")),
    )

    assert upgrade._load_verified_backup(
        values=_values(backup_root),
        backup_id=BACKUP_ID,
        source_candidate_sha=SOURCE_SHA,
        backup_root=backup_root,
        backup_record_dir=backup_records,
        restore_record_dir=restore_records,
    ) == payload

    restore_payload["m7_content_snapshot"] = _m7_content_snapshot("8" * 64)
    restore_path.write_text(json.dumps(restore_payload), encoding="utf-8")
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

    m7_source = _source_backup_snapshot(7)
    m7_invariants = _m7_invariants()
    upgrade._validate_final_snapshot(
        m7_source,
        final,
        source_version=7,
        source_m7_invariants=m7_invariants,
    )
    with pytest.raises(upgrade.GateAUpgradeError, match="M7 invariant"):
        upgrade._validate_final_snapshot(
            m7_source,
            final,
            source_version=7,
            source_m7_invariants=m7_invariants | {"payments": 1},
        )
    with pytest.raises(upgrade.GateAUpgradeError, match="unavailable"):
        upgrade._validate_final_snapshot(m7_source, final, source_version=7)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("already_current", False),
        ("created_images", 1),
        ("database_changes", 1),
        ("images_reused", 220),
        ("images_to_create", 1),
    ),
)
def test_m7_mard_result_requires_every_noop_signal(
    field: str,
    value: object,
) -> None:
    result = {
        "already_current": True,
        "colors": 221,
        "created_images": 0,
        "database_changes": 0,
        "images_reused": 221,
        "images_to_create": 0,
        "manifest_sha256": MANIFEST_SHA,
        "mode": "apply",
    }
    upgrade._validate_mard_result(
        result,
        expected_mode="apply",
        manifest_sha256=MANIFEST_SHA,
        require_noop=True,
    )

    with pytest.raises(upgrade.GateAUpgradeError, match="exact no-op"):
        upgrade._validate_mard_result(
            result | {field: value},
            expected_mode="apply",
            manifest_sha256=MANIFEST_SHA,
            require_noop=True,
        )


def test_m7_image_manifest_must_be_identical_while_m2_may_publish_images() -> None:
    existing = _mard_image_manifest()
    upgrade._validate_final_image_manifest(
        source_version=7,
        stopped_manifest=existing,
        final_manifest=existing.copy(),
    )

    changed = existing.copy()
    changed[-1] = f"{'1' * 64} mard-220.png"
    with pytest.raises(upgrade.GateAUpgradeError, match="changed unexpectedly"):
        upgrade._validate_final_image_manifest(
            source_version=7,
            stopped_manifest=existing,
            final_manifest=changed,
        )
    with pytest.raises(upgrade.GateAUpgradeError, match="changed unexpectedly"):
        upgrade._validate_final_image_manifest(
            source_version=7,
            stopped_manifest=existing,
            final_manifest=list(reversed(existing)),
        )

    upgrade._validate_final_image_manifest(
        source_version=2,
        stopped_manifest=[],
        final_manifest=existing,
    )


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


def test_m7_invariant_snapshot_uses_pre_m8_safe_aggregate_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(_m7_invariants()),
            stderr="",
        )

    monkeypatch.setattr(gatea, "_run_compose", fake_compose)
    result = upgrade._read_m7_invariant_snapshot(
        values={},
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
    )

    assert result == _m7_invariants()
    arguments = calls[0]["arguments"]
    assert isinstance(arguments, tuple)
    assert arguments[:5] == ("exec", "--no-TTY", "mysql", "sh", "-ec")
    assert "swatch_hex" not in str(arguments[-1])

    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess(
            [],
            0,
            stdout='{"wallet_accounts": 0}',
            stderr="",
        ),
    )
    with pytest.raises(upgrade.GateAUpgradeError, match="incomplete"):
        upgrade._read_m7_invariant_snapshot(
            values={},
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
        )


def test_m7_mard_catalog_reader_uses_only_pre_m8_columns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_rows, _, _ = upgrade._m7_manifest_contract(_values(tmp_path))
    calls: list[dict[str, object]] = []

    def fake_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(
            [],
            0,
            stdout="\n".join(expected_rows) + "\n",
            stderr="",
        )

    monkeypatch.setattr(gatea, "_run_compose", fake_compose)
    assert upgrade._read_m7_mard_catalog(
        values=_values(tmp_path),
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
    ) == expected_rows
    arguments = calls[0]["arguments"]
    assert isinstance(arguments, tuple)
    assert arguments[:5] == ("exec", "--no-TTY", "mysql", "sh", "-ec")
    assert "swatch_hex" not in str(arguments[-1])


def test_m7_source_preflight_requires_exact_catalog_png_hash_and_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _values(tmp_path)
    expected_rows, expected_images, expected_image_set_sha = (
        upgrade._m7_manifest_contract(values)
    )
    image_manifest = [
        f"{digest}  {filename}" for filename, digest in expected_images.items()
    ]
    image_manifest.append(f"{'a' * 64}  unrelated-product-photo.webp")
    mode_manifest = [f"644 {filename}" for filename in expected_images]
    mode_manifest.append("600 unrelated-product-photo.webp")
    monkeypatch.setattr(
        upgrade,
        "_read_m7_mard_catalog",
        lambda **kwargs: expected_rows,
    )
    monkeypatch.setattr(
        upgrade,
        "_read_m7_schema_status",
        lambda **kwargs: {"swatch_hex_columns": 0},
    )
    monkeypatch.setattr(
        upgrade,
        "_read_m7_image_mode_manifest",
        lambda **kwargs: tuple(mode_manifest),
    )

    result = upgrade._run_m7_source_preflight(
        values=values,
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
        stopped_image_manifest=image_manifest,
        manifest_sha256=MANIFEST_SHA,
    )
    assert result == {
        "catalog_rows": 221,
        "catalog_sha256": upgrade._manifest_summary(expected_rows)["sha256"],
        "image_set_sha256": expected_image_set_sha,
        "images": 221,
        "manifest_sha256": MANIFEST_SHA,
        "profile": upgrade.M7_MARD_PREFLIGHT_PROFILE,
        "swatch_hex_columns": 0,
    }

    changed_rows = list(expected_rows)
    changed_rows[0] = changed_rows[0].replace("4131", "5A39", 1)
    monkeypatch.setattr(
        upgrade,
        "_read_m7_mard_catalog",
        lambda **kwargs: tuple(changed_rows),
    )
    with pytest.raises(upgrade.GateAUpgradeError, match="catalog differs"):
        upgrade._run_m7_source_preflight(
            values=values,
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            stopped_image_manifest=image_manifest,
            manifest_sha256=MANIFEST_SHA,
        )

    bad_hashes = image_manifest.copy()
    bad_hashes[0] = f"{'f' * 64}  {next(iter(expected_images))}"
    monkeypatch.setattr(
        upgrade,
        "_read_m7_mard_catalog",
        lambda **kwargs: expected_rows,
    )
    with pytest.raises(upgrade.GateAUpgradeError, match="image set differs"):
        upgrade._run_m7_source_preflight(
            values=values,
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            stopped_image_manifest=bad_hashes,
            manifest_sha256=MANIFEST_SHA,
        )

    with pytest.raises(upgrade.GateAUpgradeError, match="image set differs"):
        upgrade._run_m7_source_preflight(
            values=values,
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            stopped_image_manifest=image_manifest[1:],
            manifest_sha256=MANIFEST_SHA,
        )

    monkeypatch.setattr(
        upgrade,
        "_read_m7_mard_catalog",
        lambda **kwargs: expected_rows,
    )
    first_filename = next(iter(expected_images))
    bad_modes = [
        (f"600 {filename}" if filename == first_filename else line)
        for filename, line in zip(expected_images, mode_manifest, strict=False)
    ]
    monkeypatch.setattr(
        upgrade,
        "_read_m7_image_mode_manifest",
        lambda **kwargs: tuple(bad_modes),
    )
    with pytest.raises(upgrade.GateAUpgradeError, match="image set differs"):
        upgrade._run_m7_source_preflight(
            values=values,
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            stopped_image_manifest=image_manifest,
            manifest_sha256=MANIFEST_SHA,
        )

    monkeypatch.setattr(
        upgrade,
        "_read_m7_schema_status",
        lambda **kwargs: {"swatch_hex_columns": 1},
    )
    with pytest.raises(upgrade.GateAUpgradeError, match="partially upgraded"):
        upgrade._run_m7_source_preflight(
            values=values,
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            stopped_image_manifest=image_manifest,
            manifest_sha256=MANIFEST_SHA,
        )


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
        "target_aerich_versions": list(gatea.APPROVED_TARGET_M7_CHAIN),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert tuple(APPROVED_MIGRATIONS) == gatea.APPROVED_TARGET_M8_CHAIN
    loaded = gatea._require_deployment_record(
        record_dir=tmp_path,
        candidate_sha=TARGET_SHA,
        image_id="sha256:target",
    )
    assert loaded == payload

    payload["target_aerich_versions"] = list(APPROVED_MIGRATIONS)
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert gatea._require_deployment_record(
        record_dir=tmp_path,
        candidate_sha=TARGET_SHA,
        image_id="sha256:target",
    ) == payload

    payload["source_aerich_versions"] = list(APPROVED_MIGRATIONS[:8])
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(gatea.GateAError, match="does not match"):
        gatea._require_deployment_record(
            record_dir=tmp_path,
            candidate_sha=TARGET_SHA,
            image_id="sha256:target",
        )

    payload["source_version"] = 7
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert gatea._require_deployment_record(
        record_dir=tmp_path,
        candidate_sha=TARGET_SHA,
        image_id="sha256:target",
    ) == payload

    payload["source_version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(gatea.GateAError, match="does not match"):
        gatea._require_deployment_record(
            record_dir=tmp_path,
            candidate_sha=TARGET_SHA,
            image_id="sha256:target",
        )

    payload["source_version"] = 7
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
