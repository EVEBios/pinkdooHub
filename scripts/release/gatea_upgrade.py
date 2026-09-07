#!/usr/bin/env python3
"""受控编排 Gate A 既有 M2 数据库到当前 M7 候选的升级。

该入口只支持经 Review 的精确 M2 起点。默认 plan 全程只读；apply 必须同时绑定
source/target SHA、Backup ID 与 MARD manifest SHA-256。写入前验证新鲜 Backup 与
独立 Restore PASS Record，随后停止 App/Nginx、比较停写后的数据库/图片与备份，
依次执行 M3、M4、Wallet 准备、M5、M6、MARD 发布和 M7。任一步失败都会保留脱敏
证据并保持业务入口停止，不会 fake、downgrade、恢复或盲目重跑。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence

from scripts.release import gatea_backup as backup
from scripts.release import gatea_operations as gatea


APPROVED_MIGRATIONS = gatea.APPROVED_TARGET_M7_CHAIN
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_SOURCE_VERSION = 2
TARGET_VERSION = 7
MAX_BACKUP_AGE = timedelta(hours=24)
FUTURE_CLOCK_TOLERANCE = timedelta(minutes=5)
MARD_MANIFEST = (
    gatea.REPOSITORY_ROOT / "app" / "tasks" / "manifests" / "mard_221.json"
)
CORE_INVARIANT_KEYS = (
    "users",
    "products",
    "experience_options",
    "product_images",
    "product_kits",
    "kit_stock",
    "orders",
    "order_items",
    "order_total",
    "inventory_transactions",
    "inventory_change",
    "audit_logs",
)
RESTORE_TRUE_FIELDS = (
    "database_matches",
    "images_match",
    "restore_app_ready",
    "redis_started_empty",
    "refresh_sessions_invalidated",
    "temporary_resources_removed",
    "passed",
)
RUNTIME_PREFLIGHT_COMMAND = """import json
from app.core.config import settings
print(json.dumps({
    "app_env": settings.app_env,
    "db_engine": settings.db_engine,
    "jwt_algorithm": settings.jwt_algorithm,
    "validated": True,
}, sort_keys=True))
"""

FINAL_DATABASE_STATUS_COMMAND = r"""MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"
export MYSQL_PWD
mysql --batch --skip-column-names --raw --host=127.0.0.1 --user=root "$MYSQL_DATABASE" <<'SQL'
SET SESSION group_concat_max_len = 1048576;
SELECT JSON_OBJECT(
  'aerich_versions', COALESCE((SELECT GROUP_CONCAT(version ORDER BY id SEPARATOR ',') FROM aerich), ''),
  'tables', (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()),
  'columns', (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()),
  'statistics', (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE()),
  'constraints', (SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema = DATABASE()),
  'columns_sha256', SHA2(COALESCE((
    SELECT GROUP_CONCAT(
      CONCAT_WS(':', table_name, ordinal_position, column_name, column_type,
                is_nullable, COALESCE(column_default, '<NULL>'), extra)
      ORDER BY table_name, ordinal_position SEPARATOR '\n'
    ) FROM information_schema.columns WHERE table_schema = DATABASE()
  ), ''), 256),
  'statistics_sha256', SHA2(COALESCE((
    SELECT GROUP_CONCAT(
      CONCAT_WS(':', table_name, index_name, non_unique, seq_in_index,
                column_name, COALESCE(sub_part, '<NULL>'))
      ORDER BY table_name, index_name, seq_in_index SEPARATOR '\n'
    ) FROM information_schema.statistics WHERE table_schema = DATABASE()
  ), ''), 256),
  'constraints_sha256', SHA2(COALESCE((
    SELECT GROUP_CONCAT(
      CONCAT_WS(':', table_name, constraint_name, constraint_type)
      ORDER BY table_name, constraint_name SEPARATOR '\n'
    ) FROM information_schema.table_constraints WHERE table_schema = DATABASE()
  ), ''), 256),
  'users', (SELECT COUNT(*) FROM users),
  'products', (SELECT COUNT(*) FROM products),
  'experience_options', (SELECT COUNT(*) FROM experience_options),
  'product_images', (SELECT COUNT(*) FROM product_images),
  'product_kits', (SELECT COUNT(*) FROM product_kits),
  'kit_stock', (SELECT COALESCE(SUM(stock), 0) FROM product_kits),
  'orders', (SELECT COUNT(*) FROM orders),
  'order_items', (SELECT COUNT(*) FROM order_items),
  'order_total', (SELECT CAST(COALESCE(SUM(total_amount), 0) AS CHAR) FROM orders),
  'inventory_transactions', (SELECT COUNT(*) FROM inventory_transactions),
  'inventory_change', (SELECT COALESCE(SUM(change_quantity), 0) FROM inventory_transactions),
  'audit_logs', (SELECT COUNT(*) FROM audit_logs),
  'external_identities', (SELECT COUNT(*) FROM external_identities),
  'eligible_wallet_users', (SELECT COUNT(*) FROM users WHERE role = 1 AND status IN (1, 2)),
  'wallet_accounts', (SELECT COUNT(*) FROM wallet_accounts),
  'ineligible_wallet_accounts', (
    SELECT COUNT(*) FROM wallet_accounts wa
    JOIN users u ON u.id = wa.user_id
    WHERE u.role <> 1 OR u.status NOT IN (1, 2)
  ),
  'wallet_balance', (SELECT CAST(COALESCE(SUM(balance), 0) AS CHAR) FROM wallet_accounts),
  'wallet_transactions', (SELECT COUNT(*) FROM wallet_transactions),
  'recharge_orders', (SELECT COUNT(*) FROM recharge_orders),
  'payments', (SELECT COUNT(*) FROM payments),
  'payment_settlements', (SELECT COUNT(*) FROM payment_settlements),
  'refunds', (SELECT COUNT(*) FROM refunds),
  'store_business_days', (SELECT COUNT(*) FROM store_business_days),
  'reservations', (SELECT COUNT(*) FROM reservations),
  'bead_colors', (SELECT COUNT(*) FROM bead_colors),
  'bead_color_slots', (SELECT COUNT(DISTINCT slot_no) FROM bead_colors),
  'bead_color_min_slot', (SELECT MIN(slot_no) FROM bead_colors),
  'bead_color_max_slot', (SELECT MAX(slot_no) FROM bead_colors),
  'configured_bead_colors', (
    SELECT COUNT(*) FROM bead_colors
    WHERE color_code IS NOT NULL AND name IS NOT NULL AND swatch_image_url IS NOT NULL
  ),
  'active_bead_colors', (SELECT COUNT(*) FROM bead_colors WHERE is_active = 1),
  'product_kit_colors', (SELECT COUNT(*) FROM product_kit_colors),
  'reservation_settings', (SELECT COUNT(*) FROM reservation_settings),
  'reservation_settings_invalid', (
    SELECT COUNT(*) FROM reservation_settings
    WHERE singleton_key <> 1 OR weekly_closed_weekday NOT IN
      ('monday','tuesday','wednesday','thursday','friday','saturday','sunday')
  ),
  'reservation_settings_check', (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = DATABASE()
      AND table_name = 'reservation_settings'
      AND constraint_name = 'ck_reservation_settings_singleton'
      AND constraint_type = 'CHECK'
  ),
  'reservation_settings_unique', (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'reservation_settings'
      AND index_name = 'uidx_reservation_settings_singleton'
      AND non_unique = 0
  )
);
SQL"""


class GateAUpgradeError(gatea.GateAError):
    """不包含 Secret、PII、业务明细或外部命令原始输出的升级错误。"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _parse_utc_timestamp(value: object, description: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise GateAUpgradeError(f"Gate A {description} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GateAUpgradeError(
            f"Gate A {description} timestamp is invalid"
        ) from error
    if parsed.tzinfo is None:
        raise GateAUpgradeError(f"Gate A {description} timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_sha256() -> str:
    try:
        digest = _sha256(MARD_MANIFEST)
    except FileNotFoundError as error:
        raise GateAUpgradeError("Gate A MARD manifest is unavailable") from error
    if SHA256_PATTERN.fullmatch(digest) is None:
        raise GateAUpgradeError("Gate A MARD manifest digest is invalid")
    return digest


def _parse_json_object(output: str, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(output.strip())
    except json.JSONDecodeError as error:
        raise GateAUpgradeError(f"Gate A {description} output is invalid") from error
    if not isinstance(payload, dict):
        raise GateAUpgradeError(f"Gate A {description} output has an invalid shape")
    return payload


def _normalize_versions(snapshot: dict[str, Any]) -> dict[str, Any]:
    raw_versions = snapshot.get("aerich_versions")
    if isinstance(raw_versions, str):
        snapshot["aerich_versions"] = (
            raw_versions.split(",") if raw_versions else []
        )
    if not isinstance(snapshot.get("aerich_versions"), list):
        raise GateAUpgradeError("Gate A Aerich chain is invalid")
    return snapshot


def _manifest_summary(lines: Sequence[str]) -> dict[str, object]:
    normalized = "\n".join(lines)
    if lines:
        normalized += "\n"
    return {
        "files": len(lines),
        "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _expected_versions(version: int) -> list[str]:
    return list(APPROVED_MIGRATIONS[: version + 1])


def _validate_confirmations(
    *,
    candidate_sha: str,
    source_candidate_sha: str,
    backup_id: str,
    manifest_sha256: str,
    confirm_target_sha: str | None,
    confirm_source_sha: str | None,
    confirm_backup_id: str | None,
    confirm_manifest_sha256: str | None,
) -> None:
    if (
        confirm_target_sha != candidate_sha
        or confirm_source_sha != source_candidate_sha
        or confirm_backup_id != backup_id
        or confirm_manifest_sha256 != manifest_sha256
    ):
        raise GateAUpgradeError(
            "Gate A apply confirmations must exactly match target/source SHA, "
            "Backup ID and MARD manifest SHA-256"
        )


def _load_restore_record(
    *,
    backup_id: str,
    source_candidate_sha: str,
    restore_record_dir: Path,
    backup_completed_at: datetime,
    now: datetime,
) -> dict[str, Any]:
    path = restore_record_dir / f"{backup_id}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise GateAUpgradeError("Gate A restore PASS record is unavailable") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("backup_id") != backup_id
        or payload.get("candidate_sha") != source_candidate_sha
        or payload.get("restore_project") != backup.restore_project(backup_id)
        or payload.get("host_ports_published") is not False
        or any(payload.get(field) is not True for field in RESTORE_TRUE_FIELDS)
    ):
        raise GateAUpgradeError("Gate A restore PASS record is invalid")
    completed_at = _parse_utc_timestamp(
        payload.get("completed_at"), "restore completion"
    )
    if completed_at < backup_completed_at or completed_at > now + FUTURE_CLOCK_TOLERANCE:
        raise GateAUpgradeError("Gate A restore PASS record time is invalid")
    return payload


def _load_verified_backup(
    *,
    values: Mapping[str, str],
    backup_id: str,
    source_candidate_sha: str,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
) -> dict[str, Any]:
    backup._validate_backup_directories(
        values=values,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
    )
    payload, _, _ = backup._load_backup_record(
        backup_id=backup_id,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
    )
    if (
        payload.get("candidate_sha") != source_candidate_sha
        or not isinstance(payload.get("image_id"), str)
        or not payload.get("image_id")
        or payload.get("consistency") != "nginx-and-app-stopped"
        or payload.get("application_restarted") is not True
        or payload.get("passed") is not True
        or not isinstance(payload.get("database_snapshot"), dict)
        or not isinstance(payload.get("image_manifest"), list)
    ):
        raise GateAUpgradeError("Gate A backup record does not match the source")
    now = _utc_now()
    completed_at = _parse_utc_timestamp(
        payload.get("completed_at"), "backup completion"
    )
    if completed_at > now + FUTURE_CLOCK_TOLERANCE or now - completed_at > MAX_BACKUP_AGE:
        raise GateAUpgradeError("Gate A backup must have completed within 24 hours")
    _load_restore_record(
        backup_id=backup_id,
        source_candidate_sha=source_candidate_sha,
        restore_record_dir=restore_record_dir,
        backup_completed_at=completed_at,
        now=now,
    )
    return payload


def _ensure_stopped(rows: Sequence[Mapping[str, Any]], *services: str) -> None:
    by_service = {str(row.get("Service")): row for row in rows}
    for service in services:
        row = by_service.get(service)
        if row is None:
            raise GateAUpgradeError(f"Gate A service {service} is unavailable")
        if str(row.get("State", "")).lower() not in {"exited", "stopped"}:
            raise GateAUpgradeError(f"Gate A service {service} did not stop")


def _validate_wallet_result(result: Mapping[str, Any]) -> None:
    wallet_accounts = result.get("wallet_accounts")
    settlements = result.get("legacy_settlements")
    reconciliation = result.get("reconciliation")
    if (
        not isinstance(wallet_accounts, dict)
        or wallet_accounts.get("replay_would_create") != 0
        or not isinstance(settlements, dict)
        or settlements.get("replay_would_create") != 0
        or settlements.get("blocked") != 0
        or not isinstance(reconciliation, dict)
        or reconciliation.get("mismatches") != 0
        or reconciliation.get("violations") != 0
    ):
        raise GateAUpgradeError("Gate A Wallet preparation result is not reconciled")


def _run_task(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    service: str,
    module: str,
    arguments: Sequence[str] = (),
    operations_profile: bool = False,
    description: str,
) -> dict[str, Any]:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        profiles=("operations",) if operations_profile else (),
        arguments=(
            "run",
            "--rm",
            "--no-deps",
            service,
            "python",
            "-m",
            module,
            *arguments,
        ),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateAUpgradeError(f"Gate A {description} task failed")
    return _parse_json_object(result.stdout, description)


def _run_runtime_preflight(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
) -> dict[str, Any]:
    """通过镜像默认入口加载 Secret，并在停业务入口前校验生产配置。"""

    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        profiles=("operations",),
        arguments=(
            "run",
            "--rm",
            "--no-deps",
            "migrate",
            "python",
            "-c",
            RUNTIME_PREFLIGHT_COMMAND,
        ),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateAUpgradeError(
            "Gate A candidate runtime configuration preflight failed"
        )
    payload = _parse_json_object(result.stdout, "runtime-preflight")
    if payload != {
        "app_env": "production",
        "db_engine": "mysql",
        "jwt_algorithm": "HS256",
        "validated": True,
    }:
        raise GateAUpgradeError(
            "Gate A candidate runtime configuration preflight is invalid"
        )
    return payload


def _read_final_snapshot(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
) -> dict[str, Any]:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=(
            "exec",
            "--no-tty",
            "mysql",
            "sh",
            "-ec",
            FINAL_DATABASE_STATUS_COMMAND,
        ),
        capture_output=True,
    )
    return _normalize_versions(
        _parse_json_object(result.stdout, "final database status")
    )


def _validate_final_snapshot(
    source_snapshot: Mapping[str, Any],
    final_snapshot: Mapping[str, Any],
) -> None:
    if final_snapshot.get("aerich_versions") != _expected_versions(TARGET_VERSION):
        raise GateAUpgradeError("Gate A final Aerich chain is not exactly M0-M7")
    for key in CORE_INVARIANT_KEYS:
        if final_snapshot.get(key) != source_snapshot.get(key):
            raise GateAUpgradeError(
                f"Gate A final core invariant changed unexpectedly: {key}"
            )
    if (
        final_snapshot.get("wallet_accounts")
        != final_snapshot.get("eligible_wallet_users")
        or final_snapshot.get("ineligible_wallet_accounts") != 0
    ):
        raise GateAUpgradeError("Gate A Wallet owner backfill invariant failed")
    expected_color_values = {
        "bead_colors": 221,
        "bead_color_slots": 221,
        "bead_color_min_slot": 1,
        "bead_color_max_slot": 221,
        "configured_bead_colors": 221,
        "active_bead_colors": 221,
    }
    for key, expected in expected_color_values.items():
        if final_snapshot.get(key) != expected:
            raise GateAUpgradeError(f"Gate A final MARD invariant failed: {key}")
    if (
        final_snapshot.get("reservation_settings") != 1
        or final_snapshot.get("reservation_settings_invalid") != 0
        or final_snapshot.get("reservation_settings_check") != 1
        or final_snapshot.get("reservation_settings_unique") != 1
    ):
        raise GateAUpgradeError("Gate A final ReservationSettings invariant failed")


def _record_step(
    *,
    evidence_path: Path,
    evidence: dict[str, Any],
    name: str,
    started_at: str,
    result: Mapping[str, Any],
    database_snapshot: Mapping[str, Any],
) -> None:
    evidence["steps"].append(
        {
            "completed_at": _iso_now(),
            "database_snapshot": dict(database_snapshot),
            "name": name,
            "result": dict(result),
            "started_at": started_at,
        }
    )
    evidence["current_stage"] = name
    backup._write_json_atomic(evidence_path, evidence, 0o644)


def _upgrade_paths(record_dir: Path, candidate_sha: str) -> tuple[Path, Path]:
    return (
        gatea._upgrade_marker(record_dir, candidate_sha),
        record_dir / f"{candidate_sha}.existing-database-upgrade.evidence.json",
    )


def _plan(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    source_candidate_sha: str,
    backup_id: str,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
    release_record_dir: Path,
) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
    candidate_sha = gatea._candidate_sha(values)
    if (
        SHA_PATTERN.fullmatch(candidate_sha) is None
        or SHA_PATTERN.fullmatch(source_candidate_sha) is None
        or candidate_sha == source_candidate_sha
    ):
        raise GateAUpgradeError("Gate A source and target candidate SHA are invalid")
    gatea._validate_root_directory(
        release_record_dir, 0o755, "Gate A release record directory"
    )
    image_id = gatea.validate_app_image(values)
    success_path, evidence_path = _upgrade_paths(release_record_dir, candidate_sha)
    if success_path.exists():
        gatea._require_upgrade_record(
            record_dir=release_record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
        try:
            success_record = json.loads(success_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise GateAUpgradeError(
                "Gate A existing-database upgrade record is invalid"
            ) from error
        if (
            success_record.get("source_candidate_sha") != source_candidate_sha
            or success_record.get("backup_id") != backup_id
            or success_record.get("manifest_sha256") != _manifest_sha256()
        ):
            raise GateAUpgradeError(
                "Gate A recorded upgrade does not match the requested replay"
            )
        final_snapshot = _read_final_snapshot(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
        )
        if final_snapshot.get("aerich_versions") != _expected_versions(TARGET_VERSION):
            raise GateAUpgradeError(
                "Gate A recorded upgrade no longer matches the database"
            )
        return candidate_sha, image_id, {}, final_snapshot, _manifest_sha256()
    if evidence_path.exists():
        raise GateAUpgradeError(
            "Gate A prior upgrade evidence requires manual review before retry"
        )

    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("mysql", "redis", "app", "nginx"),
    )
    gatea._ensure_services_healthy(rows, "mysql", "redis", "app", "nginx")
    source_status = gatea.read_database_snapshot(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
    )
    if source_status.get("aerich_versions") != _expected_versions(
        SUPPORTED_SOURCE_VERSION
    ):
        raise GateAUpgradeError("Gate A database is not the approved M2 source")
    backup_record = _load_verified_backup(
        values=values,
        backup_id=backup_id,
        source_candidate_sha=source_candidate_sha,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
    )
    backup_versions = backup_record["database_snapshot"].get("aerich_versions")
    if backup_versions != ",".join(_expected_versions(SUPPORTED_SOURCE_VERSION)):
        raise GateAUpgradeError("Gate A verified backup is not from exact M2")
    return candidate_sha, image_id, backup_record, source_status, _manifest_sha256()


def upgrade_existing_database(
    *,
    config_file: Path,
    secret_dir: Path,
    mode: str,
    source_candidate_sha: str,
    backup_id: str,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
    release_record_dir: Path,
    apply: bool,
    confirm_target_sha: str | None,
    confirm_source_sha: str | None,
    confirm_backup_id: str | None,
    confirm_manifest_sha256: str | None,
) -> dict[str, Any]:
    """规划或执行精确 M2→M7 升级，并生成可供 app-up 使用的成功 Record。"""

    gatea._require_loopback_write_mode(mode)
    backup_id = backup._backup_id(backup_id)
    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=False,
    )
    candidate_sha, image_id, backup_record, source_status, manifest_sha256 = _plan(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        source_candidate_sha=source_candidate_sha,
        backup_id=backup_id,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
        release_record_dir=release_record_dir,
    )
    success_path, evidence_path = _upgrade_paths(release_record_dir, candidate_sha)
    if success_path.exists():
        if apply:
            _validate_confirmations(
                candidate_sha=candidate_sha,
                source_candidate_sha=source_candidate_sha,
                backup_id=backup_id,
                manifest_sha256=manifest_sha256,
                confirm_target_sha=confirm_target_sha,
                confirm_source_sha=confirm_source_sha,
                confirm_backup_id=confirm_backup_id,
                confirm_manifest_sha256=confirm_manifest_sha256,
            )
        return {
            "already_current": True,
            "backup_id": backup_id,
            "candidate_sha": candidate_sha,
            "manifest_sha256": manifest_sha256,
            "mode": "apply-replay" if apply else "plan-replay",
            "target_version": TARGET_VERSION,
        }
    if not apply:
        if any(
            value is not None
            for value in (
                confirm_target_sha,
                confirm_source_sha,
                confirm_backup_id,
                confirm_manifest_sha256,
            )
        ):
            raise GateAUpgradeError("Gate A plan does not accept apply confirmations")
        return {
            "already_current": False,
            "backup_id": backup_id,
            "candidate_sha": candidate_sha,
            "manifest_sha256": manifest_sha256,
            "mode": "plan",
            "restore_verified": True,
            "source_candidate_sha": source_candidate_sha,
            "source_version": SUPPORTED_SOURCE_VERSION,
            "target_version": TARGET_VERSION,
        }

    _validate_confirmations(
        candidate_sha=candidate_sha,
        source_candidate_sha=source_candidate_sha,
        backup_id=backup_id,
        manifest_sha256=manifest_sha256,
        confirm_target_sha=confirm_target_sha,
        confirm_source_sha=confirm_source_sha,
        confirm_backup_id=confirm_backup_id,
        confirm_manifest_sha256=confirm_manifest_sha256,
    )
    runtime_preflight = _run_runtime_preflight(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
    )

    started_at = _iso_now()
    evidence: dict[str, Any] = {
        "backup_id": backup_id,
        "candidate_sha": candidate_sha,
        "current_stage": "validated",
        "image_id": image_id,
        "manifest_sha256": manifest_sha256,
        "record_type": "existing-database-upgrade-evidence",
        "runtime_preflight": runtime_preflight,
        "schema_version": 1,
        "source_candidate_sha": source_candidate_sha,
        "source_database_status": source_status,
        "started_at": started_at,
        "status": "in_progress",
        "steps": [],
    }
    _write_json_exclusive(evidence_path, evidence)
    business_stopped = False
    final_snapshot: dict[str, Any] = {}
    final_image_manifest: list[str] = []
    wallet_result: dict[str, Any] = {}
    mard_result: dict[str, Any] = {}
    try:
        evidence["current_stage"] = "stop-business-entry"
        backup._write_json_atomic(evidence_path, evidence, 0o644)
        gatea._run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=("stop", "--timeout", "30", "nginx", "app"),
        )
        business_stopped = True
        rows = gatea._compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("mysql", "redis", "app", "nginx"),
        )
        gatea._ensure_services_healthy(rows, "mysql", "redis")
        _ensure_stopped(rows, "app", "nginx")

        evidence["current_stage"] = "verify-stopped-source"
        stopped_snapshot = backup._source_snapshot(
            values, config_file, secret_dir, mode
        )
        stopped_images = backup._source_image_manifest(
            values, config_file, secret_dir, mode
        )
        if stopped_snapshot != backup_record["database_snapshot"]:
            raise GateAUpgradeError(
                "Gate A stopped database no longer matches the verified backup"
            )
        if stopped_images != backup_record["image_manifest"]:
            raise GateAUpgradeError(
                "Gate A stopped image volume no longer matches the verified backup"
            )
        evidence["stopped_source_verified"] = True
        evidence["source_image_manifest"] = _manifest_summary(stopped_images)
        backup._write_json_atomic(evidence_path, evidence, 0o644)

        for target_version in (3, 4, 5, 6, 7):
            name = f"migrate-m{target_version}"
            step_started = _iso_now()
            migration_result = _run_task(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                mode=mode,
                service="migrate",
                module="app.tasks.gatea_migrate_step",
                arguments=("--target-version", str(target_version)),
                operations_profile=True,
                description=name,
            )
            database_status = gatea.read_database_snapshot(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                mode=mode,
            )
            if database_status.get("aerich_versions") != _expected_versions(
                target_version
            ):
                raise GateAUpgradeError(
                    f"Gate A database did not converge after M{target_version}"
                )
            _record_step(
                evidence_path=evidence_path,
                evidence=evidence,
                name=name,
                started_at=step_started,
                result=migration_result,
                database_snapshot=database_status,
            )

            if target_version == 4:
                step_started = _iso_now()
                wallet_result = _run_task(
                    values=values,
                    config_file=config_file,
                    secret_dir=secret_dir,
                    mode=mode,
                    service="migrate",
                    module="app.tasks.gatea_wallet_prepare",
                    operations_profile=True,
                    description="wallet-prepare",
                )
                _validate_wallet_result(wallet_result)
                _record_step(
                    evidence_path=evidence_path,
                    evidence=evidence,
                    name="wallet-prepare",
                    started_at=step_started,
                    result=wallet_result,
                    database_snapshot=database_status,
                )

            if target_version == 6:
                step_started = _iso_now()
                preview = _run_task(
                    values=values,
                    config_file=config_file,
                    secret_dir=secret_dir,
                    mode=mode,
                    service="app",
                    module="app.tasks.gatea_mard_publish",
                    description="mard-preview",
                )
                if (
                    preview.get("mode") != "preview"
                    or preview.get("colors") != 221
                    or preview.get("manifest_sha256") != manifest_sha256
                ):
                    raise GateAUpgradeError("Gate A MARD preview result is invalid")
                mard_result = _run_task(
                    values=values,
                    config_file=config_file,
                    secret_dir=secret_dir,
                    mode=mode,
                    service="app",
                    module="app.tasks.gatea_mard_publish",
                    arguments=(
                        "--apply",
                        "--confirm-manifest-sha256",
                        manifest_sha256,
                    ),
                    description="mard-apply",
                )
                replay = _run_task(
                    values=values,
                    config_file=config_file,
                    secret_dir=secret_dir,
                    mode=mode,
                    service="app",
                    module="app.tasks.gatea_mard_publish",
                    description="mard-replay-preview",
                )
                if (
                    mard_result.get("mode") != "apply"
                    or mard_result.get("colors") != 221
                    or mard_result.get("manifest_sha256") != manifest_sha256
                    or replay.get("already_current") is not True
                    or replay.get("database_changes") != 0
                    or replay.get("images_to_create") != 0
                ):
                    raise GateAUpgradeError("Gate A MARD apply did not converge")
                _record_step(
                    evidence_path=evidence_path,
                    evidence=evidence,
                    name="mard-publish",
                    started_at=step_started,
                    result={"apply": mard_result, "preview": preview, "replay": replay},
                    database_snapshot=database_status,
                )

        final_snapshot = _read_final_snapshot(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
        )
        _validate_final_snapshot(backup_record["database_snapshot"], final_snapshot)
        final_image_manifest = backup._source_image_manifest(
            values, config_file, secret_dir, mode
        )
        if _manifest_summary(final_image_manifest)["files"] < 221:
            raise GateAUpgradeError("Gate A final image manifest is incomplete")

        evidence["completed_at"] = _iso_now()
        evidence["current_stage"] = "completed"
        evidence["final_database_snapshot"] = final_snapshot
        evidence["final_image_manifest"] = _manifest_summary(final_image_manifest)
        evidence["status"] = "succeeded"
        backup._write_json_atomic(evidence_path, evidence, 0o644)

        success_payload = {
            "backup_id": backup_id,
            "candidate_sha": candidate_sha,
            "completed_at": _iso_now(),
            "evidence_path": str(evidence_path),
            "evidence_sha256": _sha256(evidence_path),
            "final_database_snapshot": final_snapshot,
            "final_image_manifest": _manifest_summary(final_image_manifest),
            "image_id": image_id,
            "manifest_sha256": manifest_sha256,
            "passed": True,
            "record_type": "existing-database-upgrade",
            "runtime_preflight": runtime_preflight,
            "schema_version": 1,
            "source_aerich_versions": _expected_versions(SUPPORTED_SOURCE_VERSION),
            "source_candidate_sha": source_candidate_sha,
            "source_image_id": backup_record["image_id"],
            "source_database_snapshot": backup_record["database_snapshot"],
            "source_image_manifest": _manifest_summary(
                backup_record["image_manifest"]
            ),
            "started_at": started_at,
            "target_aerich_versions": _expected_versions(TARGET_VERSION),
            "wallet_preparation": wallet_result,
            "mard_publication": mard_result,
        }
        _write_json_exclusive(success_path, success_payload)
    except BaseException as error:
        evidence["completed_at"] = _iso_now()
        evidence["error_type"] = type(error).__name__
        evidence["status"] = "failed"
        evidence["business_entry_stopped"] = business_stopped
        try:
            evidence["failure_database_status"] = gatea.read_database_snapshot(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                mode=mode,
            )
        except BaseException as snapshot_error:
            evidence["failure_snapshot_error_type"] = type(snapshot_error).__name__
        backup._write_json_atomic(evidence_path, evidence, 0o644)
        raise

    return {
        "already_current": False,
        "application_stopped": True,
        "backup_id": backup_id,
        "candidate_sha": candidate_sha,
        "manifest_sha256": manifest_sha256,
        "mode": "apply",
        "record": str(success_path),
        "source_candidate_sha": source_candidate_sha,
        "source_version": SUPPORTED_SOURCE_VERSION,
        "target_version": TARGET_VERSION,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or apply the guarded Gate A M2-to-M7 upgrade",
    )
    parser.add_argument("--mode", choices=tuple(gatea.MODE_COMPOSE), required=True)
    parser.add_argument("--config-file", type=Path, default=gatea.DEFAULT_CONFIG_FILE)
    parser.add_argument("--secret-dir", type=Path, default=gatea.DEFAULT_SECRET_DIR)
    parser.add_argument("--source-candidate-sha", required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--backup-root", type=Path, default=backup.DEFAULT_BACKUP_ROOT)
    parser.add_argument(
        "--backup-record-dir", type=Path, default=backup.DEFAULT_BACKUP_RECORD_DIR
    )
    parser.add_argument(
        "--restore-record-dir", type=Path, default=backup.DEFAULT_RESTORE_RECORD_DIR
    )
    parser.add_argument(
        "--release-record-dir", type=Path, default=gatea.DEFAULT_RECORD_DIR
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-target-sha")
    parser.add_argument("--confirm-source-sha")
    parser.add_argument("--confirm-backup-id")
    parser.add_argument("--confirm-manifest-sha256")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = upgrade_existing_database(
            config_file=args.config_file,
            secret_dir=args.secret_dir,
            mode=args.mode,
            source_candidate_sha=args.source_candidate_sha,
            backup_id=args.backup_id,
            backup_root=args.backup_root,
            backup_record_dir=args.backup_record_dir,
            restore_record_dir=args.restore_record_dir,
            release_record_dir=args.release_record_dir,
            apply=args.apply,
            confirm_target_sha=args.confirm_target_sha,
            confirm_source_sha=args.confirm_source_sha,
            confirm_backup_id=args.confirm_backup_id,
            confirm_manifest_sha256=args.confirm_manifest_sha256,
        )
    except (gatea.GateAError, subprocess.SubprocessError) as error:
        print(f"Gate A existing-database upgrade failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(
            "Gate A existing-database upgrade failed: "
            f"error_type={type(error).__name__}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
