"""MySQL 权威首迁移的静态契约测试。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from aerich.utils import decompress_dict


def _load_initial_migration() -> ModuleType:
    migration_files = list(Path("migrations/models").glob("0_*_init.py"))
    assert len(migration_files) == 1

    spec = spec_from_file_location("initial_mysql_migration", migration_files[0])
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_initial_migration_contains_reviewed_mysql_schema() -> None:
    """首迁移必须严格创建完整 MySQL Schema，不得静默跳过漂移表。"""

    migration = _load_initial_migration()
    ddl = await migration.upgrade(None)

    assert migration.RUN_IN_TRANSACTION is False
    assert "IF NOT EXISTS" not in ddl
    assert "CHECK (" not in ddl
    assert "DROP TABLE" not in ddl

    expected_tables = {
        "audit_logs",
        "products",
        "experience_options",
        "product_images",
        "product_kits",
        "users",
        "aerich",
    }
    created_tables = {
        normalized.split("`")[1]
        for line in ddl.splitlines()
        if (normalized := line.strip()).startswith("CREATE TABLE `")
    }
    assert created_tables == expected_tables

    assert "`phone` VARCHAR(11) NOT NULL UNIQUE" in ddl
    assert "KEY `idx_users_status_role` (`status`, `role`)" in ddl
    assert (
        "KEY `idx_audit_target_created` "
        "(`target_type`, `target_id`, `created_at`)"
    ) in ddl
    assert "KEY `idx_audit_operator_created` (`operator_id`, `created_at`)" in ddl
    assert "KEY `idx_products_status_deleted` (`status`, `is_deleted`)" in ddl
    assert (
        "UNIQUE KEY `idx_option_unique` "
        "(`product_id`, `duration`, `participants`, `day_type`)"
    ) in ddl
    assert "`product_id` BIGINT NOT NULL UNIQUE" in ddl
    assert ddl.count("ON DELETE RESTRICT") == 3
    assert ddl.count("ON DELETE SET NULL") == 1
    assert "KEY `idx_image_product_sort` (`product_id`, `sort`)" in ddl
    assert "KEY `idx_image_product_cover` (`product_id`, `is_cover`)" in ddl
    assert "KEY `idx_image_option_sort` (`experience_option_id`, `sort`)" in ddl


async def test_initial_migration_has_non_destructive_downgrade() -> None:
    """首迁移不得通过 downgrade 自动删除全部业务数据。"""

    migration = _load_initial_migration()

    assert await migration.downgrade(None) == ""


def test_initial_migration_state_tracks_phone_uniqueness() -> None:
    """压缩 Model 状态必须同步唯一约束，供后续离线 diff 使用。"""

    migration = _load_initial_migration()
    state = decompress_dict(migration.MODELS_STATE)
    phone_field = next(
        field
        for field in state["models.User"]["data_fields"]
        if field["name"] == "phone"
    )

    assert phone_field["nullable"] is False
    assert phone_field["unique"] is True
