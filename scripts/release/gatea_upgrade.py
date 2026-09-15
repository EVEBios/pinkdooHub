#!/usr/bin/env python3
"""受控编排 Gate A 既有 M2、M7 或 M9 数据库到当前 M9 候选。

未指定 source version 的旧调用继续只接受经 Review 的精确 M2 起点；M7 起点必须显式
指定 ``--source-version 7``。默认 plan 全程只读；apply 必须同时绑定 source/target SHA、
Backup ID 与 MARD manifest SHA-256。写入前验证新鲜 Backup 与独立 Restore PASS Record，
随后停止 App/Nginx、比较停写后的数据库/图片与备份，并只执行 source 后尚未应用的迁移
及其数据任务。M9→M9 adoption 只轮换不可变候选，严禁执行迁移、bootstrap
或业务写入。任一步失败都会保留脱敏证据并保持业务入口停止，不会
fake、downgrade、恢复或盲目重跑。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence

from app.tasks.mard_catalog import (
    EXPECTED_COLOR_COUNT,
    MardCatalogError,
    build_swatch_png,
    load_manifest,
)
from scripts.release import gatea_backup as backup
from scripts.release import gatea_operations as gatea


APPROVED_MIGRATIONS = gatea.APPROVED_TARGET_M9_CHAIN
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_SOURCE_VERSION = 2
SUPPORTED_SOURCE_VERSIONS = (2, 7, 9)
TARGET_VERSION = 9
M9_ADOPTION_TRANSITION_KIND = "m9-candidate-adoption"
TAKEOVER_RECOVERY_KIND = "prepared-retirement-takeover"
MAX_ADOPTION_RECORD_BYTES = 4 * 1024 * 1024
DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR = Path(
    "/srv/pinkdoohub/gatea/records/m9-acceptance-failures"
)
DEFAULT_RETIREMENT_FAILURE_ARCHIVE_DIR = Path(
    "/srv/pinkdoohub/gatea/records/m9-retirement-failures"
)
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
M7_INVARIANT_KEYS = (
    "external_identities",
    "eligible_wallet_users",
    "wallet_accounts",
    "ineligible_wallet_accounts",
    "wallet_balance",
    "wallet_transactions",
    "recharge_orders",
    "payments",
    "payment_settlements",
    "refunds",
    "store_business_days",
    "reservations",
    "bead_colors",
    "bead_color_slots",
    "bead_color_min_slot",
    "bead_color_max_slot",
    "active_bead_colors",
    "product_kit_colors",
    "reservation_settings",
    "reservation_settings_invalid",
    "reservation_settings_check",
    "reservation_settings_unique",
)
M9_EMPTY_TABLE_INVARIANTS = (
    ("store_tables", 30),
    ("enabled_store_tables", 30),
    ("invalid_table_numbers", 0),
    ("invalid_table_display_names", 0),
    ("invalid_table_qr_token_lengths", 0),
    ("invalid_table_qr_token_characters", 0),
    ("invalid_store_tables", 0),
    ("distinct_table_qr_tokens", 30),
    ("table_sessions", 0),
    ("table_session_timers", 0),
    ("table_occupancies", 0),
)
M9_EMPTY_TABLE_RECONCILE_KEYS = (
    "open_sessions",
    "occupancies",
    "closed_with_occupancy",
    "awaiting_with_timers",
    "active_without_timers",
    "scanned",
    "violations",
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
ADOPTION_RETIREMENT_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "candidate_sha",
        "image_id",
        "source_candidate_sha",
        "source_image_id",
        "lineage_source_candidate_sha",
        "lineage_source_image_id",
        "stage_record_sha256",
        "predecessor_stage_record_sha256",
        "predecessor_activation_record_sha256",
        "predecessor_upgrade_record_sha256",
        "predecessor_upgrade_evidence_sha256",
        "predecessor_upgrade_plan_replay_record_sha256",
        "acceptance_pending_sha256",
        "acceptance_attempt_id_sha256",
        "acceptance_archive_path",
        "acceptance_archive_sha256",
        "live_verification",
        "started_at",
        "phase",
        "secret_values_recorded",
        "completed_at",
        "passed",
    }
)
# A takeover retirement is still the same immutable M9 adoption retirement
# record, but carries the identity of the superseded candidate's prepared
# retirement journal.  Keep this local to the upgrader: the upgrader must not
# accept an arbitrary recovery/bypass payload merely because it has a digest.
TAKEOVER_RETIREMENT_FIELDS = frozenset(
    {
        "recovery_kind",
        "superseded_retirement_candidate_sha",
        "superseded_retirement_image_id",
        "superseded_retirement_stage_record_sha256",
        "superseded_retirement_pending_sha256",
        "superseded_retirement_archive_path",
        "superseded_retirement_archive_sha256",
    }
)
TAKEOVER_RETIREMENT_RECORD_KEYS = (
    ADOPTION_RETIREMENT_RECORD_KEYS | TAKEOVER_RETIREMENT_FIELDS
)
ADOPTION_RETIREMENT_PENDING_RECORD_KEYS = ADOPTION_RETIREMENT_RECORD_KEYS - {
    "completed_at",
    "passed",
}
FAILED_ACCEPTANCE_BUSINESS_COUNTS = {
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
}
FAILED_ACCEPTANCE_CLEANUP_KEYS = frozenset(
    {
        "order_cancelled",
        "fixture_products_offline",
        "synthetic_session_revoked",
        "super_admin_session_revoked",
    }
)
FAILED_ACCEPTANCE_BUSINESS_EVIDENCE_SHA256 = (
    "9f262cb7c7a500cfd3b245f045c9ff8a887a640a6576539b421a61add81c1012"
)
RUNTIME_PREFLIGHT_COMMAND = """import json
from app.core.config import settings
print(json.dumps({
    "app_env": settings.app_env,
    "db_engine": settings.db_engine,
    "jwt_algorithm": settings.jwt_algorithm,
    "table_session_claims_enabled": settings.table_session_claims_enabled,
    "validated": True,
}, sort_keys=True))
"""

# Pin both the mysql client encoding and the non-ASCII suffix bytes. The official
# mysql:8.0.46 CLI otherwise defaults to latin1 in this non-interactive path.
FINAL_DATABASE_STATUS_COMMAND = r"""MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"
export MYSQL_PWD
mysql --default-character-set=utf8mb4 --batch --skip-column-names --raw \
  --host=127.0.0.1 --user=root "$MYSQL_DATABASE" <<'SQL'
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
    WHERE color_code IS NOT NULL AND name IS NOT NULL AND swatch_hex IS NOT NULL
  ),
  'distinct_bead_color_hex', (SELECT COUNT(DISTINCT swatch_hex) FROM bead_colors),
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
  ),
  'store_tables', (SELECT COUNT(*) FROM store_tables),
  'enabled_store_tables', (SELECT COUNT(*) FROM store_tables WHERE is_enabled = 1),
  'invalid_table_numbers', (
    SELECT COUNT(*) FROM store_tables
    WHERE table_no NOT REGEXP '^T(0[1-9]|[12][0-9]|30)$'
  ),
  'invalid_table_display_names', (
    SELECT COUNT(*) FROM store_tables
    WHERE display_name <> CONCAT(
      table_no, CONVERT(0xE58FB7E6A18C USING utf8mb4)
    )
  ),
  'invalid_table_qr_token_lengths', (
    SELECT COUNT(*) FROM store_tables WHERE CHAR_LENGTH(qr_token) <> 32
  ),
  'invalid_table_qr_token_characters', (
    SELECT COUNT(*) FROM store_tables
    WHERE CONVERT(qr_token USING ascii) NOT REGEXP '^[A-Za-z0-9]{32}$'
  ),
  'invalid_store_tables', (
    SELECT COUNT(*) FROM store_tables
    WHERE table_no NOT REGEXP '^T(0[1-9]|[12][0-9]|30)$'
       OR display_name <> CONCAT(
         table_no, CONVERT(0xE58FB7E6A18C USING utf8mb4)
       )
       OR CHAR_LENGTH(qr_token) <> 32
       OR CONVERT(qr_token USING ascii) NOT REGEXP '^[A-Za-z0-9]{32}$'
  ),
  'distinct_table_qr_tokens', (SELECT COUNT(DISTINCT BINARY qr_token) FROM store_tables),
  'table_sessions', (SELECT COUNT(*) FROM table_sessions),
  'table_session_timers', (SELECT COUNT(*) FROM table_session_timers),
  'table_occupancies', (SELECT COUNT(*) FROM table_occupancies)
);
SQL"""

M7_INVARIANT_STATUS_COMMAND = r"""MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"
export MYSQL_PWD
mysql --batch --skip-column-names --raw --host=127.0.0.1 --user=root "$MYSQL_DATABASE" <<'SQL'
SELECT JSON_OBJECT(
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
M7_MARD_CATALOG_STATUS_COMMAND = r"""MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"
export MYSQL_PWD
mysql --batch --skip-column-names --raw --host=127.0.0.1 --user=root "$MYSQL_DATABASE" <<'SQL'
SELECT
  CAST(`slot_no` AS CHAR),
  COALESCE(HEX(`color_code`), '<NULL>'),
  COALESCE(HEX(`name`), '<NULL>'),
  COALESCE(HEX(`swatch_image_url`), '<NULL>'),
  CAST(`sort` AS CHAR),
  CAST(`is_active` + 0 AS CHAR)
FROM `bead_colors`
ORDER BY `slot_no`;
SQL"""
M7_SCHEMA_STATUS_COMMAND = r"""MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"
export MYSQL_PWD
mysql --batch --skip-column-names --raw --host=127.0.0.1 --user=root "$MYSQL_DATABASE" <<'SQL'
SELECT JSON_OBJECT(
  'swatch_hex_columns', (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'bead_colors'
      AND column_name = 'swatch_hex'
  )
);
SQL"""
M7_IMAGE_MODE_MANIFEST_COMMAND = (
    "find /data/images -type f -exec stat -c '%a %n' {} + | "
    "sed 's# /data/images/# #' | sort"
)
M7_MARD_PREFLIGHT_PROFILE = "m7-mard-source-v1"


class GateAUpgradeError(gatea.GateAError):
    """不包含 Secret、PII、业务明细或外部命令原始输出的升级错误。"""


@dataclass(frozen=True, slots=True)
class _BoundBackupRecords:
    """从稳定 fd 读取的 Backup/Restore payload 与同字节摘要。"""

    backup_record: dict[str, Any]
    backup_record_sha256: str
    restore_record: dict[str, Any]
    restore_record_sha256: str


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


def _m7_manifest_contract(
    values: Mapping[str, str],
) -> tuple[tuple[str, ...], dict[str, str], str]:
    try:
        colors = load_manifest(MARD_MANIFEST)
    except MardCatalogError as error:
        raise GateAUpgradeError("Gate A MARD manifest is invalid") from error
    base_url = values.get("PRODUCT_IMAGE_BASE_URL", "").rstrip("/")
    if not base_url:
        raise GateAUpgradeError("Gate A MARD image base URL is unavailable")

    expected_rows: list[str] = []
    expected_images: dict[str, str] = {}
    image_set_digest = hashlib.sha256()
    for color in colors:
        expected_rows.append(
            "\t".join(
                (
                    str(color.slot_no),
                    color.color_code.encode("utf-8").hex().upper(),
                    color.name.encode("utf-8").hex().upper(),
                    f"{base_url}/{color.image_filename}"
                    .encode("utf-8")
                    .hex()
                    .upper(),
                    str(color.sort),
                    "1",
                )
            )
        )
        image_sha256 = hashlib.sha256(build_swatch_png(color.rgb)).hexdigest()
        expected_images[color.image_filename] = image_sha256
        image_set_digest.update(color.image_filename.encode("ascii"))
        image_set_digest.update(b"\0")
        image_set_digest.update(bytes.fromhex(image_sha256))
    if (
        len(expected_rows) != EXPECTED_COLOR_COUNT
        or len(expected_images) != EXPECTED_COLOR_COUNT
    ):
        raise GateAUpgradeError("Gate A MARD manifest cardinality is invalid")
    return tuple(expected_rows), expected_images, image_set_digest.hexdigest()


def _parse_hash_manifest(lines: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in lines:
        parts = line.split(maxsplit=1)
        if (
            len(parts) != 2
            or SHA256_PATTERN.fullmatch(parts[0]) is None
            or not parts[1]
            or parts[1] in parsed
        ):
            raise GateAUpgradeError("Gate A image hash manifest is invalid")
        parsed[parts[1]] = parts[0]
    return parsed


def _parse_mode_manifest(lines: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in lines:
        parts = line.split(maxsplit=1)
        if (
            len(parts) != 2
            or re.fullmatch(r"[0-7]{3,4}", parts[0]) is None
            or not parts[1]
            or parts[1] in parsed
        ):
            raise GateAUpgradeError("Gate A image mode manifest is invalid")
        parsed[parts[1]] = parts[0]
    return parsed


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    """通过共享 durable writer 发布不可覆盖的升级证据。"""

    try:
        backup._write_json_exclusive(path, payload, 0o644)
    except gatea.GateAError as error:
        raise GateAUpgradeError(
            "Gate A upgrade record path is already reserved"
        ) from error


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _validate_published_upgrade_commit(
    *,
    success_path: Path,
    evidence_path: Path,
    success_payload: Mapping[str, Any] | None,
    evidence: Mapping[str, Any],
) -> None:
    """验证已可见 success 是当前 succeeded evidence 的完整提交点。"""

    if success_payload is None:
        raise GateAUpgradeError(
            "Gate A visible upgrade success record has no prepared payload"
        )
    if success_path.is_symlink() or evidence_path.is_symlink():
        raise GateAUpgradeError("Gate A published upgrade commit is invalid")
    try:
        success_bytes = success_path.read_bytes()
        evidence_bytes = evidence_path.read_bytes()
    except OSError as error:
        raise GateAUpgradeError(
            "Gate A published upgrade commit is unavailable"
        ) from error
    evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
    if (
        evidence.get("status") != "succeeded"
        or evidence.get("current_stage") != "completed"
        or success_payload.get("record_type") != "existing-database-upgrade"
        or success_payload.get("passed") is not True
        or success_payload.get("evidence_path") != str(evidence_path)
        or success_payload.get("evidence_sha256") != evidence_sha256
        or success_bytes != _canonical_json_bytes(success_payload)
        or evidence_bytes != _canonical_json_bytes(evidence)
    ):
        raise GateAUpgradeError("Gate A published upgrade commit is invalid")


def _expected_versions(version: int) -> list[str]:
    return list(APPROVED_MIGRATIONS[: version + 1])


def _validate_source_version(source_version: object) -> int:
    if (
        type(source_version) is not int
        or source_version not in SUPPORTED_SOURCE_VERSIONS
    ):
        raise GateAUpgradeError(
            "Gate A source version must be explicitly M2, M7 or M9"
        )
    return source_version


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


def _validate_adoption_confirmations(
    *,
    lineage_source_candidate_sha: str,
    acceptance_retirement_record_sha256: str,
    confirm_lineage_source_sha: str | None,
    confirm_acceptance_retirement_record_sha256: str | None,
) -> None:
    if (
        confirm_lineage_source_sha != lineage_source_candidate_sha
        or confirm_acceptance_retirement_record_sha256
        != acceptance_retirement_record_sha256
    ):
        raise GateAUpgradeError(
            "Gate A M9 adoption confirmations must exactly match lineage and "
            "acceptance retirement evidence"
        )


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _require_adoption_record_metadata(
    metadata: os.stat_result,
    description: str,
) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o644
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_nlink != 1
        or metadata.st_size > MAX_ADOPTION_RECORD_BYTES
    ):
        raise GateAUpgradeError(f"Gate A {description} has unsafe metadata")


def _require_takeover_archive_metadata(
    metadata: os.stat_result,
    description: str,
) -> None:
    """Require the root-only, no-clobber form used by takeover archives."""

    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_nlink != 1
        or metadata.st_size > MAX_ADOPTION_RECORD_BYTES
    ):
        raise GateAUpgradeError(f"Gate A {description} has unsafe metadata")


def _require_takeover_archive_directory(path: Path, description: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise GateAUpgradeError(f"Gate A {description} is unavailable") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != 0
        or metadata.st_gid != 0
    ):
        raise GateAUpgradeError(f"Gate A {description} has unsafe metadata")


def _json_object_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate JSON key")
        payload[key] = value
    return payload


def _load_bound_json_with_sha256(
    path: Path,
    description: str,
) -> tuple[dict[str, Any], str]:
    """通过 no-follow fd 稳定读取不可变 Record，摘要与解析共用同一批字节。"""

    descriptor: int | None = None
    try:
        path_metadata = path.lstat()
        _require_adoption_record_metadata(path_metadata, description)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before_metadata = os.fstat(descriptor)
        _require_adoption_record_metadata(before_metadata, description)
        if _file_identity(path_metadata) != _file_identity(before_metadata):
            raise GateAUpgradeError(
                f"Gate A {description} changed during validation"
            )
        chunks: list[bytes] = []
        remaining = MAX_ADOPTION_RECORD_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise GateAUpgradeError(f"Gate A {description} is unexpectedly large")
        after_metadata = os.fstat(descriptor)
        final_metadata = path.lstat()
        _require_adoption_record_metadata(after_metadata, description)
        _require_adoption_record_metadata(final_metadata, description)
        if not (
            _file_identity(before_metadata)
            == _file_identity(after_metadata)
            == _file_identity(final_metadata)
        ):
            raise GateAUpgradeError(
                f"Gate A {description} changed during validation"
            )
        content = b"".join(chunks)
        digest_before = hashlib.sha256(content).hexdigest()
        digest_after = hashlib.sha256(content).hexdigest()
        if digest_before != digest_after:
            raise GateAUpgradeError(
                f"Gate A {description} digest changed during validation"
            )
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicates,
        )
    except GateAUpgradeError:
        raise
    except (
        FileNotFoundError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise GateAUpgradeError(f"Gate A {description} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise GateAUpgradeError(f"Gate A {description} is invalid")
    return payload, digest_after


def _load_bound_json(path: Path, description: str) -> dict[str, Any]:
    payload, _ = _load_bound_json_with_sha256(path, description)
    return payload


def _load_bound_takeover_archive_with_sha256(
    path: Path,
    description: str,
) -> tuple[dict[str, Any], str]:
    """Read a takeover archive through one stable fd and bind its bytes.

    Candidate/upgrade Records are deliberately 0644.  A prepared retirement
    journal archive is different: it contains the original recovery journal
    and must remain a root-owned 0600 file with one link.  Do not route it
    through ``_load_bound_json_with_sha256`` because that would either weaken
    this contract or accidentally accept a normal Record as the archive.
    """

    descriptor: int | None = None
    try:
        initial = path.lstat()
        _require_takeover_archive_metadata(initial, description)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        _require_takeover_archive_metadata(before, description)
        if _file_identity(initial) != _file_identity(before):
            raise GateAUpgradeError(f"Gate A {description} changed during validation")
        chunks: list[bytes] = []
        remaining = MAX_ADOPTION_RECORD_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise GateAUpgradeError(f"Gate A {description} is unexpectedly large")
        after = os.fstat(descriptor)
        final = path.lstat()
        _require_takeover_archive_metadata(after, description)
        _require_takeover_archive_metadata(final, description)
        if not (
            _file_identity(before)
            == _file_identity(after)
            == _file_identity(final)
        ):
            raise GateAUpgradeError(f"Gate A {description} changed during validation")
        content = b"".join(chunks)
        digest = hashlib.sha256(content).hexdigest()
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicates,
        )
    except GateAUpgradeError:
        raise
    except (
        FileNotFoundError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise GateAUpgradeError(f"Gate A {description} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise GateAUpgradeError(f"Gate A {description} is invalid")
    return payload, digest


def _require_sha256(value: object, description: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise GateAUpgradeError(f"Gate A {description} digest is invalid")
    return value


def _adoption_record_paths(
    record_dir: Path,
    *,
    source_candidate_sha: str,
    candidate_sha: str,
) -> dict[str, Path]:
    return {
        "stage": record_dir / f"{candidate_sha}.candidate-stage.json",
        "activation": record_dir / f"{candidate_sha}.config-activation.json",
        "retirement": record_dir / f"{candidate_sha}.acceptance-retirement.json",
        "predecessor_stage": (
            record_dir / f"{source_candidate_sha}.candidate-stage.json"
        ),
        "predecessor_activation": (
            record_dir / f"{source_candidate_sha}.config-activation.json"
        ),
        "predecessor_upgrade": gatea._upgrade_marker(
            record_dir, source_candidate_sha
        ),
        "predecessor_evidence": record_dir
        / f"{source_candidate_sha}.existing-database-upgrade.evidence.json",
        "predecessor_replay": gatea._upgrade_replay_marker(
            record_dir, source_candidate_sha
        ),
    }


def _acceptance_failure_archive_path(
    archive_dir: Path,
    source_candidate_sha: str,
    acceptance_pending_sha256: str,
) -> Path:
    return archive_dir / (
        "gatea-m9-failed-acceptance-"
        f"{source_candidate_sha}-{acceptance_pending_sha256}.json"
    )


def _retirement_failure_archive_path(
    archive_dir: Path,
    superseded_candidate_sha: str,
    retirement_pending_sha256: str,
) -> Path:
    return archive_dir / (
        "gatea-m9-superseded-retirement-"
        f"{superseded_candidate_sha}-{retirement_pending_sha256}.json"
    )


def _validate_takeover_retirement_archive(
    *,
    release_record_dir: Path,
    acceptance_failure_archive_dir: Path,
    retirement_failure_archive_dir: Path,
    retirement: Mapping[str, Any],
    target_stage: Mapping[str, Any],
    candidate_sha: str,
    source_candidate_sha: str,
    source_image_id: str,
    lineage_source_candidate_sha: str,
    lineage_source_image_id: str,
    predecessor_digests: Mapping[str, str],
) -> None:
    """Validate the archived prepared retirement journal carried by takeover.

    The archive is B's *prepared* journal, not a second acceptance allowance.
    Its candidate/image/stage/pending identities must therefore agree with the
    takeover fields on both B's stage and the target retirement Record.  The
    embedded acceptance archive is also reopened by digest, so retaining only
    a retirement Record cannot make a broken A archive appear valid.
    """

    superseded_candidate_sha = retirement.get(
        "superseded_retirement_candidate_sha"
    )
    superseded_image_id = retirement.get("superseded_retirement_image_id")
    superseded_stage_sha256 = retirement.get(
        "superseded_retirement_stage_record_sha256"
    )
    superseded_pending_sha256 = retirement.get(
        "superseded_retirement_pending_sha256"
    )
    archive_path_value = retirement.get("superseded_retirement_archive_path")
    archive_sha256 = retirement.get("superseded_retirement_archive_sha256")
    if (
        superseded_candidate_sha != target_stage.get(
            "superseded_retirement_candidate_sha"
        )
        or superseded_stage_sha256 != target_stage.get(
            "superseded_retirement_stage_record_sha256"
        )
        or superseded_pending_sha256 != target_stage.get(
            "superseded_retirement_pending_sha256"
        )
        or not isinstance(superseded_candidate_sha, str)
        or SHA_PATTERN.fullmatch(superseded_candidate_sha) is None
        or superseded_candidate_sha in {candidate_sha, source_candidate_sha}
        or not isinstance(superseded_image_id, str)
        or not superseded_image_id
        or not isinstance(archive_path_value, str)
        or not archive_path_value
        or not Path(archive_path_value).is_absolute()
        or SHA256_PATTERN.fullmatch(str(superseded_stage_sha256)) is None
        or SHA256_PATTERN.fullmatch(str(superseded_pending_sha256)) is None
        or SHA256_PATTERN.fullmatch(str(archive_sha256)) is None
        or archive_sha256 != superseded_pending_sha256
    ):
        raise GateAUpgradeError("Gate A takeover retirement binding is invalid")

    superseded_stage_path = (
        release_record_dir
        / f"{superseded_candidate_sha}.candidate-stage.json"
    )
    superseded_stage, loaded_stage_sha256 = _load_bound_json_with_sha256(
        superseded_stage_path,
        "superseded retirement stage record",
    )
    if (
        loaded_stage_sha256 != superseded_stage_sha256
        or superseded_stage.get("schema_version") != 2
        or superseded_stage.get("transition_kind")
        != M9_ADOPTION_TRANSITION_KIND
        or superseded_stage.get("record_type") != "gatea-candidate-stage"
        or superseded_stage.get("passed") is not True
        or superseded_stage.get("candidate_sha") != superseded_candidate_sha
        or superseded_stage.get("image_id") != superseded_image_id
        or superseded_stage.get("superseded_candidate_sha")
        != source_candidate_sha
        or superseded_stage.get("failed_acceptance_sha256")
        != retirement.get("acceptance_pending_sha256")
        or superseded_stage.get("secret_values_recorded") is not False
    ):
        raise GateAUpgradeError(
            "Gate A superseded retirement stage record is invalid"
        )

    expected_archive_path = _retirement_failure_archive_path(
        retirement_failure_archive_dir,
        superseded_candidate_sha,
        str(superseded_pending_sha256),
    )
    archive_path = Path(archive_path_value)
    if archive_path != expected_archive_path:
        raise GateAUpgradeError(
            "Gate A superseded retirement archive path is invalid"
        )
    _require_takeover_archive_directory(
        retirement_failure_archive_dir,
        "superseded retirement archive directory",
    )
    archived, archived_sha256 = _load_bound_takeover_archive_with_sha256(
        archive_path,
        "superseded retirement archive",
    )
    if archived_sha256 != archive_sha256:
        raise GateAUpgradeError(
            "Gate A superseded retirement archive digest is invalid"
        )

    # This is deliberately an exact schema-v1 prepared journal.  In
    # particular, a completed retirement Record, an arbitrary JSON digest, or
    # a takeover journal from another candidate is not an own-recovery input.
    if (
        set(archived) != ADOPTION_RETIREMENT_PENDING_RECORD_KEYS
        or archived.get("schema_version") != 1
        or archived.get("record_type")
        != "gatea-m9-failed-acceptance-retirement-pending"
        or archived.get("candidate_sha") != superseded_candidate_sha
        or archived.get("image_id") != superseded_image_id
        or archived.get("source_candidate_sha") != source_candidate_sha
        or archived.get("source_image_id") != source_image_id
        or archived.get("lineage_source_candidate_sha")
        != lineage_source_candidate_sha
        or archived.get("lineage_source_image_id") != lineage_source_image_id
        or archived.get("stage_record_sha256") != superseded_stage_sha256
        or any(
            archived.get(key) != value
            for key, value in predecessor_digests.items()
        )
        or archived.get("phase") != "prepared"
        or archived.get("live_verification") is not None
        or not isinstance(archived.get("started_at"), str)
        or archived.get("secret_values_recorded") is not False
        or archived.get("acceptance_pending_sha256")
        != retirement.get("acceptance_pending_sha256")
        or archived.get("acceptance_attempt_id_sha256")
        != retirement.get("acceptance_attempt_id_sha256")
        or archived.get("acceptance_archive_path")
        != retirement.get("acceptance_archive_path")
        or archived.get("acceptance_archive_sha256")
        != retirement.get("acceptance_archive_sha256")
    ):
        raise GateAUpgradeError("Gate A superseded retirement archive is invalid")
    _parse_utc_timestamp(
        archived.get("started_at"),
        "superseded retirement start",
    )

    acceptance_archive_value = archived.get("acceptance_archive_path")
    acceptance_archive_sha256 = archived.get("acceptance_archive_sha256")
    expected_acceptance_archive = _acceptance_failure_archive_path(
        acceptance_failure_archive_dir,
        source_candidate_sha,
        str(retirement.get("acceptance_pending_sha256")),
    )
    if (
        not isinstance(acceptance_archive_value, str)
        or Path(acceptance_archive_value) != expected_acceptance_archive
        or SHA256_PATTERN.fullmatch(str(acceptance_archive_sha256)) is None
    ):
        raise GateAUpgradeError("Gate A acceptance archive binding is invalid")
    _require_takeover_archive_directory(
        acceptance_failure_archive_dir,
        "acceptance archive directory",
    )
    failed_acceptance, reopened_acceptance_sha256 = (
        _load_bound_takeover_archive_with_sha256(
            expected_acceptance_archive,
            "acceptance archive",
        )
    )
    cleanup = failed_acceptance.get("cleanup")
    attempt_id = failed_acceptance.get("attempt_id")
    if (
        reopened_acceptance_sha256 != acceptance_archive_sha256
        or reopened_acceptance_sha256
        != retirement.get("acceptance_pending_sha256")
        or failed_acceptance.get("schema_version") != 3
        or failed_acceptance.get("record_type")
        != "gatea-m9-internal-acceptance-pending"
        or failed_acceptance.get("environment") != "gatea"
        or failed_acceptance.get("candidate_sha") != source_candidate_sha
        or failed_acceptance.get("operations_sha") != source_candidate_sha
        or failed_acceptance.get("image_id") != source_image_id
        or failed_acceptance.get("source_candidate_sha")
        != lineage_source_candidate_sha
        or failed_acceptance.get("attempt_id_sha256")
        != retirement.get("acceptance_attempt_id_sha256")
        or not isinstance(attempt_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None
        or failed_acceptance.get("attempt_id_sha256")
        != hashlib.sha256(attempt_id.encode("utf-8")).hexdigest()
        or failed_acceptance.get("stage") != "order_created"
        or failed_acceptance.get("failure") is not True
        or failed_acceptance.get("payment_committed") is not False
        or failed_acceptance.get("session_released") is not False
        or any(
            failed_acceptance.get(field) is not False
            for field in (
                "claim_replay_verified",
                "payment_replay_verified",
                "admin_visibility_verified",
                "release_replay_verified",
            )
        )
        or failed_acceptance.get("passed") is not False
        or failed_acceptance.get("secret_values_recorded") is not False
        or failed_acceptance.get("source_volume_restored") is not False
        or not isinstance(cleanup, dict)
        or set(cleanup) != FAILED_ACCEPTANCE_CLEANUP_KEYS
        or any(value is not True for value in cleanup.values())
    ):
        raise GateAUpgradeError("Gate A acceptance archive is invalid")


def _validate_m9_adoption_lineage(
    *,
    release_record_dir: Path,
    acceptance_failure_archive_dir: Path = DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    retirement_failure_archive_dir: Path = DEFAULT_RETIREMENT_FAILURE_ARCHIVE_DIR,
    backup_id: str,
    bound_backup_records: _BoundBackupRecords,
    manifest_sha256: str,
    candidate_sha: str,
    image_id: str,
    source_candidate_sha: str,
    source_image_id: str,
    lineage_source_candidate_sha: str,
    acceptance_retirement_record_sha256: str,
    require_activation: bool,
) -> dict[str, Any]:
    """将 M9 adoption 绑定到 A 的完整 M7→M9 证据链与退役证据。"""

    if (
        SHA_PATTERN.fullmatch(lineage_source_candidate_sha) is None
        or lineage_source_candidate_sha
        in {source_candidate_sha, candidate_sha}
    ):
        raise GateAUpgradeError("Gate A M9 adoption lineage source is invalid")
    acceptance_retirement_record_sha256 = _require_sha256(
        acceptance_retirement_record_sha256,
        "acceptance retirement record",
    )
    paths = _adoption_record_paths(
        release_record_dir,
        source_candidate_sha=source_candidate_sha,
        candidate_sha=candidate_sha,
    )

    stage, stage_record_sha256 = _load_bound_json_with_sha256(
        paths["stage"], "candidate stage record"
    )
    takeover_stage = stage.get("schema_version") == 3
    superseded_retirement_candidate_sha = stage.get(
        "superseded_retirement_candidate_sha"
    )
    if (
        stage.get("schema_version") not in {2, 3}
        or stage.get("transition_kind") != M9_ADOPTION_TRANSITION_KIND
        or stage.get("record_type") != "gatea-candidate-stage"
        or stage.get("passed") is not True
        or stage.get("candidate_sha") != candidate_sha
        or stage.get("image_id") != image_id
        or stage.get("superseded_candidate_sha") != source_candidate_sha
        or SHA256_PATTERN.fullmatch(
            str(stage.get("failed_acceptance_sha256", ""))
        )
        is None
        or stage.get("secret_values_recorded") is not False
        or (
            takeover_stage
            and (
                stage.get("recovery_kind")
                != TAKEOVER_RECOVERY_KIND
                or SHA_PATTERN.fullmatch(
                    str(superseded_retirement_candidate_sha or "")
                )
                is None
                or superseded_retirement_candidate_sha
                in {source_candidate_sha, candidate_sha}
                or SHA256_PATTERN.fullmatch(
                    str(stage.get("superseded_retirement_stage_record_sha256", ""))
                )
                is None
                or SHA256_PATTERN.fullmatch(
                    str(stage.get("superseded_retirement_pending_sha256", ""))
                )
                is None
            )
        )
        or (
            not takeover_stage
            and stage.get("schema_version") != 2
        )
    ):
        raise GateAUpgradeError("Gate A candidate stage record is invalid")
    predecessor_stage, predecessor_stage_record_sha256 = (
        _load_bound_json_with_sha256(
            paths["predecessor_stage"], "predecessor stage record"
        )
    )
    if (
        predecessor_stage.get("schema_version") != 1
        or predecessor_stage.get("record_type") != "gatea-candidate-stage"
        or predecessor_stage.get("passed") is not True
        or predecessor_stage.get("candidate_sha") != source_candidate_sha
        or predecessor_stage.get("image_id") != source_image_id
        or predecessor_stage.get("secret_values_recorded") is not False
    ):
        raise GateAUpgradeError("Gate A predecessor stage record is invalid")

    predecessor_upgrade_raw, predecessor_upgrade_record_sha256 = (
        _load_bound_json_with_sha256(
            paths["predecessor_upgrade"], "predecessor upgrade record"
        )
    )
    predecessor_upgrade = gatea._require_upgrade_record(
        record_dir=release_record_dir,
        candidate_sha=source_candidate_sha,
        image_id=source_image_id,
    )
    lineage_source_image_id = predecessor_upgrade.get("source_image_id")
    if (
        predecessor_upgrade != predecessor_upgrade_raw
        or predecessor_upgrade.get("schema_version") != 1
        or "transition_kind" in predecessor_upgrade
        or predecessor_upgrade.get("source_version") != 7
        or predecessor_upgrade.get("source_candidate_sha")
        != lineage_source_candidate_sha
        or not isinstance(lineage_source_image_id, str)
        or not lineage_source_image_id
        or predecessor_upgrade.get("source_aerich_versions")
        != _expected_versions(7)
        or predecessor_upgrade.get("target_aerich_versions")
        != _expected_versions(9)
    ):
        raise GateAUpgradeError("Gate A predecessor upgrade lineage is invalid")

    predecessor_activation, predecessor_activation_record_sha256 = (
        _load_bound_json_with_sha256(
            paths["predecessor_activation"], "predecessor activation record"
        )
    )
    if (
        predecessor_activation.get("schema_version") != 1
        or "transition_kind" in predecessor_activation
        or predecessor_activation.get("record_type") != "gatea-config-activation"
        or predecessor_activation.get("passed") is not True
        or predecessor_activation.get("source_candidate_sha")
        != lineage_source_candidate_sha
        or predecessor_activation.get("candidate_sha") != source_candidate_sha
        or predecessor_activation.get("image_id") != source_image_id
        or predecessor_activation.get("stage_record_sha256")
        != predecessor_stage_record_sha256
        or predecessor_activation.get("backup_id")
        != predecessor_upgrade.get("backup_id")
        or predecessor_activation.get("manifest_sha256")
        != predecessor_upgrade.get("manifest_sha256")
        or predecessor_activation.get("secret_values_recorded") is not False
        or predecessor_activation.get("passed") is not True
    ):
        raise GateAUpgradeError("Gate A predecessor activation record is invalid")

    predecessor_evidence, predecessor_upgrade_evidence_sha256 = (
        _load_bound_json_with_sha256(
            paths["predecessor_evidence"], "predecessor upgrade evidence"
        )
    )
    predecessor_replay, predecessor_upgrade_plan_replay_record_sha256 = (
        _load_bound_json_with_sha256(
            paths["predecessor_replay"], "predecessor upgrade replay record"
        )
    )
    validated_predecessor_replay = gatea._require_m9_upgrade_replay_record(
        record_dir=release_record_dir,
        candidate_sha=source_candidate_sha,
        image_id=source_image_id,
        upgrade_record=predecessor_upgrade,
    )
    if (
        predecessor_evidence.get("status") != "succeeded"
        or validated_predecessor_replay != predecessor_replay
    ):
        raise GateAUpgradeError("Gate A predecessor upgrade evidence is invalid")
    predecessor_digests = {
        "predecessor_stage_record_sha256": predecessor_stage_record_sha256,
        "predecessor_activation_record_sha256": (
            predecessor_activation_record_sha256
        ),
        "predecessor_upgrade_record_sha256": predecessor_upgrade_record_sha256,
        "predecessor_upgrade_evidence_sha256": (
            predecessor_upgrade_evidence_sha256
        ),
        "predecessor_upgrade_plan_replay_record_sha256": (
            predecessor_upgrade_plan_replay_record_sha256
        ),
    }

    retirement, retirement_record_sha256 = _load_bound_json_with_sha256(
        paths["retirement"], "acceptance retirement record"
    )
    live_verification = retirement.get("live_verification")
    live_reconcile = (
        live_verification.get("table_reconcile")
        if isinstance(live_verification, dict)
        else None
    )
    live_wallet = (
        live_verification.get("wallet_reconcile")
        if isinstance(live_verification, dict)
        else None
    )
    live_database = (
        live_verification.get("database_snapshot")
        if isinstance(live_verification, dict)
        else None
    )
    live_business = (
        live_verification.get("business_verification")
        if isinstance(live_verification, dict)
        else None
    )
    takeover_retirement = retirement.get("schema_version") == 2
    if (
        set(retirement)
        != (
            TAKEOVER_RETIREMENT_RECORD_KEYS
            if takeover_retirement
            else ADOPTION_RETIREMENT_RECORD_KEYS
        )
        or retirement_record_sha256 != acceptance_retirement_record_sha256
        or retirement.get("schema_version") not in {1, 2}
        or retirement.get("record_type")
        != "gatea-m9-failed-acceptance-retirement"
        or retirement.get("passed") is not True
        or retirement.get("phase") != "record-published"
        or retirement.get("candidate_sha") != candidate_sha
        or retirement.get("image_id") != image_id
        or retirement.get("source_candidate_sha") != source_candidate_sha
        or retirement.get("source_image_id") != source_image_id
        or retirement.get("lineage_source_candidate_sha")
        != lineage_source_candidate_sha
        or retirement.get("lineage_source_image_id") != lineage_source_image_id
        or retirement.get("stage_record_sha256") != stage_record_sha256
        or any(
            retirement.get(key) != value
            for key, value in predecessor_digests.items()
        )
        or any(
            SHA256_PATTERN.fullmatch(str(retirement.get(key, ""))) is None
            for key in (
                "acceptance_pending_sha256",
                "acceptance_attempt_id_sha256",
                "acceptance_archive_sha256",
            )
        )
        or retirement.get("acceptance_pending_sha256")
        != stage.get("failed_acceptance_sha256")
        or retirement.get("acceptance_archive_sha256")
        != stage.get("failed_acceptance_sha256")
        or not isinstance(live_verification, dict)
        or set(live_verification)
        != {
            "business_verification",
            "database_snapshot",
            "runtime_services",
            "database_services_healthy",
            "writer_services_stopped",
            "table_reconcile",
            "wallet_reconcile",
            "checked_at",
        }
        or not isinstance(live_business, dict)
        or set(live_business)
        != {
            "schema_version",
            "passed",
            "counts",
            "evidence_sha256",
            "secret_values_recorded",
        }
        or live_business.get("schema_version")
        not in ({2} if takeover_retirement else {1, 2})
        or live_business.get("passed") is not True
        or live_business.get("counts") != FAILED_ACCEPTANCE_BUSINESS_COUNTS
        or live_business.get("evidence_sha256")
        != FAILED_ACCEPTANCE_BUSINESS_EVIDENCE_SHA256
        or live_business.get("secret_values_recorded") is not False
        or not isinstance(live_database, dict)
        or live_database.get("aerich_versions") != _expected_versions(9)
        or live_verification.get("runtime_services")
        != ["mysql", "redis", "app", "table-sweeper", "nginx"]
        or live_verification.get("database_services_healthy")
        != ["mysql", "redis"]
        or live_verification.get("writer_services_stopped")
        != ["nginx", "table-sweeper", "app"]
        or not isinstance(live_reconcile, dict)
        or not isinstance(live_wallet, dict)
        or set(live_wallet) != {"scanned", "mismatches", "violations"}
        or any(type(value) is not int or value < 0 for value in live_wallet.values())
        or live_wallet.get("scanned", 0) <= 0
        or live_wallet.get("mismatches") != 0
        or live_wallet.get("violations") != 0
        or retirement.get("secret_values_recorded") is not False
        or (
            takeover_retirement
            and (
                not takeover_stage
                or retirement.get("recovery_kind")
                != TAKEOVER_RECOVERY_KIND
                or retirement.get("superseded_retirement_candidate_sha")
                != stage.get("superseded_retirement_candidate_sha")
                or retirement.get("superseded_retirement_stage_record_sha256")
                != stage.get("superseded_retirement_stage_record_sha256")
                or retirement.get("superseded_retirement_pending_sha256")
                != stage.get("superseded_retirement_pending_sha256")
                or not isinstance(
                    retirement.get("superseded_retirement_image_id"), str
                )
                or not retirement.get("superseded_retirement_image_id")
                or SHA256_PATTERN.fullmatch(
                    str(retirement.get("superseded_retirement_archive_sha256", ""))
                )
                is None
            )
        )
        or (not takeover_retirement and takeover_stage)
    ):
        raise GateAUpgradeError("Gate A acceptance retirement record is invalid")
    _validate_adoption_table_reconcile_result(live_reconcile)
    if any(live_reconcile.values()):
        raise GateAUpgradeError("Gate A acceptance retirement record is invalid")
    _parse_utc_timestamp(live_verification.get("checked_at"), "retirement check")
    retirement_started_at = _parse_utc_timestamp(
        retirement.get("started_at"), "retirement start"
    )
    retirement_completed_at = _parse_utc_timestamp(
        retirement.get("completed_at"), "retirement completion"
    )
    if retirement_completed_at < retirement_started_at:
        raise GateAUpgradeError("Gate A acceptance retirement time is invalid")

    if takeover_retirement:
        _validate_takeover_retirement_archive(
            release_record_dir=release_record_dir,
            acceptance_failure_archive_dir=acceptance_failure_archive_dir,
            retirement_failure_archive_dir=retirement_failure_archive_dir,
            retirement=retirement,
            target_stage=stage,
            candidate_sha=candidate_sha,
            source_candidate_sha=source_candidate_sha,
            source_image_id=source_image_id,
            lineage_source_candidate_sha=lineage_source_candidate_sha,
            lineage_source_image_id=str(lineage_source_image_id),
            predecessor_digests=predecessor_digests,
        )

    activation_record_sha256: str | None = None
    if require_activation:
        activation, activation_record_sha256 = _load_bound_json_with_sha256(
            paths["activation"], "candidate activation record"
        )
        expected_activation = {
            "source_candidate_sha": source_candidate_sha,
            "source_image_id": source_image_id,
            "candidate_sha": candidate_sha,
            "image_id": image_id,
            "lineage_source_candidate_sha": lineage_source_candidate_sha,
            "lineage_source_image_id": lineage_source_image_id,
            "backup_id": backup_id,
            "manifest_sha256": manifest_sha256,
            "stage_record_sha256": stage_record_sha256,
            "acceptance_retirement_record_sha256": (
                acceptance_retirement_record_sha256
            ),
            **predecessor_digests,
        }
        if (
            activation.get("schema_version") != 2
            or activation.get("transition_kind") != M9_ADOPTION_TRANSITION_KIND
            or activation.get("record_type") != "gatea-config-activation"
            or activation.get("passed") is not True
            or activation.get("changed_keys") != ["GATEA_APP_IMAGE"]
            or any(
                activation.get(key) != value
                for key, value in expected_activation.items()
            )
            or activation.get("config_values_recorded") is not False
            or activation.get("secret_values_recorded") is not False
        ):
            raise GateAUpgradeError("Gate A candidate activation record is invalid")
        activation_started_at = _parse_utc_timestamp(
            activation.get("started_at"), "candidate activation start"
        )
        activation_completed_at = _parse_utc_timestamp(
            activation.get("completed_at"), "candidate activation completion"
        )
        if activation_completed_at < activation_started_at:
            raise GateAUpgradeError("Gate A candidate activation time is invalid")

    context: dict[str, Any] = {
        "stage_record_sha256": stage_record_sha256,
        "activation_record_sha256": activation_record_sha256,
        "lineage_source_candidate_sha": lineage_source_candidate_sha,
        "lineage_source_image_id": lineage_source_image_id,
        "acceptance_retirement_record_sha256": (
            acceptance_retirement_record_sha256
        ),
        "backup_record_sha256": bound_backup_records.backup_record_sha256,
        "restore_record_sha256": bound_backup_records.restore_record_sha256,
        **predecessor_digests,
    }
    return context


def _validate_restore_record(
    *,
    payload: dict[str, Any],
    backup_id: str,
    source_candidate_sha: str,
    backup_completed_at: datetime,
    now: datetime,
    backup_record_sha256: str,
    mysql_artifact_sha256: str,
    image_artifact_sha256: str,
    expected_m7_content_snapshot: Mapping[str, Any] | None = None,
    expected_m8_swatch_content_snapshot: Mapping[str, Any] | None = None,
    expected_m9_table_content_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if (
        payload.get("schema_version") != 1
        or payload.get("backup_id") != backup_id
        or payload.get("candidate_sha") != source_candidate_sha
        or payload.get("restore_project") != backup.restore_project(backup_id)
        or payload.get("backup_record_sha256") != backup_record_sha256
        or payload.get("mysql_artifact_sha256") != mysql_artifact_sha256
        or payload.get("image_artifact_sha256") != image_artifact_sha256
        or payload.get("host_ports_published") is not False
        or any(payload.get(field) is not True for field in RESTORE_TRUE_FIELDS)
    ):
        raise GateAUpgradeError("Gate A restore PASS record is invalid")
    if expected_m7_content_snapshot is not None:
        try:
            expected_m7_content = backup._validate_m7_content_snapshot(
                expected_m7_content_snapshot
            )
            restored_m7_content = backup._validate_m7_content_snapshot(
                payload.get("m7_content_snapshot")
            )
        except gatea.GateAError as error:
            raise GateAUpgradeError("Gate A restore PASS record is invalid") from error
        if (
            payload.get("m7_content_matches") is not True
            or restored_m7_content != expected_m7_content
        ):
            raise GateAUpgradeError("Gate A restore PASS record is invalid")
    if expected_m9_table_content_snapshot is not None:
        try:
            expected_m9_content = backup._validate_m9_table_content_snapshot(
                expected_m9_table_content_snapshot
            )
            restored_m9_content = backup._validate_m9_table_content_snapshot(
                payload.get("m9_table_content_snapshot")
            )
        except gatea.GateAError as error:
            raise GateAUpgradeError("Gate A restore PASS record is invalid") from error
        if (
            payload.get("m9_table_content_matches") is not True
            or restored_m9_content != expected_m9_content
        ):
            raise GateAUpgradeError("Gate A restore PASS record is invalid")
    if expected_m8_swatch_content_snapshot is not None:
        try:
            expected_m8_swatch = backup._validate_m8_swatch_content_snapshot(
                expected_m8_swatch_content_snapshot
            )
            restored_m8_swatch = backup._validate_m8_swatch_content_snapshot(
                payload.get("m8_swatch_content_snapshot")
            )
        except gatea.GateAError as error:
            raise GateAUpgradeError("Gate A restore PASS record is invalid") from error
        if (
            payload.get("m8_swatch_content_matches") is not True
            or restored_m8_swatch != expected_m8_swatch
        ):
            raise GateAUpgradeError("Gate A restore PASS record is invalid")
    completed_at = _parse_utc_timestamp(
        payload.get("completed_at"), "restore completion"
    )
    if (
        completed_at < backup_completed_at
        or completed_at > now + FUTURE_CLOCK_TOLERANCE
    ):
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
    require_m8_swatch_content_snapshot: bool = False,
    enforce_backup_max_age: bool = True,
) -> _BoundBackupRecords:
    backup._validate_backup_directories(
        values=values,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
    )
    pending_path = backup_record_dir / f".{backup_id}.pending.json"
    if pending_path.exists() or pending_path.is_symlink():
        raise GateAUpgradeError(
            "Gate A backup pending journal requires manual review"
        )
    payload, backup_record_sha256 = _load_bound_json_with_sha256(
        backup_record_dir / f"{backup_id}.json",
        "verified backup record",
    )
    try:
        payload, database_path, image_path = backup._validate_loaded_backup_record(
            payload=payload,
            backup_id=backup_id,
            backup_root=backup_root,
        )
    except gatea.GateAError as error:
        raise GateAUpgradeError("Gate A verified backup record is invalid") from error
    mysql_artifact_sha256 = backup._sha256(database_path)
    image_artifact_sha256 = backup._sha256(image_path)
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
    expected_m8_swatch_content_snapshot: Mapping[str, Any] | None = None
    if require_m8_swatch_content_snapshot:
        try:
            expected_m8_swatch_content_snapshot = (
                backup._validate_m8_swatch_content_snapshot(
                    payload.get("m8_swatch_content_snapshot")
                )
            )
        except gatea.GateAError as error:
            raise GateAUpgradeError(
                "Gate A M9 adoption backup lacks M8 swatch content evidence"
            ) from error
    now = _utc_now()
    completed_at = _parse_utc_timestamp(
        payload.get("completed_at"), "backup completion"
    )
    if (
        completed_at > now + FUTURE_CLOCK_TOLERANCE
        or (
            enforce_backup_max_age
            and now - completed_at > MAX_BACKUP_AGE
        )
    ):
        raise GateAUpgradeError("Gate A backup must have completed within 24 hours")
    restore_payload, restore_record_sha256 = _load_bound_json_with_sha256(
        restore_record_dir / f"{backup_id}.json",
        "restore PASS record",
    )
    restore_payload = _validate_restore_record(
        payload=restore_payload,
        backup_id=backup_id,
        source_candidate_sha=source_candidate_sha,
        backup_completed_at=completed_at,
        now=now,
        backup_record_sha256=backup_record_sha256,
        mysql_artifact_sha256=mysql_artifact_sha256,
        image_artifact_sha256=image_artifact_sha256,
        expected_m7_content_snapshot=(
            payload.get("m7_content_snapshot")
            if backup._requires_m7_content_snapshot(payload["database_snapshot"])
            else None
        ),
        expected_m8_swatch_content_snapshot=(
            expected_m8_swatch_content_snapshot
            if require_m8_swatch_content_snapshot
            else payload.get("m8_swatch_content_snapshot")
        ),
        expected_m9_table_content_snapshot=(
            payload.get("m9_table_content_snapshot")
            if backup._requires_m9_table_content_snapshot(
                payload["database_snapshot"]
            )
            else None
        ),
    )
    return _BoundBackupRecords(
        backup_record=payload,
        backup_record_sha256=backup_record_sha256,
        restore_record=restore_payload,
        restore_record_sha256=restore_record_sha256,
    )


def _ensure_stopped(rows: Sequence[Mapping[str, Any]], *services: str) -> None:
    by_service = {str(row.get("Service")): row for row in rows}
    for service in services:
        row = by_service.get(service)
        if row is None:
            raise GateAUpgradeError(f"Gate A service {service} is unavailable")
        if str(row.get("State", "")).lower() not in {"exited", "stopped"}:
            raise GateAUpgradeError(f"Gate A service {service} did not stop")


def _ensure_not_running(rows: Sequence[Mapping[str, Any]], *services: str) -> None:
    """允许服务尚未创建，但拒绝任何仍可执行后台写入的状态。"""

    by_service = {str(row.get("Service")): row for row in rows}
    for service in services:
        row = by_service.get(service)
        if row is None:
            continue
        if str(row.get("State", "")).lower() not in {"created", "exited", "stopped"}:
            raise GateAUpgradeError(f"Gate A service {service} must not be running")


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
        "table_session_claims_enabled": True,
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
            "--no-TTY",
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


def _read_m7_invariant_snapshot(
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
            "--no-TTY",
            "mysql",
            "sh",
            "-ec",
            M7_INVARIANT_STATUS_COMMAND,
        ),
        capture_output=True,
    )
    snapshot = _parse_json_object(result.stdout, "M7 invariant status")
    if any(key not in snapshot for key in M7_INVARIANT_KEYS):
        raise GateAUpgradeError("Gate A M7 invariant status is incomplete")
    return snapshot


def _read_m7_mard_catalog(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
) -> tuple[str, ...]:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=(
            "exec",
            "--no-TTY",
            "mysql",
            "sh",
            "-ec",
            M7_MARD_CATALOG_STATUS_COMMAND,
        ),
        capture_output=True,
    )
    rows = tuple(result.stdout.splitlines())
    for row in rows:
        fields = row.split("\t")
        if len(fields) != 6:
            raise GateAUpgradeError("Gate A M7 MARD catalog output is invalid")
    return rows


def _read_m7_schema_status(
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
            "--no-TTY",
            "mysql",
            "sh",
            "-ec",
            M7_SCHEMA_STATUS_COMMAND,
        ),
        capture_output=True,
    )
    return _parse_json_object(result.stdout, "M7 schema status")


def _read_m7_image_mode_manifest(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
) -> tuple[str, ...]:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=(
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "/bin/sh",
            "image-init",
            "-ec",
            M7_IMAGE_MODE_MANIFEST_COMMAND,
        ),
        capture_output=True,
    )
    return tuple(result.stdout.splitlines())


def _run_m7_source_preflight(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    stopped_image_manifest: Sequence[str],
    manifest_sha256: str,
) -> dict[str, Any]:
    expected_rows, expected_images, image_set_sha256 = _m7_manifest_contract(values)
    schema_status = _read_m7_schema_status(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
    )
    if schema_status != {"swatch_hex_columns": 0}:
        raise GateAUpgradeError("Gate A M7 source schema is partially upgraded")
    actual_rows = _read_m7_mard_catalog(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
    )
    if actual_rows != expected_rows:
        raise GateAUpgradeError("Gate A M7 MARD catalog differs from the manifest")

    image_hashes = _parse_hash_manifest(stopped_image_manifest)
    image_modes = _parse_mode_manifest(
        _read_m7_image_mode_manifest(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
        )
    )
    for filename, expected_sha256 in expected_images.items():
        if (
            image_hashes.get(filename) != expected_sha256
            or image_modes.get(filename) != "644"
        ):
            raise GateAUpgradeError(
                "Gate A M7 MARD image set differs from the manifest"
            )

    return {
        "catalog_rows": len(actual_rows),
        "catalog_sha256": _manifest_summary(actual_rows)["sha256"],
        "image_set_sha256": image_set_sha256,
        "images": len(expected_images),
        "manifest_sha256": manifest_sha256,
        "profile": M7_MARD_PREFLIGHT_PROFILE,
        "swatch_hex_columns": 0,
    }


def _validate_final_snapshot(
    source_snapshot: Mapping[str, Any],
    final_snapshot: Mapping[str, Any],
    *,
    source_version: int = DEFAULT_SOURCE_VERSION,
    source_m7_invariants: Mapping[str, Any] | None = None,
) -> None:
    if final_snapshot.get("aerich_versions") != _expected_versions(TARGET_VERSION):
        raise GateAUpgradeError("Gate A final Aerich chain is not exactly M0-M9")
    for key in CORE_INVARIANT_KEYS:
        if final_snapshot.get(key) != source_snapshot.get(key):
            raise GateAUpgradeError(
                f"Gate A final core invariant changed unexpectedly: {key}"
            )
    if source_version == 7:
        if source_m7_invariants is None:
            raise GateAUpgradeError("Gate A M7 source invariants are unavailable")
        for key in M7_INVARIANT_KEYS:
            if (
                key not in source_m7_invariants
                or key not in final_snapshot
                or final_snapshot[key] != source_m7_invariants[key]
            ):
                raise GateAUpgradeError(
                    f"Gate A final M7 invariant changed unexpectedly: {key}"
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
        "distinct_bead_color_hex": 221,
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
    _validate_empty_m9_table_snapshot(final_snapshot)


def _validate_empty_m9_table_snapshot(snapshot: Mapping[str, Any]) -> None:
    """严格验证 bootstrap 后尚无会话的 M9 桌台数据库状态。"""

    for key, expected in M9_EMPTY_TABLE_INVARIANTS:
        actual = snapshot.get(key)
        if type(actual) is not int or actual != expected:
            raise GateAUpgradeError(
                "Gate A final M9 invariant failed: "
                f"{key} expected={expected} actual={actual!r}"
            )


def _validate_empty_table_reconcile_result(result: Mapping[str, Any]) -> None:
    """要求空表期 reconcile 只返回冻结字段，且每个计数都是整数零。"""

    if set(result) != set(M9_EMPTY_TABLE_RECONCILE_KEYS) or any(
        type(result.get(key)) is not int or result[key] != 0
        for key in M9_EMPTY_TABLE_RECONCILE_KEYS
    ):
        raise GateAUpgradeError(
            "Gate A M9 empty table reconciliation result is invalid"
        )


def _validate_adoption_table_reconcile_result(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """M9 adoption 允许已关闭历史，但不允许存量占用或不一致。"""

    if (
        set(result) != set(M9_EMPTY_TABLE_RECONCILE_KEYS)
        or any(
            type(result.get(key)) is not int or result[key] < 0
            for key in M9_EMPTY_TABLE_RECONCILE_KEYS
        )
        or any(
            result[key] != 0
            for key in (
                "open_sessions",
                "occupancies",
                "closed_with_occupancy",
                "awaiting_with_timers",
                "active_without_timers",
                "violations",
            )
        )
    ):
        raise GateAUpgradeError(
            "Gate A M9 adoption table reconciliation result is invalid"
        )
    return dict(result)


def _validate_m9_adoption_snapshot(snapshot: Mapping[str, Any]) -> None:
    """验证 M9 adoption 的静态结构，不把已关闭 Session/Timer 历史误当空表。"""

    if snapshot.get("aerich_versions") != _expected_versions(TARGET_VERSION):
        raise GateAUpgradeError("Gate A M9 adoption requires the exact M0-M9 chain")
    for key, expected in M9_EMPTY_TABLE_INVARIANTS[:8]:
        actual = snapshot.get(key)
        if type(actual) is not int or actual != expected:
            raise GateAUpgradeError(
                "Gate A M9 adoption invariant failed: "
                f"{key} expected={expected} actual={actual!r}"
            )
    for key in ("table_sessions", "table_session_timers", "table_occupancies"):
        if type(snapshot.get(key)) is not int or snapshot[key] < 0:
            raise GateAUpgradeError(
                f"Gate A M9 adoption invariant failed: {key}"
            )
    if snapshot.get("table_occupancies") != 0:
        raise GateAUpgradeError(
            "Gate A M9 adoption requires zero table occupancies"
        )


def _validate_empty_table_sweep_result(result: Mapping[str, Any]) -> None:
    """要求空表期 sweep 成功且没有关闭任何会话。"""

    if (
        set(result) != {"status", "closed"}
        or result.get("status") != "ok"
        or type(result.get("closed")) is not int
        or result["closed"] != 0
    ):
        raise GateAUpgradeError("Gate A M9 empty table sweep result is invalid")


def _validate_mard_result(
    result: Mapping[str, Any],
    *,
    expected_mode: str,
    manifest_sha256: str,
    require_noop: bool,
) -> None:
    if (
        result.get("mode") != expected_mode
        or result.get("colors") != 221
        or result.get("manifest_sha256") != manifest_sha256
    ):
        raise GateAUpgradeError(f"Gate A MARD {expected_mode} result is invalid")
    if require_noop:
        expected_noop = {
            "already_current": True,
            "created_images": 0,
            "database_changes": 0,
            "images_reused": 221,
            "images_to_create": 0,
        }
        if any(result.get(key) != value for key, value in expected_noop.items()):
            raise GateAUpgradeError(
                f"Gate A MARD {expected_mode} result is not an exact no-op"
            )


def _validate_final_image_manifest(
    *,
    source_version: int,
    stopped_manifest: Sequence[str],
    final_manifest: Sequence[str],
) -> None:
    if source_version == 7:
        if list(final_manifest) != list(stopped_manifest):
            raise GateAUpgradeError(
                "Gate A M7-to-M9 image manifest changed unexpectedly"
            )
        return
    if _manifest_summary(final_manifest)["files"] < 221:
        raise GateAUpgradeError("Gate A final image manifest is incomplete")


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


def _write_plan_replay_record(
    *,
    record_dir: Path,
    success_path: Path,
    success_record: Mapping[str, Any],
    candidate_sha: str,
    image_id: str,
    source_candidate_sha: str,
    source_version: int,
    backup_id: str,
    manifest_sha256: str,
    database_snapshot: Mapping[str, Any],
    image_manifest: Mapping[str, Any],
    table_reconcile: Mapping[str, Any],
) -> None:
    """发布 app-up 必须消费的不可覆盖、只读 replay 证据。"""

    result = {
        "already_current": True,
        "backup_id": backup_id,
        "candidate_sha": candidate_sha,
        "manifest_sha256": manifest_sha256,
        "mode": "plan-replay",
        "source_aerich_versions": _expected_versions(source_version),
        "source_version": source_version,
        "target_aerich_versions": _expected_versions(TARGET_VERSION),
        "target_version": TARGET_VERSION,
    }
    _write_json_exclusive(
        gatea._upgrade_replay_marker(record_dir, candidate_sha),
        {
            "schema_version": 1,
            "record_type": "gatea-m9-upgrade-plan-replay",
            "passed": True,
            "candidate_sha": candidate_sha,
            "source_candidate_sha": source_candidate_sha,
            "source_version": source_version,
            "image_id": image_id,
            "backup_id": backup_id,
            "manifest_sha256": manifest_sha256,
            "database_snapshot": dict(database_snapshot),
            "image_manifest": dict(image_manifest),
            "table_reconcile": dict(table_reconcile),
            "upgrade_record_sha256": _sha256(success_path),
            "evidence_sha256": success_record["evidence_sha256"],
            "result": result,
            "completed_at": _iso_now(),
            "secret_values_recorded": False,
        },
    )


def _m9_adoption_result(
    *,
    mode: str,
    candidate_sha: str,
    backup_id: str,
    manifest_sha256: str,
) -> dict[str, Any]:
    return {
        "already_current": mode in {"plan-replay", "apply-replay"},
        "backup_id": backup_id,
        "candidate_sha": candidate_sha,
        "database_changes_applied": False,
        "manifest_sha256": manifest_sha256,
        "migrations_applied": [],
        "mode": mode,
        "source_aerich_versions": _expected_versions(9),
        "source_version": 9,
        "target_aerich_versions": _expected_versions(9),
        "target_version": 9,
        "transition_kind": M9_ADOPTION_TRANSITION_KIND,
    }


def _write_m9_adoption_plan_replay_record(
    *,
    record_dir: Path,
    success_path: Path,
    success_record: Mapping[str, Any],
    table_reconcile: Mapping[str, Any],
) -> None:
    candidate_sha = str(success_record["candidate_sha"])
    stable_success, success_sha256 = _load_bound_json_with_sha256(
        success_path, "M9 adoption upgrade record"
    )
    if stable_success != success_record:
        raise GateAUpgradeError(
            "Gate A M9 adoption upgrade record changed before replay publication"
        )
    _write_json_exclusive(
        gatea._upgrade_replay_marker(record_dir, candidate_sha),
        {
            "schema_version": 2,
            "transition_kind": M9_ADOPTION_TRANSITION_KIND,
            "record_type": "gatea-m9-upgrade-plan-replay",
            "passed": True,
            "candidate_sha": candidate_sha,
            "source_candidate_sha": success_record["source_candidate_sha"],
            "source_version": 9,
            "image_id": success_record["image_id"],
            "backup_id": success_record["backup_id"],
            "manifest_sha256": success_record["manifest_sha256"],
            "lineage_source_candidate_sha": success_record[
                "lineage_source_candidate_sha"
            ],
            "lineage_source_image_id": success_record[
                "lineage_source_image_id"
            ],
            "acceptance_retirement_record_sha256": success_record[
                "acceptance_retirement_record_sha256"
            ],
            "database_changes_applied": False,
            "migrations_applied": [],
            "database_snapshot": dict(
                success_record["final_database_snapshot"]
            ),
            "m8_swatch_content_snapshot": dict(
                success_record["final_m8_swatch_content_snapshot"]
            ),
            "image_manifest": dict(success_record["final_image_manifest"]),
            "table_reconcile": dict(table_reconcile),
            "upgrade_record_sha256": success_sha256,
            "evidence_sha256": success_record["evidence_sha256"],
            "result": _m9_adoption_result(
                mode="plan-replay",
                candidate_sha=candidate_sha,
                backup_id=str(success_record["backup_id"]),
                manifest_sha256=str(success_record["manifest_sha256"]),
            ),
            "completed_at": _iso_now(),
            "secret_values_recorded": False,
        },
    )


def _read_m9_adoption_state(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    backup_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """只读抓取 adoption 状态，并证明 reconcile 前后无任何数据变化。"""

    source_database_snapshot = _read_final_snapshot(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
    )
    _validate_m9_adoption_snapshot(source_database_snapshot)
    source_m7_content_snapshot = backup._source_m7_content_snapshot(
        values, config_file, secret_dir, mode
    )
    source_m8_swatch_content_snapshot = (
        backup._source_m8_swatch_content_snapshot(
            values, config_file, secret_dir, mode
        )
    )
    source_m9_table_content_snapshot = backup._source_m9_table_content_snapshot(
        values, config_file, secret_dir, mode
    )
    source_images = backup._source_image_manifest(
        values, config_file, secret_dir, mode
    )
    if backup_record is not None:
        stopped_database_snapshot = backup._source_snapshot(
            values, config_file, secret_dir, mode
        )
        if stopped_database_snapshot != backup_record.get("database_snapshot"):
            raise GateAUpgradeError(
                "Gate A M9 adoption database no longer matches the verified backup"
            )
        try:
            expected_m7 = backup._validate_m7_content_snapshot(
                backup_record.get("m7_content_snapshot")
            )
            expected_m8_swatch = backup._validate_m8_swatch_content_snapshot(
                backup_record.get("m8_swatch_content_snapshot")
            )
            expected_m9 = backup._validate_m9_table_content_snapshot(
                backup_record.get("m9_table_content_snapshot")
            )
        except gatea.GateAError as error:
            raise GateAUpgradeError(
                "Gate A M9 adoption backup content evidence is invalid"
            ) from error
        if (
            source_m7_content_snapshot != expected_m7
            or source_m8_swatch_content_snapshot != expected_m8_swatch
            or source_m9_table_content_snapshot != expected_m9
            or source_images != backup_record.get("image_manifest")
        ):
            raise GateAUpgradeError(
                "Gate A M9 adoption content no longer matches the verified backup"
            )

    table_reconcile = _run_task(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        service="app",
        module="app.tasks.table_reconcile",
        description="m9-adoption-table-reconcile",
    )
    table_reconcile = _validate_adoption_table_reconcile_result(table_reconcile)
    final_database_snapshot = _read_final_snapshot(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
    )
    final_m7_content_snapshot = backup._source_m7_content_snapshot(
        values, config_file, secret_dir, mode
    )
    final_m8_swatch_content_snapshot = (
        backup._source_m8_swatch_content_snapshot(
            values, config_file, secret_dir, mode
        )
    )
    final_m9_table_content_snapshot = backup._source_m9_table_content_snapshot(
        values, config_file, secret_dir, mode
    )
    final_images = backup._source_image_manifest(
        values, config_file, secret_dir, mode
    )
    if (
        final_database_snapshot != source_database_snapshot
        or final_m7_content_snapshot != source_m7_content_snapshot
        or final_m8_swatch_content_snapshot
        != source_m8_swatch_content_snapshot
        or final_m9_table_content_snapshot != source_m9_table_content_snapshot
        or final_images != source_images
    ):
        raise GateAUpgradeError(
            "Gate A M9 adoption read-only verification changed persistent state"
        )
    return {
        "source_database_snapshot": source_database_snapshot,
        "final_database_snapshot": final_database_snapshot,
        "source_m7_content_snapshot": source_m7_content_snapshot,
        "final_m7_content_snapshot": final_m7_content_snapshot,
        "source_m8_swatch_content_snapshot": (
            source_m8_swatch_content_snapshot
        ),
        "final_m8_swatch_content_snapshot": final_m8_swatch_content_snapshot,
        "source_m9_table_content_snapshot": source_m9_table_content_snapshot,
        "final_m9_table_content_snapshot": final_m9_table_content_snapshot,
        "source_image_manifest": _manifest_summary(source_images),
        "final_image_manifest": _manifest_summary(final_images),
        "table_reconcile": table_reconcile,
    }


def _validate_m9_adoption_success_evidence(
    *,
    success_record: Mapping[str, Any],
    evidence_path: Path,
) -> dict[str, Any]:
    evidence, evidence_sha256 = _load_bound_json_with_sha256(
        evidence_path, "M9 adoption upgrade evidence"
    )
    bound_fields = (
        "transition_kind",
        "candidate_sha",
        "image_id",
        "source_candidate_sha",
        "source_image_id",
        "lineage_source_candidate_sha",
        "lineage_source_image_id",
        "source_version",
        "target_version",
        "source_aerich_versions",
        "target_aerich_versions",
        "backup_id",
        "manifest_sha256",
        "runtime_preflight",
        "started_at",
        "completed_at",
        "stage_record_sha256",
        "activation_record_sha256",
        "predecessor_stage_record_sha256",
        "predecessor_activation_record_sha256",
        "predecessor_upgrade_record_sha256",
        "predecessor_upgrade_evidence_sha256",
        "predecessor_upgrade_plan_replay_record_sha256",
        "acceptance_retirement_record_sha256",
        "backup_record_sha256",
        "restore_record_sha256",
        "source_database_snapshot",
        "final_database_snapshot",
        "source_image_manifest",
        "final_image_manifest",
        "source_m7_content_snapshot",
        "final_m7_content_snapshot",
        "source_m8_swatch_content_snapshot",
        "final_m8_swatch_content_snapshot",
        "source_m9_table_content_snapshot",
        "final_m9_table_content_snapshot",
        "database_changes_applied",
        "migrations_applied",
        "table_reconcile",
    )
    if (
        success_record.get("evidence_path") != str(evidence_path)
        or evidence_sha256 != success_record.get("evidence_sha256")
        or evidence.get("schema_version") != 2
        or evidence.get("record_type") != "existing-database-upgrade-evidence"
        or evidence.get("transition_kind") != M9_ADOPTION_TRANSITION_KIND
        or evidence.get("status") != "succeeded"
        or evidence.get("current_stage") != "completed"
        or evidence.get("stopped_source_verified") is not True
        or evidence.get("steps") != []
        or any(evidence.get(key) != success_record.get(key) for key in bound_fields)
    ):
        raise GateAUpgradeError("Gate A M9 adoption upgrade evidence is invalid")
    started_at = _parse_utc_timestamp(evidence.get("started_at"), "adoption start")
    completed_at = _parse_utc_timestamp(
        evidence.get("completed_at"), "adoption completion"
    )
    if completed_at < started_at:
        raise GateAUpgradeError("Gate A M9 adoption completion precedes its start")
    _validate_adoption_table_reconcile_result(evidence.get("table_reconcile", {}))
    return evidence


def _m9_adoption_success_from_evidence(
    *,
    evidence_path: Path,
    evidence: Mapping[str, Any],
    evidence_sha256: str,
) -> dict[str, Any]:
    """从 durable succeeded evidence 唯一重建对应 success 提交点。"""

    success_only = {"passed", "evidence_path", "evidence_sha256"}
    differing = {
        "record_type",
        "status",
        "current_stage",
        "stopped_source_verified",
        "steps",
    }
    shared_fields = gatea.M9_ADOPTION_UPGRADE_RECORD_KEYS - success_only - {
        "record_type"
    }
    expected_evidence_fields = shared_fields | differing
    if (
        set(evidence) != expected_evidence_fields
        or evidence.get("schema_version") != 2
        or evidence.get("transition_kind") != M9_ADOPTION_TRANSITION_KIND
        or evidence.get("record_type") != "existing-database-upgrade-evidence"
        or evidence.get("status") != "succeeded"
        or evidence.get("current_stage") != "completed"
        or evidence.get("stopped_source_verified") is not True
        or evidence.get("steps") != []
        or evidence.get("database_changes_applied") is not False
        or evidence.get("migrations_applied") != []
    ):
        raise GateAUpgradeError(
            "Gate A prior upgrade evidence requires manual review before retry"
        )
    return {
        **{key: evidence[key] for key in shared_fields},
        "record_type": "existing-database-upgrade",
        "passed": True,
        "evidence_path": str(evidence_path),
        "evidence_sha256": evidence_sha256,
    }


def _plan_m9_adoption(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    source_candidate_sha: str,
    lineage_source_candidate_sha: str,
    acceptance_retirement_record_sha256: str,
    backup_id: str,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
    release_record_dir: Path,
    require_activation: bool,
    acceptance_failure_archive_dir: Path = DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    retirement_failure_archive_dir: Path = DEFAULT_RETIREMENT_FAILURE_ARCHIVE_DIR,
    enforce_backup_max_age: bool = True,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    candidate_sha = gatea._candidate_sha(values)
    if (
        SHA_PATTERN.fullmatch(candidate_sha) is None
        or SHA_PATTERN.fullmatch(source_candidate_sha) is None
        or candidate_sha == source_candidate_sha
    ):
        raise GateAUpgradeError("Gate A source and target candidate SHA are invalid")
    image_id = gatea.validate_app_image(values)
    manifest_sha256 = _manifest_sha256()
    verified_backup = _load_verified_backup(
        values=values,
        backup_id=backup_id,
        source_candidate_sha=source_candidate_sha,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
        require_m8_swatch_content_snapshot=True,
        enforce_backup_max_age=enforce_backup_max_age,
    )
    backup_record = verified_backup.backup_record
    source_image_id = backup_record.get("image_id")
    if not isinstance(source_image_id, str) or not source_image_id:
        raise GateAUpgradeError("Gate A M9 adoption source image is invalid")
    if backup_record.get("database_snapshot", {}).get("aerich_versions") != ",".join(
        _expected_versions(9)
    ):
        raise GateAUpgradeError("Gate A verified backup is not from exact M9")
    context = _validate_m9_adoption_lineage(
        release_record_dir=release_record_dir,
        acceptance_failure_archive_dir=acceptance_failure_archive_dir,
        retirement_failure_archive_dir=retirement_failure_archive_dir,
        backup_id=backup_id,
        bound_backup_records=verified_backup,
        manifest_sha256=manifest_sha256,
        candidate_sha=candidate_sha,
        image_id=image_id,
        source_candidate_sha=source_candidate_sha,
        source_image_id=source_image_id,
        lineage_source_candidate_sha=lineage_source_candidate_sha,
        acceptance_retirement_record_sha256=(
            acceptance_retirement_record_sha256
        ),
        require_activation=require_activation,
    )
    return candidate_sha, image_id, backup_record, context


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
    source_version: int = DEFAULT_SOURCE_VERSION,
) -> tuple[str, str, dict[str, Any], dict[str, Any], str]:
    source_version = _validate_source_version(source_version)
    expected_source_versions = _expected_versions(source_version)
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
    manifest_sha256 = _manifest_sha256()
    success_path, evidence_path = _upgrade_paths(release_record_dir, candidate_sha)
    if success_path.exists():
        replay_rows = gatea._compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("mysql", "redis", "app", "table-sweeper", "nginx"),
        )
        gatea._ensure_services_healthy(replay_rows, "mysql", "redis")
        _ensure_stopped(replay_rows, "app", "nginx")
        _ensure_not_running(replay_rows, "table-sweeper")
        success_record = gatea._require_upgrade_record(
            record_dir=release_record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
        recorded_source_version = success_record.get(
            "source_version", DEFAULT_SOURCE_VERSION
        )
        if (
            success_record.get("source_candidate_sha") != source_candidate_sha
            or success_record.get("backup_id") != backup_id
            or success_record.get("manifest_sha256") != manifest_sha256
            or success_record.get("source_aerich_versions")
            != expected_source_versions
            or type(recorded_source_version) is not int
            or recorded_source_version != source_version
            or success_record.get("evidence_path") != str(evidence_path)
            or SHA256_PATTERN.fullmatch(
                str(success_record.get("evidence_sha256", ""))
            )
            is None
            or not isinstance(success_record.get("final_database_snapshot"), dict)
            or not isinstance(success_record.get("final_image_manifest"), dict)
        ):
            raise GateAUpgradeError(
                "Gate A recorded upgrade does not match the requested replay"
            )
        recorded_table_reconcile = success_record.get("table_reconcile")
        recorded_table_sweep = success_record.get("table_sweep")
        if not isinstance(recorded_table_reconcile, dict) or not isinstance(
            recorded_table_sweep, dict
        ):
            raise GateAUpgradeError(
                "Gate A recorded upgrade table consistency evidence is unavailable"
            )
        _validate_empty_table_reconcile_result(recorded_table_reconcile)
        _validate_empty_table_sweep_result(recorded_table_sweep)
        try:
            if _sha256(evidence_path) != success_record["evidence_sha256"]:
                raise GateAUpgradeError(
                    "Gate A recorded upgrade evidence digest does not match"
                )
            replay_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise GateAUpgradeError(
                "Gate A recorded upgrade evidence is unavailable"
            ) from error
        if (
            not isinstance(replay_evidence, dict)
            or replay_evidence.get("schema_version") != 1
            or replay_evidence.get("record_type")
            != "existing-database-upgrade-evidence"
            or replay_evidence.get("status") != "succeeded"
            or replay_evidence.get("candidate_sha") != candidate_sha
            or replay_evidence.get("source_candidate_sha") != source_candidate_sha
            or replay_evidence.get("backup_id") != backup_id
            or replay_evidence.get("final_database_snapshot")
            != success_record["final_database_snapshot"]
            or replay_evidence.get("final_image_manifest")
            != success_record["final_image_manifest"]
            or replay_evidence.get("table_reconcile")
            != recorded_table_reconcile
            or replay_evidence.get("table_sweep") != recorded_table_sweep
        ):
            raise GateAUpgradeError("Gate A recorded upgrade evidence is invalid")
        final_snapshot = _read_final_snapshot(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
        )
        if (
            final_snapshot.get("aerich_versions")
            != _expected_versions(TARGET_VERSION)
            or final_snapshot != success_record["final_database_snapshot"]
        ):
            raise GateAUpgradeError(
                "Gate A recorded upgrade no longer matches the database"
            )
        _validate_empty_m9_table_snapshot(final_snapshot)
        final_images = backup._source_image_manifest(
            values, config_file, secret_dir, mode
        )
        if _manifest_summary(final_images) != success_record["final_image_manifest"]:
            raise GateAUpgradeError(
                "Gate A recorded upgrade no longer matches the image volume"
            )
        if source_version == 7:
            try:
                recorded_m7_content = backup._validate_m7_content_snapshot(
                    success_record.get("final_m7_content_snapshot")
                )
            except gatea.GateAError as error:
                raise GateAUpgradeError(
                    "Gate A recorded M7 content snapshot is invalid"
                ) from error
            if replay_evidence.get("final_m7_content_snapshot") != recorded_m7_content:
                raise GateAUpgradeError("Gate A recorded upgrade evidence is invalid")
            current_m7_content = backup._source_m7_content_snapshot(
                values,
                config_file,
                secret_dir,
                mode,
            )
            if current_m7_content != recorded_m7_content:
                raise GateAUpgradeError(
                    "Gate A recorded upgrade no longer matches preserved M7 content"
                )
        replay_mard_result = _run_task(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            service="app",
            module="app.tasks.gatea_mard_publish",
            description="recorded-upgrade-mard-preview",
        )
        _validate_mard_result(
            replay_mard_result,
            expected_mode="preview",
            manifest_sha256=manifest_sha256,
            require_noop=True,
        )
        replay_table_reconcile = _run_task(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            service="app",
            module="app.tasks.table_reconcile",
            description="recorded-upgrade-table-reconcile",
        )
        _validate_empty_table_reconcile_result(replay_table_reconcile)
        # table_sweep 可能关闭到期会话，plan replay 必须保持业务数据只读；这里
        # 重新验证只读 reconcile 与完整 M9 SQL invariant，并绑定 apply 时的 sweep 证据。
        return candidate_sha, image_id, {}, final_snapshot, manifest_sha256
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
    if source_status.get("aerich_versions") != expected_source_versions:
        raise GateAUpgradeError(
            f"Gate A database is not the explicitly approved M{source_version} source"
        )
    verified_backup = _load_verified_backup(
        values=values,
        backup_id=backup_id,
        source_candidate_sha=source_candidate_sha,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
    )
    backup_record = verified_backup.backup_record
    backup_versions = backup_record["database_snapshot"].get("aerich_versions")
    if backup_versions != ",".join(expected_source_versions):
        raise GateAUpgradeError(
            f"Gate A verified backup is not from exact M{source_version}"
        )
    return candidate_sha, image_id, backup_record, source_status, manifest_sha256


def _recover_m9_adoption_success(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    source_candidate_sha: str,
    lineage_source_candidate_sha: str,
    acceptance_retirement_record_sha256: str,
    backup_id: str,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
    release_record_dir: Path,
    acceptance_failure_archive_dir: Path,
    retirement_failure_archive_dir: Path,
    candidate_sha: str,
    image_id: str,
    manifest_sha256: str,
    success_path: Path,
    evidence_path: Path,
    apply: bool,
    confirm_target_sha: str | None,
    confirm_source_sha: str | None,
    confirm_backup_id: str | None,
    confirm_manifest_sha256: str | None,
    confirm_lineage_source_sha: str | None,
    confirm_acceptance_retirement_record_sha256: str | None,
) -> dict[str, Any]:
    """只从完整 succeeded evidence 恢复 SIGKILL 后缺失的 success 提交点。"""

    evidence, evidence_sha256 = _load_bound_json_with_sha256(
        evidence_path, "M9 adoption upgrade evidence"
    )
    if not apply:
        raise GateAUpgradeError(
            "Gate A succeeded adoption evidence recovery requires apply confirmations"
        )
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
    _validate_adoption_confirmations(
        lineage_source_candidate_sha=lineage_source_candidate_sha,
        acceptance_retirement_record_sha256=acceptance_retirement_record_sha256,
        confirm_lineage_source_sha=confirm_lineage_source_sha,
        confirm_acceptance_retirement_record_sha256=(
            confirm_acceptance_retirement_record_sha256
        ),
    )
    success_payload = _m9_adoption_success_from_evidence(
        evidence_path=evidence_path,
        evidence=evidence,
        evidence_sha256=evidence_sha256,
    )
    requested_identity = {
        "candidate_sha": candidate_sha,
        "image_id": image_id,
        "source_candidate_sha": source_candidate_sha,
        "lineage_source_candidate_sha": lineage_source_candidate_sha,
        "acceptance_retirement_record_sha256": (
            acceptance_retirement_record_sha256
        ),
        "backup_id": backup_id,
        "manifest_sha256": manifest_sha256,
    }
    if any(
        evidence.get(key) != value
        for key, value in requested_identity.items()
    ):
        raise GateAUpgradeError("Gate A succeeded adoption evidence binding changed")
    stopped_rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("mysql", "redis", "app", "table-sweeper", "nginx"),
    )
    gatea._ensure_services_healthy(stopped_rows, "mysql", "redis")
    _ensure_stopped(stopped_rows, "app", "nginx")
    _ensure_not_running(stopped_rows, "table-sweeper")
    (
        planned_candidate_sha,
        planned_image_id,
        backup_record,
        context,
    ) = _plan_m9_adoption(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        source_candidate_sha=source_candidate_sha,
        lineage_source_candidate_sha=lineage_source_candidate_sha,
        acceptance_retirement_record_sha256=(
            acceptance_retirement_record_sha256
        ),
        backup_id=backup_id,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
        release_record_dir=release_record_dir,
        require_activation=True,
        acceptance_failure_archive_dir=acceptance_failure_archive_dir,
        retirement_failure_archive_dir=retirement_failure_archive_dir,
        # 此分支只在上方稳定读取并精确验证 durable succeeded evidence
        # 后可达。其 Backup/Restore 仍做完整语义与 digest 绑定校验；仅不因
        # 运维恢复跨过 24 小时而把缺失 success 的提交点永久卡死。
        enforce_backup_max_age=False,
    )
    if planned_candidate_sha != candidate_sha or planned_image_id != image_id:
        raise GateAUpgradeError("Gate A adoption recovery candidate changed")
    expected_identity = {
        "candidate_sha": candidate_sha,
        "image_id": image_id,
        "source_candidate_sha": source_candidate_sha,
        "source_image_id": backup_record.get("image_id"),
        "lineage_source_candidate_sha": lineage_source_candidate_sha,
        "source_version": 9,
        "target_version": 9,
        "source_aerich_versions": _expected_versions(9),
        "target_aerich_versions": _expected_versions(9),
        "backup_id": backup_id,
        "manifest_sha256": manifest_sha256,
        "runtime_preflight": {
            "app_env": "production",
            "db_engine": "mysql",
            "jwt_algorithm": "HS256",
            "table_session_claims_enabled": True,
            "validated": True,
        },
        "database_changes_applied": False,
        "migrations_applied": [],
        **context,
    }
    if any(evidence.get(key) != value for key, value in expected_identity.items()):
        raise GateAUpgradeError("Gate A succeeded adoption evidence binding changed")
    state = _read_m9_adoption_state(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        backup_record=backup_record,
    )
    if any(evidence.get(key) != value for key, value in state.items()):
        raise GateAUpgradeError(
            "Gate A succeeded adoption evidence no longer matches persistent state"
        )
    final_rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("mysql", "redis", "app", "table-sweeper", "nginx"),
    )
    gatea._ensure_services_healthy(final_rows, "mysql", "redis")
    _ensure_stopped(final_rows, "app", "nginx")
    _ensure_not_running(final_rows, "table-sweeper")
    _validate_m9_adoption_success_evidence(
        success_record=success_payload,
        evidence_path=evidence_path,
    )
    try:
        gatea._require_m9_adoption_upgrade_record(
            success_payload,
            record_dir=release_record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
    except gatea.GateAError as error:
        raise GateAUpgradeError(
            "Gate A succeeded adoption evidence is invalid"
        ) from error
    _write_json_exclusive(success_path, success_payload)
    published, _ = _load_bound_json_with_sha256(
        success_path, "M9 adoption upgrade record"
    )
    if published != success_payload:
        raise GateAUpgradeError("Gate A recovered adoption success record changed")
    return {
        **_m9_adoption_result(
            mode="apply",
            candidate_sha=candidate_sha,
            backup_id=backup_id,
            manifest_sha256=manifest_sha256,
        ),
        "application_stopped": True,
        "record": str(success_path),
        "source_candidate_sha": source_candidate_sha,
        "lineage_source_candidate_sha": lineage_source_candidate_sha,
        "lineage_source_image_id": context["lineage_source_image_id"],
        "acceptance_retirement_record_sha256": (
            acceptance_retirement_record_sha256
        ),
    }


def _adopt_m9_candidate(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    source_candidate_sha: str,
    lineage_source_candidate_sha: str,
    acceptance_retirement_record_sha256: str,
    backup_id: str,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
    release_record_dir: Path,
    acceptance_failure_archive_dir: Path,
    retirement_failure_archive_dir: Path,
    apply: bool,
    confirm_target_sha: str | None,
    confirm_source_sha: str | None,
    confirm_backup_id: str | None,
    confirm_manifest_sha256: str | None,
    confirm_lineage_source_sha: str | None,
    confirm_acceptance_retirement_record_sha256: str | None,
) -> dict[str, Any]:
    """在 M9 数据不变的前提下，为新候选发布 schema-v2 adoption 证据。"""

    candidate_sha = gatea._candidate_sha(values)
    image_id = gatea.validate_app_image(values)
    manifest_sha256 = _manifest_sha256()
    success_path, evidence_path = _upgrade_paths(release_record_dir, candidate_sha)

    if success_path.exists() or success_path.is_symlink():
        replay_rows = gatea._compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("mysql", "redis", "app", "table-sweeper", "nginx"),
        )
        gatea._ensure_services_healthy(replay_rows, "mysql", "redis")
        _ensure_stopped(replay_rows, "app", "nginx")
        _ensure_not_running(replay_rows, "table-sweeper")
        raw_success_record, _ = _load_bound_json_with_sha256(
            success_path, "M9 adoption upgrade record"
        )
        success_record = gatea._require_upgrade_record(
            record_dir=release_record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
        if (
            success_record != raw_success_record
            or success_record.get("schema_version") != 2
            or success_record.get("transition_kind")
            != M9_ADOPTION_TRANSITION_KIND
            or success_record.get("source_candidate_sha")
            != source_candidate_sha
            or success_record.get("lineage_source_candidate_sha")
            != lineage_source_candidate_sha
            or success_record.get("backup_id") != backup_id
            or success_record.get("manifest_sha256") != manifest_sha256
            or success_record.get("acceptance_retirement_record_sha256")
            != acceptance_retirement_record_sha256
        ):
            raise GateAUpgradeError(
                "Gate A recorded M9 adoption does not match the requested replay"
            )
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
            _validate_adoption_confirmations(
                lineage_source_candidate_sha=lineage_source_candidate_sha,
                acceptance_retirement_record_sha256=(
                    acceptance_retirement_record_sha256
                ),
                confirm_lineage_source_sha=confirm_lineage_source_sha,
                confirm_acceptance_retirement_record_sha256=(
                    confirm_acceptance_retirement_record_sha256
                ),
            )
        bound_backup_records = _load_verified_backup(
            values=values,
            backup_id=backup_id,
            source_candidate_sha=source_candidate_sha,
            backup_root=backup_root,
            backup_record_dir=backup_record_dir,
            restore_record_dir=restore_record_dir,
            require_m8_swatch_content_snapshot=True,
        )
        context = _validate_m9_adoption_lineage(
            release_record_dir=release_record_dir,
            acceptance_failure_archive_dir=acceptance_failure_archive_dir,
            retirement_failure_archive_dir=retirement_failure_archive_dir,
            backup_id=backup_id,
            bound_backup_records=bound_backup_records,
            manifest_sha256=manifest_sha256,
            candidate_sha=candidate_sha,
            image_id=image_id,
            source_candidate_sha=source_candidate_sha,
            source_image_id=str(success_record["source_image_id"]),
            lineage_source_candidate_sha=lineage_source_candidate_sha,
            acceptance_retirement_record_sha256=(
                acceptance_retirement_record_sha256
            ),
            require_activation=True,
        )
        if any(success_record.get(key) != value for key, value in context.items()):
            raise GateAUpgradeError(
                "Gate A recorded M9 adoption lineage no longer matches"
            )
        _validate_m9_adoption_success_evidence(
            success_record=success_record,
            evidence_path=evidence_path,
        )
        current_state = _read_m9_adoption_state(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            backup_record=None,
        )
        for key in (
            "source_database_snapshot",
            "final_database_snapshot",
            "source_m7_content_snapshot",
            "final_m7_content_snapshot",
            "source_m8_swatch_content_snapshot",
            "final_m8_swatch_content_snapshot",
            "source_m9_table_content_snapshot",
            "final_m9_table_content_snapshot",
            "source_image_manifest",
            "final_image_manifest",
            "table_reconcile",
        ):
            expected_key = (
                "final_database_snapshot"
                if key == "source_database_snapshot"
                else "final_m7_content_snapshot"
                if key == "source_m7_content_snapshot"
                else "final_m8_swatch_content_snapshot"
                if key == "source_m8_swatch_content_snapshot"
                else "final_m9_table_content_snapshot"
                if key == "source_m9_table_content_snapshot"
                else "final_image_manifest"
                if key == "source_image_manifest"
                else key
            )
            if current_state[key] != success_record.get(expected_key):
                raise GateAUpgradeError(
                    "Gate A recorded M9 adoption no longer matches persistent state"
                )
        result = _m9_adoption_result(
            mode="apply-replay" if apply else "plan-replay",
            candidate_sha=candidate_sha,
            backup_id=backup_id,
            manifest_sha256=manifest_sha256,
        )
        if not apply:
            _write_m9_adoption_plan_replay_record(
                record_dir=release_record_dir,
                success_path=success_path,
                success_record=success_record,
                table_reconcile=current_state["table_reconcile"],
            )
        return result

    if evidence_path.exists() or evidence_path.is_symlink():
        return _recover_m9_adoption_success(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            source_candidate_sha=source_candidate_sha,
            lineage_source_candidate_sha=lineage_source_candidate_sha,
            acceptance_retirement_record_sha256=(
                acceptance_retirement_record_sha256
            ),
            backup_id=backup_id,
            backup_root=backup_root,
            backup_record_dir=backup_record_dir,
            restore_record_dir=restore_record_dir,
            release_record_dir=release_record_dir,
            acceptance_failure_archive_dir=acceptance_failure_archive_dir,
            retirement_failure_archive_dir=retirement_failure_archive_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
            manifest_sha256=manifest_sha256,
            success_path=success_path,
            evidence_path=evidence_path,
            apply=apply,
            confirm_target_sha=confirm_target_sha,
            confirm_source_sha=confirm_source_sha,
            confirm_backup_id=confirm_backup_id,
            confirm_manifest_sha256=confirm_manifest_sha256,
            confirm_lineage_source_sha=confirm_lineage_source_sha,
            confirm_acceptance_retirement_record_sha256=(
                confirm_acceptance_retirement_record_sha256
            ),
        )
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("mysql", "redis", "app", "table-sweeper", "nginx"),
    )
    gatea._ensure_services_healthy(
        rows, "mysql", "redis", "app", "table-sweeper", "nginx"
    )
    (
        candidate_sha,
        image_id,
        backup_record,
        context,
    ) = _plan_m9_adoption(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        source_candidate_sha=source_candidate_sha,
        lineage_source_candidate_sha=lineage_source_candidate_sha,
        acceptance_retirement_record_sha256=(
            acceptance_retirement_record_sha256
        ),
        backup_id=backup_id,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
        release_record_dir=release_record_dir,
        require_activation=apply,
        acceptance_failure_archive_dir=acceptance_failure_archive_dir,
        retirement_failure_archive_dir=retirement_failure_archive_dir,
    )
    if not apply:
        if any(
            value is not None
            for value in (
                confirm_target_sha,
                confirm_source_sha,
                confirm_backup_id,
                confirm_manifest_sha256,
                confirm_lineage_source_sha,
                confirm_acceptance_retirement_record_sha256,
            )
        ):
            raise GateAUpgradeError("Gate A plan does not accept apply confirmations")
        plan_state = _read_m9_adoption_state(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            backup_record=backup_record,
        )
        return {
            **_m9_adoption_result(
                mode="plan",
                candidate_sha=candidate_sha,
                backup_id=backup_id,
                manifest_sha256=manifest_sha256,
            ),
            "restore_verified": True,
            "source_candidate_sha": source_candidate_sha,
            "lineage_source_candidate_sha": lineage_source_candidate_sha,
            "lineage_source_image_id": context["lineage_source_image_id"],
            "acceptance_retirement_record_sha256": (
                acceptance_retirement_record_sha256
            ),
            "table_reconcile": plan_state["table_reconcile"],
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
    _validate_adoption_confirmations(
        lineage_source_candidate_sha=lineage_source_candidate_sha,
        acceptance_retirement_record_sha256=acceptance_retirement_record_sha256,
        confirm_lineage_source_sha=confirm_lineage_source_sha,
        confirm_acceptance_retirement_record_sha256=(
            confirm_acceptance_retirement_record_sha256
        ),
    )
    runtime_preflight = _run_runtime_preflight(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
    )
    started_at = _iso_now()
    evidence: dict[str, Any] = {
        "schema_version": 2,
        "transition_kind": M9_ADOPTION_TRANSITION_KIND,
        "record_type": "existing-database-upgrade-evidence",
        "status": "in_progress",
        "current_stage": "validated",
        "candidate_sha": candidate_sha,
        "image_id": image_id,
        "source_candidate_sha": source_candidate_sha,
        "source_image_id": backup_record["image_id"],
        "source_version": 9,
        "target_version": 9,
        "source_aerich_versions": _expected_versions(9),
        "target_aerich_versions": _expected_versions(9),
        "backup_id": backup_id,
        "manifest_sha256": manifest_sha256,
        "runtime_preflight": runtime_preflight,
        "started_at": started_at,
        "database_changes_applied": False,
        "migrations_applied": [],
        "steps": [],
        **context,
    }
    _write_json_exclusive(evidence_path, evidence)
    business_stopped = False
    success_payload: dict[str, Any] | None = None
    try:
        evidence["current_stage"] = "stop-business-entry"
        backup._write_json_atomic(evidence_path, evidence, 0o644)
        gatea._run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=(
                "stop",
                "--timeout",
                "30",
                "nginx",
                "table-sweeper",
                "app",
            ),
        )
        business_stopped = True
        stopped_rows = gatea._compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("mysql", "redis", "app", "table-sweeper", "nginx"),
        )
        gatea._ensure_services_healthy(stopped_rows, "mysql", "redis")
        _ensure_stopped(stopped_rows, "app", "nginx")
        _ensure_not_running(stopped_rows, "table-sweeper")
        evidence["current_stage"] = "verify-stopped-source"
        state = _read_m9_adoption_state(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            backup_record=backup_record,
        )
        evidence.update(state)
        evidence["stopped_source_verified"] = True
        evidence["completed_at"] = _iso_now()
        evidence["current_stage"] = "completed"
        evidence["status"] = "succeeded"
        backup._write_json_atomic(evidence_path, evidence, 0o644)

        success_payload = {
            "schema_version": 2,
            "transition_kind": M9_ADOPTION_TRANSITION_KIND,
            "record_type": "existing-database-upgrade",
            "passed": True,
            "candidate_sha": candidate_sha,
            "image_id": image_id,
            "source_candidate_sha": source_candidate_sha,
            "source_image_id": backup_record["image_id"],
            "source_version": 9,
            "target_version": 9,
            "source_aerich_versions": _expected_versions(9),
            "target_aerich_versions": _expected_versions(9),
            "backup_id": backup_id,
            "manifest_sha256": manifest_sha256,
            "runtime_preflight": runtime_preflight,
            "started_at": started_at,
            "completed_at": evidence["completed_at"],
            "evidence_path": str(evidence_path),
            "evidence_sha256": _sha256(evidence_path),
            "database_changes_applied": False,
            "migrations_applied": [],
            **context,
            **state,
        }
        _write_json_exclusive(success_path, success_payload)
    except BaseException as error:
        if success_path.exists() or success_path.is_symlink():
            _validate_published_upgrade_commit(
                success_path=success_path,
                evidence_path=evidence_path,
                success_payload=success_payload,
                evidence=evidence,
            )
            raise
        if evidence.get("status") == "succeeded":
            try:
                durable_evidence, durable_evidence_sha256 = (
                    _load_bound_json_with_sha256(
                        evidence_path,
                        "M9 adoption upgrade evidence",
                    )
                )
            except BaseException as recovery_error:
                raise recovery_error from error
            if durable_evidence.get("status") == "succeeded":
                try:
                    _m9_adoption_success_from_evidence(
                        evidence_path=evidence_path,
                        evidence=durable_evidence,
                        evidence_sha256=durable_evidence_sha256,
                    )
                except BaseException as recovery_error:
                    raise recovery_error from error
                # succeeded evidence 是可恢复提交点。success 尚未发布时的
                # 控制信号或工作异常不得把它降级为 failed；下次 apply 会在
                # 停写状态下重新核验现场并只发布缺失的 success Record。
                raise
        evidence["completed_at"] = _iso_now()
        evidence["error_type"] = type(error).__name__
        evidence["status"] = "failed"
        evidence["business_entry_stopped"] = business_stopped
        try:
            evidence["failure_database_status"] = _read_final_snapshot(
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
        **_m9_adoption_result(
            mode="apply",
            candidate_sha=candidate_sha,
            backup_id=backup_id,
            manifest_sha256=manifest_sha256,
        ),
        "application_stopped": True,
        "record": str(success_path),
        "source_candidate_sha": source_candidate_sha,
        "lineage_source_candidate_sha": lineage_source_candidate_sha,
        "lineage_source_image_id": context["lineage_source_image_id"],
        "acceptance_retirement_record_sha256": (
            acceptance_retirement_record_sha256
        ),
    }


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
    lineage_source_candidate_sha: str | None = None,
    acceptance_retirement_record_sha256: str | None = None,
    confirm_lineage_source_sha: str | None = None,
    confirm_acceptance_retirement_record_sha256: str | None = None,
    source_version: int = DEFAULT_SOURCE_VERSION,
    acceptance_record_dir: Path = gatea.DEFAULT_M9_ACCEPTANCE_RECORD_DIR,
    acceptance_failure_archive_dir: Path = DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    retirement_failure_archive_dir: Path = DEFAULT_RETIREMENT_FAILURE_ARCHIVE_DIR,
) -> dict[str, Any]:
    """规划或执行精确 M2/M7→M9 升级或 M9→M9 adoption。"""

    gatea._require_loopback_write_mode(mode)
    source_version = _validate_source_version(source_version)
    backup_id = backup._backup_id(backup_id)
    gatea._validate_root_directory(
        release_record_dir, 0o755, "Gate A release record directory"
    )
    gatea.reject_unresolved_candidate_transition_journals(
        record_dir=release_record_dir,
    )
    gatea.reject_unresolved_m9_acceptance_sidecars(
        record_dir=acceptance_record_dir,
    )
    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=False,
    )
    if source_version == 9:
        if (
            not isinstance(lineage_source_candidate_sha, str)
            or not isinstance(acceptance_retirement_record_sha256, str)
        ):
            raise GateAUpgradeError(
                "Gate A M9 adoption requires lineage and retirement evidence"
            )
        return _adopt_m9_candidate(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            source_candidate_sha=source_candidate_sha,
            lineage_source_candidate_sha=lineage_source_candidate_sha,
            acceptance_retirement_record_sha256=(
                acceptance_retirement_record_sha256
            ),
            backup_id=backup_id,
            backup_root=backup_root,
            backup_record_dir=backup_record_dir,
            restore_record_dir=restore_record_dir,
            release_record_dir=release_record_dir,
            acceptance_failure_archive_dir=acceptance_failure_archive_dir,
            retirement_failure_archive_dir=retirement_failure_archive_dir,
            apply=apply,
            confirm_target_sha=confirm_target_sha,
            confirm_source_sha=confirm_source_sha,
            confirm_backup_id=confirm_backup_id,
            confirm_manifest_sha256=confirm_manifest_sha256,
            confirm_lineage_source_sha=confirm_lineage_source_sha,
            confirm_acceptance_retirement_record_sha256=(
                confirm_acceptance_retirement_record_sha256
            ),
        )
    if any(
        value is not None
        for value in (
            lineage_source_candidate_sha,
            acceptance_retirement_record_sha256,
            confirm_lineage_source_sha,
            confirm_acceptance_retirement_record_sha256,
        )
    ):
        raise GateAUpgradeError(
            "Gate A M9 adoption evidence is invalid for an M2/M7 source"
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
        source_version=source_version,
    )
    success_path, evidence_path = _upgrade_paths(release_record_dir, candidate_sha)
    if success_path.exists():
        success_record = gatea._require_upgrade_record(
            record_dir=release_record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
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
        result = {
            "already_current": True,
            "backup_id": backup_id,
            "candidate_sha": candidate_sha,
            "manifest_sha256": manifest_sha256,
            "mode": "apply-replay" if apply else "plan-replay",
            "source_aerich_versions": _expected_versions(source_version),
            "source_version": source_version,
            "target_aerich_versions": _expected_versions(TARGET_VERSION),
            "target_version": TARGET_VERSION,
        }
        if not apply:
            _write_plan_replay_record(
                record_dir=release_record_dir,
                success_path=success_path,
                success_record=success_record,
                candidate_sha=candidate_sha,
                image_id=image_id,
                source_candidate_sha=source_candidate_sha,
                source_version=source_version,
                backup_id=backup_id,
                manifest_sha256=manifest_sha256,
                database_snapshot=success_record["final_database_snapshot"],
                image_manifest=success_record["final_image_manifest"],
                table_reconcile=success_record["table_reconcile"],
            )
        return result
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
            "source_aerich_versions": _expected_versions(source_version),
            "source_candidate_sha": source_candidate_sha,
            "source_version": source_version,
            "target_aerich_versions": _expected_versions(TARGET_VERSION),
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
        "source_aerich_versions": _expected_versions(source_version),
        "source_candidate_sha": source_candidate_sha,
        "source_database_status": source_status,
        "source_version": source_version,
        "started_at": started_at,
        "status": "in_progress",
        "steps": [],
        "target_aerich_versions": _expected_versions(TARGET_VERSION),
    }
    _write_json_exclusive(evidence_path, evidence)
    business_stopped = False
    final_snapshot: dict[str, Any] = {}
    final_image_manifest: list[str] = []
    wallet_result: dict[str, Any] = {}
    mard_result: dict[str, Any] = {}
    table_bootstrap_result: dict[str, Any] = {}
    table_reconcile_result: dict[str, Any] = {}
    table_sweep_result: dict[str, Any] = {}
    source_m7_invariants: dict[str, Any] | None = None
    source_m7_content_snapshot: dict[str, Any] | None = None
    final_m7_content_snapshot: dict[str, Any] | None = None
    m7_source_preflight: dict[str, Any] = {}
    stopped_images: list[str] = []
    success_payload: dict[str, Any] | None = None
    try:
        evidence["current_stage"] = "stop-business-entry"
        backup._write_json_atomic(evidence_path, evidence, 0o644)
        gatea._run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=(
                "stop",
                "--timeout",
                "30",
                "nginx",
                "table-sweeper",
                "app",
            ),
        )
        business_stopped = True
        rows = gatea._compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("mysql", "redis", "app", "table-sweeper", "nginx"),
        )
        gatea._ensure_services_healthy(rows, "mysql", "redis")
        _ensure_stopped(rows, "app", "nginx")
        _ensure_not_running(rows, "table-sweeper")

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
        if source_version == 7:
            expected_m7_content_snapshot = backup._validate_m7_content_snapshot(
                backup_record.get("m7_content_snapshot")
            )
            source_m7_content_snapshot = backup._source_m7_content_snapshot(
                values,
                config_file,
                secret_dir,
                mode,
            )
            if source_m7_content_snapshot != expected_m7_content_snapshot:
                raise GateAUpgradeError(
                    "Gate A stopped M7 content no longer matches the verified backup"
                )
            source_m7_invariants = _read_m7_invariant_snapshot(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                mode=mode,
            )
            m7_source_preflight = _run_m7_source_preflight(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                mode=mode,
                stopped_image_manifest=stopped_images,
                manifest_sha256=manifest_sha256,
            )
            evidence["source_m7_content_snapshot"] = source_m7_content_snapshot
            evidence["source_m7_invariants"] = source_m7_invariants
            evidence["source_m7_mard_preflight"] = m7_source_preflight
        backup._write_json_atomic(evidence_path, evidence, 0o644)

        for target_version in range(source_version + 1, TARGET_VERSION + 1):
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

            if target_version == 8:
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
                _validate_mard_result(
                    preview,
                    expected_mode="preview",
                    manifest_sha256=manifest_sha256,
                    require_noop=source_version == 7,
                )
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
                _validate_mard_result(
                    mard_result,
                    expected_mode="apply",
                    manifest_sha256=manifest_sha256,
                    require_noop=source_version == 7,
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
                _validate_mard_result(
                    replay,
                    expected_mode="preview",
                    manifest_sha256=manifest_sha256,
                    require_noop=True,
                )
                _record_step(
                    evidence_path=evidence_path,
                    evidence=evidence,
                    name="mard-publish",
                    started_at=step_started,
                    result={"apply": mard_result, "preview": preview, "replay": replay},
                    database_snapshot=database_status,
                )

            if target_version == 9:
                step_started = _iso_now()
                table_bootstrap_result = _run_task(
                    values=values,
                    config_file=config_file,
                    secret_dir=secret_dir,
                    mode=mode,
                    service="app",
                    module="app.tasks.table_bootstrap",
                    arguments=("--apply",),
                    description="table-bootstrap",
                )
                if table_bootstrap_result != {
                    "status": "ok",
                    "table_count": 30,
                    "placeholder_qr_count": 0,
                    "wechat_environment": "develop",
                }:
                    raise GateAUpgradeError("Gate A M9 table bootstrap result is invalid")
                table_bootstrap_replay = _run_task(
                    values=values,
                    config_file=config_file,
                    secret_dir=secret_dir,
                    mode=mode,
                    service="app",
                    module="app.tasks.table_bootstrap",
                    description="table-bootstrap-replay",
                )
                if table_bootstrap_replay != table_bootstrap_result:
                    raise GateAUpgradeError(
                        "Gate A M9 table bootstrap replay is not an exact no-op"
                    )
                _record_step(
                    evidence_path=evidence_path,
                    evidence=evidence,
                    name="table-bootstrap",
                    started_at=step_started,
                    result={
                        "apply": table_bootstrap_result,
                        "replay": table_bootstrap_replay,
                    },
                    database_snapshot=database_status,
                )

        step_started = _iso_now()
        evidence["current_stage"] = "table-reconcile"
        backup._write_json_atomic(evidence_path, evidence, 0o644)
        table_reconcile_result = _run_task(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            service="app",
            module="app.tasks.table_reconcile",
            description="table-reconcile",
        )
        _validate_empty_table_reconcile_result(table_reconcile_result)
        reconcile_snapshot = _read_final_snapshot(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
        )
        _validate_empty_m9_table_snapshot(reconcile_snapshot)
        evidence["table_reconcile"] = table_reconcile_result
        _record_step(
            evidence_path=evidence_path,
            evidence=evidence,
            name="table-reconcile",
            started_at=step_started,
            result=table_reconcile_result,
            database_snapshot=reconcile_snapshot,
        )

        step_started = _iso_now()
        evidence["current_stage"] = "table-sweep"
        backup._write_json_atomic(evidence_path, evidence, 0o644)
        table_sweep_result = _run_task(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            service="app",
            module="app.tasks.table_sweep",
            description="table-sweep",
        )
        _validate_empty_table_sweep_result(table_sweep_result)
        final_snapshot = _read_final_snapshot(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
        )
        _validate_empty_m9_table_snapshot(final_snapshot)
        evidence["table_sweep"] = table_sweep_result
        _record_step(
            evidence_path=evidence_path,
            evidence=evidence,
            name="table-sweep",
            started_at=step_started,
            result=table_sweep_result,
            database_snapshot=final_snapshot,
        )

        evidence["current_stage"] = "validate-final"
        evidence["final_database_snapshot"] = final_snapshot
        backup._write_json_atomic(evidence_path, evidence, 0o644)
        _validate_final_snapshot(
            backup_record["database_snapshot"],
            final_snapshot,
            source_version=source_version,
            source_m7_invariants=source_m7_invariants,
        )
        final_image_manifest = backup._source_image_manifest(
            values, config_file, secret_dir, mode
        )
        _validate_final_image_manifest(
            source_version=source_version,
            stopped_manifest=stopped_images,
            final_manifest=final_image_manifest,
        )
        if source_version == 7:
            final_m7_content_snapshot = backup._source_m7_content_snapshot(
                values,
                config_file,
                secret_dir,
                mode,
            )
            if final_m7_content_snapshot != source_m7_content_snapshot:
                raise GateAUpgradeError(
                    "Gate A M7 preserved content changed during the M9 upgrade"
                )

        evidence["completed_at"] = _iso_now()
        evidence["current_stage"] = "completed"
        evidence["final_database_snapshot"] = final_snapshot
        evidence["final_image_manifest"] = _manifest_summary(final_image_manifest)
        if final_m7_content_snapshot is not None:
            evidence["final_m7_content_snapshot"] = final_m7_content_snapshot
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
            **(
                {
                    "final_m7_content_snapshot": final_m7_content_snapshot,
                    "source_m7_content_snapshot": source_m7_content_snapshot,
                    "source_m7_mard_preflight": m7_source_preflight,
                }
                if final_m7_content_snapshot is not None
                else {}
            ),
            "image_id": image_id,
            "manifest_sha256": manifest_sha256,
            "passed": True,
            "record_type": "existing-database-upgrade",
            "runtime_preflight": runtime_preflight,
            "schema_version": 1,
            "source_aerich_versions": _expected_versions(source_version),
            "source_candidate_sha": source_candidate_sha,
            "source_image_id": backup_record["image_id"],
            "source_database_snapshot": backup_record["database_snapshot"],
            "source_image_manifest": _manifest_summary(
                backup_record["image_manifest"]
            ),
            "source_version": source_version,
            "started_at": started_at,
            "target_aerich_versions": _expected_versions(TARGET_VERSION),
            "wallet_preparation": wallet_result,
            "mard_publication": mard_result,
            "table_bootstrap": table_bootstrap_result,
            "table_reconcile": table_reconcile_result,
            "table_sweep": table_sweep_result,
        }
        _write_json_exclusive(success_path, success_payload)
    except BaseException as error:
        if success_path.exists() or success_path.is_symlink():
            # success hard-link 是不可变提交点。其发布后的 temp 清理/目录
            # fsync 若报错，绝不能反向污染已绑定 digest 的 succeeded evidence。
            _validate_published_upgrade_commit(
                success_path=success_path,
                evidence_path=evidence_path,
                success_payload=success_payload,
                evidence=evidence,
            )
            raise
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
        "source_aerich_versions": _expected_versions(source_version),
        "source_candidate_sha": source_candidate_sha,
        "source_version": source_version,
        "target_aerich_versions": _expected_versions(TARGET_VERSION),
        "target_version": TARGET_VERSION,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or apply the guarded Gate A M2/M7-to-M9 upgrade or "
            "M9-to-M9 candidate adoption; M7 requires explicit "
            "--source-version 7"
        ),
    )
    parser.add_argument("--mode", choices=tuple(gatea.MODE_COMPOSE), required=True)
    parser.add_argument("--config-file", type=Path, default=gatea.DEFAULT_CONFIG_FILE)
    parser.add_argument("--secret-dir", type=Path, default=gatea.DEFAULT_SECRET_DIR)
    parser.add_argument("--source-candidate-sha", required=True)
    parser.add_argument(
        "--source-version",
        type=int,
        choices=SUPPORTED_SOURCE_VERSIONS,
        default=DEFAULT_SOURCE_VERSION,
        help=(
            "approved source checkpoint; defaults to M2 only for legacy command "
            "compatibility; M7 and M9 must be selected explicitly"
        ),
    )
    parser.add_argument("--lineage-source-candidate-sha")
    parser.add_argument("--acceptance-retirement-record-sha256")
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
    parser.add_argument(
        "--acceptance-record-dir",
        type=Path,
        default=gatea.DEFAULT_M9_ACCEPTANCE_RECORD_DIR,
    )
    parser.add_argument(
        "--acceptance-failure-archive-dir",
        type=Path,
        default=DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    )
    parser.add_argument(
        "--retirement-failure-archive-dir",
        type=Path,
        default=DEFAULT_RETIREMENT_FAILURE_ARCHIVE_DIR,
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-target-sha")
    parser.add_argument("--confirm-source-sha")
    parser.add_argument("--confirm-backup-id")
    parser.add_argument("--confirm-manifest-sha256")
    parser.add_argument("--confirm-lineage-source-sha")
    parser.add_argument("--confirm-acceptance-retirement-record-sha256")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with gatea.operation_lock(), gatea.operation_termination_guard():
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
                acceptance_record_dir=args.acceptance_record_dir,
                acceptance_failure_archive_dir=(
                    args.acceptance_failure_archive_dir
                ),
                retirement_failure_archive_dir=(
                    args.retirement_failure_archive_dir
                ),
                apply=args.apply,
                confirm_target_sha=args.confirm_target_sha,
                confirm_source_sha=args.confirm_source_sha,
                confirm_backup_id=args.confirm_backup_id,
                confirm_manifest_sha256=args.confirm_manifest_sha256,
                lineage_source_candidate_sha=args.lineage_source_candidate_sha,
                acceptance_retirement_record_sha256=(
                    args.acceptance_retirement_record_sha256
                ),
                confirm_lineage_source_sha=args.confirm_lineage_source_sha,
                confirm_acceptance_retirement_record_sha256=(
                    args.confirm_acceptance_retirement_record_sha256
                ),
                source_version=args.source_version,
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
