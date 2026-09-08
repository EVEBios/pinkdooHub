#!/usr/bin/env python3
"""验证、记录并清理 Phase 9.2.4 隔离 MySQL 发布门槛。"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from typing import Mapping, Sequence


EXPECTED_DATABASE = "pinkdoohub_inventory_4311_ci"
M5_MIGRATION = "5_20260906094653_add_reservations.py"
M6_MIGRATION = "6_20260906123000_add_color_selectable_kits.py"
M7_MIGRATION = "7_20260907190000_add_reservation_settings.py"
M8_MIGRATION = "8_20260908140000_add_bead_color_swatch_hex.py"
MARD_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "tasks"
    / "manifests"
    / "mard_221.json"
)
EXPECTED_MIGRATIONS_THROUGH_M5 = [
    "0_20260810101218_init.py",
    "1_20260813130455_add_order_tables.py",
    "2_20260814104655_add_inventory_transactions.py",
    "3_20260902125032_phase95_external_identity.py",
    "4_20260905162243_add_wallet_payment_refund.py",
    M5_MIGRATION,
]
EXPECTED_MIGRATIONS_THROUGH_M6 = [
    *EXPECTED_MIGRATIONS_THROUGH_M5,
    M6_MIGRATION,
]
EXPECTED_MIGRATIONS_THROUGH_M7 = [
    *EXPECTED_MIGRATIONS_THROUGH_M6,
    M7_MIGRATION,
]
EXPECTED_MIGRATIONS = [
    *EXPECTED_MIGRATIONS_THROUGH_M7,
    M8_MIGRATION,
]
MYSQL_VERSION_PREFIX = "8.0.46"
CONTAINER_ID_PATTERN = re.compile(r"^[0-9a-f]{12,64}$")
M6_LEGACY_PRODUCT_NAME = "__ci_m6_legacy_fixed_kit__"
M7_LEGACY_USERNAME = "__ci_m7_legacy_user__"
M7_LEGACY_PRODUCT_NAME = "__ci_m7_legacy_experience__"
M7_LEGACY_OPEN_DATE = "2026-09-10"
M7_LEGACY_CLOSED_DATE = "2026-09-11"
M6_EXPECTED_COLUMNS = {
    ("product_kits", "stock", "YES", "int"),
    ("product_kits", "kit_kind", "NO", "varchar"),
    ("product_kits", "sale_unit_grams", "YES", "smallint"),
    ("bead_colors", "slot_no", "NO", "smallint"),
    ("bead_colors", "color_code", "YES", "varchar"),
    ("bead_colors", "name", "YES", "varchar"),
    ("bead_colors", "swatch_image_url", "YES", "varchar"),
    ("bead_colors", "sort", "NO", "smallint"),
    ("bead_colors", "is_active", "NO", "tinyint"),
    ("product_kit_colors", "is_enabled", "NO", "tinyint"),
    ("product_kit_colors", "stock_units", "NO", "int"),
    ("product_kit_colors", "bead_color_id", "NO", "bigint"),
    ("product_kit_colors", "product_id", "NO", "bigint"),
    ("order_items", "kit_color_id", "YES", "bigint"),
    ("order_items", "kit_color_slot_no", "YES", "smallint"),
    ("order_items", "kit_color_code", "YES", "varchar"),
    ("order_items", "kit_color_name", "YES", "varchar"),
    ("order_items", "sale_unit_grams", "YES", "smallint"),
    ("inventory_transactions", "kit_color_id", "YES", "bigint"),
}
M6_EXPECTED_FOREIGN_KEYS = {
    (
        "fk_product_kit_colors_bead_color",
        "product_kit_colors",
        "bead_color_id",
        "bead_colors",
        "id",
        "RESTRICT",
    ),
    (
        "fk_product_kit_colors_product",
        "product_kit_colors",
        "product_id",
        "products",
        "id",
        "RESTRICT",
    ),
    (
        "fk_order_items_kit_color",
        "order_items",
        "kit_color_id",
        "product_kit_colors",
        "id",
        "RESTRICT",
    ),
    (
        "fk_inventory_transactions_kit_color",
        "inventory_transactions",
        "kit_color_id",
        "product_kit_colors",
        "id",
        "RESTRICT",
    ),
}
M6_EXPECTED_INDEXES = {
    ("bead_colors", "uidx_bead_colors_slot_no"): (0, ["slot_no"]),
    ("bead_colors", "uidx_bead_colors_color_code"): (0, ["color_code"]),
    ("bead_colors", "idx_bead_colors_active_sort_slot"): (
        1,
        ["is_active", "sort", "slot_no"],
    ),
    ("product_kit_colors", "uidx_product_kit_colors_product_color"): (
        0,
        ["product_id", "bead_color_id"],
    ),
    ("product_kit_colors", "idx_product_kit_colors_product_enabled"): (
        1,
        ["product_id", "is_enabled"],
    ),
    ("product_kit_colors", "idx_product_kit_colors_color_enabled"): (
        1,
        ["bead_color_id", "is_enabled"],
    ),
    ("inventory_transactions", "idx_inventory_color_created_id"): (
        1,
        ["kit_color_id", "created_at", "id"],
    ),
}
M7_EXPECTED_COLUMNS = {
    "singleton_key": ("NO", "tinyint", "1"),
    "weekly_closed_weekday": ("NO", "varchar", "monday"),
}
M7_EXPECTED_INDEXES = {
    ("reservation_settings", "uidx_reservation_settings_singleton"): (
        0,
        ["singleton_key"],
    ),
}
M8_EXPECTED_COLUMN = ("YES", "varchar", 7)


class GateError(RuntimeError):
    """不包含凭据或连接串的 CI 门槛错误。"""


@dataclass(frozen=True)
class GateConfig:
    """Aerich 与 pytest 共用的唯一隔离 MySQL 目标。"""

    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)

    def safe_target(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
        }


def _required(environment: Mapping[str, str], key: str) -> str:
    value = environment.get(key, "")
    if not value:
        raise GateError(f"{key} is required")
    return value


def load_config(environment: Mapping[str, str]) -> GateConfig:
    """拒绝默认端口、远端地址以及 Aerich/pytest 目标漂移。"""

    if environment.get("APP_ENV") != "testing":
        raise GateError("APP_ENV must be testing")
    if environment.get("DB_ENGINE") != "mysql":
        raise GateError("DB_ENGINE must be mysql")
    if environment.get("INVENTORY_MYSQL_TEST_ENABLED") != "1":
        raise GateError("the isolated MySQL gate must be explicitly enabled")

    host = _required(environment, "INVENTORY_MYSQL_TEST_HOST")
    try:
        port = int(_required(environment, "INVENTORY_MYSQL_TEST_PORT"))
    except ValueError as error:
        raise GateError("MySQL gate port must be an integer") from error
    database = _required(environment, "INVENTORY_MYSQL_TEST_DB")
    user = _required(environment, "INVENTORY_MYSQL_TEST_USER")
    password = _required(environment, "INVENTORY_MYSQL_TEST_PASSWORD")

    if host != "127.0.0.1":
        raise GateError("MySQL gate only permits 127.0.0.1")
    if port == 3306 or not 1024 <= port <= 65535:
        raise GateError("MySQL gate refuses the default or invalid port")
    if database != EXPECTED_DATABASE:
        raise GateError("MySQL gate requires the frozen disposable schema")
    if user != "root":
        raise GateError("MySQL gate requires its disposable container user")

    mirrored_values = {
        "DB_HOST": host,
        "DB_PORT": str(port),
        "DB_NAME": database,
        "DB_USER": user,
        "DB_PASSWORD": password,
    }
    for key, expected_value in mirrored_values.items():
        if environment.get(key) != expected_value:
            raise GateError(f"{key} must match the pytest MySQL target")

    return GateConfig(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
    )


def write_report(path: Path, document: Mapping[str, object]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def preflight(config: GateConfig, report_path: Path) -> None:
    write_report(
        report_path,
        {
            "schema_version": 1,
            "status": "preflight-passed",
            **config.safe_target(),
        },
    )
    print(
        "MySQL gate preflight passed: "
        f"host={config.host} port={config.port} database={config.database}"
    )


def _group_index_rows(
    rows: Sequence[Sequence[object]],
) -> dict[tuple[str, str], tuple[int, list[str]]]:
    """按表和索引聚合列序，并冻结 MySQL NON_UNIQUE 标志。"""

    flags: dict[tuple[str, str], int] = {}
    columns: dict[tuple[str, str], list[str]] = {}
    for table_name, index_name, non_unique, column_name in rows:
        key = (str(table_name), str(index_name))
        flag = int(non_unique)
        if key in flags and flags[key] != flag:
            raise GateError("index uniqueness metadata is inconsistent")
        flags[key] = flag
        columns.setdefault(key, []).append(str(column_name))
    return {key: (flags[key], value) for key, value in columns.items()}


async def _read_snapshot(config: GateConfig) -> tuple[str, list[str]]:
    import asyncmy

    connection = await asyncmy.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        connect_timeout=5,
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT VERSION()")
            version_row = await cursor.fetchone()
            await cursor.execute("SELECT version FROM aerich ORDER BY id")
            migration_rows = await cursor.fetchall()
    finally:
        await connection.ensure_closed()

    if not version_row:
        raise GateError("MySQL version query returned no rows")
    mysql_version = str(version_row[0])
    migrations = [str(row[0]) for row in migration_rows]
    return mysql_version, migrations


async def _seed_m6_legacy_fixed_kit(config: GateConfig) -> None:
    """在仅回退 M6 的一次性 Schema 中写入一条 M5 fixed Kit。"""

    import asyncmy

    connection = await asyncmy.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        connect_timeout=5,
        autocommit=False,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT version FROM aerich ORDER BY id")
            migration_rows = await cursor.fetchall()
            migrations = [str(row[0]) for row in migration_rows]
            if migrations != EXPECTED_MIGRATIONS_THROUGH_M5:
                raise GateError(
                    "M6 legacy seed requires the reviewed chain through M5"
                )

            await cursor.execute(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'product_kits' "
                "AND COLUMN_NAME IN ('kit_kind', 'sale_unit_grams')",
                (config.database,),
            )
            column_row = await cursor.fetchone()
            if column_row is None or int(column_row[0]) != 0:
                raise GateError("M6 columns must be absent before legacy seeding")

            await cursor.execute(
                "SELECT COUNT(*) FROM products WHERE name = %s",
                (M6_LEGACY_PRODUCT_NAME,),
            )
            existing_row = await cursor.fetchone()
            if existing_row is None or int(existing_row[0]) != 0:
                raise GateError("M6 legacy seed marker already exists")

            await cursor.execute(
                "INSERT INTO products ("
                "created_at, updated_at, name, product_type, description, "
                "status, is_deleted"
                ") VALUES ("
                "UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), %s, 'kit', NULL, "
                "'draft', 0"
                ")",
                (M6_LEGACY_PRODUCT_NAME,),
            )
            product_id = int(cursor.lastrowid)
            await cursor.execute(
                "INSERT INTO product_kits ("
                "created_at, updated_at, price, stock, product_id"
                ") VALUES ("
                "UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), 12.30, 7, %s"
                ")",
                (product_id,),
            )
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.ensure_closed()


async def _seed_m7_legacy_reservation_history(config: GateConfig) -> None:
    """在仅回退 M7 的 M6 Schema 中写入预约与单日店休历史。"""

    import asyncmy

    connection = await asyncmy.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        connect_timeout=5,
        autocommit=False,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT version FROM aerich ORDER BY id")
            migration_rows = await cursor.fetchall()
            migrations = [str(row[0]) for row in migration_rows]
            if migrations != EXPECTED_MIGRATIONS_THROUGH_M6:
                raise GateError(
                    "M7 legacy seed requires the reviewed chain through M6"
                )

            await cursor.execute(
                "SELECT COUNT(*) FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s "
                "AND TABLE_NAME = 'reservation_settings'",
                (config.database,),
            )
            table_row = await cursor.fetchone()
            if table_row is None or int(table_row[0]) != 0:
                raise GateError(
                    "M7 reservation_settings must be absent before legacy seeding"
                )

            await cursor.execute(
                "SELECT COUNT(*) FROM users WHERE username = %s",
                (M7_LEGACY_USERNAME,),
            )
            user_marker_row = await cursor.fetchone()
            await cursor.execute(
                "SELECT COUNT(*) FROM products WHERE name = %s",
                (M7_LEGACY_PRODUCT_NAME,),
            )
            product_marker_row = await cursor.fetchone()
            if (
                user_marker_row is None
                or product_marker_row is None
                or int(user_marker_row[0]) != 0
                or int(product_marker_row[0]) != 0
            ):
                raise GateError("M7 legacy seed marker already exists")

            await cursor.execute(
                "INSERT INTO users ("
                "created_at, updated_at, username, password, nickname, phone, "
                "avatar, role, status"
                ") VALUES ("
                "'2026-09-07 01:00:00.000000', "
                "'2026-09-07 01:00:00.000000', %s, "
                "'ci-only-non-secret-password-hash', 'M7 legacy user', "
                "'13970000007', NULL, 1, 1"
                ")",
                (M7_LEGACY_USERNAME,),
            )
            user_id = int(cursor.lastrowid)
            await cursor.execute(
                "INSERT INTO products ("
                "created_at, updated_at, name, product_type, description, "
                "status, is_deleted"
                ") VALUES ("
                "'2026-09-07 01:00:00.000000', "
                "'2026-09-07 01:00:00.000000', %s, 'experience', "
                "'M7 migration preservation marker', 'online', 0"
                ")",
                (M7_LEGACY_PRODUCT_NAME,),
            )
            product_id = int(cursor.lastrowid)
            await cursor.execute(
                "INSERT INTO experience_options ("
                "created_at, updated_at, duration, participants, day_type, "
                "price, is_deleted, product_id"
                ") VALUES ("
                "'2026-09-07 01:00:00.000000', "
                "'2026-09-07 01:00:00.000000', 90, 2, 'weekday', "
                "123.45, 0, %s"
                ")",
                (product_id,),
            )
            option_id = int(cursor.lastrowid)

            business_day_ids: dict[str, int] = {}
            for business_date, is_closed in (
                (M7_LEGACY_OPEN_DATE, 0),
                (M7_LEGACY_CLOSED_DATE, 1),
            ):
                await cursor.execute(
                    "INSERT INTO store_business_days ("
                    "created_at, updated_at, business_date, is_closed"
                    ") VALUES ("
                    "'2026-09-07 01:00:00.000000', "
                    "'2026-09-07 01:00:00.000000', %s, %s"
                    ")",
                    (business_date, is_closed),
                )
                business_day_ids[business_date] = int(cursor.lastrowid)

            await cursor.execute(
                "INSERT INTO reservations ("
                "created_at, updated_at, scheduled_start_at, scheduled_end_at, "
                "product_name, option_duration_minutes, option_participants, "
                "option_day_type, option_price, status, rejection_reason, "
                "cancellation_reason, confirmed_at, rejected_at, cancelled_at, "
                "business_day_id, experience_option_id, product_id, user_id"
                ") VALUES ("
                "'2026-09-07 01:00:00.000000', "
                "'2026-09-07 02:00:00.000000', "
                "'2026-09-10 06:00:00.000000', "
                "'2026-09-10 07:30:00.000000', %s, 90, 2, 'weekday', "
                "123.45, 'confirmed', NULL, NULL, "
                "'2026-09-07 02:00:00.000000', NULL, NULL, %s, %s, %s, %s"
                ")",
                (
                    M7_LEGACY_PRODUCT_NAME,
                    business_day_ids[M7_LEGACY_OPEN_DATE],
                    option_id,
                    product_id,
                    user_id,
                ),
            )
            await cursor.execute(
                "INSERT INTO reservations ("
                "created_at, updated_at, scheduled_start_at, scheduled_end_at, "
                "product_name, option_duration_minutes, option_participants, "
                "option_day_type, option_price, status, rejection_reason, "
                "cancellation_reason, confirmed_at, rejected_at, cancelled_at, "
                "business_day_id, experience_option_id, product_id, user_id"
                ") VALUES ("
                "'2026-09-07 01:00:00.000000', "
                "'2026-09-07 03:00:00.000000', "
                "'2026-09-11 06:30:00.000000', "
                "'2026-09-11 08:00:00.000000', %s, 90, 2, 'weekday', "
                "123.45, 'cancelled', NULL, 'store_closed', NULL, NULL, "
                "'2026-09-07 03:00:00.000000', %s, %s, %s, %s"
                ")",
                (
                    M7_LEGACY_PRODUCT_NAME,
                    business_day_ids[M7_LEGACY_CLOSED_DATE],
                    option_id,
                    product_id,
                    user_id,
                ),
            )
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.ensure_closed()


async def _read_m6_evidence(config: GateConfig) -> dict[str, object]:
    """读取 M6 数据迁移证据；仅返回非敏感聚合与布尔结论。"""

    import asyncmy

    connection = await asyncmy.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        connect_timeout=5,
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT COUNT(*), MIN(slot_no), MAX(slot_no), "
                "COUNT(DISTINCT slot_no), "
                "SUM(color_code IS NOT NULL), SUM(name IS NOT NULL), "
                "SUM(swatch_image_url IS NOT NULL), SUM(is_active <> 0), "
                "SUM(sort <> slot_no) FROM bead_colors"
            )
            palette_row = await cursor.fetchone()
            expected_palette = (221, 1, 221, 221, 0, 0, 0, 0, 0)
            if (
                palette_row is None
                or any(value is None for value in palette_row)
                or tuple(map(int, palette_row)) != expected_palette
            ):
                raise GateError(
                    "M6 did not create the exact 221-slot placeholder palette"
                )

            await cursor.execute(
                "SELECT product_kits.stock, product_kits.kit_kind, "
                "product_kits.sale_unit_grams "
                "FROM product_kits "
                "INNER JOIN products ON products.id = product_kits.product_id "
                "WHERE products.name = %s",
                (M6_LEGACY_PRODUCT_NAME,),
            )
            legacy_rows = await cursor.fetchall()
            if len(legacy_rows) != 1 or legacy_rows[0] != (7, "fixed", None):
                raise GateError("M6 changed the historical fixed Kit semantics")

            await cursor.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, IS_NULLABLE, DATA_TYPE, "
                "COLUMN_DEFAULT FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ("
                "'product_kits', 'bead_colors', 'product_kit_colors', "
                "'order_items', 'inventory_transactions'"
                ")",
                (config.database,),
            )
            column_rows = await cursor.fetchall()
            expected_column_names = {
                (table_name, column_name)
                for table_name, column_name, _, _ in M6_EXPECTED_COLUMNS
            }
            actual_columns = {
                (str(table), str(column), str(nullable), str(data_type))
                for table, column, nullable, data_type, _ in column_rows
                if (str(table), str(column)) in expected_column_names
            }
            if actual_columns != M6_EXPECTED_COLUMNS:
                raise GateError("M6 critical column shape does not match the contract")
            kit_kind_defaults = [
                default
                for table, column, _, _, default in column_rows
                if table == "product_kits" and column == "kit_kind"
            ]
            if kit_kind_defaults != ["fixed"]:
                raise GateError("M6 fixed Kit database default is missing")

            await cursor.execute(
                "SELECT kcu.CONSTRAINT_NAME, kcu.TABLE_NAME, "
                "kcu.COLUMN_NAME, kcu.REFERENCED_TABLE_NAME, "
                "kcu.REFERENCED_COLUMN_NAME, rc.DELETE_RULE "
                "FROM information_schema.KEY_COLUMN_USAGE AS kcu "
                "INNER JOIN information_schema.REFERENTIAL_CONSTRAINTS AS rc "
                "ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA "
                "AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
                "WHERE kcu.CONSTRAINT_SCHEMA = %s "
                "AND kcu.CONSTRAINT_NAME IN ("
                "'fk_product_kit_colors_bead_color', "
                "'fk_product_kit_colors_product', "
                "'fk_order_items_kit_color', "
                "'fk_inventory_transactions_kit_color'"
                ")",
                (config.database,),
            )
            foreign_key_rows = await cursor.fetchall()
            actual_foreign_keys = {
                tuple(str(value) for value in row) for row in foreign_key_rows
            }
            if actual_foreign_keys != M6_EXPECTED_FOREIGN_KEYS:
                raise GateError("M6 named foreign keys do not match the contract")

            await cursor.execute(
                "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, COLUMN_NAME "
                "FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = %s AND INDEX_NAME IN ("
                "'uidx_bead_colors_slot_no', "
                "'uidx_bead_colors_color_code', "
                "'idx_bead_colors_active_sort_slot', "
                "'uidx_product_kit_colors_product_color', "
                "'idx_product_kit_colors_product_enabled', "
                "'idx_product_kit_colors_color_enabled', "
                "'idx_inventory_color_created_id'"
                ") ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
                (config.database,),
            )
            index_rows = await cursor.fetchall()
            actual_indexes = _group_index_rows(index_rows)
            if actual_indexes != M6_EXPECTED_INDEXES:
                raise GateError("M6 named indexes do not match the contract")
    finally:
        await connection.ensure_closed()

    return {
        "palette_slots": 221,
        "palette_placeholder_shape_valid": True,
        "legacy_fixed_kit_compatible": True,
        "critical_column_count": len(M6_EXPECTED_COLUMNS),
        "named_foreign_key_count": len(M6_EXPECTED_FOREIGN_KEYS),
        "named_index_count": len(M6_EXPECTED_INDEXES),
    }


async def _read_m7_evidence(config: GateConfig) -> dict[str, object]:
    """读取 M7 单例设置及既有 Reservation 数据不漂移证据。"""

    import asyncmy

    connection = await asyncmy.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        connect_timeout=5,
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT COLUMN_NAME, IS_NULLABLE, DATA_TYPE, COLUMN_DEFAULT "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s "
                "AND TABLE_NAME = 'reservation_settings' "
                "AND COLUMN_NAME IN ('singleton_key', 'weekly_closed_weekday')",
                (config.database,),
            )
            column_rows = await cursor.fetchall()
            actual_columns = {
                str(column): (
                    str(nullable),
                    str(data_type),
                    None if default is None else str(default),
                )
                for column, nullable, data_type, default in column_rows
            }
            if actual_columns != M7_EXPECTED_COLUMNS:
                raise GateError("M7 critical column shape does not match the contract")

            await cursor.execute(
                "SELECT CONSTRAINT_NAME, CONSTRAINT_TYPE "
                "FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = %s "
                "AND TABLE_NAME = 'reservation_settings' "
                "AND CONSTRAINT_NAME IN ("
                "'ck_reservation_settings_singleton', "
                "'uidx_reservation_settings_singleton'"
                ")",
                (config.database,),
            )
            constraint_rows = await cursor.fetchall()
            actual_constraints = {
                (str(name), str(constraint_type))
                for name, constraint_type in constraint_rows
            }
            expected_constraints = {
                ("ck_reservation_settings_singleton", "CHECK"),
                ("uidx_reservation_settings_singleton", "UNIQUE"),
            }
            if actual_constraints != expected_constraints:
                raise GateError("M7 singleton constraints do not match the contract")

            await cursor.execute(
                "SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = %s "
                "AND CONSTRAINT_NAME = 'ck_reservation_settings_singleton'",
                (config.database,),
            )
            check_rows = await cursor.fetchall()
            if len(check_rows) != 1:
                raise GateError("M7 singleton CHECK constraint is missing")
            normalized_check = "".join(str(check_rows[0][0]).lower().split())
            if "singleton_key" not in normalized_check or "=1" not in normalized_check:
                raise GateError("M7 singleton CHECK constraint has drifted")

            await cursor.execute(
                "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, COLUMN_NAME "
                "FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = %s "
                "AND TABLE_NAME = 'reservation_settings' "
                "AND INDEX_NAME = 'uidx_reservation_settings_singleton' "
                "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
                (config.database,),
            )
            index_rows = await cursor.fetchall()
            actual_indexes = _group_index_rows(index_rows)
            if actual_indexes != M7_EXPECTED_INDEXES:
                raise GateError("M7 singleton index does not match the contract")

            await cursor.execute(
                "SELECT singleton_key, weekly_closed_weekday "
                "FROM reservation_settings ORDER BY id"
            )
            settings_rows = await cursor.fetchall()
            if settings_rows != ((1, "monday"),):
                raise GateError(
                    "M7 must create exactly one default Monday settings row"
                )

            await cursor.execute(
                "SELECT DATE_FORMAT(days.business_date, '%%Y-%%m-%%d'), "
                "days.is_closed, reservations.status, "
                "reservations.cancellation_reason, "
                "DATE_FORMAT(reservations.scheduled_start_at, "
                "'%%Y-%%m-%%d %%H:%%i:%%s.%%f'), "
                "DATE_FORMAT(reservations.scheduled_end_at, "
                "'%%Y-%%m-%%d %%H:%%i:%%s.%%f'), "
                "reservations.product_name, "
                "reservations.option_duration_minutes, "
                "reservations.option_participants, "
                "reservations.option_day_type, "
                "CAST(reservations.option_price AS CHAR) "
                "FROM reservations "
                "INNER JOIN store_business_days AS days "
                "ON days.id = reservations.business_day_id "
                "INNER JOIN products "
                "ON products.id = reservations.product_id "
                "INNER JOIN users ON users.id = reservations.user_id "
                "WHERE products.name = %s AND users.username = %s "
                "ORDER BY days.business_date",
                (M7_LEGACY_PRODUCT_NAME, M7_LEGACY_USERNAME),
            )
            legacy_rows = await cursor.fetchall()
            expected_legacy_rows = (
                (
                    M7_LEGACY_OPEN_DATE,
                    0,
                    "confirmed",
                    None,
                    "2026-09-10 06:00:00.000000",
                    "2026-09-10 07:30:00.000000",
                    M7_LEGACY_PRODUCT_NAME,
                    90,
                    2,
                    "weekday",
                    "123.45",
                ),
                (
                    M7_LEGACY_CLOSED_DATE,
                    1,
                    "cancelled",
                    "store_closed",
                    "2026-09-11 06:30:00.000000",
                    "2026-09-11 08:00:00.000000",
                    M7_LEGACY_PRODUCT_NAME,
                    90,
                    2,
                    "weekday",
                    "123.45",
                ),
            )
            if legacy_rows != expected_legacy_rows:
                raise GateError(
                    "M7 changed existing Reservation or store-closure history"
                )
    finally:
        await connection.ensure_closed()

    return {
        "singleton_row_count": 1,
        "default_weekly_closed_weekday": "monday",
        "singleton_check_valid": True,
        "named_index_count": len(M7_EXPECTED_INDEXES),
        "legacy_reservation_count": 2,
        "legacy_store_business_day_count": 2,
        "legacy_history_unchanged": True,
    }


def _expected_mard_hex_rows() -> tuple[tuple[int, str], ...]:
    """Read only the frozen slot/HEX projection used by the M8 gate."""

    try:
        document = json.loads(MARD_MANIFEST.read_text(encoding="utf-8"))
        raw_colors = document["colors"]
        rows = tuple(
            (int(color["slot_no"]), str(color["hex"]))
            for color in raw_colors
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise GateError("M8 frozen MARD manifest is invalid") from error
    if (
        len(rows) != 221
        or tuple(slot_no for slot_no, _ in rows) != tuple(range(1, 222))
        or len({hex_value for _, hex_value in rows}) != 221
        or any(
            len(hex_value) != 7
            or not hex_value.startswith("#")
            or any(
                character not in "0123456789ABCDEF"
                for character in hex_value[1:]
            )
            for _, hex_value in rows
        )
    ):
        raise GateError("M8 frozen MARD manifest projection is invalid")
    return rows


async def _read_m8_evidence(config: GateConfig) -> dict[str, object]:
    """Verify nullable column shape and exact 221-slot MARD HEX backfill."""

    import asyncmy

    connection = await asyncmy.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        connect_timeout=5,
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "SELECT IS_NULLABLE, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'bead_colors' "
                "AND COLUMN_NAME = 'swatch_hex'",
                (config.database,),
            )
            column_rows = await cursor.fetchall()
            actual_column = (
                None
                if len(column_rows) != 1
                else (
                    str(column_rows[0][0]),
                    str(column_rows[0][1]),
                    int(column_rows[0][2]),
                )
            )
            if actual_column != M8_EXPECTED_COLUMN:
                raise GateError("M8 swatch_hex column shape does not match")

            await cursor.execute(
                "SELECT slot_no, swatch_hex FROM bead_colors ORDER BY slot_no"
            )
            actual_rows = tuple(
                (int(slot_no), str(swatch_hex))
                for slot_no, swatch_hex in await cursor.fetchall()
            )
            expected_rows = _expected_mard_hex_rows()
            if actual_rows != expected_rows:
                raise GateError("M8 did not backfill the exact MARD HEX catalog")
    finally:
        await connection.ensure_closed()

    return {
        "swatch_hex_nullable": True,
        "swatch_hex_max_length": 7,
        "backfilled_slots": 221,
        "distinct_hex_values": len({hex_value for _, hex_value in actual_rows}),
        "manifest_projection_matches": True,
    }


def seed_m6_legacy(config: GateConfig, report_path: Path) -> None:
    """为 M6 二次升级写入受控 M5 历史数据。"""

    asyncio.run(_seed_m6_legacy_fixed_kit(config))
    write_report(
        report_path,
        {
            "schema_version": 1,
            "status": "m6-legacy-seed-ready",
            **config.safe_target(),
            "migration_tail": M5_MIGRATION,
        },
    )
    print("MySQL M6 legacy fixed Kit seed passed")


def seed_m7_legacy(config: GateConfig, report_path: Path) -> None:
    """为 M7 二次升级写入受控 M6 Reservation 历史。"""

    asyncio.run(_seed_m7_legacy_reservation_history(config))
    write_report(
        report_path,
        {
            "schema_version": 1,
            "status": "m7-legacy-seed-ready",
            **config.safe_target(),
            "migration_tail": M6_MIGRATION,
            "legacy_reservation_count": 2,
            "legacy_store_business_day_count": 2,
        },
    )
    print("MySQL M7 legacy Reservation history seed passed")


def snapshot(config: GateConfig, report_path: Path) -> None:
    mysql_version, migrations = asyncio.run(_read_snapshot(config))
    if not mysql_version.startswith(MYSQL_VERSION_PREFIX):
        raise GateError("MySQL server is not the frozen 8.0.46 release-gate version")
    if migrations != EXPECTED_MIGRATIONS:
        raise GateError("Aerich did not apply the complete reviewed migration chain")
    m6_evidence = asyncio.run(_read_m6_evidence(config))
    m7_evidence = asyncio.run(_read_m7_evidence(config))
    m8_evidence = asyncio.run(_read_m8_evidence(config))

    write_report(
        report_path,
        {
            "schema_version": 1,
            "status": "release-gate-ready",
            **config.safe_target(),
            "mysql_version": mysql_version,
            "aerich_versions": migrations,
            "m6_evidence": m6_evidence,
            "m7_evidence": m7_evidence,
            "m8_evidence": m8_evidence,
            "git_sha": os.getenv("GITHUB_SHA", "local-uncommitted"),
            "workflow_run_id": os.getenv("GITHUB_RUN_ID", "local"),
        },
    )
    print(
        "MySQL release gate snapshot passed: "
        f"version={mysql_version} migrations={len(migrations)}"
    )


def _run_command(
    command: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    try:
        result = subprocess.run(
            command,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _port_is_closed(host: str, port: int) -> bool:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.5)
            if connection.connect_ex((host, port)) != 0:
                return True
        time.sleep(0.25)
    return False


def cleanup(config: GateConfig, report_path: Path) -> bool:
    """删除专用 Schema、停止 service container，并复核端口已经释放。"""

    container_id = _required(os.environ, "MYSQL_SERVICE_CONTAINER_ID")
    if not CONTAINER_ID_PATTERN.fullmatch(container_id):
        raise GateError("MYSQL_SERVICE_CONTAINER_ID is invalid")
    docker = shutil.which("docker")
    if docker is None:
        raise GateError("docker CLI is required for MySQL service cleanup")

    docker_environment = os.environ.copy()
    docker_environment["MYSQL_PWD"] = config.password
    schema_dropped = _run_command(
        [
            docker,
            "exec",
            "--env",
            "MYSQL_PWD",
            container_id,
            "mysql",
            "--protocol=socket",
            f"--user={config.user}",
            "--execute",
            f"DROP DATABASE `{config.database}`",
        ],
        environment=docker_environment,
    )
    container_stopped = _run_command(
        [docker, "stop", "--time", "10", container_id],
    )

    try:
        inspect_result = subprocess.run(
            [docker, "inspect", "--format", "{{.State.Running}}", container_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=10,
        )
        container_inspected = inspect_result.returncode == 0
        container_running = (
            container_inspected
            and inspect_result.stdout.strip().lower() == "true"
        )
    except (OSError, subprocess.TimeoutExpired):
        container_inspected = False
        container_running = True
    port_closed = _port_is_closed(config.host, config.port)
    passed = (
        schema_dropped
        and container_stopped
        and container_inspected
        and not container_running
        and port_closed
    )
    write_report(
        report_path,
        {
            "schema_version": 1,
            "status": "cleanup-passed" if passed else "cleanup-failed",
            **config.safe_target(),
            "schema_dropped": schema_dropped,
            "container_stopped": container_stopped,
            "container_inspected": container_inspected,
            "container_running": container_running,
            "port_closed": port_closed,
        },
    )
    print(
        "MySQL release gate cleanup: "
        f"schema_dropped={schema_dropped} container_stopped={container_stopped} "
        f"container_inspected={container_inspected} "
        f"container_running={container_running} port_closed={port_closed}"
    )
    return passed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "preflight",
            "seed-m6-legacy",
            "seed-m7-legacy",
            "snapshot",
            "cleanup",
        ),
    )
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        config = load_config(os.environ)
        if arguments.command == "preflight":
            preflight(config, arguments.report)
            return 0
        if arguments.command == "snapshot":
            snapshot(config, arguments.report)
            return 0
        if arguments.command == "seed-m6-legacy":
            seed_m6_legacy(config, arguments.report)
            return 0
        if arguments.command == "seed-m7-legacy":
            seed_m7_legacy(config, arguments.report)
            return 0
        return 0 if cleanup(config, arguments.report) else 1
    except GateError as error:
        print(f"MySQL release gate failed: {error}", file=sys.stderr)
    except Exception as error:
        print(
            f"MySQL release gate failed safely: {type(error).__name__}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
