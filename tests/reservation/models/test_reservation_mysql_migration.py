"""Reservation M5 MySQL 增量迁移的静态契约测试。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from aerich.utils import decompress_dict

MIGRATION_NAME = "5_20260906094653_add_reservations.py"


def _load_reservation_migration() -> ModuleType:
    migration_files = list(
        Path("migrations/models").glob("5_*_add_reservations.py")
    )
    assert [path.name for path in migration_files] == [MIGRATION_NAME]

    spec = spec_from_file_location(
        "reservation_mysql_migration",
        migration_files[0],
    )
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_m5_only_creates_the_two_reviewed_tables() -> None:
    migration = _load_reservation_migration()
    ddl = await migration.upgrade(None)

    assert migration.RUN_IN_TRANSACTION is False
    assert "IF NOT EXISTS" not in ddl
    assert "ALTER TABLE" not in ddl
    assert "DROP TABLE" not in ddl
    created_tables = [
        normalized.split("`")[1]
        for line in ddl.splitlines()
        if (normalized := line.strip()).startswith("CREATE TABLE `")
    ]
    assert created_tables == ["store_business_days", "reservations"]


async def test_m5_has_four_restrict_foreign_keys_and_all_named_indexes() -> None:
    migration = _load_reservation_migration()
    ddl = await migration.upgrade(None)

    assert ddl.count("ON DELETE RESTRICT") == 4
    assert (
        "FOREIGN KEY (`business_day_id`) REFERENCES `store_business_days` (`id`) "
        "ON DELETE RESTRICT"
    ) in ddl
    assert (
        "FOREIGN KEY (`experience_option_id`) REFERENCES `experience_options` (`id`) "
        "ON DELETE RESTRICT"
    ) in ddl
    assert (
        "FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT"
        in ddl
    )
    assert (
        "FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT"
        in ddl
    )

    assert (
        "UNIQUE KEY `uidx_store_business_day_date` (`business_date`)" in ddl
    )
    assert (
        "KEY `idx_reservations_user_start_id` "
        "(`user_id`, `scheduled_start_at`, `id`)"
    ) in ddl
    assert (
        "KEY `idx_reservations_user_status_end_id` "
        "(`user_id`, `status`, `scheduled_end_at`, `id`)"
    ) in ddl
    assert (
        "KEY `idx_reservations_user_status_start_id` "
        "(`user_id`, `status`, `scheduled_start_at`, `id`)"
    ) in ddl
    assert (
        "KEY `idx_reservations_day_status_start_id` "
        "(`business_day_id`, `status`, `scheduled_start_at`, `id`)"
    ) in ddl
    assert (
        "KEY `idx_reservations_status_start_id` "
        "(`status`, `scheduled_start_at`, `id`)"
    ) in ddl


async def test_m5_downgrade_drops_reservations_before_business_day() -> None:
    migration = _load_reservation_migration()
    ddl = await migration.downgrade(None)

    assert ddl.index("DROP TABLE `reservations`") < ddl.index(
        "DROP TABLE `store_business_days`"
    )


def test_m5_models_state_contains_reservation_models_and_prior_history() -> None:
    migration = _load_reservation_migration()
    state = decompress_dict(migration.MODELS_STATE)

    assert "models.Reservation" in state
    assert "models.StoreBusinessDay" in state
    assert "models.User" in state
    assert "models.Product" in state
    assert "models.ExperienceOption" in state
    assert "models.Order" in state
    assert "models.InventoryTransaction" in state
    assert "models.WalletAccount" in state
    assert [
        index["name"] for index in state["models.Reservation"]["indexes"]
    ] == [
        "idx_reservations_user_start_id",
        "idx_reservations_user_status_end_id",
        "idx_reservations_user_status_start_id",
        "idx_reservations_day_status_start_id",
        "idx_reservations_status_start_id",
    ]
