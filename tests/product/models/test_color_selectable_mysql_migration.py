"""M6 自选颜色 Kit MySQL 迁移静态契约。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from aerich.utils import decompress_dict
from tortoise import connections


def _load_migration() -> ModuleType:
    files = list(
        Path("migrations/models").glob("6_*_add_color_selectable_kits.py")
    )
    assert len(files) == 1
    spec = spec_from_file_location("color_selectable_migration", files[0])
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_m6_product_tables_and_palette_seed_match_contract() -> None:
    migration = _load_migration()
    sql = await migration.upgrade(None)

    assert migration.RUN_IN_TRANSACTION is False
    assert "MODIFY COLUMN `stock` INT NULL DEFAULT 0" in sql
    assert "ADD COLUMN `kit_kind` VARCHAR(20) NOT NULL" in sql
    assert "DEFAULT 'fixed'" in sql
    assert "ADD COLUMN `sale_unit_grams` SMALLINT NULL" in sql
    assert "CREATE TABLE `bead_colors`" in sql
    assert "`slot_no` SMALLINT NOT NULL" in sql
    assert "`color_code` VARCHAR(50)" in sql
    assert "`name` VARCHAR(100)" in sql
    assert "`swatch_image_url` VARCHAR(2048)" in sql
    assert "CHECK (`sort` BETWEEN 0 AND 32767)" in sql
    assert "`is_active` BOOL NOT NULL DEFAULT 0" in sql
    assert "CREATE TABLE `product_kit_colors`" in sql
    assert "`is_enabled` BOOL NOT NULL DEFAULT 0" in sql
    assert "`stock_units` INT NOT NULL DEFAULT 0" in sql
    assert "(`product_id`, `bead_color_id`)" in sql
    assert "WHERE numbers.slot_no BETWEEN 1 AND 221" in sql
    assert "NULL, NULL, NULL, numbers.slot_no, 0" in sql


async def test_m6_downgrade_drops_dependants_before_product_color_tables() -> None:
    sql = await _load_migration().downgrade(None)

    inventory_fk = sql.index("fk_inventory_transactions_kit_color")
    order_fk = sql.index("fk_order_items_kit_color")
    product_colors = sql.index("DROP TABLE `product_kit_colors`")
    bead_colors = sql.index("DROP TABLE `bead_colors`")
    product_kit_columns = sql.index("DROP COLUMN `kit_kind`")
    assert inventory_fk < product_colors
    assert order_fk < product_colors
    assert product_colors < bead_colors < product_kit_columns


def test_m6_models_state_contains_complete_cross_module_shape() -> None:
    state = decompress_dict(_load_migration().MODELS_STATE)

    assert "models.BeadColor" in state
    assert "models.ProductKitColor" in state
    product_kit_fields = {
        field["name"]: field
        for field in state["models.ProductKit"]["data_fields"]
    }
    assert product_kit_fields["stock"]["nullable"] is True
    assert product_kit_fields["kit_kind"]["default"] == "fixed"
    assert product_kit_fields["sale_unit_grams"]["nullable"] is True

    color_fields = {
        field["name"]: field
        for field in state["models.BeadColor"]["data_fields"]
    }
    assert {"slot_no", "color_code", "name", "swatch_image_url"} <= set(
        color_fields
    )
    assert color_fields["sort"]["constraints"] == {
        "ge": -32768,
        "le": 32767,
    }
    assert state["models.ProductKitColor"]["unique_together"] == [
        ["product", "bead_color"]
    ]

    order_item_fields = {
        field["name"]
        for field in state["models.OrderItem"]["data_fields"]
    }
    assert {
        "kit_color_id",
        "kit_color_slot_no",
        "kit_color_code",
        "kit_color_name",
        "sale_unit_grams",
    } <= order_item_fields
    inventory_fields = {
        field["name"]
        for field in state["models.InventoryTransaction"]["data_fields"]
    }
    assert "kit_color_id" in inventory_fields


async def test_product_kit_color_sqlite_indexes_use_physical_fk_columns() -> None:
    """开发库自动建表不能把关系名生成为无效表达式索引。"""

    connection = connections.get("default")
    expected_indexes = {
        "idx_product_kit_colors_product_enabled": [
            "product_id",
            "is_enabled",
        ],
        "idx_product_kit_colors_color_enabled": [
            "bead_color_id",
            "is_enabled",
        ],
    }
    indexes = await connection.execute_query_dict(
        "PRAGMA index_list('product_kit_colors')"
    )
    indexes_by_name = {index["name"]: index for index in indexes}
    for index_name, expected_columns in expected_indexes.items():
        assert indexes_by_name[index_name]["unique"] == 0
        columns = await connection.execute_query_dict(
            f"PRAGMA index_info('{index_name}')"
        )
        assert [column["name"] for column in columns] == expected_columns
