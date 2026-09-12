"""Phase 9.5 外部身份与账号生命周期 MySQL 迁移契约。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from aerich.utils import decompress_dict


def _load_migration() -> ModuleType:
    migration_files = list(
        Path("migrations/models").glob("3_*_phase95_external_identity.py")
    )
    assert len(migration_files) == 1
    spec = spec_from_file_location("phase95_mysql_migration", migration_files[0])
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_phase95_upgrade_is_explicit_reviewed_mysql_ddl() -> None:
    migration = _load_migration()
    sql = await migration.upgrade(None)

    assert migration.RUN_IN_TRANSACTION is False
    assert "IF NOT EXISTS" not in sql
    assert "CREATE TABLE `external_identities`" in sql
    assert sql.count("CREATE TABLE") == 1
    assert sql.count("ALTER TABLE `users`") == 4
    assert "ADD `auth_version` INT NOT NULL DEFAULT 0" in sql
    assert "ADD `deleted_at` DATETIME(6)" in sql
    assert "MODIFY COLUMN `phone` VARCHAR(11);" in sql
    assert "MODIFY COLUMN `password` VARCHAR(128);" in sql
    assert "UPDATE " not in sql
    assert "DELETE FROM" not in sql
    assert "DROP " not in sql


async def test_external_identity_constraints_and_indexes_match_contract() -> None:
    migration = _load_migration()
    sql = await migration.upgrade(None)

    assert "`provider` VARCHAR(32) NOT NULL" in sql
    assert "`app_id` VARCHAR(64) NOT NULL" in sql
    assert "`subject_id` VARCHAR(128) NOT NULL" in sql
    assert "`union_id` VARCHAR(128)," in sql
    assert "`user_id` BIGINT NOT NULL" in sql
    assert (
        "FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT"
        in sql
    )
    assert (
        "UNIQUE KEY `uidx_external_identity_subject` "
        "(`provider`, `app_id`, `subject_id`)"
    ) in sql
    assert (
        "UNIQUE KEY `uidx_external_identity_union` (`provider`, `union_id`)"
        in sql
    )
    assert (
        "KEY `idx_external_identity_user_provider` "
        "(`user_id`, `provider`, `created_at`)"
    ) in sql


async def test_phase95_downgrade_orders_destructive_steps_safely() -> None:
    migration = _load_migration()
    sql = await migration.downgrade(None)

    assert sql.index("DROP TABLE IF EXISTS `external_identities`") < sql.index(
        "MODIFY COLUMN `phone`"
    )
    assert sql.index("DROP COLUMN `auth_version`") < sql.index(
        "MODIFY COLUMN `password`"
    )
    assert "MODIFY COLUMN `phone` VARCHAR(11) NOT NULL" in sql
    assert "MODIFY COLUMN `password` VARCHAR(128) NOT NULL" in sql


def test_phase95_migration_state_tracks_identity_and_nullable_credentials() -> None:
    migration = _load_migration()
    state = decompress_dict(migration.MODELS_STATE)

    identity = state["models.ExternalIdentity"]
    user = state["models.User"]
    identity_fields = {field["name"]: field for field in identity["data_fields"]}
    user_fields = {field["name"]: field for field in user["data_fields"]}

    assert identity_fields["subject_id"]["constraints"]["max_length"] == 128
    assert identity_fields["union_id"]["nullable"] is True
    assert {index["name"] for index in identity["indexes"]} == {
        "uidx_external_identity_subject",
        "uidx_external_identity_union",
        "idx_external_identity_user_provider",
    }
    assert user_fields["password"]["nullable"] is True
    assert user_fields["phone"]["nullable"] is True
    assert user_fields["auth_version"]["default"] == 0
    assert user_fields["deleted_at"]["nullable"] is True
