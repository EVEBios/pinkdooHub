"""Gate A 非空 M2/M7→M9 升级编排的授权、顺序、证据与失败语义。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.tasks.gatea_migrate_step import APPROVED_MIGRATIONS
from scripts.release import gatea_operations as gatea
from scripts.release import gatea_upgrade as upgrade


SOURCE_SHA = "a" * 40
TARGET_SHA = "b" * 40
BACKUP_ID = "20260907t120000z"
MANIFEST_SHA = "c" * 64
LINEAGE_SHA = "d" * 40
RETIREMENT_SHA = "e" * 64


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
        "store_tables": 30,
        "enabled_store_tables": 30,
        "invalid_table_numbers": 0,
        "invalid_table_display_names": 0,
        "invalid_table_qr_token_lengths": 0,
        "invalid_table_qr_token_characters": 0,
        "invalid_store_tables": 0,
        "distinct_table_qr_tokens": 30,
        "table_sessions": 0,
        "table_session_timers": 0,
        "table_occupancies": 0,
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
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
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
            "table_session_claims_enabled": True,
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


def _empty_table_reconcile_result() -> dict[str, object]:
    return {key: 0 for key in upgrade.M9_EMPTY_TABLE_RECONCILE_KEYS}


def _empty_table_sweep_result() -> dict[str, object]:
    return {"status": "ok", "closed": 0}


def _adoption_content_snapshot(profile: str, digest: str) -> dict[str, object]:
    return {"schema_version": 1, "profile": profile, "content_sha256": digest}


def _adoption_backup_record() -> dict[str, object]:
    return {
        "candidate_sha": SOURCE_SHA,
        "image_id": "sha256:" + "1" * 64,
        "database_snapshot": _source_backup_snapshot(9),
        "image_manifest": _mard_image_manifest(),
        "m7_content_snapshot": _adoption_content_snapshot(
            "m7-preserved-business-v1", "2" * 64
        ),
        "m8_swatch_content_snapshot": _adoption_content_snapshot(
            "m8-swatch-content-v1", "a" * 64
        ),
        "m9_table_content_snapshot": _adoption_content_snapshot(
            "m9-table-business-v1", "3" * 64
        ),
    }


def _bound_backup(
    backup_record: dict[str, object],
    *,
    backup_record_sha256: str = "a" * 64,
    restore_record: dict[str, object] | None = None,
    restore_record_sha256: str = "d" * 64,
) -> upgrade._BoundBackupRecords:
    return upgrade._BoundBackupRecords(
        backup_record=backup_record,
        backup_record_sha256=backup_record_sha256,
        restore_record=restore_record or {},
        restore_record_sha256=restore_record_sha256,
    )


def _patch_verified_backup_payload(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    """语义测试绕过文件 owner；稳定 reader 本身由独立回归覆盖。"""

    def load_record(path: Path, description: str) -> tuple[dict[str, object], str]:
        if description == "verified backup record":
            return payload, "a" * 64
        try:
            content = path.read_bytes()
            loaded = json.loads(content)
        except (OSError, json.JSONDecodeError) as error:
            raise upgrade.GateAUpgradeError(
                f"Gate A {description} is unavailable"
            ) from error
        return loaded, upgrade.hashlib.sha256(content).hexdigest()

    monkeypatch.setattr(upgrade, "_load_bound_json_with_sha256", load_record)
    monkeypatch.setattr(
        upgrade.backup,
        "_validate_loaded_backup_record",
        lambda **kwargs: (
            kwargs["payload"],
            Path("/db.sql"),
            Path("/images.tar"),
        ),
    )


def _allow_local_bound_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产必须 root:root；测试只替换临时文件的 owner。"""

    real_validator = upgrade._require_adoption_record_metadata

    def local_metadata(metadata: os.stat_result, description: str) -> None:
        adjusted = SimpleNamespace(
            **{
                field: getattr(metadata, field)
                for field in (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_nlink",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
            },
            st_uid=0,
            st_gid=0,
        )
        real_validator(adjusted, description)

    monkeypatch.setattr(upgrade, "_require_adoption_record_metadata", local_metadata)


def _adoption_context() -> dict[str, object]:
    return {
        "stage_record_sha256": "4" * 64,
        "activation_record_sha256": "5" * 64,
        "lineage_source_candidate_sha": LINEAGE_SHA,
        "lineage_source_image_id": "sha256:" + "6" * 64,
        "acceptance_retirement_record_sha256": RETIREMENT_SHA,
        "backup_record_sha256": "7" * 64,
        "restore_record_sha256": "8" * 64,
        "predecessor_stage_record_sha256": "9" * 64,
        "predecessor_activation_record_sha256": "a" * 64,
        "predecessor_upgrade_record_sha256": "b" * 64,
        "predecessor_upgrade_evidence_sha256": "c" * 64,
        "predecessor_upgrade_plan_replay_record_sha256": "d" * 64,
    }


def _adoption_state() -> dict[str, object]:
    snapshot = _final_snapshot() | {
        "table_sessions": 4,
        "table_session_timers": 3,
        "table_occupancies": 0,
    }
    m7_content = _adoption_content_snapshot(
        "m7-preserved-business-v1", "2" * 64
    )
    m8_swatch_content = _adoption_content_snapshot(
        "m8-swatch-content-v1", "a" * 64
    )
    m9_content = _adoption_content_snapshot("m9-table-business-v1", "3" * 64)
    images = _manifest_summary_fixture(_mard_image_manifest())
    return {
        "source_database_snapshot": snapshot,
        "final_database_snapshot": snapshot,
        "source_m7_content_snapshot": m7_content,
        "final_m7_content_snapshot": m7_content,
        "source_m8_swatch_content_snapshot": m8_swatch_content,
        "final_m8_swatch_content_snapshot": m8_swatch_content,
        "source_m9_table_content_snapshot": m9_content,
        "final_m9_table_content_snapshot": m9_content,
        "source_image_manifest": images,
        "final_image_manifest": images,
        "table_reconcile": _empty_table_reconcile_result() | {"scanned": 4},
    }


def _replay_task_result(
    description: str,
    *,
    mard_preview: dict[str, object] | None = None,
    table_reconcile: dict[str, object] | None = None,
) -> dict[str, object]:
    if description == "recorded-upgrade-mard-preview":
        return mard_preview or _noop_mard_preview()
    if description == "recorded-upgrade-table-reconcile":
        return table_reconcile or _empty_table_reconcile_result()
    raise AssertionError(f"unexpected replay task: {description}")


def _stopped_replay_service_rows() -> list[dict[str, str]]:
    return [
        {
            "Service": service,
            "State": "running" if service in {"mysql", "redis"} else "exited",
            "Health": "healthy" if service in {"mysql", "redis"} else "",
        }
        for service in ("mysql", "redis", "app", "nginx", "table-sweeper")
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
        "table_reconcile": _empty_table_reconcile_result(),
        "table_sweep": _empty_table_sweep_result(),
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
        "table_reconcile": _empty_table_reconcile_result(),
        "table_sweep": _empty_table_sweep_result(),
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
            "target_version": 9,
    }
    assert not list(tmp_path.glob("*.json"))

    arguments = _common_arguments(tmp_path, apply=False)
    arguments["confirm_target_sha"] = TARGET_SHA
    with pytest.raises(upgrade.GateAUpgradeError, match="does not accept"):
        upgrade.upgrade_existing_database(**arguments)


@pytest.mark.parametrize(
    "pending_suffix",
    gatea.CANDIDATE_TRANSITION_PENDING_SUFFIXES,
)
def test_upgrade_rejects_unresolved_candidate_transition_before_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pending_suffix: str,
) -> None:
    _patch_plan(monkeypatch, tmp_path)
    (tmp_path / f"{TARGET_SHA}.{pending_suffix}").write_text(
        "{}\n", encoding="utf-8"
    )

    with pytest.raises(gatea.GateAError, match="unresolved pending journal"):
        upgrade.upgrade_existing_database(
            **_common_arguments(tmp_path, apply=False)
        )


@pytest.mark.parametrize("apply", (False, True), ids=("plan", "apply"))
def test_upgrade_rejects_acceptance_sidecar_before_plan_or_compose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    apply: bool,
) -> None:
    acceptance_record_dir = tmp_path / "acceptance"
    acceptance_record_dir.mkdir()
    (
        acceptance_record_dir
        / (
            f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{'b' * 40}"
            f"{gatea.M9_ACCEPTANCE_PENDING_SUFFIX}"
        )
    ).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: pytest.fail("acceptance guard must run before compose config"),
    )
    monkeypatch.setattr(
        upgrade,
        "_plan",
        lambda **kwargs: pytest.fail("acceptance guard must run before plan"),
    )
    arguments = _common_arguments(tmp_path, apply=apply)
    arguments["acceptance_record_dir"] = acceptance_record_dir

    with pytest.raises(gatea.GateAError, match="unresolved sidecar"):
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

    def load_backup(**kwargs: object) -> upgrade._BoundBackupRecords:
        nonlocal backup_loads
        backup_loads += 1
        return _bound_backup(_backup_record(7))

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
        if description in {"table-bootstrap", "table-bootstrap-replay"}:
            return {
                "status": "ok",
                "table_count": 30,
                "placeholder_qr_count": 0,
                "wechat_environment": "develop",
            }
        if description == "table-reconcile":
            return _empty_table_reconcile_result()
        if description == "table-sweep":
            return _empty_table_sweep_result()
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

    assert compose_commands == [
        ("stop", "--timeout", "30", "nginx", "table-sweeper", "app")
    ]
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
        "migrate-m9",
        "table-bootstrap",
        "table-bootstrap-replay",
        "table-reconcile",
        "table-sweep",
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
    assert success["table_reconcile"] == _empty_table_reconcile_result()
    assert success["table_sweep"] == _empty_table_sweep_result()
    assert evidence["status"] == "succeeded"
    assert evidence["table_reconcile"] == _empty_table_reconcile_result()
    assert evidence["table_sweep"] == _empty_table_sweep_result()
    assert [step["name"] for step in evidence["steps"]] == [
        "migrate-m3",
        "migrate-m4",
        "wallet-prepare",
        "migrate-m5",
        "migrate-m6",
        "migrate-m7",
        "migrate-m8",
        "mard-publish",
        "migrate-m9",
        "table-bootstrap",
        "table-reconcile",
        "table-sweep",
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
        if description in {"migrate-m8", "migrate-m9"}:
            current_version = int(description.removeprefix("migrate-m"))
            return {
                "aerich_versions": list(
                    APPROVED_MIGRATIONS[: current_version + 1]
                ),
                "applied": True,
                "migration": APPROVED_MIGRATIONS[current_version],
                "target_version": current_version,
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
        if description in {"table-bootstrap", "table-bootstrap-replay"}:
            return {
                "status": "ok",
                "table_count": 30,
                "placeholder_qr_count": 0,
                "wechat_environment": "develop",
            }
        if description == "table-reconcile":
            return _empty_table_reconcile_result()
        if description == "table-sweep":
            return _empty_table_sweep_result()
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

    assert compose_commands == [
        ("stop", "--timeout", "30", "nginx", "table-sweeper", "app")
    ]
    assert task_names == [
        "migrate-m8",
        "mard-preview",
        "mard-apply",
        "mard-replay-preview",
        "migrate-m9",
        "table-bootstrap",
        "table-bootstrap-replay",
        "table-reconcile",
        "table-sweep",
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
    assert success["table_reconcile"] == _empty_table_reconcile_result()
    assert success["table_sweep"] == _empty_table_sweep_result()
    assert evidence["source_version"] == 7
    assert evidence["source_aerich_versions"] == list(APPROVED_MIGRATIONS[:8])
    assert evidence["target_aerich_versions"] == list(APPROVED_MIGRATIONS)
    assert evidence["source_m7_content_snapshot"] == _m7_content_snapshot()
    assert evidence["final_m7_content_snapshot"] == _m7_content_snapshot()
    assert evidence["source_m7_mard_preflight"] == _m7_source_preflight()
    assert evidence["table_reconcile"] == _empty_table_reconcile_result()
    assert evidence["table_sweep"] == _empty_table_sweep_result()
    assert [step["name"] for step in evidence["steps"]] == [
        "migrate-m8",
        "mard-publish",
        "migrate-m9",
        "table-bootstrap",
        "table-reconcile",
        "table-sweep",
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
        "target_version": 9,
    }
    replay_record_path = gatea._upgrade_replay_marker(tmp_path, TARGET_SHA)
    replay_record = json.loads(replay_record_path.read_text(encoding="utf-8"))
    assert set(replay_record) == {
        "backup_id",
        "candidate_sha",
        "completed_at",
        "database_snapshot",
        "evidence_sha256",
        "image_id",
        "image_manifest",
        "manifest_sha256",
        "passed",
        "record_type",
        "result",
        "schema_version",
        "secret_values_recorded",
        "source_candidate_sha",
        "source_version",
        "table_reconcile",
        "upgrade_record_sha256",
    }
    assert replay_record["record_type"] == "gatea-m9-upgrade-plan-replay"
    assert replay_record["result"] == replay
    assert replay_record["database_snapshot"] == _final_snapshot()
    assert replay_record["table_reconcile"] == _empty_table_reconcile_result()
    assert replay_record["upgrade_record_sha256"] == upgrade._sha256(success_path)
    assert replay_record["evidence_sha256"] == success["evidence_sha256"]
    assert replay_record["secret_values_recorded"] is False
    assert task_names == [
        "migrate-m8",
        "mard-preview",
        "mard-apply",
        "mard-replay-preview",
        "migrate-m9",
        "table-bootstrap",
        "table-bootstrap-replay",
        "table-reconcile",
        "table-sweep",
    ]


def test_success_publication_cleanup_failure_preserves_evidence_and_replays(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_plan = upgrade._plan
    _patch_plan(monkeypatch, tmp_path, source_version=7)
    current_version = 7

    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess([], 0),
    )
    _patch_stopped_replay_services(monkeypatch)
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
        lambda **kwargs: _m7_source_preflight(),
    )

    def fake_task(**kwargs: object) -> dict[str, object]:
        nonlocal current_version
        description = str(kwargs["description"])
        if description in {"migrate-m8", "migrate-m9"}:
            current_version = int(description.removeprefix("migrate-m"))
            return {
                "aerich_versions": list(
                    APPROVED_MIGRATIONS[: current_version + 1]
                ),
                "applied": True,
                "migration": APPROVED_MIGRATIONS[current_version],
                "target_version": current_version,
            }
        if description in {"mard-preview", "mard-replay-preview"}:
            return _noop_mard_preview()
        if description == "mard-apply":
            return _noop_mard_preview() | {"mode": "apply"}
        if description in {"table-bootstrap", "table-bootstrap-replay"}:
            return {
                "status": "ok",
                "table_count": 30,
                "placeholder_qr_count": 0,
                "wechat_environment": "develop",
            }
        if description in {"table-reconcile", "recorded-upgrade-table-reconcile"}:
            return _empty_table_reconcile_result()
        if description == "table-sweep":
            return _empty_table_sweep_result()
        if description == "recorded-upgrade-mard-preview":
            return _noop_mard_preview()
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

    success_path = gatea._upgrade_marker(tmp_path, TARGET_SHA)
    evidence_path = tmp_path / (
        f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    success_temp_prefix = f".{success_path.name}.tmp-"
    real_unlink_and_fsync = upgrade.backup._unlink_and_fsync

    def fail_after_success_temp_cleanup(path: Path) -> None:
        real_unlink_and_fsync(path)
        if path.name.startswith(success_temp_prefix):
            raise OSError("simulated post-publication cleanup fsync failure")

    monkeypatch.setattr(
        upgrade.backup,
        "_unlink_and_fsync",
        fail_after_success_temp_cleanup,
    )

    with pytest.raises(OSError, match="post-publication cleanup fsync"):
        upgrade.upgrade_existing_database(
            **_common_arguments(tmp_path, apply=True, source_version=7)
        )

    success = json.loads(success_path.read_text(encoding="utf-8"))
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    assert evidence["status"] == "succeeded"
    assert evidence["current_stage"] == "completed"
    assert "error_type" not in evidence
    assert "business_entry_stopped" not in evidence
    assert success["evidence_sha256"] == upgrade._sha256(evidence_path)

    # 恢复真实 plan 路径，证明磁盘上的不可变 success/evidence 绑定可以被
    # 完整重验，而不是只依赖本次调用的内存对象。
    monkeypatch.setattr(upgrade.backup, "_unlink_and_fsync", real_unlink_and_fsync)
    monkeypatch.setattr(upgrade, "_plan", original_plan)
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda values: "sha256:target-image",
    )
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)

    replay = upgrade.upgrade_existing_database(
        **_common_arguments(tmp_path, apply=False, source_version=7)
    )

    assert replay["already_current"] is True
    assert replay["mode"] == "plan-replay"
    assert evidence_path.read_bytes() == evidence_bytes
    assert gatea._upgrade_replay_marker(tmp_path, TARGET_SHA).is_file()


@pytest.mark.parametrize(
    ("invalid_task", "invalid_result", "message"),
    (
        (
            "table-reconcile",
            _empty_table_reconcile_result() | {"scanned": 1},
            "empty table reconciliation",
        ),
        (
            "table-sweep",
            {"status": "ok", "closed": 1},
            "empty table sweep",
        ),
    ),
)
def test_invalid_table_consistency_result_preserves_failure_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    invalid_task: str,
    invalid_result: dict[str, object],
    message: str,
) -> None:
    _patch_plan(monkeypatch, tmp_path, source_version=7)
    current_version = 7
    task_names: list[str] = []

    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess([], 0),
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: _stopped_replay_service_rows(),
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
        lambda **kwargs: _m7_source_preflight(),
    )
    monkeypatch.setattr(
        upgrade,
        "_read_final_snapshot",
        lambda **kwargs: _final_snapshot(),
    )

    def fake_task(**kwargs: object) -> dict[str, object]:
        nonlocal current_version
        description = str(kwargs["description"])
        task_names.append(description)
        if description in {"migrate-m8", "migrate-m9"}:
            current_version = int(description.removeprefix("migrate-m"))
            return {
                "aerich_versions": list(
                    APPROVED_MIGRATIONS[: current_version + 1]
                ),
                "applied": True,
                "migration": APPROVED_MIGRATIONS[current_version],
                "target_version": current_version,
            }
        if description == "mard-apply":
            return _noop_mard_preview() | {"mode": "apply"}
        if description in {"mard-preview", "mard-replay-preview"}:
            return _noop_mard_preview()
        if description in {"table-bootstrap", "table-bootstrap-replay"}:
            return {
                "status": "ok",
                "table_count": 30,
                "placeholder_qr_count": 0,
                "wechat_environment": "develop",
            }
        if description == invalid_task:
            return invalid_result
        if description == "table-reconcile":
            return _empty_table_reconcile_result()
        if description == "table-sweep":
            return _empty_table_sweep_result()
        raise AssertionError(f"unexpected task: {description}")

    monkeypatch.setattr(upgrade, "_run_task", fake_task)
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: _source_status(7)
        | {"aerich_versions": list(APPROVED_MIGRATIONS[: current_version + 1])},
    )

    with pytest.raises(upgrade.GateAUpgradeError, match=message):
        upgrade.upgrade_existing_database(
            **_common_arguments(tmp_path, apply=True, source_version=7)
        )

    evidence_path = tmp_path / (
        f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "failed"
    assert evidence["business_entry_stopped"] is True
    assert evidence["current_stage"] == invalid_task
    assert evidence["error_type"] == "GateAUpgradeError"
    assert not gatea._upgrade_marker(tmp_path, TARGET_SHA).exists()
    assert task_names[-1] == invalid_task
    if invalid_task == "table-sweep":
        assert evidence["table_reconcile"] == _empty_table_reconcile_result()


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
    assert compose_commands == [
        ("stop", "--timeout", "30", "nginx", "table-sweeper", "app")
    ]
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
    assert compose_commands == [
        ("stop", "--timeout", "30", "nginx", "table-sweeper", "app")
    ]


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
    assert compose_commands == [
        ("stop", "--timeout", "30", "nginx", "table-sweeper", "app")
    ]


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


def test_upgrade_exclusive_writer_never_overwrites_or_leaves_tempfiles(
    tmp_path: Path,
) -> None:
    path = tmp_path / "upgrade.json"
    upgrade._write_json_exclusive(path, {"owner": "first"})

    with pytest.raises(upgrade.GateAUpgradeError, match="already reserved"):
        upgrade._write_json_exclusive(path, {"owner": "second"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"owner": "first"}
    assert list(tmp_path.glob(".upgrade.json.tmp-*")) == []


def test_upgrade_exclusive_writer_does_not_publish_partial_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "upgrade.json"

    def fail_after_partial_write(
        payload: object,
        stream: object,
        **kwargs: object,
    ) -> None:
        del payload, kwargs
        stream.write('{"partial":')
        raise OSError("simulated ENOSPC")

    monkeypatch.setattr(upgrade.backup.json, "dump", fail_after_partial_write)

    with pytest.raises(OSError, match="ENOSPC"):
        upgrade._write_json_exclusive(path, {"owner": "first"})

    assert not path.exists()
    assert list(tmp_path.glob(".upgrade.json.tmp-*")) == []


def test_upgrade_mutable_evidence_keeps_last_complete_record_on_enospc(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "upgrade.evidence.json"
    previous = {"current_stage": "validated", "steps": []}
    evidence_path.write_text(json.dumps(previous) + "\n", encoding="utf-8")
    evidence: dict[str, object] = {"current_stage": "validated", "steps": []}

    def fail_after_partial_write(
        payload: object,
        stream: object,
        **kwargs: object,
    ) -> None:
        del payload, kwargs
        stream.write('{"current_stage":"partial"')
        raise OSError("simulated ENOSPC")

    monkeypatch.setattr(upgrade.backup.json, "dump", fail_after_partial_write)

    with pytest.raises(OSError, match="ENOSPC"):
        upgrade._record_step(
            evidence_path=evidence_path,
            evidence=evidence,
            name="migrate-m8",
            started_at="2026-09-11T00:00:00+00:00",
            result={"applied": True},
            database_snapshot={"aerich_versions": ["m8"]},
        )

    assert json.loads(evidence_path.read_text(encoding="utf-8")) == previous
    assert list(tmp_path.glob(".upgrade.evidence.json.tmp-*")) == []


def test_m7_replay_record_must_match_explicit_source_version_and_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_replay_fixture(tmp_path)
    task_names: list[str] = []
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
        lambda **kwargs: task_names.append(str(kwargs["description"]))
        or _replay_task_result(str(kwargs["description"])),
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
    assert task_names == [
        "recorded-upgrade-mard-preview",
        "recorded-upgrade-table-reconcile",
    ]
    assert not any("sweep" in name for name in task_names)

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
    monkeypatch.setattr(
        upgrade,
        "_run_task",
        lambda **kwargs: _replay_task_result(str(kwargs["description"])),
    )

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
    ("field", "value", "message"),
    (
        ("table_reconcile", None, "table consistency evidence"),
        (
            "table_reconcile",
            _empty_table_reconcile_result() | {"violations": False},
            "empty table reconciliation",
        ),
        ("table_sweep", None, "table consistency evidence"),
        ("table_sweep", {"status": "ok", "closed": 1}, "empty table sweep"),
    ),
)
def test_replay_rejects_missing_or_invalid_recorded_table_consistency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    success_path, _, success = _write_replay_fixture(tmp_path)
    if value is None:
        success.pop(field)
    else:
        success[field] = value
    success_path.write_text(json.dumps(success), encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:target")
    _patch_stopped_replay_services(monkeypatch)
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)

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


def test_replay_rejects_table_consistency_evidence_different_from_success_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    success_path, evidence_path, success = _write_replay_fixture(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["table_sweep"] = {"status": "ok", "closed": 1}
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    success["evidence_sha256"] = upgrade._sha256(evidence_path)
    success_path.write_text(json.dumps(success), encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:target")
    _patch_stopped_replay_services(monkeypatch)
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)

    with pytest.raises(upgrade.GateAUpgradeError, match="upgrade evidence is invalid"):
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
        ("evidence_path", "requested replay"),
        ("evidence_digest", "evidence digest"),
        ("database", "database"),
        ("images", "image volume"),
        ("m7_content", "preserved M7 content"),
        ("mard", "exact no-op"),
        ("reconcile", "empty table reconciliation"),
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
    table_reconcile = _empty_table_reconcile_result()

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
    elif scenario == "reconcile":
        table_reconcile = table_reconcile | {"scanned": 1}

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
        lambda **kwargs: _replay_task_result(
            str(kwargs["description"]),
            mard_preview=mard_preview,
            table_reconcile=table_reconcile,
        ),
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
        ("table-sweeper-running", "service table-sweeper must not be running"),
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
    elif scenario == "table-sweeper-running":
        rows[-1] = {
            "Service": "table-sweeper",
            "State": "running",
            "Health": "healthy",
        }

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
    _patch_verified_backup_payload(monkeypatch, payload)
    monkeypatch.setattr(upgrade.backup, "_sha256", lambda path: "a" * 64)

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


def test_verified_backup_rejects_pending_before_loading_backup_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root = tmp_path / "backups"
    backup_records = tmp_path / "backup-records"
    restore_records = tmp_path / "restore-records"
    backup_records.mkdir()
    pending = backup_records / f".{BACKUP_ID}.pending.json"
    pending.write_text("{}\n", encoding="utf-8")
    loaded = False

    monkeypatch.setattr(
        upgrade.backup,
        "_validate_backup_directories",
        lambda **kwargs: None,
    )

    def unexpected_load(*args: object, **kwargs: object) -> object:
        nonlocal loaded
        loaded = True
        raise AssertionError("pending backup must fail before record loading")

    monkeypatch.setattr(upgrade, "_load_bound_json_with_sha256", unexpected_load)

    with pytest.raises(
        upgrade.GateAUpgradeError,
        match="pending journal requires manual review",
    ):
        upgrade._load_verified_backup(
            values=_values(backup_root),
            backup_id=BACKUP_ID,
            source_candidate_sha=SOURCE_SHA,
            backup_root=backup_root,
            backup_record_dir=backup_records,
            restore_record_dir=restore_records,
        )

    assert loaded is False


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
        "backup_record_sha256": "a" * 64,
        "mysql_artifact_sha256": "b" * 64,
        "image_artifact_sha256": "c" * 64,
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
    _patch_verified_backup_payload(monkeypatch, payload)
    monkeypatch.setattr(
        upgrade.backup,
        "_sha256",
        lambda path: {
            f"{BACKUP_ID}.json": "a" * 64,
            "db.sql": "b" * 64,
            "images.tar": "c" * 64,
        }[path.name],
    )

    assert upgrade._load_verified_backup(
        values=_values(backup_root),
        backup_id=BACKUP_ID,
        source_candidate_sha=SOURCE_SHA,
        backup_root=backup_root,
        backup_record_dir=backup_records,
        restore_record_dir=restore_records,
    ).backup_record == payload

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


def test_m9_adoption_backup_requires_exact_swatch_restore_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root = tmp_path / "backups"
    backup_records = tmp_path / "backup-records"
    restore_records = tmp_path / "restore-records"
    restore_records.mkdir()
    completed = datetime.now(timezone.utc) - timedelta(minutes=10)
    backup_payload = {
        **_adoption_backup_record(),
        "completed_at": completed.isoformat(),
        "consistency": "nginx-and-app-stopped",
        "application_restarted": True,
        "passed": True,
    }
    restore_payload: dict[str, object] = {
        "schema_version": 1,
        "backup_id": BACKUP_ID,
        "candidate_sha": SOURCE_SHA,
        "restore_project": upgrade.backup.restore_project(BACKUP_ID),
        "completed_at": (completed + timedelta(minutes=1)).isoformat(),
        "host_ports_published": False,
        "backup_record_sha256": "a" * 64,
        "mysql_artifact_sha256": "b" * 64,
        "image_artifact_sha256": "c" * 64,
        "m7_content_matches": True,
        "m7_content_snapshot": backup_payload["m7_content_snapshot"],
        "m8_swatch_content_matches": True,
        "m8_swatch_content_snapshot": backup_payload[
            "m8_swatch_content_snapshot"
        ],
        "m9_table_content_matches": True,
        "m9_table_content_snapshot": backup_payload[
            "m9_table_content_snapshot"
        ],
    }
    restore_payload.update({field: True for field in upgrade.RESTORE_TRUE_FIELDS})
    restore_path = restore_records / f"{BACKUP_ID}.json"
    restore_path.write_text(json.dumps(restore_payload), encoding="utf-8")
    monkeypatch.setattr(
        upgrade.backup, "_validate_backup_directories", lambda **kwargs: None
    )
    _patch_verified_backup_payload(monkeypatch, backup_payload)
    monkeypatch.setattr(
        upgrade.backup,
        "_sha256",
        lambda path: {
            f"{BACKUP_ID}.json": "a" * 64,
            "db.sql": "b" * 64,
            "images.tar": "c" * 64,
        }[path.name],
    )

    assert upgrade._load_verified_backup(
        values=_values(backup_root),
        backup_id=BACKUP_ID,
        source_candidate_sha=SOURCE_SHA,
        backup_root=backup_root,
        backup_record_dir=backup_records,
        restore_record_dir=restore_records,
        require_m8_swatch_content_snapshot=True,
    ).backup_record == backup_payload

    missing_backup = dict(backup_payload)
    missing_backup.pop("m8_swatch_content_snapshot")
    _patch_verified_backup_payload(monkeypatch, missing_backup)
    with pytest.raises(upgrade.GateAUpgradeError, match="lacks M8 swatch"):
        upgrade._load_verified_backup(
            values=_values(backup_root),
            backup_id=BACKUP_ID,
            source_candidate_sha=SOURCE_SHA,
            backup_root=backup_root,
            backup_record_dir=backup_records,
            restore_record_dir=restore_records,
            require_m8_swatch_content_snapshot=True,
        )

    _patch_verified_backup_payload(monkeypatch, backup_payload)
    restore_payload.pop("m8_swatch_content_snapshot")
    restore_path.write_text(json.dumps(restore_payload), encoding="utf-8")
    with pytest.raises(upgrade.GateAUpgradeError, match="restore PASS record"):
        upgrade._load_verified_backup(
            values=_values(backup_root),
            backup_id=BACKUP_ID,
            source_candidate_sha=SOURCE_SHA,
            backup_root=backup_root,
            backup_record_dir=backup_records,
            restore_record_dir=restore_records,
            require_m8_swatch_content_snapshot=True,
        )

    restore_payload["m8_swatch_content_snapshot"] = _adoption_content_snapshot(
        "m8-swatch-content-v1", "f" * 64
    )
    restore_path.write_text(json.dumps(restore_payload), encoding="utf-8")
    with pytest.raises(upgrade.GateAUpgradeError, match="restore PASS record"):
        upgrade._load_verified_backup(
            values=_values(backup_root),
            backup_id=BACKUP_ID,
            source_candidate_sha=SOURCE_SHA,
            backup_root=backup_root,
            backup_record_dir=backup_records,
            restore_record_dir=restore_records,
            require_m8_swatch_content_snapshot=True,
        )


def _write_verified_m9_backup_pair(
    tmp_path: Path,
    *,
    completed_at: datetime | None = None,
) -> tuple[
    Path,
    Path,
    Path,
    dict[str, object],
    dict[str, object],
    bytes,
    bytes,
]:
    backup_root = tmp_path / "backups"
    backup_records = tmp_path / "backup-records"
    restore_records = tmp_path / "restore-records"
    database_path, image_path = upgrade.backup._backup_paths(
        backup_root,
        BACKUP_ID,
    )
    for directory in (
        database_path.parent,
        image_path.parent,
        backup_records,
        restore_records,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    database_path.write_bytes(b"verified mysql backup\n")
    image_path.write_bytes(b"verified image backup\n")
    completed_at = completed_at or (
        datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    backup_payload = {
        **_adoption_backup_record(),
        "schema_version": 1,
        "backup_id": BACKUP_ID,
        "completed_at": completed_at.isoformat(),
        "consistency": "nginx-and-app-stopped",
        "application_restarted": True,
        "passed": True,
        "artifacts": {
            "mysql": {
                "path": str(database_path),
                "bytes": database_path.stat().st_size,
                "sha256": upgrade.backup._sha256(database_path),
            },
            "images": {
                "path": str(image_path),
                "bytes": image_path.stat().st_size,
                "sha256": upgrade.backup._sha256(image_path),
            },
        },
    }
    backup_path = backup_records / f"{BACKUP_ID}.json"
    backup_bytes = (
        json.dumps(backup_payload, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()
    backup_path.write_bytes(backup_bytes)
    backup_path.chmod(0o644)
    restore_payload: dict[str, object] = {
        "schema_version": 1,
        "backup_id": BACKUP_ID,
        "candidate_sha": SOURCE_SHA,
        "restore_project": upgrade.backup.restore_project(BACKUP_ID),
        "completed_at": (completed_at + timedelta(minutes=1)).isoformat(),
        "host_ports_published": False,
        "backup_record_sha256": upgrade.hashlib.sha256(backup_bytes).hexdigest(),
        "mysql_artifact_sha256": upgrade.backup._sha256(database_path),
        "image_artifact_sha256": upgrade.backup._sha256(image_path),
        "m7_content_matches": True,
        "m7_content_snapshot": backup_payload["m7_content_snapshot"],
        "m8_swatch_content_matches": True,
        "m8_swatch_content_snapshot": backup_payload[
            "m8_swatch_content_snapshot"
        ],
        "m9_table_content_matches": True,
        "m9_table_content_snapshot": backup_payload[
            "m9_table_content_snapshot"
        ],
    }
    restore_payload.update({field: True for field in upgrade.RESTORE_TRUE_FIELDS})
    restore_path = restore_records / f"{BACKUP_ID}.json"
    restore_bytes = (
        json.dumps(restore_payload, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()
    restore_path.write_bytes(restore_bytes)
    restore_path.chmod(0o644)
    return (
        backup_root,
        backup_path,
        restore_path,
        backup_payload,
        restore_payload,
        backup_bytes,
        restore_bytes,
    )


def test_verified_backup_digests_are_from_the_semantically_validated_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (
        backup_root,
        backup_path,
        restore_path,
        backup_payload,
        restore_payload,
        backup_bytes,
        restore_bytes,
    ) = _write_verified_m9_backup_pair(tmp_path)
    _allow_local_bound_records(monkeypatch)
    monkeypatch.setattr(
        upgrade.backup,
        "_validate_backup_directories",
        lambda **kwargs: None,
    )
    real_backup_validator = upgrade.backup._validate_loaded_backup_record
    real_restore_validator = upgrade._validate_restore_record

    def replace_backup_after_read(
        **kwargs: object,
    ) -> tuple[dict[str, object], Path, Path]:
        replacement = backup_path.with_name("replacement-backup.json")
        replacement.write_text('{"replacement":true}\n', encoding="utf-8")
        replacement.chmod(0o644)
        replacement.replace(backup_path)
        return real_backup_validator(**kwargs)

    def replace_restore_after_read(**kwargs: object) -> dict[str, object]:
        replacement = restore_path.with_name("replacement-restore.json")
        replacement.write_text('{"replacement":true}\n', encoding="utf-8")
        replacement.chmod(0o644)
        replacement.replace(restore_path)
        return real_restore_validator(**kwargs)

    monkeypatch.setattr(
        upgrade.backup,
        "_validate_loaded_backup_record",
        replace_backup_after_read,
    )
    monkeypatch.setattr(
        upgrade,
        "_validate_restore_record",
        replace_restore_after_read,
    )

    verified = upgrade._load_verified_backup(
        values=_values(backup_root),
        backup_id=BACKUP_ID,
        source_candidate_sha=SOURCE_SHA,
        backup_root=backup_root,
        backup_record_dir=backup_path.parent,
        restore_record_dir=restore_path.parent,
        require_m8_swatch_content_snapshot=True,
    )

    assert verified.backup_record == backup_payload
    assert verified.restore_record == restore_payload
    assert verified.backup_record_sha256 == upgrade.hashlib.sha256(
        backup_bytes
    ).hexdigest()
    assert verified.restore_record_sha256 == upgrade.hashlib.sha256(
        restore_bytes
    ).hexdigest()
    assert backup_path.read_bytes() != backup_bytes
    assert restore_path.read_bytes() != restore_bytes


@pytest.mark.parametrize(
    "description",
    ("verified backup record", "restore PASS record"),
)
def test_bound_backup_reader_rejects_path_swap_during_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    description: str,
) -> None:
    record_path = tmp_path / "record.json"
    replacement_path = tmp_path / "replacement.json"
    displaced_path = tmp_path / "displaced.json"
    record_path.write_text('{"schema_version":1}\n', encoding="utf-8")
    replacement_path.write_text('{"schema_version":1}\n', encoding="utf-8")
    record_path.chmod(0o644)
    replacement_path.chmod(0o644)
    _allow_local_bound_records(monkeypatch)
    real_open = upgrade.os.open
    swapped = False

    def swapping_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        if Path(path) == record_path and not swapped:
            swapped = True
            assert flags & os.O_NOFOLLOW
            record_path.replace(displaced_path)
            replacement_path.replace(record_path)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(upgrade.os, "open", swapping_open)

    with pytest.raises(upgrade.GateAUpgradeError, match="changed during validation"):
        upgrade._load_bound_json_with_sha256(record_path, description)


@pytest.mark.parametrize(
    "description",
    ("verified backup record", "restore PASS record"),
)
def test_bound_backup_reader_rejects_fd_metadata_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    description: str,
) -> None:
    record_path = tmp_path / "record.json"
    record_path.write_text('{"schema_version":1}\n', encoding="utf-8")
    record_path.chmod(0o644)
    _allow_local_bound_records(monkeypatch)
    real_fstat = upgrade.os.fstat
    fstat_calls = 0

    def drifting_fstat(descriptor: int) -> object:
        nonlocal fstat_calls
        metadata = real_fstat(descriptor)
        fstat_calls += 1
        if fstat_calls == 1:
            return metadata
        return SimpleNamespace(
            st_dev=metadata.st_dev,
            st_ino=metadata.st_ino,
            st_mode=metadata.st_mode,
            st_nlink=metadata.st_nlink,
            st_uid=metadata.st_uid,
            st_gid=metadata.st_gid,
            st_size=metadata.st_size,
            st_mtime_ns=metadata.st_mtime_ns + 1,
            st_ctime_ns=metadata.st_ctime_ns,
        )

    monkeypatch.setattr(upgrade.os, "fstat", drifting_fstat)

    with pytest.raises(upgrade.GateAUpgradeError, match="changed during validation"):
        upgrade._load_bound_json_with_sha256(record_path, description)


@pytest.mark.parametrize(
    ("description", "mutation"),
    (
        ("verified backup record", "duplicate-key"),
        ("verified backup record", "symlink"),
        ("verified backup record", "hardlink"),
        ("restore PASS record", "duplicate-key"),
        ("restore PASS record", "symlink"),
        ("restore PASS record", "hardlink"),
    ),
)
def test_bound_backup_reader_rejects_ambiguous_or_aliased_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    description: str,
    mutation: str,
) -> None:
    record_path = tmp_path / "record.json"
    target_path = tmp_path / "target.json"
    alias_path = tmp_path / "alias.json"
    if mutation == "duplicate-key":
        record_path.write_text(
            '{"schema_version":1,"schema_version":1}\n',
            encoding="utf-8",
        )
    elif mutation == "symlink":
        target_path.write_text('{"schema_version":1}\n', encoding="utf-8")
        record_path.symlink_to(target_path)
    else:
        record_path.write_text('{"schema_version":1}\n', encoding="utf-8")
        alias_path.hardlink_to(record_path)
    _allow_local_bound_records(monkeypatch)

    with pytest.raises(
        upgrade.GateAUpgradeError,
        match="unsafe metadata|unavailable",
    ):
        upgrade._load_bound_json_with_sha256(record_path, description)


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
        ("store_tables", 29, "M9 invariant"),
        ("invalid_table_numbers", 1, "M9 invariant"),
        ("invalid_table_display_names", 1, "M9 invariant"),
        ("invalid_table_qr_token_lengths", 1, "M9 invariant"),
        ("invalid_table_qr_token_characters", 1, "M9 invariant"),
        ("invalid_store_tables", 1, "M9 invariant"),
        ("distinct_table_qr_tokens", 29, "M9 invariant"),
        ("table_sessions", False, "M9 invariant"),
        ("table_session_timers", "0", "M9 invariant"),
        ("table_occupancies", 0.0, "M9 invariant"),
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


def test_empty_table_reconcile_requires_exact_integer_zero_contract() -> None:
    valid = _empty_table_reconcile_result()
    upgrade._validate_empty_table_reconcile_result(valid)

    invalid_results = [
        valid | {"scanned": 1},
        valid | {"violations": False},
        valid | {"open_sessions": "0"},
        {key: value for key, value in valid.items() if key != "occupancies"},
        valid | {"unexpected": 0},
    ]
    for result in invalid_results:
        with pytest.raises(
            upgrade.GateAUpgradeError,
            match="empty table reconciliation",
        ):
            upgrade._validate_empty_table_reconcile_result(result)


def test_empty_table_sweep_requires_exact_integer_zero_contract() -> None:
    valid = _empty_table_sweep_result()
    upgrade._validate_empty_table_sweep_result(valid)

    invalid_results = [
        {"status": "ok", "closed": 1},
        {"status": "ok", "closed": False},
        {"status": "ok", "closed": "0"},
        {"status": "failed", "closed": 0},
        {"status": "ok"},
        valid | {"unexpected": 0},
    ]
    for result in invalid_results:
        with pytest.raises(
            upgrade.GateAUpgradeError,
            match="empty table sweep",
        ):
            upgrade._validate_empty_table_sweep_result(result)


def test_final_database_status_fixes_utf8mb4_for_table_display_names() -> None:
    command = upgrade.FINAL_DATABASE_STATUS_COMMAND

    assert "mysql --default-character-set=utf8mb4" in command
    assert command.count("CONVERT(0xE58FB7E6A18C USING utf8mb4)") == 2
    assert "'invalid_table_numbers'" in command
    assert "'invalid_table_display_names'" in command
    assert "'invalid_table_qr_token_lengths'" in command
    assert "'invalid_table_qr_token_characters'" in command

    with pytest.raises(
        upgrade.GateAUpgradeError,
        match=r"invalid_table_display_names expected=0 actual=30",
    ):
        upgrade._validate_final_snapshot(
            _source_backup_snapshot(),
            _final_snapshot() | {"invalid_table_display_names": 30},
        )


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
                    '"jwt_algorithm":"HS256",'
                    '"table_session_claims_enabled":true,"validated":true}'
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

    assert tuple(APPROVED_MIGRATIONS) == gatea.APPROVED_TARGET_M9_CHAIN
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


def _patch_m9_adoption_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    state: dict[str, object] | None = None,
) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        gatea, "_validated_inputs", lambda **kwargs: _values(tmp_path / "backups")
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea, "validate_app_image", lambda values: "sha256:" + "0" * 64
    )
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {
                "Service": service,
                "State": "running",
                "Health": "healthy",
            }
            for service in kwargs["services"]
        ],
    )
    monkeypatch.setattr(
        upgrade,
        "_plan_m9_adoption",
        lambda **kwargs: (
            TARGET_SHA,
            "sha256:" + "0" * 64,
            _adoption_backup_record(),
            _adoption_context(),
        ),
    )
    monkeypatch.setattr(
        upgrade,
        "_read_m9_adoption_state",
        lambda **kwargs: state or _adoption_state(),
    )
    monkeypatch.setattr(
        upgrade,
        "_run_runtime_preflight",
        lambda **kwargs: {
            "app_env": "production",
            "db_engine": "mysql",
            "jwt_algorithm": "HS256",
            "table_session_claims_enabled": True,
            "validated": True,
        },
    )
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess(args=[], returncode=0),
    )
    return commands


def _m9_adoption_arguments(tmp_path: Path, *, apply: bool) -> dict[str, object]:
    return {
        **_common_arguments(tmp_path, apply=apply, source_version=9),
        "lineage_source_candidate_sha": LINEAGE_SHA,
        "acceptance_retirement_record_sha256": RETIREMENT_SHA,
        "confirm_lineage_source_sha": LINEAGE_SHA if apply else None,
        "confirm_acceptance_retirement_record_sha256": (
            RETIREMENT_SHA if apply else None
        ),
    }


def _write_succeeded_adoption_evidence(
    tmp_path: Path,
    *,
    context: dict[str, object] | None = None,
    started_at: str = "2026-09-11T12:00:00+00:00",
    completed_at: str = "2026-09-11T12:01:00+00:00",
) -> Path:
    evidence_path = (
        tmp_path / f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    evidence = {
        "schema_version": 2,
        "transition_kind": upgrade.M9_ADOPTION_TRANSITION_KIND,
        "record_type": "existing-database-upgrade-evidence",
        "status": "succeeded",
        "current_stage": "completed",
        "candidate_sha": TARGET_SHA,
        "image_id": "sha256:" + "0" * 64,
        "source_candidate_sha": SOURCE_SHA,
        "source_image_id": _adoption_backup_record()["image_id"],
        "source_version": 9,
        "target_version": 9,
        "source_aerich_versions": list(APPROVED_MIGRATIONS),
        "target_aerich_versions": list(APPROVED_MIGRATIONS),
        "backup_id": BACKUP_ID,
        "manifest_sha256": MANIFEST_SHA,
        "runtime_preflight": {
            "app_env": "production",
            "db_engine": "mysql",
            "jwt_algorithm": "HS256",
            "table_session_claims_enabled": True,
            "validated": True,
        },
        "started_at": started_at,
        "completed_at": completed_at,
        "database_changes_applied": False,
        "migrations_applied": [],
        "steps": [],
        **(context or _adoption_context()),
        **_adoption_state(),
        "stopped_source_verified": True,
    }
    assert set(evidence) == gatea.M9_ADOPTION_EVIDENCE_RECORD_KEYS
    upgrade._write_json_exclusive(evidence_path, evidence)
    return evidence_path


def _patch_stopped_adoption_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    state: dict[str, object] | None = None,
) -> list[tuple[str, ...]]:
    commands = _patch_m9_adoption_entry(
        monkeypatch,
        tmp_path,
        state=state,
    )
    monkeypatch.setattr(
        upgrade, "_require_adoption_record_metadata", lambda *args: None
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {
                "Service": service,
                "State": (
                    "running" if service in {"mysql", "redis"} else "exited"
                ),
                "Health": (
                    "healthy" if service in {"mysql", "redis"} else ""
                ),
            }
            for service in kwargs["services"]
        ],
    )
    return commands


def test_m9_adoption_plan_is_read_only_and_preserves_closed_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands = _patch_m9_adoption_entry(monkeypatch, tmp_path)

    result = upgrade.upgrade_existing_database(
        **_m9_adoption_arguments(tmp_path, apply=False)
    )

    assert result == {
        "already_current": False,
        "backup_id": BACKUP_ID,
        "candidate_sha": TARGET_SHA,
        "database_changes_applied": False,
        "manifest_sha256": MANIFEST_SHA,
        "migrations_applied": [],
        "mode": "plan",
        "source_aerich_versions": list(APPROVED_MIGRATIONS),
        "source_version": 9,
        "target_aerich_versions": list(APPROVED_MIGRATIONS),
        "target_version": 9,
        "transition_kind": upgrade.M9_ADOPTION_TRANSITION_KIND,
        "restore_verified": True,
        "source_candidate_sha": SOURCE_SHA,
        "lineage_source_candidate_sha": LINEAGE_SHA,
        "lineage_source_image_id": "sha256:" + "6" * 64,
        "acceptance_retirement_record_sha256": RETIREMENT_SHA,
        "table_reconcile": _empty_table_reconcile_result() | {"scanned": 4},
    }
    assert commands == []
    assert not list(tmp_path.glob("*.json"))


def test_m9_adoption_apply_writes_schema2_without_database_tasks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands = _patch_m9_adoption_entry(monkeypatch, tmp_path)
    compose_calls = 0

    def compose_ps(**kwargs: object) -> list[dict[str, str]]:
        nonlocal compose_calls
        compose_calls += 1
        stopped = compose_calls > 1
        return [
            {
                "Service": service,
                "State": (
                    "exited"
                    if stopped and service in {"app", "table-sweeper", "nginx"}
                    else "running"
                ),
                "Health": (
                    "healthy" if service in {"mysql", "redis"} or not stopped else ""
                ),
            }
            for service in kwargs["services"]
        ]

    monkeypatch.setattr(gatea, "_compose_ps", compose_ps)

    result = upgrade.upgrade_existing_database(
        **_m9_adoption_arguments(tmp_path, apply=True)
    )

    assert commands == [
        ("stop", "--timeout", "30", "nginx", "table-sweeper", "app")
    ]
    assert result["database_changes_applied"] is False
    assert result["migrations_applied"] == []
    success = json.loads(
        gatea._upgrade_marker(tmp_path, TARGET_SHA).read_text(encoding="utf-8")
    )
    evidence = json.loads(
        (
            tmp_path
            / f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
        ).read_text(encoding="utf-8")
    )
    assert set(success) == gatea.M9_ADOPTION_UPGRADE_RECORD_KEYS
    assert set(evidence) == gatea.M9_ADOPTION_EVIDENCE_RECORD_KEYS
    assert success["schema_version"] == 2
    assert success["transition_kind"] == upgrade.M9_ADOPTION_TRANSITION_KIND
    assert success["source_database_snapshot"] == success["final_database_snapshot"]
    assert success["source_m7_content_snapshot"] == success["final_m7_content_snapshot"]
    assert (
        success["source_m8_swatch_content_snapshot"]
        == success["final_m8_swatch_content_snapshot"]
        == _adoption_backup_record()["m8_swatch_content_snapshot"]
    )
    assert (
        success["source_m9_table_content_snapshot"]
        == success["final_m9_table_content_snapshot"]
    )
    assert success["source_image_manifest"] == success["final_image_manifest"]
    assert "table_sweep" not in success
    assert "table_bootstrap" not in success
    assert "mard_publication" not in success
    assert "wallet_preparation" not in success


@pytest.mark.parametrize("error_kind", ("sigterm", "keyboard-interrupt", "runtime"))
def test_m9_adoption_preserves_succeeded_evidence_when_success_publish_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error_kind: str,
) -> None:
    commands = _patch_m9_adoption_entry(monkeypatch, tmp_path)
    compose_calls = 0

    def compose_ps(**kwargs: object) -> list[dict[str, str]]:
        nonlocal compose_calls
        compose_calls += 1
        stopped = compose_calls > 1
        return [
            {
                "Service": service,
                "State": (
                    "exited"
                    if stopped and service in {"app", "table-sweeper", "nginx"}
                    else "running"
                ),
                "Health": (
                    "healthy" if service in {"mysql", "redis"} or not stopped else ""
                ),
            }
            for service in kwargs["services"]
        ]

    monkeypatch.setattr(gatea, "_compose_ps", compose_ps)
    monkeypatch.setattr(
        upgrade, "_require_adoption_record_metadata", lambda *args: None
    )
    publish_error: BaseException
    if error_kind == "sigterm":
        publish_error = gatea.GateAOperationInterrupted("received SIGTERM")
    elif error_kind == "keyboard-interrupt":
        publish_error = KeyboardInterrupt("received SIGINT")
    else:
        publish_error = RuntimeError("success publish failed")
    success_path = gatea._upgrade_marker(tmp_path, TARGET_SHA)
    original_writer = upgrade._write_json_exclusive

    def interrupted_writer(path: Path, payload: dict[str, object]) -> None:
        if path == success_path:
            raise publish_error
        original_writer(path, payload)

    monkeypatch.setattr(upgrade, "_write_json_exclusive", interrupted_writer)

    with pytest.raises(type(publish_error)) as raised:
        upgrade.upgrade_existing_database(
            **_m9_adoption_arguments(tmp_path, apply=True)
        )

    evidence_path = (
        tmp_path / f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert raised.value is publish_error
    assert commands == [
        ("stop", "--timeout", "30", "nginx", "table-sweeper", "app")
    ]
    assert evidence["status"] == "succeeded"
    assert evidence["current_stage"] == "completed"
    assert "error_type" not in evidence
    assert not success_path.exists()


def test_m9_adoption_checkpoint_error_precedes_success_publish_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_m9_adoption_entry(monkeypatch, tmp_path)
    compose_calls = 0

    def compose_ps(**kwargs: object) -> list[dict[str, str]]:
        nonlocal compose_calls
        compose_calls += 1
        stopped = compose_calls > 1
        return [
            {
                "Service": service,
                "State": (
                    "exited"
                    if stopped and service in {"app", "table-sweeper", "nginx"}
                    else "running"
                ),
                "Health": (
                    "healthy" if service in {"mysql", "redis"} or not stopped else ""
                ),
            }
            for service in kwargs["services"]
        ]

    monkeypatch.setattr(gatea, "_compose_ps", compose_ps)
    monkeypatch.setattr(
        upgrade, "_require_adoption_record_metadata", lambda *args: None
    )
    success_path = gatea._upgrade_marker(tmp_path, TARGET_SHA)
    publish_error = RuntimeError("success publish failed")
    checkpoint_error = upgrade.GateAUpgradeError("checkpoint validation failed")
    original_writer = upgrade._write_json_exclusive

    def interrupted_writer(path: Path, payload: dict[str, object]) -> None:
        if path == success_path:
            raise publish_error
        original_writer(path, payload)

    def reject_checkpoint(**kwargs: object) -> dict[str, object]:
        raise checkpoint_error

    monkeypatch.setattr(upgrade, "_write_json_exclusive", interrupted_writer)
    monkeypatch.setattr(
        upgrade,
        "_m9_adoption_success_from_evidence",
        reject_checkpoint,
    )

    with pytest.raises(upgrade.GateAUpgradeError) as raised:
        upgrade.upgrade_existing_database(
            **_m9_adoption_arguments(tmp_path, apply=True)
        )

    evidence_path = (
        tmp_path / f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert raised.value is checkpoint_error
    assert raised.value.__cause__ is publish_error
    assert evidence["status"] == "succeeded"
    assert "error_type" not in evidence
    assert not success_path.exists()


def test_m9_adoption_recovers_success_after_succeeded_evidence_sigkill_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands = _patch_stopped_adoption_recovery(monkeypatch, tmp_path)
    evidence_path = _write_succeeded_adoption_evidence(tmp_path)
    monkeypatch.setattr(
        upgrade,
        "_run_task",
        lambda **kwargs: pytest.fail("adoption recovery ran a database task"),
    )

    result = upgrade.upgrade_existing_database(
        **_m9_adoption_arguments(tmp_path, apply=True)
    )

    success_path = gatea._upgrade_marker(tmp_path, TARGET_SHA)
    success = json.loads(success_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert commands == []
    assert result["mode"] == "apply"
    assert result["database_changes_applied"] is False
    assert result["migrations_applied"] == []
    assert set(success) == gatea.M9_ADOPTION_UPGRADE_RECORD_KEYS
    assert success["evidence_sha256"] == upgrade._sha256(evidence_path)
    assert success["completed_at"] == evidence["completed_at"]
    assert success["source_database_snapshot"] == success[
        "final_database_snapshot"
    ]


def test_m9_adoption_succeeded_evidence_recovers_after_backup_max_age(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_plan = upgrade._plan_m9_adoption
    original_metadata_validator = upgrade._require_adoption_record_metadata
    commands = _patch_stopped_adoption_recovery(monkeypatch, tmp_path)
    monkeypatch.setattr(upgrade, "_plan_m9_adoption", original_plan)
    monkeypatch.setattr(
        upgrade,
        "_require_adoption_record_metadata",
        original_metadata_validator,
    )
    stale_completed_at = datetime.now(timezone.utc) - timedelta(hours=48)
    (
        backup_root,
        _,
        _,
        _,
        _,
        backup_bytes,
        restore_bytes,
    ) = _write_verified_m9_backup_pair(
        tmp_path,
        completed_at=stale_completed_at,
    )
    context = {
        **_adoption_context(),
        "backup_record_sha256": upgrade.hashlib.sha256(
            backup_bytes
        ).hexdigest(),
        "restore_record_sha256": upgrade.hashlib.sha256(
            restore_bytes
        ).hexdigest(),
    }
    _write_succeeded_adoption_evidence(
        tmp_path,
        context=context,
        started_at=(stale_completed_at + timedelta(minutes=2)).isoformat(),
        completed_at=(stale_completed_at + timedelta(minutes=3)).isoformat(),
    )
    _allow_local_bound_records(monkeypatch)
    monkeypatch.setattr(
        upgrade.backup,
        "_validate_backup_directories",
        lambda **kwargs: None,
    )

    def validate_lineage(**kwargs: object) -> dict[str, object]:
        records = kwargs["bound_backup_records"]
        assert isinstance(records, upgrade._BoundBackupRecords)
        assert records.backup_record_sha256 == context[
            "backup_record_sha256"
        ]
        assert records.restore_record_sha256 == context[
            "restore_record_sha256"
        ]
        return context

    monkeypatch.setattr(
        upgrade,
        "_validate_m9_adoption_lineage",
        validate_lineage,
    )
    monkeypatch.setattr(
        upgrade,
        "_run_task",
        lambda **kwargs: pytest.fail("adoption recovery ran a database task"),
    )

    result = upgrade.upgrade_existing_database(
        **_m9_adoption_arguments(tmp_path, apply=True)
    )

    success_path = gatea._upgrade_marker(tmp_path, TARGET_SHA)
    success = json.loads(success_path.read_text(encoding="utf-8"))
    assert backup_root == tmp_path / "backups"
    assert commands == []
    assert result["mode"] == "apply"
    assert success["backup_record_sha256"] == context[
        "backup_record_sha256"
    ]
    assert success["restore_record_sha256"] == context[
        "restore_record_sha256"
    ]


@pytest.mark.parametrize("require_activation", (False, True))
def test_m9_adoption_plan_and_apply_keep_backup_max_age(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    require_activation: bool,
) -> None:
    monkeypatch.setattr(gatea, "_candidate_sha", lambda values: TARGET_SHA)
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda values: "sha256:" + "0" * 64,
    )
    monkeypatch.setattr(upgrade, "_manifest_sha256", lambda: MANIFEST_SHA)

    def reject_stale_backup(**kwargs: object) -> upgrade._BoundBackupRecords:
        assert kwargs["enforce_backup_max_age"] is True
        raise upgrade.GateAUpgradeError(
            "Gate A backup must have completed within 24 hours"
        )

    monkeypatch.setattr(upgrade, "_load_verified_backup", reject_stale_backup)

    with pytest.raises(upgrade.GateAUpgradeError, match="within 24 hours"):
        upgrade._plan_m9_adoption(
            values=_values(tmp_path / "backups"),
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            source_candidate_sha=SOURCE_SHA,
            lineage_source_candidate_sha=LINEAGE_SHA,
            acceptance_retirement_record_sha256=RETIREMENT_SHA,
            backup_id=BACKUP_ID,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            release_record_dir=tmp_path,
            require_activation=require_activation,
        )


def test_m9_adoption_success_replay_keeps_backup_max_age(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands = _patch_stopped_adoption_recovery(monkeypatch, tmp_path)
    evidence_path = _write_succeeded_adoption_evidence(tmp_path)
    evidence, evidence_sha256 = upgrade._load_bound_json_with_sha256(
        evidence_path,
        "M9 adoption upgrade evidence",
    )
    success = upgrade._m9_adoption_success_from_evidence(
        evidence_path=evidence_path,
        evidence=evidence,
        evidence_sha256=evidence_sha256,
    )
    upgrade._write_json_exclusive(
        gatea._upgrade_marker(tmp_path, TARGET_SHA),
        success,
    )
    monkeypatch.setattr(
        gatea,
        "_require_upgrade_record",
        lambda **kwargs: success,
    )

    def reject_stale_backup(**kwargs: object) -> upgrade._BoundBackupRecords:
        assert kwargs.get("enforce_backup_max_age", True) is True
        raise upgrade.GateAUpgradeError(
            "Gate A backup must have completed within 24 hours"
        )

    monkeypatch.setattr(upgrade, "_load_verified_backup", reject_stale_backup)

    with pytest.raises(upgrade.GateAUpgradeError, match="within 24 hours"):
        upgrade.upgrade_existing_database(
            **_m9_adoption_arguments(tmp_path, apply=True)
        )

    assert commands == []


@pytest.mark.parametrize("status", ("in_progress", "failed"))
def test_m9_adoption_does_not_recover_incomplete_or_failed_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
) -> None:
    commands = _patch_stopped_adoption_recovery(monkeypatch, tmp_path)
    evidence_path = _write_succeeded_adoption_evidence(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["status"] = status
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(
        upgrade,
        "_plan_m9_adoption",
        lambda **kwargs: pytest.fail(
            "incomplete evidence must not receive stale-backup recovery"
        ),
    )

    with pytest.raises(upgrade.GateAUpgradeError, match="manual review"):
        upgrade.upgrade_existing_database(
            **_m9_adoption_arguments(tmp_path, apply=True)
        )

    assert commands == []
    assert not gatea._upgrade_marker(tmp_path, TARGET_SHA).exists()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("candidate_sha", "c" * 40),
        ("backup_id", "20260910t000000z"),
        ("backup_record_sha256", "f" * 64),
        ("restore_record_sha256", "f" * 64),
    ),
)
def test_m9_adoption_stale_backup_recovery_rejects_evidence_binding_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    commands = _patch_stopped_adoption_recovery(monkeypatch, tmp_path)
    evidence_path = _write_succeeded_adoption_evidence(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence[field] = value
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(upgrade.GateAUpgradeError, match="binding changed"):
        upgrade.upgrade_existing_database(
            **_m9_adoption_arguments(tmp_path, apply=True)
        )

    assert commands == []
    assert not gatea._upgrade_marker(tmp_path, TARGET_SHA).exists()


def test_m9_adoption_succeeded_evidence_recovery_requires_apply_confirmations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands = _patch_stopped_adoption_recovery(monkeypatch, tmp_path)
    _write_succeeded_adoption_evidence(tmp_path)

    with pytest.raises(upgrade.GateAUpgradeError, match="requires apply"):
        upgrade.upgrade_existing_database(
            **_m9_adoption_arguments(tmp_path, apply=False)
        )

    assert commands == []
    assert not gatea._upgrade_marker(tmp_path, TARGET_SHA).exists()


def test_m9_adoption_succeeded_evidence_recovery_rejects_live_state_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    drifted = _adoption_state()
    drifted["final_m9_table_content_snapshot"] = _adoption_content_snapshot(
        "m9-table-business-v1", "f" * 64
    )
    commands = _patch_stopped_adoption_recovery(
        monkeypatch,
        tmp_path,
        state=drifted,
    )
    _write_succeeded_adoption_evidence(tmp_path)

    with pytest.raises(upgrade.GateAUpgradeError, match="persistent state"):
        upgrade.upgrade_existing_database(
            **_m9_adoption_arguments(tmp_path, apply=True)
        )

    assert commands == []
    assert not gatea._upgrade_marker(tmp_path, TARGET_SHA).exists()


def test_m9_adoption_succeeded_evidence_recovery_rechecks_live_swatch_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    drifted = _adoption_state()
    drifted["final_m8_swatch_content_snapshot"] = _adoption_content_snapshot(
        "m8-swatch-content-v1", "f" * 64
    )
    commands = _patch_stopped_adoption_recovery(
        monkeypatch,
        tmp_path,
        state=drifted,
    )
    _write_succeeded_adoption_evidence(tmp_path)

    with pytest.raises(upgrade.GateAUpgradeError, match="persistent state"):
        upgrade.upgrade_existing_database(
            **_m9_adoption_arguments(tmp_path, apply=True)
        )

    assert commands == []
    assert not gatea._upgrade_marker(tmp_path, TARGET_SHA).exists()


def test_m9_adoption_succeeded_evidence_recovery_rejects_reversed_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands = _patch_stopped_adoption_recovery(monkeypatch, tmp_path)
    evidence_path = _write_succeeded_adoption_evidence(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["completed_at"] = "2026-09-11T11:59:59+00:00"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(upgrade.GateAUpgradeError, match="precedes"):
        upgrade.upgrade_existing_database(
            **_m9_adoption_arguments(tmp_path, apply=True)
        )

    assert commands == []
    assert not gatea._upgrade_marker(tmp_path, TARGET_SHA).exists()


def test_m9_adoption_succeeded_evidence_recovery_never_clobbers_racing_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands = _patch_stopped_adoption_recovery(monkeypatch, tmp_path)
    _write_succeeded_adoption_evidence(tmp_path)
    success_path = gatea._upgrade_marker(tmp_path, TARGET_SHA)
    original_writer = upgrade._write_json_exclusive

    def racing_writer(path: Path, payload: dict[str, object]) -> None:
        if path == success_path:
            path.write_text('{"untrusted": true}\n', encoding="utf-8")
        original_writer(path, payload)

    monkeypatch.setattr(upgrade, "_write_json_exclusive", racing_writer)

    with pytest.raises(upgrade.GateAUpgradeError, match="already reserved"):
        upgrade.upgrade_existing_database(
            **_m9_adoption_arguments(tmp_path, apply=True)
        )

    assert commands == []
    assert json.loads(success_path.read_text(encoding="utf-8")) == {
        "untrusted": True
    }


@pytest.mark.parametrize(
    "field",
    ("lineage_source_candidate_sha", "acceptance_retirement_record_sha256"),
)
def test_m9_adoption_requires_explicit_lineage_and_retirement_before_compose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    monkeypatch.setattr(
        gatea, "_validated_inputs", lambda **kwargs: _values(tmp_path / "backups")
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    arguments = _m9_adoption_arguments(tmp_path, apply=False)
    arguments[field] = None

    with pytest.raises(upgrade.GateAUpgradeError, match="requires lineage"):
        upgrade.upgrade_existing_database(**arguments)


def test_legacy_upgrade_rejects_adoption_only_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_plan(monkeypatch, tmp_path, source_version=7)
    arguments = _common_arguments(tmp_path, apply=False, source_version=7)
    arguments["lineage_source_candidate_sha"] = LINEAGE_SHA

    with pytest.raises(upgrade.GateAUpgradeError, match="invalid for an M2/M7"):
        upgrade.upgrade_existing_database(**arguments)


def test_m9_adoption_state_check_is_read_only_and_allows_closed_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _adoption_state()["source_database_snapshot"]
    backup_record = _adoption_backup_record()
    final_reads = 0

    def read_final(**kwargs: object) -> dict[str, object]:
        nonlocal final_reads
        final_reads += 1
        return dict(snapshot)

    monkeypatch.setattr(upgrade, "_read_final_snapshot", read_final)
    monkeypatch.setattr(
        upgrade.backup,
        "_source_snapshot",
        lambda *args: backup_record["database_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m7_content_snapshot",
        lambda *args: backup_record["m7_content_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m9_table_content_snapshot",
        lambda *args: backup_record["m9_table_content_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m8_swatch_content_snapshot",
        lambda *args: backup_record["m8_swatch_content_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: backup_record["image_manifest"],
    )
    task_calls: list[str] = []
    monkeypatch.setattr(
        upgrade,
        "_run_task",
        lambda **kwargs: task_calls.append(str(kwargs["module"]))
        or (_empty_table_reconcile_result() | {"scanned": 4}),
    )

    state = upgrade._read_m9_adoption_state(
        values={},
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
        backup_record=backup_record,
    )

    assert final_reads == 2
    assert task_calls == ["app.tasks.table_reconcile"]
    assert state["source_database_snapshot"] == state["final_database_snapshot"]
    assert (
        state["source_m8_swatch_content_snapshot"]
        == state["final_m8_swatch_content_snapshot"]
        == backup_record["m8_swatch_content_snapshot"]
    )
    assert state["table_reconcile"]["scanned"] == 4


def test_m9_adoption_state_rejects_same_count_swatch_digest_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _adoption_state()["source_database_snapshot"]
    backup_record = _adoption_backup_record()
    swatch_snapshots = iter(
        (
            backup_record["m8_swatch_content_snapshot"],
            _adoption_content_snapshot("m8-swatch-content-v1", "f" * 64),
        )
    )
    monkeypatch.setattr(
        upgrade, "_read_final_snapshot", lambda **kwargs: dict(snapshot)
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m7_content_snapshot",
        lambda *args: backup_record["m7_content_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m8_swatch_content_snapshot",
        lambda *args: next(swatch_snapshots),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m9_table_content_snapshot",
        lambda *args: backup_record["m9_table_content_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: backup_record["image_manifest"],
    )
    monkeypatch.setattr(
        upgrade,
        "_run_task",
        lambda **kwargs: _empty_table_reconcile_result() | {"scanned": 4},
    )

    with pytest.raises(upgrade.GateAUpgradeError, match="changed persistent state"):
        upgrade._read_m9_adoption_state(
            values={},
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_record=None,
        )


def test_m9_adoption_state_rejects_live_swatch_not_matching_backup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _adoption_state()["source_database_snapshot"]
    backup_record = _adoption_backup_record()
    monkeypatch.setattr(
        upgrade, "_read_final_snapshot", lambda **kwargs: dict(snapshot)
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_snapshot",
        lambda *args: backup_record["database_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m7_content_snapshot",
        lambda *args: backup_record["m7_content_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m8_swatch_content_snapshot",
        lambda *args: _adoption_content_snapshot(
            "m8-swatch-content-v1", "f" * 64
        ),
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m9_table_content_snapshot",
        lambda *args: backup_record["m9_table_content_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: backup_record["image_manifest"],
    )
    monkeypatch.setattr(
        upgrade,
        "_run_task",
        lambda **kwargs: pytest.fail("backup mismatch must precede reconcile"),
    )

    with pytest.raises(upgrade.GateAUpgradeError, match="verified backup"):
        upgrade._read_m9_adoption_state(
            values={},
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_record=backup_record,
        )


@pytest.mark.parametrize("key", ("open_sessions", "occupancies", "violations"))
def test_m9_adoption_state_rejects_live_or_inconsistent_tables(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
) -> None:
    snapshot = _adoption_state()["source_database_snapshot"]
    monkeypatch.setattr(
        upgrade, "_read_final_snapshot", lambda **kwargs: dict(snapshot)
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m7_content_snapshot",
        lambda *args: _adoption_backup_record()["m7_content_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m9_table_content_snapshot",
        lambda *args: _adoption_backup_record()["m9_table_content_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_m8_swatch_content_snapshot",
        lambda *args: _adoption_backup_record()["m8_swatch_content_snapshot"],
    )
    monkeypatch.setattr(
        upgrade.backup,
        "_source_image_manifest",
        lambda *args: _mard_image_manifest(),
    )
    monkeypatch.setattr(
        upgrade,
        "_run_task",
        lambda **kwargs: _empty_table_reconcile_result() | {key: 1},
    )

    with pytest.raises(upgrade.GateAUpgradeError, match="reconciliation"):
        upgrade._read_m9_adoption_state(
            values={},
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_record=None,
        )


def test_adoption_bound_json_rejects_duplicate_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "record.json"
    path.write_text('{"schema_version":2,"schema_version":1}\n', encoding="utf-8")
    path.chmod(0o644)
    monkeypatch.setattr(
        upgrade, "_require_adoption_record_metadata", lambda *args: None
    )

    with pytest.raises(upgrade.GateAUpgradeError, match="unavailable"):
        upgrade._load_bound_json_with_sha256(path, "adoption record")


def test_adoption_bound_record_requires_single_root_owned_link(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    alias = tmp_path / "record.alias.json"
    path.write_text("{}\n", encoding="utf-8")
    path.chmod(0o644)
    alias.hardlink_to(path)

    with pytest.raises(upgrade.GateAUpgradeError, match="unsafe metadata"):
        upgrade._require_adoption_record_metadata(path.stat(), "adoption record")


def test_m9_adoption_lineage_accepts_canonical_schema2_stage_and_retirement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_image_id = "sha256:" + "1" * 64
    lineage_image_id = "sha256:" + "6" * 64
    target_image_id = "sha256:" + "0" * 64
    failed_acceptance_sha256 = "f" * 64
    digests = {
        "candidate stage record": "1" * 64,
        "predecessor stage record": "2" * 64,
        "predecessor upgrade record": "3" * 64,
        "predecessor activation record": "4" * 64,
        "predecessor upgrade evidence": "5" * 64,
        "predecessor upgrade replay record": "6" * 64,
        "acceptance retirement record": RETIREMENT_SHA,
        "candidate activation record": "7" * 64,
        "M9 adoption backup record": "8" * 64,
        "M9 adoption restore record": "9" * 64,
    }
    predecessor_digests = {
        "predecessor_stage_record_sha256": digests["predecessor stage record"],
        "predecessor_activation_record_sha256": digests[
            "predecessor activation record"
        ],
        "predecessor_upgrade_record_sha256": digests[
            "predecessor upgrade record"
        ],
        "predecessor_upgrade_evidence_sha256": digests[
            "predecessor upgrade evidence"
        ],
        "predecessor_upgrade_plan_replay_record_sha256": digests[
            "predecessor upgrade replay record"
        ],
    }
    predecessor_upgrade = {
        "schema_version": 1,
        "source_version": 7,
        "source_candidate_sha": LINEAGE_SHA,
        "source_image_id": lineage_image_id,
        "source_aerich_versions": list(APPROVED_MIGRATIONS[:8]),
        "target_aerich_versions": list(APPROVED_MIGRATIONS),
        "candidate_sha": SOURCE_SHA,
        "image_id": source_image_id,
        "backup_id": "20260911t000000z",
        "manifest_sha256": MANIFEST_SHA,
    }
    predecessor_replay = {"validated": True}
    records: dict[str, dict[str, object]] = {
        "candidate stage record": {
            "schema_version": 2,
            "transition_kind": upgrade.M9_ADOPTION_TRANSITION_KIND,
            "record_type": "gatea-candidate-stage",
            "passed": True,
            "candidate_sha": TARGET_SHA,
            "image_id": target_image_id,
            "superseded_candidate_sha": SOURCE_SHA,
            "failed_acceptance_sha256": failed_acceptance_sha256,
            "secret_values_recorded": False,
        },
        "predecessor stage record": {
            "schema_version": 1,
            "record_type": "gatea-candidate-stage",
            "passed": True,
            "candidate_sha": SOURCE_SHA,
            "image_id": source_image_id,
            "secret_values_recorded": False,
        },
        "predecessor upgrade record": predecessor_upgrade,
        "predecessor activation record": {
            "schema_version": 1,
            "record_type": "gatea-config-activation",
            "passed": True,
            "source_candidate_sha": LINEAGE_SHA,
            "candidate_sha": SOURCE_SHA,
            "image_id": source_image_id,
            "stage_record_sha256": digests["predecessor stage record"],
            "backup_id": predecessor_upgrade["backup_id"],
            "manifest_sha256": MANIFEST_SHA,
            "secret_values_recorded": False,
        },
        "predecessor upgrade evidence": {"status": "succeeded"},
        "predecessor upgrade replay record": predecessor_replay,
        "M9 adoption backup record": {},
        "M9 adoption restore record": {},
    }
    retirement = {
        key: None for key in upgrade.ADOPTION_RETIREMENT_RECORD_KEYS
    }
    retirement.update(
        {
            "schema_version": 1,
            "record_type": "gatea-m9-failed-acceptance-retirement",
            "candidate_sha": TARGET_SHA,
            "image_id": target_image_id,
            "source_candidate_sha": SOURCE_SHA,
            "source_image_id": source_image_id,
            "lineage_source_candidate_sha": LINEAGE_SHA,
            "lineage_source_image_id": lineage_image_id,
            "stage_record_sha256": digests["candidate stage record"],
            **predecessor_digests,
            "acceptance_pending_sha256": failed_acceptance_sha256,
            "acceptance_attempt_id_sha256": "a" * 64,
            "acceptance_archive_path": "/root-only/raw-archive.json",
            "acceptance_archive_sha256": failed_acceptance_sha256,
            "live_verification": {
                "business_verification": {
                    "schema_version": 1,
                    "passed": True,
                    "counts": {
                        "orders": 1,
                        "fixtures": 2,
                        "fixture_images": 5,
                        "experience_options": 3,
                        "order_items": 4,
                        "experience_items": 3,
                        "kit_items": 1,
                        "payments": 0,
                        "settlements": 0,
                        "refunds": 0,
                        "wallet_transactions": 0,
                        "table_sessions": 0,
                        "admin_adjustments": 1,
                        "order_deductions": 1,
                        "cancellation_restores": 1,
                    },
                    "evidence_sha256": (
                        "9f262cb7c7a500cfd3b245f045c9ff8a887a640a6576539b"
                        "421a61add81c1012"
                    ),
                    "secret_values_recorded": False,
                },
                "database_snapshot": {
                    "aerich_versions": list(APPROVED_MIGRATIONS)
                },
                "runtime_services": [
                    "mysql",
                    "redis",
                    "app",
                    "table-sweeper",
                    "nginx",
                ],
                "table_reconcile": _empty_table_reconcile_result(),
                "wallet_reconcile": {
                    "scanned": 1,
                    "mismatches": 0,
                    "violations": 0,
                },
                "checked_at": "2026-09-11T00:00:00+00:00",
            },
            "started_at": "2026-09-11T00:00:00+00:00",
            "phase": "record-published",
            "secret_values_recorded": False,
            "completed_at": "2026-09-11T00:01:00+00:00",
            "passed": True,
        }
    )
    records["acceptance retirement record"] = retirement
    records["candidate activation record"] = {
        "schema_version": 2,
        "transition_kind": upgrade.M9_ADOPTION_TRANSITION_KIND,
        "record_type": "gatea-config-activation",
        "passed": True,
        "changed_keys": ["GATEA_APP_IMAGE"],
        "source_candidate_sha": SOURCE_SHA,
        "source_image_id": source_image_id,
        "candidate_sha": TARGET_SHA,
        "image_id": target_image_id,
        "lineage_source_candidate_sha": LINEAGE_SHA,
        "lineage_source_image_id": lineage_image_id,
        "backup_id": BACKUP_ID,
        "manifest_sha256": MANIFEST_SHA,
        "stage_record_sha256": digests["candidate stage record"],
        "acceptance_retirement_record_sha256": RETIREMENT_SHA,
        **predecessor_digests,
        "started_at": "2026-09-11T00:02:00+00:00",
        "completed_at": "2026-09-11T00:03:00+00:00",
        "config_values_recorded": False,
        "secret_values_recorded": False,
    }

    monkeypatch.setattr(
        upgrade,
        "_load_bound_json_with_sha256",
        lambda path, description: (records[description], digests[description]),
    )
    monkeypatch.setattr(
        gatea, "_require_upgrade_record", lambda **kwargs: predecessor_upgrade
    )
    monkeypatch.setattr(
        gatea,
        "_require_m9_upgrade_replay_record",
        lambda **kwargs: predecessor_replay,
    )

    context = upgrade._validate_m9_adoption_lineage(
        release_record_dir=tmp_path,
        backup_id=BACKUP_ID,
        bound_backup_records=_bound_backup(
            {},
            backup_record_sha256=digests["M9 adoption backup record"],
            restore_record_sha256=digests["M9 adoption restore record"],
        ),
        manifest_sha256=MANIFEST_SHA,
        candidate_sha=TARGET_SHA,
        image_id=target_image_id,
        source_candidate_sha=SOURCE_SHA,
        source_image_id=source_image_id,
        lineage_source_candidate_sha=LINEAGE_SHA,
        acceptance_retirement_record_sha256=RETIREMENT_SHA,
        require_activation=True,
    )

    assert context == {
        "stage_record_sha256": digests["candidate stage record"],
        "activation_record_sha256": digests["candidate activation record"],
        "lineage_source_candidate_sha": LINEAGE_SHA,
        "lineage_source_image_id": lineage_image_id,
        "acceptance_retirement_record_sha256": RETIREMENT_SHA,
        "backup_record_sha256": digests["M9 adoption backup record"],
        "restore_record_sha256": digests["M9 adoption restore record"],
        **predecessor_digests,
    }
