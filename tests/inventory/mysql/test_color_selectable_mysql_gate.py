"""M6 自选颜色 Kit 的真实 MySQL 迁移、索引与行锁门槛。"""

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest
from tortoise import connections
from tortoise.transactions import in_transaction

from app.common.enums.product import KitKind, ProductStatus, ProductType
from app.models.bead_color import BeadColor
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.product_kit_color import ProductKitColor
from app.repositories.inventory_repo import InventoryRepository
from app.tasks.mard_catalog import load_manifest


pytestmark = pytest.mark.mysql

M6_MIGRATIONS = list(
    Path("migrations/models").glob("6_*_add_color_selectable_kits.py")
)
MARD_MANIFEST = Path("app/tasks/manifests/mard_221.json")
EXPECTED_MIGRATIONS = [
    "0_20260810101218_init.py",
    "1_20260813130455_add_order_tables.py",
    "2_20260814104655_add_inventory_transactions.py",
    "3_20260902125032_phase95_external_identity.py",
    "4_20260905162243_add_wallet_payment_refund.py",
    "5_20260906094653_add_reservations.py",
    "6_20260906123000_add_color_selectable_kits.py",
    "7_20260907190000_add_reservation_settings.py",
    "8_20260908140000_add_bead_color_swatch_hex.py",
    "9_20260910180000_add_table_sessions.py",
]
EXPECTED_FOREIGN_KEYS = {
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
EXPECTED_INDEXES = {
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


async def _create_color_rows() -> tuple[ProductKitColor, ProductKitColor]:
    product = await Product.create(
        name="M6 MySQL 颜色锁测试",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    await ProductKit.create(
        product_id=product.id,
        price=Decimal("1.00"),
        stock=None,
        kit_kind=KitKind.COLOR_SELECTABLE,
        sale_unit_grams=10,
    )
    colors = await BeadColor.all().order_by("slot_no")
    assert len(colors) == 221
    await ProductKitColor.bulk_create(
        [
            ProductKitColor(
                product_id=product.id,
                bead_color_id=color.id,
                is_enabled=True,
                stock_units=10,
            )
            for color in colors
        ]
    )
    created = await ProductKitColor.filter(product_id=product.id).order_by(
        "bead_color_id"
    )
    return created[0], created[-1]


async def _wait_for_data_lock_wait() -> None:
    connection = connections.get("default")
    for _ in range(200):
        rows = await connection.execute_query_dict(
            "SELECT COUNT(*) AS wait_count "
            "FROM performance_schema.data_lock_waits"
        )
        if int(rows[0]["wait_count"]) > 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("expected an observable ProductKitColor row-lock wait")


async def test_m6_schema_palette_fixed_default_fks_indexes_and_lock_plan() -> None:
    assert len(M6_MIGRATIONS) == 1
    connection = connections.get("default")

    migration_rows = await connection.execute_query_dict(
        "SELECT version FROM aerich ORDER BY id"
    )
    assert [row["version"] for row in migration_rows] == EXPECTED_MIGRATIONS

    palette_rows = await connection.execute_query_dict(
        "SELECT COUNT(*) AS row_count, MIN(slot_no) AS min_slot, "
        "MAX(slot_no) AS max_slot, "
        "COUNT(DISTINCT slot_no) AS distinct_slots, "
        "SUM(color_code IS NOT NULL) AS configured_codes, "
        "SUM(name IS NOT NULL) AS configured_names, "
        "SUM(swatch_hex IS NOT NULL) AS configured_hex, "
        "SUM(swatch_image_url IS NOT NULL) AS configured_swatches, "
        "SUM(is_active <> 0) AS active_slots, "
        "SUM(sort <> slot_no) AS unexpected_sort "
        "FROM bead_colors"
    )
    assert {key: int(value) for key, value in palette_rows[0].items()} == {
        "row_count": 221,
        "min_slot": 1,
        "max_slot": 221,
        "distinct_slots": 221,
        "configured_codes": 0,
        "configured_names": 0,
        "configured_hex": 221,
        "configured_swatches": 0,
        "active_slots": 0,
        "unexpected_sort": 0,
    }
    colors = load_manifest(MARD_MANIFEST)
    swatch_hex_rows = await connection.execute_query_dict(
        "SELECT slot_no, swatch_hex FROM bead_colors ORDER BY slot_no"
    )
    assert [
        (int(row["slot_no"]), row["swatch_hex"])
        for row in swatch_hex_rows
    ] == [(color.slot_no, color.hex) for color in colors]

    fixed_product = await Product.create(
        name="M6 MySQL fixed default",
        product_type=ProductType.KIT,
    )
    await connection.execute_query(
        "INSERT INTO product_kits ("
        "created_at, updated_at, price, stock, product_id"
        ") VALUES (UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), %s, %s, %s)",
        [Decimal("18.50"), 7, fixed_product.id],
    )
    fixed_rows = await connection.execute_query_dict(
        "SELECT stock, kit_kind, sale_unit_grams "
        "FROM product_kits WHERE product_id = %s",
        [fixed_product.id],
    )
    assert fixed_rows == [
        {"stock": 7, "kit_kind": KitKind.FIXED.value, "sale_unit_grams": None}
    ]

    foreign_key_rows = await connection.execute_query_dict(
        "SELECT kcu.CONSTRAINT_NAME AS constraint_name, "
        "kcu.TABLE_NAME AS table_name, "
        "kcu.COLUMN_NAME AS column_name, "
        "kcu.REFERENCED_TABLE_NAME AS referenced_table_name, "
        "kcu.REFERENCED_COLUMN_NAME AS referenced_column_name, "
        "rc.DELETE_RULE AS delete_rule "
        "FROM information_schema.KEY_COLUMN_USAGE AS kcu "
        "INNER JOIN information_schema.REFERENTIAL_CONSTRAINTS AS rc "
        "ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA "
        "AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME "
        "WHERE kcu.CONSTRAINT_SCHEMA = DATABASE() "
        "AND kcu.CONSTRAINT_NAME IN ("
        "'fk_product_kit_colors_bead_color', "
        "'fk_product_kit_colors_product', "
        "'fk_order_items_kit_color', "
        "'fk_inventory_transactions_kit_color'"
        ")"
    )
    assert {
        (
            row["constraint_name"],
            row["table_name"],
            row["column_name"],
            row["referenced_table_name"],
            row["referenced_column_name"],
            row["delete_rule"],
        )
        for row in foreign_key_rows
    } == EXPECTED_FOREIGN_KEYS

    index_rows = await connection.execute_query_dict(
        "SELECT TABLE_NAME AS table_name, INDEX_NAME AS index_name, "
        "NON_UNIQUE AS non_unique, COLUMN_NAME AS column_name "
        "FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND INDEX_NAME IN ("
        "'uidx_bead_colors_slot_no', "
        "'uidx_bead_colors_color_code', "
        "'idx_bead_colors_active_sort_slot', "
        "'uidx_product_kit_colors_product_color', "
        "'idx_product_kit_colors_product_enabled', "
        "'idx_product_kit_colors_color_enabled', "
        "'idx_inventory_color_created_id'"
        ") ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX"
    )
    index_flags: dict[tuple[str, str], int] = {}
    index_columns: dict[tuple[str, str], list[str]] = {}
    for row in index_rows:
        key = (row["table_name"], row["index_name"])
        index_flags[key] = int(row["non_unique"])
        index_columns.setdefault(key, []).append(row["column_name"])
    actual_indexes = {
        key: (index_flags[key], columns)
        for key, columns in index_columns.items()
    }
    assert actual_indexes == EXPECTED_INDEXES

    first, second = await _create_color_rows()
    await connection.execute_query("ANALYZE TABLE product_kit_colors")
    lock_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM product_kit_colors "
        "WHERE id IN (%s, %s) "
        "ORDER BY product_id, bead_color_id FOR UPDATE",
        [second.id, first.id],
    )
    assert lock_plan[0]["key"] == "PRIMARY"


async def test_reverse_color_lock_request_waits_then_uses_stable_order() -> None:
    first, second = await _create_color_rows()
    repository = InventoryRepository()
    holder_ready = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_forward() -> list[ProductKitColor]:
        async with in_transaction() as connection:
            colors = await repository.get_kit_colors_for_update(
                {first.id, second.id},
                using_db=connection,
            )
            holder_ready.set()
            await release_holder.wait()
            return colors

    async def lock_reverse() -> list[ProductKitColor]:
        await holder_ready.wait()
        async with in_transaction() as connection:
            return await repository.get_kit_colors_for_update(
                {second.id, first.id},
                using_db=connection,
            )

    holder_task = asyncio.create_task(hold_forward())
    await asyncio.wait_for(holder_ready.wait(), timeout=5)
    waiter_task = asyncio.create_task(lock_reverse())
    try:
        await _wait_for_data_lock_wait()
    finally:
        release_holder.set()
        forward, reverse = await asyncio.wait_for(
            asyncio.gather(holder_task, waiter_task),
            timeout=5,
        )

    expected_order = [first.id, second.id]
    assert [color.id for color in forward] == expected_order
    assert [color.id for color in reverse] == expected_order
