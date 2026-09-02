"""Inventory MySQL 增量迁移的静态契约测试。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from aerich.utils import decompress_dict


def _load_inventory_migration() -> ModuleType:
    migration_files = list(
        Path("migrations/models").glob("2_*_add_inventory_transactions.py")
    )
    assert len(migration_files) == 1

    spec = spec_from_file_location(
        "inventory_mysql_migration",
        migration_files[0],
    )
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_inventory_migration_only_adds_reviewed_mysql_table_and_data() -> None:
    """升级只可新增流水表和期初流水，不得静默容忍 Schema 漂移。"""

    migration = _load_inventory_migration()
    sql = await migration.upgrade(None)

    assert migration.RUN_IN_TRANSACTION is False
    assert "IF NOT EXISTS" not in sql
    assert "ALTER TABLE" not in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert "CHECK (" not in sql
    assert "UPDATE `product_kits`" not in sql
    assert "DELETE FROM" not in sql

    created_tables = [
        normalized.split("`")[1]
        for line in sql.splitlines()
        if (normalized := line.strip()).startswith("CREATE TABLE `")
    ]
    assert created_tables == ["inventory_transactions"]
    assert sql.count("INSERT INTO `inventory_transactions`") == 1
    assert sql.index("CREATE TABLE `inventory_transactions`") < sql.index(
        "INSERT INTO `inventory_transactions`"
    )


async def test_inventory_migration_fields_foreign_keys_and_indexes_match_contract() -> None:
    """字段容量、NULL、追溯外键和五组命名索引必须与 DBML 一致。"""

    migration = _load_inventory_migration()
    sql = await migration.upgrade(None)

    assert "`created_at` DATETIME(6) NOT NULL" in sql
    assert "`updated_at` DATETIME(6) NOT NULL" in sql
    assert "`transaction_type` VARCHAR(40) NOT NULL" in sql
    assert "`change_quantity` INT NOT NULL" in sql
    assert "`before_quantity` INT NOT NULL" in sql
    assert "`after_quantity` INT NOT NULL" in sql
    assert "`source_type` VARCHAR(30) NOT NULL" in sql
    assert "`source_id` BIGINT," in sql
    assert "`reason` VARCHAR(256) NOT NULL" in sql
    assert "`idempotency_key` VARCHAR(256) NOT NULL" in sql
    assert "`operator_id` BIGINT," in sql
    assert "`product_id` BIGINT NOT NULL" in sql

    assert sql.count("ON DELETE RESTRICT") == 2
    assert "FOREIGN KEY (`operator_id`) REFERENCES `users` (`id`)" in sql
    assert "FOREIGN KEY (`product_id`) REFERENCES `products` (`id`)" in sql
    assert "FOREIGN KEY (`source_id`)" not in sql
    assert "REFERENCES `orders`" not in sql

    assert (
        "UNIQUE KEY `uidx_inventory_idempotency_key` (`idempotency_key`)"
        in sql
    )
    assert (
        "KEY `idx_inventory_product_created_id` "
        "(`product_id`, `created_at`, `id`)"
    ) in sql
    assert (
        "KEY `idx_inventory_source_created_id` "
        "(`source_type`, `source_id`, `created_at`, `id`)"
    ) in sql
    assert (
        "KEY `idx_inventory_type_created_id` "
        "(`transaction_type`, `created_at`, `id`)"
    ) in sql
    assert "KEY `idx_inventory_created_id` (`created_at`, `id`)" in sql


async def test_inventory_migration_backfills_only_positive_opening_balances() -> None:
    """现有正库存必须生成可追溯期初流水，零库存不得伪造零变化。"""

    migration = _load_inventory_migration()
    sql = await migration.upgrade(None)

    assert "'opening_balance'" in sql
    assert "'migration'" in sql
    assert "'Inventory opening balance migration'" in sql
    assert "`product_kits`.`stock`,\n            0," in sql
    assert "0,\n            `product_kits`.`stock`" in sql
    assert (
        "CONCAT('inventory:opening:product:', "
        "`product_kits`.`product_id`)"
    ) in sql
    assert "FROM `product_kits`" in sql
    assert "WHERE `product_kits`.`stock` > 0" in sql
    assert "ORDER BY `product_kits`.`product_id`" in sql
    assert sql.count("UTC_TIMESTAMP(6)") == 2
    assert "INSERT IGNORE" not in sql
    assert "ON DUPLICATE KEY UPDATE" not in sql


async def test_inventory_migration_downgrade_is_explicitly_destructive() -> None:
    """降级只删流水表且不伪造反向余额；执行仍需单独授权和备份。"""

    migration = _load_inventory_migration()
    sql = await migration.downgrade(None)

    assert sql.strip() == "DROP TABLE IF EXISTS `inventory_transactions`;"
    assert "UPDATE `product_kits`" not in sql
    assert "INSERT INTO" not in sql


def test_inventory_migration_state_contains_new_and_prior_models() -> None:
    """压缩状态必须包含新 Model 和既有历史，供下一次离线 diff 使用。"""

    migration = _load_inventory_migration()
    state = decompress_dict(migration.MODELS_STATE)

    assert "models.InventoryTransaction" in state
    assert "models.ProductKit" in state
    assert "models.Order" in state
    assert "models.OrderItem" in state
