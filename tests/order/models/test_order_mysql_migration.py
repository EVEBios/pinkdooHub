"""Order MySQL 增量迁移的静态契约测试。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from aerich.utils import decompress_dict


def _load_order_migration() -> ModuleType:
    migration_files = list(
        Path("migrations/models").glob("1_*_add_order_tables.py")
    )
    assert len(migration_files) == 1

    spec = spec_from_file_location("order_mysql_migration", migration_files[0])
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_order_migration_only_adds_reviewed_mysql_tables() -> None:
    """升级只能严格新增订单表，不得静默跳过漂移或改动既有表。"""

    migration = _load_order_migration()
    ddl = await migration.upgrade(None)

    assert migration.RUN_IN_TRANSACTION is False
    assert "IF NOT EXISTS" not in ddl
    assert "ALTER TABLE" not in ddl
    assert "DROP TABLE" not in ddl
    assert "DROP COLUMN" not in ddl
    assert "CHECK (" not in ddl

    created_tables = [
        normalized.split("`")[1]
        for line in ddl.splitlines()
        if (normalized := line.strip()).startswith("CREATE TABLE `")
    ]
    assert created_tables == ["orders", "order_items"]


async def test_order_migration_fields_foreign_keys_and_indexes_match_contract() -> None:
    """MySQL 字段类型、默认值、历史保护外键和命名索引应与 DBML 一致。"""

    migration = _load_order_migration()
    ddl = await migration.upgrade(None)

    assert "`order_no` VARCHAR(28) NOT NULL UNIQUE" in ddl
    assert "`total_amount` DECIMAL(10,2) NOT NULL" in ddl
    assert "`status` SMALLINT NOT NULL DEFAULT 0" in ddl
    assert "`remark` VARCHAR(500)" in ddl
    assert "`option_duration_minutes` INT" in ddl
    assert "`option_participants` INT" in ddl
    assert "`option_day_type` VARCHAR(20)" in ddl
    assert "`product_name` VARCHAR(100) NOT NULL" in ddl
    assert "`product_price` DECIMAL(10,2) NOT NULL" in ddl
    assert "`quantity` INT NOT NULL" in ddl
    assert "`subtotal` DECIMAL(10,2) NOT NULL" in ddl
    assert ddl.count("ON DELETE RESTRICT") == 4

    assert (
        "KEY `idx_orders_user_created_id` (`user_id`, `created_at`, `id`)" in ddl
    )
    assert (
        "KEY `idx_orders_user_status_created_id` "
        "(`user_id`, `status`, `created_at`, `id`)"
    ) in ddl
    assert (
        "KEY `idx_orders_status_created_id` (`status`, `created_at`, `id`)"
        in ddl
    )
    assert "KEY `idx_orders_created_id` (`created_at`, `id`)" in ddl
    assert "KEY `idx_order_items_order_id` (`order_id`, `id`)" in ddl


async def test_order_migration_downgrade_drops_child_before_parent() -> None:
    """显式执行降级时必须先删除明细表，避免被外键关系阻断。"""

    migration = _load_order_migration()
    ddl = await migration.downgrade(None)

    assert ddl.index("DROP TABLE IF EXISTS `order_items`") < ddl.index(
        "DROP TABLE IF EXISTS `orders`"
    )


def test_order_migration_state_contains_both_models() -> None:
    """压缩状态必须包含 Order Models，供下一个离线增量 diff 使用。"""

    migration = _load_order_migration()
    state = decompress_dict(migration.MODELS_STATE)

    assert "models.Order" in state
    assert "models.OrderItem" in state
