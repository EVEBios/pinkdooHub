#!/usr/bin/env python3
"""通过 Gate A loopback API 创建 M3--M8 综合代表性测试数据。

该入口只扩展已经完成 M2 代表数据、M2→M8 升级、当前候选备份和独立恢复
验证的持久 Gate A。三个合成账号的随机密码只写入独立的 root-only 文件；成功
Record、日志和命令行均不包含账号、密码、Token 或手机号。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any, Mapping
from urllib.parse import urlencode, urlparse

from scripts.release import gatea_backup as backup
from scripts.release import gatea_operations as gatea
from scripts.release import gatea_representative_data as base_data
from scripts.release import gatea_upgrade as upgrade


DEFAULT_BASE_RECORD = Path(
    "/srv/pinkdoohub/gatea/records/representative-data/"
    "gatea-representative-data.json"
)
DEFAULT_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/representative-data")
DEFAULT_CREDENTIALS_FILE = DEFAULT_RECORD_DIR / "gatea-m7-synthetic-credentials.json"
RECORD_PREFIX = "gatea-m7-representative-data"
EXPECTED_AERICH_VERSIONS = ",".join(gatea.APPROVED_TARGET_M8_CHAIN)
EXPECTED_RUNTIME_FEATURE_FLAGS = "true,true,true,false,disabled,true"

COLOR_PRODUCT_NAME = "[GATEA-M7] Color-selectable Kit"
COLOR_PRODUCT_PRICE = "3.00"
COLOR_COUNT = 3
COLOR_OPENING_STOCK = 50
WALLET_OPENING_BALANCE = "300.00"
WALLET_DEBIT_ADJUSTMENT = "-10.00"
EXPECTED_ORDER_USER_BALANCE = "160.00"
DEFAULT_WEEKLY_CLOSED_WEEKDAY = "monday"
TEMPORARY_WEEKLY_CLOSED_WEEKDAY = "wednesday"

SYNTHETIC_ACCOUNTS = (
    {
        "purpose": "orders-and-wallet",
        "username": "gatea_m7_orders_user",
        "nickname": "Gate A M7 Orders",
        "phone": "13900009701",
    },
    {
        "purpose": "reservations",
        "username": "gatea_m7_reservations_user",
        "nickname": "Gate A M7 Reservations",
        "phone": "13900009702",
    },
    {
        "purpose": "empty-baseline",
        "username": "gatea_m7_baseline_user",
        "nickname": "Gate A M7 Baseline",
        "phone": "13900009703",
    },
)

ORDER_REMARKS = {
    "pending_fixed": "[GATEA-M7] order:pending-fixed",
    "paid_wallet_color": "[GATEA-M7] order:paid-wallet-color",
    "paid_wallet_mixed_refunded": (
        "[GATEA-M7] order:paid-wallet-mixed-refunded"
    ),
    "completed_wallet_experience": (
        "[GATEA-M7] order:completed-wallet-experience"
    ),
    "assisted_wallet_fixed": "[GATEA-M7] order:assisted-wallet-fixed",
    "completed_manual_fixed_refunded": (
        "[GATEA-M7] order:completed-manual-fixed-refunded"
    ),
}

BASELINE_DETAILS_COMMAND = f'''MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"
export MYSQL_PWD
mysql --batch --skip-column-names --host=127.0.0.1 --user=root "$MYSQL_DATABASE" <<'SQL'
SELECT JSON_OBJECT(
  'aerich_versions', COALESCE((SELECT GROUP_CONCAT(version ORDER BY id SEPARATOR ',') FROM aerich), ''),
  'users', (SELECT COUNT(*) FROM users),
  'external_identities', (SELECT COUNT(*) FROM external_identities),
  'wallet_accounts', (SELECT COUNT(*) FROM wallet_accounts),
  'wallet_transactions', (SELECT COUNT(*) FROM wallet_transactions),
  'wallet_balance', (SELECT CAST(COALESCE(SUM(balance), 0) AS CHAR) FROM wallet_accounts),
  'payments', (SELECT COUNT(*) FROM payments),
  'payment_settlements', (SELECT COUNT(*) FROM payment_settlements),
  'refunds', (SELECT COUNT(*) FROM refunds),
  'recharge_orders', (SELECT COUNT(*) FROM recharge_orders),
  'reservations', (SELECT COUNT(*) FROM reservations),
  'store_business_days', (SELECT COUNT(*) FROM store_business_days),
  'reservation_settings', (SELECT COUNT(*) FROM reservation_settings WHERE singleton_key = 1),
  'weekly_closed_weekday', (SELECT weekly_closed_weekday FROM reservation_settings WHERE singleton_key = 1),
  'bead_colors', (SELECT COUNT(*) FROM bead_colors),
  'configured_bead_colors', (SELECT COUNT(*) FROM bead_colors WHERE color_code IS NOT NULL AND name IS NOT NULL AND swatch_hex IS NOT NULL),
  'distinct_bead_color_hex', (SELECT COUNT(DISTINCT swatch_hex) FROM bead_colors),
  'active_bead_colors', (SELECT COUNT(*) FROM bead_colors WHERE is_active = 1),
  'product_kit_colors', (SELECT COUNT(*) FROM product_kit_colors)
);
SQL'''

EXPECTED_BASELINE_DETAILS = {
    "aerich_versions": EXPECTED_AERICH_VERSIONS,
    "users": 2,
    "external_identities": 0,
    "wallet_accounts": 1,
    "wallet_transactions": 0,
    "wallet_balance": "0.00",
    "payments": 1,
    "payment_settlements": 1,
    "refunds": 0,
    "recharge_orders": 0,
    "reservations": 0,
    "store_business_days": 0,
    "reservation_settings": 1,
    "weekly_closed_weekday": DEFAULT_WEEKLY_CLOSED_WEEKDAY,
    "bead_colors": 221,
    "configured_bead_colors": 221,
    "distinct_bead_color_hex": 221,
    "active_bead_colors": 221,
    "product_kit_colors": 0,
}

AFTER_DETAILS_COMMAND = f'''MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"
export MYSQL_PWD
mysql --batch --skip-column-names --host=127.0.0.1 --user=root "$MYSQL_DATABASE" <<'SQL'
SELECT JSON_OBJECT(
  'synthetic_normal_users', (
    SELECT COUNT(*) FROM users
    WHERE username IN ('gatea_m7_orders_user', 'gatea_m7_reservations_user', 'gatea_m7_baseline_user')
      AND role = 1 AND status = 1
  ),
  'synthetic_wallets', (
    SELECT COUNT(*) FROM wallet_accounts wa
    INNER JOIN users u ON u.id = wa.user_id
    WHERE u.username IN ('gatea_m7_orders_user', 'gatea_m7_reservations_user', 'gatea_m7_baseline_user')
      AND wa.status = 'active'
  ),
  'orders_user_wallet_balance', (
    SELECT CAST(wa.balance AS CHAR) FROM wallet_accounts wa
    INNER JOIN users u ON u.id = wa.user_id
    WHERE u.username = 'gatea_m7_orders_user'
  ),
  'synthetic_wallet_transactions', (
    SELECT COUNT(*) FROM wallet_transactions wt
    INNER JOIN wallet_accounts wa ON wa.id = wt.wallet_account_id
    INNER JOIN users u ON u.id = wa.user_id
    WHERE u.username = 'gatea_m7_orders_user'
  ),
  'color_products', (
    SELECT COUNT(*) FROM products p
    INNER JOIN product_kits pk ON pk.product_id = p.id
    WHERE p.name = '{COLOR_PRODUCT_NAME}' AND p.status = 'online'
      AND p.is_deleted = 0 AND pk.kit_kind = 'color_selectable'
      AND pk.sale_unit_grams = 10 AND pk.stock IS NULL
  ),
  'color_slots', (
    SELECT COUNT(*) FROM product_kit_colors pkc
    INNER JOIN products p ON p.id = pkc.product_id
    WHERE p.name = '{COLOR_PRODUCT_NAME}'
  ),
  'enabled_colors', (
    SELECT COUNT(*) FROM product_kit_colors pkc
    INNER JOIN products p ON p.id = pkc.product_id
    WHERE p.name = '{COLOR_PRODUCT_NAME}' AND pkc.is_enabled = 1
  ),
  'color_stock_units', (
    SELECT COALESCE(SUM(pkc.stock_units), 0) FROM product_kit_colors pkc
    INNER JOIN products p ON p.id = pkc.product_id
    WHERE p.name = '{COLOR_PRODUCT_NAME}'
  ),
  'reserved_orders', (
    SELECT COUNT(*) FROM orders
    WHERE remark IN (
      '[GATEA-M7] order:pending-fixed',
      '[GATEA-M7] order:paid-wallet-color',
      '[GATEA-M7] order:paid-wallet-mixed-refunded',
      '[GATEA-M7] order:completed-wallet-experience',
      '[GATEA-M7] order:assisted-wallet-fixed',
      '[GATEA-M7] order:completed-manual-fixed-refunded'
    )
  ),
  'reserved_pending_orders', (
    SELECT COUNT(*) FROM orders
    WHERE remark = '[GATEA-M7] order:pending-fixed' AND status = 0
  ),
  'reserved_paid_orders', (
    SELECT COUNT(*) FROM orders
    WHERE remark IN (
      '[GATEA-M7] order:paid-wallet-color',
      '[GATEA-M7] order:paid-wallet-mixed-refunded',
      '[GATEA-M7] order:assisted-wallet-fixed'
    ) AND status = 1
  ),
  'reserved_completed_orders', (
    SELECT COUNT(*) FROM orders
    WHERE remark IN (
      '[GATEA-M7] order:completed-wallet-experience',
      '[GATEA-M7] order:completed-manual-fixed-refunded'
    ) AND status = 3
  ),
  'reserved_payments', (
    SELECT COUNT(*) FROM payments p
    INNER JOIN orders o ON o.id = p.order_id
    WHERE o.remark LIKE '[GATEA-M7] order:%' AND p.status = 'succeeded'
  ),
  'reserved_settlements', (
    SELECT COUNT(*) FROM payment_settlements ps
    INNER JOIN orders o ON o.id = ps.order_id
    WHERE o.remark LIKE '[GATEA-M7] order:%'
  ),
  'reserved_refunds', (
    SELECT COUNT(*) FROM refunds r
    INNER JOIN orders o ON o.id = r.order_id
    WHERE o.remark LIKE '[GATEA-M7] order:%' AND r.status = 'succeeded'
  ),
  'reserved_reservations', (
    SELECT COUNT(*) FROM reservations r
    INNER JOIN users u ON u.id = r.user_id
    WHERE u.username = 'gatea_m7_reservations_user'
  ),
  'pending_reservations', (
    SELECT COUNT(*) FROM reservations r
    INNER JOIN users u ON u.id = r.user_id
    WHERE u.username = 'gatea_m7_reservations_user' AND r.status = 'pending'
  ),
  'confirmed_reservations', (
    SELECT COUNT(*) FROM reservations r
    INNER JOIN users u ON u.id = r.user_id
    WHERE u.username = 'gatea_m7_reservations_user' AND r.status = 'confirmed'
  ),
  'rejected_reservations', (
    SELECT COUNT(*) FROM reservations r
    INNER JOIN users u ON u.id = r.user_id
    WHERE u.username = 'gatea_m7_reservations_user'
      AND r.status = 'rejected' AND r.rejection_reason = 'no_capacity'
  ),
  'customer_cancelled_reservations', (
    SELECT COUNT(*) FROM reservations r
    INNER JOIN users u ON u.id = r.user_id
    WHERE u.username = 'gatea_m7_reservations_user'
      AND r.status = 'cancelled' AND r.cancellation_reason = 'customer_request'
  ),
  'store_closed_reservations', (
    SELECT COUNT(*) FROM reservations r
    INNER JOIN users u ON u.id = r.user_id
    WHERE u.username = 'gatea_m7_reservations_user'
      AND r.status = 'cancelled' AND r.cancellation_reason = 'store_closed'
  ),
  'closed_business_days', (
    SELECT COUNT(*) FROM store_business_days WHERE is_closed = 1
  ),
  'weekly_closed_weekday', (
    SELECT weekly_closed_weekday FROM reservation_settings WHERE singleton_key = 1
  ),
  'recharge_orders', (SELECT COUNT(*) FROM recharge_orders),
  'external_identities', (SELECT COUNT(*) FROM external_identities)
);
SQL'''

EXPECTED_AFTER_DETAILS = {
    "synthetic_normal_users": 3,
    "synthetic_wallets": 3,
    "orders_user_wallet_balance": EXPECTED_ORDER_USER_BALANCE,
    "synthetic_wallet_transactions": 7,
    "color_products": 1,
    "color_slots": 221,
    "enabled_colors": 3,
    "color_stock_units": 148,
    "reserved_orders": 6,
    "reserved_pending_orders": 1,
    "reserved_paid_orders": 3,
    "reserved_completed_orders": 2,
    "reserved_payments": 5,
    "reserved_settlements": 5,
    "reserved_refunds": 2,
    "reserved_reservations": 6,
    "pending_reservations": 1,
    "confirmed_reservations": 1,
    "rejected_reservations": 1,
    "customer_cancelled_reservations": 1,
    "store_closed_reservations": 2,
    "closed_business_days": 1,
    "weekly_closed_weekday": DEFAULT_WEEKLY_CLOSED_WEEKDAY,
    "recharge_orders": 0,
    "external_identities": 0,
}

EXPECTED_AFTER_SNAPSHOT = {
    "aerich_versions": EXPECTED_AERICH_VERSIONS,
    "tables": 22,
    "columns": 217,
    "statistics": 173,
    "constraints": 83,
    "users": 5,
    "products": 3,
    "experience_options": 1,
    "product_images": 4,
    "product_kits": 2,
    "kit_stock": 7,
    "orders": 8,
    "order_items": 10,
    "order_total": "492.00",
    "inventory_transactions": 14,
    "inventory_change": 155,
}


class M7RepresentativeDataError(RuntimeError):
    """不包含身份、密码、Token、手机号或响应正文的安全错误。"""


class SecureArgumentParser(argparse.ArgumentParser):
    """参数错误不回显可能包含身份值的命令行。"""

    def error(self, message: str) -> None:
        self.exit(2, "Gate A M7 representative data arguments are invalid\n")


@dataclass(frozen=True, slots=True)
class PreparedContext:
    values: Mapping[str, str]
    config_file: Path
    secret_dir: Path
    record_dir: Path
    credentials_file: Path
    candidate_sha: str
    image_id: str
    operations_sha: str
    backup_id: str
    fixed_product_id: int
    experience_product_id: int
    before_snapshot: Mapping[str, Any]
    before_image_manifest: tuple[str, ...]
    started_at: str


LoopbackClient = base_data.LoopbackClient


def _assert_mapping(
    actual: Mapping[str, Any], expected: Mapping[str, Any], label: str
) -> None:
    mismatched = [key for key, value in expected.items() if actual.get(key) != value]
    if mismatched:
        raise M7RepresentativeDataError(
            f"Gate A M7 {label} does not match: {','.join(sorted(mismatched))}"
        )


def _database_details(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    command: str,
) -> dict[str, Any]:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("exec", "--no-TTY", "mysql", "sh", "-ec", command),
        capture_output=True,
    )
    return backup._parse_snapshot(result.stdout)


def _load_base_record(
    path: Path,
    *,
    source_candidate_sha: str,
    source_image_id: str,
) -> tuple[int, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        product_ids = payload["product_ids"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as error:
        raise M7RepresentativeDataError(
            "Gate A M2 representative data record is unavailable"
        ) from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("candidate_sha") != source_candidate_sha
        or payload.get("image_id") != source_image_id
        or payload.get("passed") is not True
        or payload.get("synthetic_user_disabled") is not True
        or payload.get("synthetic_session_revoked") is not True
        or payload.get("super_admin_session_revoked") is not True
        or not isinstance(product_ids, list)
        or len(product_ids) != 2
        or any(not isinstance(item, int) or item <= 0 for item in product_ids)
    ):
        raise M7RepresentativeDataError(
            "Gate A M2 representative data record is invalid"
        )
    return int(product_ids[0]), int(product_ids[1])


def _operations_sha(release_record_dir: Path) -> str:
    operations_sha = gatea.REPOSITORY_ROOT.resolve().name
    if gatea.GIT_SHA_PATTERN.fullmatch(operations_sha) is None:
        raise M7RepresentativeDataError(
            "Gate A M7 operation must run from a versioned release directory"
        )
    source_record = release_record_dir / f"{operations_sha}.source-sha"
    ci_record = release_record_dir / f"{operations_sha}.ci-run-id"
    try:
        source_value = source_record.read_text(encoding="utf-8").strip()
        ci_value = ci_record.read_text(encoding="utf-8").strip()
    except FileNotFoundError as error:
        raise M7RepresentativeDataError(
            "Gate A M7 operation source evidence is unavailable"
        ) from error
    if source_value != operations_sha or not ci_value.isascii() or not ci_value.isdecimal():
        raise M7RepresentativeDataError(
            "Gate A M7 operation source evidence is invalid"
        )
    return operations_sha


def _require_feature_flags(values: Mapping[str, str]) -> None:
    required = (
        "WALLET_ADMIN_WRITE_ENABLED",
        "WALLET_ORDER_PAYMENT_ENABLED",
        "WALLET_REFUND_ENABLED",
    )
    invalid = [name for name in required if values.get(name) != "true"]
    if invalid:
        raise M7RepresentativeDataError(
            "Gate A M7 internal wallet feature flags are not enabled: "
            + ",".join(invalid)
        )
    if values.get("WALLET_TOPUP_ENABLED", "false") != "false":
        raise M7RepresentativeDataError(
            "Gate A M7 wallet top-up feature must remain disabled"
        )
    if values.get("PAYMENT_PROVIDER", "disabled") != "disabled":
        raise M7RepresentativeDataError(
            "Gate A M7 payment provider must remain disabled"
        )
    if values.get("PASSWORD_REGISTRATION_ENABLED", "false") != "true":
        raise M7RepresentativeDataError(
            "Gate A M7 password registration must be enabled for synthetic data"
        )


def _require_runtime_feature_flags(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> None:
    """确认当前长期 App 进程实际加载了已批准的非 Secret 开关。"""

    command = (
        "from pathlib import Path; "
        "targets=(b'WALLET_ADMIN_WRITE_ENABLED',"
        "b'WALLET_ORDER_PAYMENT_ENABLED',b'WALLET_REFUND_ENABLED',"
        "b'WALLET_TOPUP_ENABLED',b'PAYMENT_PROVIDER',"
        "b'PASSWORD_REGISTRATION_ENABLED'); "
        "pairs=(item.partition(b'=') for item in "
        "Path('/proc/1/environ').read_bytes().split(b'\\0') if b'=' in item); "
        "env={key.decode():value.decode() for key,sep,value in pairs "
        "if sep and key in targets}; "
        "print(','.join(("
        "env.get('WALLET_ADMIN_WRITE_ENABLED',''),"
        "env.get('WALLET_ORDER_PAYMENT_ENABLED',''),"
        "env.get('WALLET_REFUND_ENABLED',''),"
        "env.get('WALLET_TOPUP_ENABLED',''),"
        "env.get('PAYMENT_PROVIDER',''),"
        "env.get('PASSWORD_REGISTRATION_ENABLED',''))))"
    )
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("exec", "--no-TTY", "app", "python", "-c", command),
        capture_output=True,
    )
    if result.stdout.strip() != EXPECTED_RUNTIME_FEATURE_FLAGS:
        raise M7RepresentativeDataError(
            "Gate A M7 running App feature flags do not match the config"
        )


def prepare(
    *,
    username: str,
    confirm_username: str,
    backup_id: str,
    confirm_backup_id: str,
    config_file: Path,
    secret_dir: Path,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
    release_record_dir: Path,
    base_record: Path,
    record_dir: Path,
    credentials_file: Path,
    acceptance_record_dir: Path = gatea.DEFAULT_M9_ACCEPTANCE_RECORD_DIR,
) -> PreparedContext:
    """在读取密码和执行 API 写入前完成全部候选、备份与基线检查。"""

    if os.geteuid() != 0:
        raise M7RepresentativeDataError(
            "Gate A M7 representative data must run as root"
        )
    base_data._validate_identity(username, confirm_username)
    backup_id = backup._backup_id(backup_id)
    if confirm_backup_id != backup_id:
        raise M7RepresentativeDataError(
            "Gate A M7 backup confirmation does not match"
        )
    gatea._validate_root_directory(
        release_record_dir,
        0o755,
        "Gate A release record directory",
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
        mode="loopback",
        require_available_port=False,
    )
    _require_feature_flags(values)
    gatea._validate_root_directory(
        record_dir,
        0o755,
        "Gate A representative data record directory",
    )
    if credentials_file.parent.resolve() != record_dir.resolve():
        raise M7RepresentativeDataError(
            "Gate A M7 credentials file must be inside the record directory"
        )
    if credentials_file.exists() or credentials_file.with_suffix(
        credentials_file.suffix + ".pending"
    ).exists():
        raise M7RepresentativeDataError(
            "Gate A M7 synthetic credentials file already exists"
        )

    image_id = gatea.validate_app_image(values)
    candidate_sha = gatea._candidate_sha(values)
    operations_sha = _operations_sha(release_record_dir)
    record_path = record_dir / f"{RECORD_PREFIX}-{candidate_sha}.json"
    if record_path.exists():
        raise M7RepresentativeDataError(
            "Gate A M7 representative data is already recorded"
        )
    upgrade_record = gatea._require_upgrade_record(
        record_dir=release_record_dir,
        candidate_sha=candidate_sha,
        image_id=image_id,
    )
    experience_product_id, fixed_product_id = _load_base_record(
        base_record,
        source_candidate_sha=str(upgrade_record["source_candidate_sha"]),
        source_image_id=str(upgrade_record["source_image_id"]),
    )
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=("mysql", "redis", "app", "nginx"),
    )
    gatea._ensure_services_healthy(rows, "mysql", "redis", "app", "nginx")
    gatea._validate_loopback_publishers(
        rows,
        int(values.get("GATEA_LOOPBACK_PORT", "18080")),
    )
    _require_runtime_feature_flags(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
    )

    backup_payload = upgrade._load_verified_backup(
        values=values,
        backup_id=backup_id,
        source_candidate_sha=candidate_sha,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
    ).backup_record
    if backup_payload.get("image_id") != image_id:
        raise M7RepresentativeDataError(
            "Gate A M7 verified backup image does not match the candidate"
        )
    before_snapshot = backup._source_snapshot(
        values, config_file, secret_dir, "loopback"
    )
    before_images = tuple(
        backup._source_image_manifest(values, config_file, secret_dir, "loopback")
    )
    if backup_payload.get("database_snapshot") != before_snapshot:
        raise M7RepresentativeDataError(
            "Gate A M7 database changed after the verified backup"
        )
    if backup_payload.get("image_manifest") != list(before_images):
        raise M7RepresentativeDataError(
            "Gate A M7 images changed after the verified backup"
        )
    details = _database_details(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        command=BASELINE_DETAILS_COMMAND,
    )
    _assert_mapping(details, EXPECTED_BASELINE_DETAILS, "pre-write details")
    return PreparedContext(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        record_dir=record_dir,
        credentials_file=credentials_file,
        candidate_sha=candidate_sha,
        image_id=image_id,
        operations_sha=operations_sha,
        backup_id=backup_id,
        fixed_product_id=fixed_product_id,
        experience_product_id=experience_product_id,
        before_snapshot=before_snapshot,
        before_image_manifest=before_images,
        started_at=datetime.now(timezone.utc).isoformat(),
    )


def _write_credentials_pending(
    context: PreparedContext,
    accounts: list[dict[str, str]],
) -> Path:
    pending = context.credentials_file.with_suffix(
        context.credentials_file.suffix + ".pending"
    )
    payload = {
        "schema_version": 1,
        "environment": "gatea",
        "candidate_sha": context.candidate_sha,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "accounts": accounts,
    }
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return pending


def _data(document: Mapping[str, Any], step: str) -> dict[str, Any]:
    data = document.get("data")
    if not isinstance(data, dict):
        raise M7RepresentativeDataError(
            f"Gate A M7 step {step} returned invalid data"
        )
    return data


def _enum_value(payload: Mapping[str, Any], field: str) -> object:
    value = payload.get(field)
    return value.get("value") if isinstance(value, dict) else None


def _assert_status(
    payload: Mapping[str, Any], expected: str, step: str
) -> None:
    if _enum_value(payload, "status") != expected:
        raise M7RepresentativeDataError(
            f"Gate A M7 step {step} returned an invalid status"
        )


def _order_item(
    product_id: int,
    *,
    quantity: int = 1,
    option_id: int | None = None,
    color_id: int | None = None,
) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "experience_option_id": option_id,
        "kit_color_id": color_id,
        "quantity": quantity,
    }


def _reservation_slots(options: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_dates = options.get("dates")
    if not isinstance(raw_dates, list):
        raise M7RepresentativeDataError(
            "Gate A M7 reservation booking options are invalid"
        )
    dates = [item for item in raw_dates if isinstance(item, dict)]
    weekly = [
        item
        for item in dates
        if date.fromisoformat(str(item.get("date"))).weekday() == 2
    ]
    regular = [
        item
        for item in dates
        if date.fromisoformat(str(item.get("date"))).weekday() != 2
    ]
    if len(regular) < 5 or not weekly:
        raise M7RepresentativeDataError(
            "Gate A M7 reservation calendar has insufficient representative dates"
        )
    selected = regular[:5]
    for item in (*selected, weekly[0]):
        start_times = item.get("start_times")
        if not isinstance(start_times, list) or not start_times:
            raise M7RepresentativeDataError(
                "Gate A M7 reservation booking options contain no start time"
            )
    return selected, weekly[0]


def _credentials_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(
    context: PreparedContext,
    *,
    username: str,
    password: str,
) -> dict[str, Any]:
    """创建代表数据、撤销全部会话、验收数据库并写脱敏成功 Record。"""

    client = LoopbackClient(int(context.values.get("GATEA_LOOPBACK_PORT", "18080")))
    admin: dict[str, Any] | None = None
    sessions: dict[str, dict[str, Any]] = {}
    logged_out: set[str] = set()
    admin_logged_out = False
    pending_credentials: Path | None = None
    operation_error: BaseException | None = None
    cleanup_errors: list[str] = []
    result_ids: dict[str, Any] = {}

    try:
        admin = base_data._login(
            client,
            step="login-super-admin",
            username=username,
            password=password,
            expected_role="super_admin",
        )
        credential_accounts = [
            {
                "purpose": str(spec["purpose"]),
                "username": str(spec["username"]),
                "password": secrets.token_urlsafe(32),
            }
            for spec in SYNTHETIC_ACCOUNTS
        ]
        pending_credentials = _write_credentials_pending(
            context, credential_accounts
        )
        user_ids: dict[str, int] = {}
        for spec, credential in zip(SYNTHETIC_ACCOUNTS, credential_accounts, strict=True):
            purpose = str(spec["purpose"])
            registered = _data(
                client.json_request(
                    f"register-{purpose}-user",
                    "POST",
                    "/api/v1/auth/register",
                    payload={
                        "username": credential["username"],
                        "password": credential["password"],
                        "nickname": spec["nickname"],
                        "phone": spec["phone"],
                    },
                    expected_status=201,
                ),
                f"register-{purpose}-user",
            )
            user_ids[purpose] = int(registered["id"])
            sessions[purpose] = base_data._login(
                client,
                step=f"login-{purpose}-user",
                username=credential["username"],
                password=credential["password"],
                expected_role="user",
            )
        for credential in credential_accounts:
            credential["password"] = ""
        credential_accounts.clear()

        admin_token = str(admin["access_token"])
        order_token = str(sessions["orders-and-wallet"]["access_token"])
        reservation_token = str(sessions["reservations"]["access_token"])

        experience = _data(
            client.json_request(
                "read-base-experience",
                "GET",
                f"/api/v1/admin/products/experience/{context.experience_product_id}",
                token=admin_token,
            ),
            "read-base-experience",
        )
        options = experience.get("options")
        if not isinstance(options, list) or len(options) != 1:
            raise M7RepresentativeDataError(
                "Gate A M7 base experience option is invalid"
            )
        option_id = int(options[0]["id"])
        fixed = _data(
            client.json_request(
                "read-base-fixed-kit",
                "GET",
                f"/api/v1/admin/products/kit/{context.fixed_product_id}",
                token=admin_token,
            ),
            "read-base-fixed-kit",
        )
        if _enum_value(fixed, "kit_kind") != "fixed" or fixed.get("stock") != 10:
            raise M7RepresentativeDataError(
                "Gate A M7 base fixed Kit is invalid"
            )

        color_product = _data(
            client.json_request(
                "create-color-kit",
                "POST",
                "/api/v1/admin/products/kit",
                token=admin_token,
                payload={
                    "name": COLOR_PRODUCT_NAME,
                    "description": "Gate A M7 color, inventory, wallet and refund fixture",
                    "price": COLOR_PRODUCT_PRICE,
                    "kit_kind": "color_selectable",
                },
                expected_status=201,
            ),
            "create-color-kit",
        )
        color_product_id = int(color_product["id"])
        color_image = base_data._upload_image(
            client,
            step="upload-color-kit-cover",
            path=f"/api/v1/admin/products/{color_product_id}/images",
            token=admin_token,
            fields={"is_cover": "true", "sort": "0"},
        )
        base_data._verify_image_read(
            client, step="read-color-kit-cover", image=color_image
        )
        color_detail = _data(
            client.json_request(
                "read-color-kit-draft",
                "GET",
                f"/api/v1/admin/products/kit/{color_product_id}",
                token=admin_token,
            ),
            "read-color-kit-draft",
        )
        color_rows = color_detail.get("colors")
        if not isinstance(color_rows, list) or len(color_rows) != 221:
            raise M7RepresentativeDataError(
                "Gate A M7 color Kit does not contain 221 slots"
            )
        selected_colors = [
            item
            for item in color_rows
            if isinstance(item, dict)
            and item.get("is_active") is True
            and item.get("is_configured") is True
        ][:COLOR_COUNT]
        if len(selected_colors) != COLOR_COUNT:
            raise M7RepresentativeDataError(
                "Gate A M7 color catalog has fewer than three sale-ready colors"
            )
        color_ids: list[int] = []
        for index, color in enumerate(selected_colors, start=1):
            color_id = int(color["id"])
            color_ids.append(color_id)
            client.json_request(
                f"enable-color-{index}",
                "PATCH",
                f"/api/v1/admin/product-kit-colors/{color_id}",
                token=admin_token,
                payload={"is_enabled": True},
            )
            adjusted = _data(
                client.json_request(
                    f"supply-color-{index}",
                    "POST",
                    f"/api/v1/admin/products/kit/{color_product_id}/colors/"
                    f"{color_id}/inventory-adjustments",
                    token=admin_token,
                    payload={
                        "change": COLOR_OPENING_STOCK,
                        "reason": "Gate A M7 representative color supply",
                    },
                    headers={
                        "Idempotency-Key": f"gatea-m7-color-supply-{index}-v1"
                    },
                    expected_status=201,
                ),
                f"supply-color-{index}",
            )
            if adjusted.get("stock_units") != COLOR_OPENING_STOCK:
                raise M7RepresentativeDataError(
                    "Gate A M7 color inventory adjustment is invalid"
                )
        client.json_request(
            "replay-color-supply-1",
            "POST",
            f"/api/v1/admin/products/kit/{color_product_id}/colors/"
            f"{color_ids[0]}/inventory-adjustments",
            token=admin_token,
            payload={
                "change": COLOR_OPENING_STOCK,
                "reason": "Gate A M7 representative color supply",
            },
            headers={"Idempotency-Key": "gatea-m7-color-supply-1-v1"},
            expected_status=200,
        )
        client.json_request(
            "online-color-kit",
            "PATCH",
            f"/api/v1/admin/products/{color_product_id}/online",
            token=admin_token,
        )
        public_color = _data(
            client.json_request(
                "read-public-color-kit",
                "GET",
                f"/api/v1/products/kit/{color_product_id}",
            ),
            "read-public-color-kit",
        )
        if len(public_color.get("colors", [])) != COLOR_COUNT:
            raise M7RepresentativeDataError(
                "Gate A M7 public color Kit has invalid enabled colors"
            )
        swatch_hex = public_color["colors"][0].get("swatch_hex")
        if (
            not isinstance(swatch_hex, str)
            or len(swatch_hex) != 7
            or not swatch_hex.startswith("#")
            or any(
                character not in "0123456789ABCDEF"
                for character in swatch_hex[1:]
            )
        ):
            raise M7RepresentativeDataError(
                "Gate A M7 public color swatch HEX is invalid"
            )
        swatch_url = str(public_color["colors"][0]["swatch_image_url"])
        parsed_swatch = urlparse(swatch_url)
        if parsed_swatch.scheme != "https" or not parsed_swatch.path.startswith(
            "/uploads/products/"
        ):
            raise M7RepresentativeDataError(
                "Gate A M7 public color swatch URL is invalid"
            )
        _, swatch_headers = client.request(
            "read-public-color-swatch", "GET", parsed_swatch.path
        )
        if not swatch_headers.get("Content-Type", "").startswith("image/png"):
            raise M7RepresentativeDataError(
                "Gate A M7 public color swatch content type is invalid"
            )

        order_user_id = user_ids["orders-and-wallet"]
        client.json_request(
            "credit-orders-wallet",
            "POST",
            f"/api/v1/admin/users/{order_user_id}/wallet-adjustments",
            token=admin_token,
            payload={
                "change": WALLET_OPENING_BALANCE,
                "reason": "Gate A M7 representative opening balance",
            },
            headers={"Idempotency-Key": "gatea-m7-wallet-credit-v1"},
            expected_status=201,
        )
        client.json_request(
            "replay-orders-wallet-credit",
            "POST",
            f"/api/v1/admin/users/{order_user_id}/wallet-adjustments",
            token=admin_token,
            payload={
                "change": WALLET_OPENING_BALANCE,
                "reason": "Gate A M7 representative opening balance",
            },
            headers={"Idempotency-Key": "gatea-m7-wallet-credit-v1"},
            expected_status=200,
        )
        client.json_request(
            "debit-orders-wallet",
            "POST",
            f"/api/v1/admin/users/{order_user_id}/wallet-adjustments",
            token=admin_token,
            payload={
                "change": WALLET_DEBIT_ADJUSTMENT,
                "reason": "Gate A M7 representative debit adjustment",
            },
            headers={"Idempotency-Key": "gatea-m7-wallet-debit-v1"},
            expected_status=201,
        )
        client.json_request(
            "wechat-recharge-disabled",
            "POST",
            "/api/v1/wallet/recharges",
            token=order_token,
            payload={"amount": "10.00"},
            headers={"Idempotency-Key": "gatea-m7-disabled-recharge-v1"},
            expected_status=503,
            expected_code=503,
        )

        def create_order(
            step: str, items: list[dict[str, Any]], remark: str
        ) -> dict[str, Any]:
            return _data(
                client.json_request(
                    step,
                    "POST",
                    "/api/v1/orders",
                    token=order_token,
                    payload={"items": items, "remark": remark},
                    expected_status=201,
                ),
                step,
            )

        pending = create_order(
            "create-pending-fixed-order",
            [_order_item(context.fixed_product_id)],
            ORDER_REMARKS["pending_fixed"],
        )
        client.json_request(
            "wechat-order-payment-disabled",
            "POST",
            f"/api/v1/orders/{pending['id']}/payments/wechat",
            token=order_token,
            headers={"Idempotency-Key": "gatea-m7-disabled-wechat-payment-v1"},
            expected_status=503,
            expected_code=503,
        )

        paid_color = create_order(
            "create-wallet-color-order",
            [_order_item(color_product_id, quantity=2, color_id=color_ids[0])],
            ORDER_REMARKS["paid_wallet_color"],
        )
        client.json_request(
            "pay-color-order-with-wallet",
            "POST",
            f"/api/v1/orders/{paid_color['id']}/payments/wallet",
            token=order_token,
            headers={"Idempotency-Key": "gatea-m7-pay-color-v1"},
            expected_status=201,
        )
        client.json_request(
            "replay-color-wallet-payment",
            "POST",
            f"/api/v1/orders/{paid_color['id']}/payments/wallet",
            token=order_token,
            headers={"Idempotency-Key": "gatea-m7-pay-color-v1"},
            expected_status=200,
        )

        mixed = create_order(
            "create-wallet-mixed-order",
            [
                _order_item(context.fixed_product_id),
                _order_item(color_product_id, quantity=2, color_id=color_ids[1]),
            ],
            ORDER_REMARKS["paid_wallet_mixed_refunded"],
        )
        client.json_request(
            "pay-mixed-order-with-wallet",
            "POST",
            f"/api/v1/orders/{mixed['id']}/payments/wallet",
            token=order_token,
            headers={"Idempotency-Key": "gatea-m7-pay-mixed-v1"},
            expected_status=201,
        )
        client.json_request(
            "refund-mixed-wallet-order",
            "POST",
            f"/api/v1/admin/orders/{mixed['id']}/refunds",
            token=admin_token,
            payload={"reason": "Gate A M7 paid wallet refund"},
            headers={"Idempotency-Key": "gatea-m7-refund-mixed-v1"},
            expected_status=201,
        )
        client.json_request(
            "replay-mixed-wallet-refund",
            "POST",
            f"/api/v1/admin/orders/{mixed['id']}/refunds",
            token=admin_token,
            payload={"reason": "Gate A M7 paid wallet refund"},
            headers={"Idempotency-Key": "gatea-m7-refund-mixed-v1"},
            expected_status=200,
        )

        completed_wallet = create_order(
            "create-completed-wallet-experience-order",
            [
                _order_item(
                    context.experience_product_id,
                    option_id=option_id,
                )
            ],
            ORDER_REMARKS["completed_wallet_experience"],
        )
        client.json_request(
            "pay-experience-order-with-wallet",
            "POST",
            f"/api/v1/orders/{completed_wallet['id']}/payments/wallet",
            token=order_token,
            headers={"Idempotency-Key": "gatea-m7-pay-experience-v1"},
            expected_status=201,
        )
        completed_wallet_result = _data(
            client.json_request(
                "complete-wallet-experience-order",
                "PATCH",
                f"/api/v1/admin/orders/{completed_wallet['id']}/complete",
                token=admin_token,
            ),
            "complete-wallet-experience-order",
        )
        _assert_status(
            completed_wallet_result,
            "completed",
            "complete-wallet-experience-order",
        )

        assisted_payload = {
            "items": [_order_item(context.fixed_product_id)],
            "remark": ORDER_REMARKS["assisted_wallet_fixed"],
        }
        assisted = _data(
            client.json_request(
                "create-assisted-wallet-order",
                "POST",
                f"/api/v1/admin/users/{order_user_id}/wallet-orders",
                token=admin_token,
                payload=assisted_payload,
                headers={"Idempotency-Key": "gatea-m7-assisted-order-v1"},
                expected_status=201,
            ),
            "create-assisted-wallet-order",
        )
        client.json_request(
            "replay-assisted-wallet-order",
            "POST",
            f"/api/v1/admin/users/{order_user_id}/wallet-orders",
            token=admin_token,
            payload=assisted_payload,
            headers={"Idempotency-Key": "gatea-m7-assisted-order-v1"},
            expected_status=200,
        )

        manual = create_order(
            "create-manual-fixed-order",
            [_order_item(context.fixed_product_id)],
            ORDER_REMARKS["completed_manual_fixed_refunded"],
        )
        client.json_request(
            "mark-manual-fixed-order-paid",
            "PATCH",
            f"/api/v1/admin/orders/{manual['id']}/paid",
            token=admin_token,
        )
        manual_completed = _data(
            client.json_request(
                "complete-manual-fixed-order",
                "PATCH",
                f"/api/v1/admin/orders/{manual['id']}/complete",
                token=admin_token,
            ),
            "complete-manual-fixed-order",
        )
        _assert_status(
            manual_completed, "completed", "complete-manual-fixed-order"
        )
        client.json_request(
            "refund-completed-manual-order",
            "POST",
            f"/api/v1/admin/orders/{manual['id']}/refunds",
            token=admin_token,
            payload={"reason": "Gate A M7 completed manual refund"},
            headers={"Idempotency-Key": "gatea-m7-refund-manual-v1"},
            expected_status=201,
        )
        client.json_request(
            "replay-completed-manual-refund",
            "POST",
            f"/api/v1/admin/orders/{manual['id']}/refunds",
            token=admin_token,
            payload={"reason": "Gate A M7 completed manual refund"},
            headers={"Idempotency-Key": "gatea-m7-refund-manual-v1"},
            expected_status=200,
        )

        client.json_request(
            "read-user-wallet",
            "GET",
            "/api/v1/wallet",
            token=order_token,
        )
        client.json_request(
            "read-user-wallet-transactions",
            "GET",
            "/api/v1/wallet/transactions?page=1&page_size=20",
            token=order_token,
        )
        client.json_request(
            "read-admin-wallet-transactions",
            "GET",
            f"/api/v1/admin/users/{order_user_id}/wallet-transactions"
            "?page=1&page_size=20",
            token=admin_token,
        )
        client.json_request(
            "read-user-order-financials",
            "GET",
            f"/api/v1/orders/{mixed['id']}/financials",
            token=order_token,
        )
        client.json_request(
            "read-admin-order-financials",
            "GET",
            f"/api/v1/admin/orders/{manual['id']}/financials",
            token=admin_token,
        )

        booking_options = _data(
            client.json_request(
                "read-reservation-booking-options",
                "GET",
                "/api/v1/reservations/booking-options?"
                + urlencode({"experience_option_id": option_id}),
                token=reservation_token,
            ),
            "read-reservation-booking-options",
        )
        regular_dates, weekly_date = _reservation_slots(booking_options)

        def create_reservation(step: str, slot: Mapping[str, Any]) -> dict[str, Any]:
            return _data(
                client.json_request(
                    step,
                    "POST",
                    "/api/v1/reservations",
                    token=reservation_token,
                    payload={
                        "experience_option_id": option_id,
                        "reservation_date": slot["date"],
                        "start_time": slot["start_times"][0],
                    },
                    expected_status=201,
                ),
                step,
            )

        pending_reservation = create_reservation(
            "create-pending-reservation", regular_dates[0]
        )
        confirmed_reservation = create_reservation(
            "create-confirmed-reservation", regular_dates[1]
        )
        rejected_reservation = create_reservation(
            "create-rejected-reservation", regular_dates[2]
        )
        cancelled_reservation = create_reservation(
            "create-customer-cancelled-reservation", regular_dates[3]
        )
        closed_reservation = create_reservation(
            "create-store-closed-reservation", regular_dates[4]
        )
        weekly_reservation = create_reservation(
            "create-weekly-closed-reservation", weekly_date
        )
        confirmed = _data(
            client.json_request(
                "confirm-reservation",
                "PATCH",
                f"/api/v1/admin/reservations/{confirmed_reservation['id']}/confirm",
                token=admin_token,
            ),
            "confirm-reservation",
        )
        _assert_status(confirmed, "confirmed", "confirm-reservation")
        rejected = _data(
            client.json_request(
                "reject-reservation",
                "PATCH",
                f"/api/v1/admin/reservations/{rejected_reservation['id']}/reject",
                token=admin_token,
            ),
            "reject-reservation",
        )
        _assert_status(rejected, "rejected", "reject-reservation")
        cancelled = _data(
            client.json_request(
                "cancel-reservation",
                "PATCH",
                f"/api/v1/reservations/{cancelled_reservation['id']}/cancel",
                token=reservation_token,
            ),
            "cancel-reservation",
        )
        _assert_status(cancelled, "cancelled", "cancel-reservation")
        client.json_request(
            "close-store-day",
            "PUT",
            f"/api/v1/admin/store-closures/{closed_reservation['reservation_date']}",
            token=admin_token,
            expected_status=201,
        )
        client.json_request(
            "set-temporary-weekly-closure",
            "PUT",
            "/api/v1/admin/reservation-settings/weekly-closed-day",
            token=admin_token,
            payload={
                "weekly_closed_weekday": TEMPORARY_WEEKLY_CLOSED_WEEKDAY
            },
        )
        client.json_request(
            "restore-default-weekly-closure",
            "PUT",
            "/api/v1/admin/reservation-settings/weekly-closed-day",
            token=admin_token,
            payload={"weekly_closed_weekday": DEFAULT_WEEKLY_CLOSED_WEEKDAY},
        )
        for step, reservation_id, expected in (
            ("verify-pending-reservation", pending_reservation["id"], "pending"),
            ("verify-store-closed-reservation", closed_reservation["id"], "cancelled"),
            ("verify-weekly-closed-reservation", weekly_reservation["id"], "cancelled"),
        ):
            reservation = _data(
                client.json_request(
                    step,
                    "GET",
                    f"/api/v1/reservations/{reservation_id}",
                    token=reservation_token,
                ),
                step,
            )
            _assert_status(reservation, expected, step)
        client.json_request(
            "read-user-reservations",
            "GET",
            "/api/v1/reservations?page=1&page_size=20",
            token=reservation_token,
        )
        client.json_request(
            "read-admin-reservations",
            "GET",
            "/api/v1/admin/reservations?page=1&page_size=20",
            token=admin_token,
        )
        client.json_request(
            "read-store-closures",
            "GET",
            "/api/v1/admin/store-closures?page=1&page_size=20&is_closed=true",
            token=admin_token,
        )

        baseline_session = sessions["empty-baseline"]
        rotated = _data(
            client.json_request(
                "rotate-baseline-refresh-family",
                "POST",
                "/api/v1/auth/refresh",
                payload={"refresh_token": baseline_session["refresh_token"]},
            ),
            "rotate-baseline-refresh-family",
        )
        client.json_request(
            "reject-replayed-baseline-refresh",
            "POST",
            "/api/v1/auth/refresh",
            payload={"refresh_token": baseline_session["refresh_token"]},
            expected_status=400,
            expected_code=1006,
        )
        sessions["empty-baseline"] = rotated
        client.json_request(
            "read-baseline-profile",
            "GET",
            "/api/v1/users/me",
            token=str(rotated["access_token"]),
        )
        client.json_request(
            "read-baseline-wallet",
            "GET",
            "/api/v1/wallet",
            token=str(rotated["access_token"]),
        )

        result_ids = {
            "synthetic_user_ids": sorted(user_ids.values()),
            "color_product_id": color_product_id,
            "color_ids": color_ids,
            "order_ids": [
                int(pending["id"]),
                int(paid_color["id"]),
                int(mixed["id"]),
                int(completed_wallet["id"]),
                int(assisted["order"]["id"]),
                int(manual["id"]),
            ],
            "reservation_ids": [
                int(pending_reservation["id"]),
                int(confirmed_reservation["id"]),
                int(rejected_reservation["id"]),
                int(cancelled_reservation["id"]),
                int(closed_reservation["id"]),
                int(weekly_reservation["id"]),
            ],
        }
    except BaseException as error:
        operation_error = error
    finally:
        for purpose, session in sessions.items():
            if purpose in logged_out:
                continue
            try:
                base_data._logout_and_verify(
                    client,
                    step_prefix=f"cleanup-{purpose}",
                    access_token=str(session["access_token"]),
                    refresh_token=str(session["refresh_token"]),
                )
                logged_out.add(purpose)
            except BaseException:
                cleanup_errors.append(f"{purpose}-session")
        if admin is not None and not admin_logged_out:
            try:
                base_data._logout_and_verify(
                    client,
                    step_prefix="cleanup-super-admin",
                    access_token=str(admin["access_token"]),
                    refresh_token=str(admin["refresh_token"]),
                )
                admin_logged_out = True
            except BaseException:
                cleanup_errors.append("super-admin-session")

    password = ""
    if cleanup_errors:
        raise M7RepresentativeDataError(
            "Gate A M7 representative data cleanup failed: "
            + ",".join(cleanup_errors)
        ) from operation_error
    if operation_error is not None:
        if isinstance(operation_error, (KeyboardInterrupt, SystemExit)):
            raise operation_error
        if isinstance(operation_error, M7RepresentativeDataError):
            raise operation_error
        if isinstance(operation_error, base_data.RepresentativeDataError):
            raise M7RepresentativeDataError(str(operation_error)) from operation_error
        raise M7RepresentativeDataError(
            "Gate A M7 representative data operation failed safely"
        ) from operation_error
    if pending_credentials is None:
        raise M7RepresentativeDataError(
            "Gate A M7 pending credentials file is unavailable"
        )

    after_snapshot = backup._source_snapshot(
        context.values, context.config_file, context.secret_dir, "loopback"
    )
    _assert_mapping(after_snapshot, EXPECTED_AFTER_SNAPSHOT, "post-write snapshot")
    if int(after_snapshot.get("audit_logs", 0)) <= int(
        context.before_snapshot.get("audit_logs", 0)
    ):
        raise M7RepresentativeDataError(
            "Gate A M7 post-write audit count did not increase"
        )
    after_details = _database_details(
        values=context.values,
        config_file=context.config_file,
        secret_dir=context.secret_dir,
        command=AFTER_DETAILS_COMMAND,
    )
    _assert_mapping(after_details, EXPECTED_AFTER_DETAILS, "post-write details")
    after_images = tuple(
        backup._source_image_manifest(
            context.values, context.config_file, context.secret_dir, "loopback"
        )
    )
    if len(after_images) != len(context.before_image_manifest) + 1:
        raise M7RepresentativeDataError(
            "Gate A M7 image manifest did not gain exactly one product image"
        )

    os.replace(pending_credentials, context.credentials_file)
    credentials_sha256 = _credentials_sha256(context.credentials_file)
    record = {
        "schema_version": 1,
        "record_type": "gatea-m7-representative-data",
        "candidate_sha": context.candidate_sha,
        "image_id": context.image_id,
        "operations_sha": context.operations_sha,
        "backup_id": context.backup_id,
        "started_at": context.started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "before_snapshot": dict(context.before_snapshot),
        "after_snapshot": after_snapshot,
        "representative_details": after_details,
        "synthetic_user_ids": result_ids["synthetic_user_ids"],
        "color_product_id": result_ids["color_product_id"],
        "color_ids": result_ids["color_ids"],
        "order_ids": result_ids["order_ids"],
        "reservation_ids": result_ids["reservation_ids"],
        "before_image_file_count": len(context.before_image_manifest),
        "after_image_file_count": len(after_images),
        "request_count": len(client.results),
        "synthetic_sessions_revoked": len(logged_out) == len(SYNTHETIC_ACCOUNTS),
        "super_admin_session_revoked": admin_logged_out,
        "credentials_file": str(context.credentials_file),
        "credentials_file_mode": "0600",
        "credentials_sha256": credentials_sha256,
        "super_admin_credentials_recorded": False,
        "request_or_response_bodies_recorded": False,
        "loopback_only": True,
        "passed": True,
    }
    backup._write_json_atomic(
        context.record_dir / f"{RECORD_PREFIX}-{context.candidate_sha}.json",
        record,
        0o644,
    )
    return record


def _parser() -> argparse.ArgumentParser:
    parser = SecureArgumentParser(description=__doc__)
    parser.add_argument("--super-admin-username", required=True)
    parser.add_argument("--confirm-super-admin-username", required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--confirm-backup-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--config-file", type=Path, default=gatea.DEFAULT_CONFIG_FILE)
    parser.add_argument("--secret-dir", type=Path, default=gatea.DEFAULT_SECRET_DIR)
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
    parser.add_argument("--base-record", type=Path, default=DEFAULT_BASE_RECORD)
    parser.add_argument("--record-dir", type=Path, default=DEFAULT_RECORD_DIR)
    parser.add_argument(
        "--credentials-file", type=Path, default=DEFAULT_CREDENTIALS_FILE
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if not arguments.apply:
            raise M7RepresentativeDataError(
                "Gate A M7 representative data requires --apply"
            )
        with gatea.operation_lock():
            context = prepare(
                username=arguments.super_admin_username,
                confirm_username=arguments.confirm_super_admin_username,
                backup_id=arguments.backup_id,
                confirm_backup_id=arguments.confirm_backup_id,
                config_file=arguments.config_file,
                secret_dir=arguments.secret_dir,
                backup_root=arguments.backup_root,
                backup_record_dir=arguments.backup_record_dir,
                restore_record_dir=arguments.restore_record_dir,
                release_record_dir=arguments.release_record_dir,
                base_record=arguments.base_record,
                record_dir=arguments.record_dir,
                credentials_file=arguments.credentials_file,
                acceptance_record_dir=arguments.acceptance_record_dir,
            )
            if not sys.stdin.isatty():
                raise M7RepresentativeDataError(
                    "Gate A M7 representative data requires an interactive TTY"
                )
            password = base_data.getpass.getpass("Current SUPER_ADMIN password: ")
            confirmation = base_data.getpass.getpass(
                "Confirm current SUPER_ADMIN password: "
            )
            base_data._validate_password(password, confirmation)
            execute(
                context,
                username=arguments.super_admin_username,
                password=password,
            )
    except M7RepresentativeDataError as error:
        print(f"Gate A M7 representative data failed: {error}", file=sys.stderr)
        return 1
    except (base_data.RepresentativeDataError, gatea.GateAError, OSError) as error:
        print(f"Gate A M7 representative data failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Gate A M7 representative data interrupted", file=sys.stderr)
        return 130
    print("Gate A M7 representative data creation and cleanup passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
