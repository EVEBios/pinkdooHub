"""Wallet、Payment 与 Refund MySQL 增量迁移的静态契约测试。"""

import inspect
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from aerich.utils import decompress_dict


MYSQL_IDEMPOTENCY_COLUMN = (
    "`idempotency_key` VARCHAR(256) "
    "CHARACTER SET ascii COLLATE ascii_bin NOT NULL"
)
MYSQL_IDEMPOTENCY_FIELD_TYPE = (
    "VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin"
)


def _load_migration() -> ModuleType:
    migration_files = list(
        Path("migrations/models").glob("4_*_add_wallet_payment_refund.py")
    )
    assert len(migration_files) == 1

    spec = spec_from_file_location(
        "wallet_payment_mysql_migration",
        migration_files[0],
    )
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _statements(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def _table_ddl(sql: str, table_name: str) -> str:
    marker = f"CREATE TABLE `{table_name}`"
    start = sql.index(marker)
    end = sql.index(";", start)
    return sql[start:end]


def _fields_by_name(state: dict[str, object], model_name: str) -> dict[str, dict]:
    model = state[model_name]
    assert isinstance(model, dict)
    return {field["name"]: field for field in model["data_fields"]}


async def test_upgrade_only_adds_six_tables_and_inventory_enum_comment() -> None:
    """升级不得夹带数据迁移、容错 DDL 或其他既有表变更。"""

    migration = _load_migration()
    sql = await migration.upgrade(None)

    assert migration.RUN_IN_TRANSACTION is False
    assert "IF NOT EXISTS" not in sql
    assert "INSERT INTO" not in sql
    assert "REPLACE INTO" not in sql
    assert "UPDATE `" not in sql
    assert "DELETE FROM" not in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert "CHECK (" not in sql

    created_tables = [
        normalized.split("`")[1]
        for line in sql.splitlines()
        if (normalized := line.strip()).startswith("CREATE TABLE `")
    ]
    assert created_tables == [
        "wallet_accounts",
        "recharge_orders",
        "payments",
        "payment_settlements",
        "refunds",
        "wallet_transactions",
    ]

    statements = _statements(sql)
    alter_statements = [
        statement for statement in statements if statement.startswith("ALTER TABLE")
    ]
    assert alter_statements == [
        "ALTER TABLE `inventory_transactions` MODIFY COLUMN "
        "`transaction_type` VARCHAR(40) NOT NULL COMMENT "
        "'OPENING_BALANCE: opening_balance\n"
        "ADMIN_ADJUSTMENT: admin_adjustment\n"
        "ORDER_DEDUCTION: order_deduction\n"
        "ORDER_CANCELLATION_RESTORE: order_cancellation_restore\n"
        "ORDER_REFUND_RESTORE: order_refund_restore'"
    ]
    assert len(statements) == 7


async def test_table_fields_and_defaults_match_frozen_contract() -> None:
    """六张表的字段必须保持冻结形状。"""

    sql = await _load_migration().upgrade(None)
    table_names = (
        "wallet_accounts",
        "recharge_orders",
        "payments",
        "payment_settlements",
        "refunds",
        "wallet_transactions",
    )
    tables = {name: _table_ddl(sql, name) for name in table_names}

    for ddl in tables.values():
        assert "`id` BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT" in ddl
        assert "`created_at` DATETIME(6) NOT NULL" in ddl
        assert "`updated_at` DATETIME(6) NOT NULL" in ddl

    wallet = tables["wallet_accounts"]
    assert "`balance` DECIMAL(10,2) NOT NULL DEFAULT 0.00" in wallet
    assert "`status` VARCHAR(32) NOT NULL" in wallet
    assert "DEFAULT 'active'" in wallet
    assert "`user_id` BIGINT NOT NULL UNIQUE" in wallet

    recharge = tables["recharge_orders"]
    assert "`recharge_no` VARCHAR(28) NOT NULL UNIQUE" in recharge
    assert "`amount` DECIMAL(10,2) NOT NULL" in recharge
    assert "`status` VARCHAR(32) NOT NULL" in recharge
    assert "DEFAULT 'pending'" in recharge
    assert MYSQL_IDEMPOTENCY_COLUMN in recharge
    assert "`succeeded_at` DATETIME(6)" in recharge
    assert "`user_id` BIGINT NOT NULL" in recharge
    assert "`wallet_account_id` BIGINT NOT NULL" in recharge

    payment = tables["payments"]
    assert "`payment_no` VARCHAR(28) NOT NULL UNIQUE" in payment
    assert "`purpose` VARCHAR(32) NOT NULL" in payment
    assert "ORDER: order\nRECHARGE: recharge" in payment
    assert "`method` VARCHAR(32) NOT NULL" in payment
    assert "WALLET: wallet\nWECHAT: wechat\nMANUAL: manual" in payment
    assert "`amount` DECIMAL(10,2) NOT NULL" in payment
    assert "`status` VARCHAR(32) NOT NULL" in payment
    assert "DEFAULT 'pending'" in payment
    assert MYSQL_IDEMPOTENCY_COLUMN in payment
    assert "`provider_transaction_id` VARCHAR(128)" in payment
    assert "`succeeded_at` DATETIME(6)" in payment
    assert "`order_id` BIGINT," in payment
    assert "`recharge_order_id` BIGINT," in payment
    assert "`user_id` BIGINT NOT NULL" in payment

    settlement = tables["payment_settlements"]
    assert "`amount` DECIMAL(10,2) NOT NULL" in settlement
    assert "`payment_id` BIGINT NOT NULL UNIQUE" in settlement
    assert "`order_id` BIGINT NOT NULL UNIQUE" in settlement
    assert "idempotency_key" not in settlement

    refund = tables["refunds"]
    assert "`refund_no` VARCHAR(28) NOT NULL UNIQUE" in refund
    assert "`amount` DECIMAL(10,2) NOT NULL" in refund
    assert "`status` VARCHAR(32) NOT NULL" in refund
    assert "DEFAULT 'pending'" in refund
    assert "`inventory_restored` BOOL NOT NULL DEFAULT 0" in refund
    assert "`reason` VARCHAR(256) NOT NULL" in refund
    assert MYSQL_IDEMPOTENCY_COLUMN in refund
    assert "`provider_refund_id` VARCHAR(128)" in refund
    assert "`succeeded_at` DATETIME(6)" in refund
    assert "`operator_id` BIGINT NOT NULL" in refund
    assert "`order_id` BIGINT NOT NULL UNIQUE" in refund
    assert "`settlement_id` BIGINT NOT NULL UNIQUE" in refund

    transaction = tables["wallet_transactions"]
    assert "`transaction_type` VARCHAR(32) NOT NULL" in transaction
    assert "`change_amount` DECIMAL(10,2) NOT NULL" in transaction
    assert "`before_balance` DECIMAL(10,2) NOT NULL" in transaction
    assert "`after_balance` DECIMAL(10,2) NOT NULL" in transaction
    assert "`source_type` VARCHAR(32) NOT NULL" in transaction
    assert "`source_id` BIGINT," in transaction
    assert "`reason` VARCHAR(256) NOT NULL" in transaction
    assert MYSQL_IDEMPOTENCY_COLUMN in transaction
    assert "`operator_id` BIGINT," in transaction
    assert "`wallet_account_id` BIGINT NOT NULL" in transaction


async def test_foreign_keys_are_thirteen_restrict_relations() -> None:
    """每个财务历史关系都必须阻止被引用记录的物理删除。"""

    sql = await _load_migration().upgrade(None)

    assert sql.count("FOREIGN KEY") == 13
    assert sql.count("ON DELETE RESTRICT") == 13
    assert "ON DELETE CASCADE" not in sql
    assert "ON DELETE SET NULL" not in sql

    expected_relations = (
        ("wallet_accounts", "user_id", "users"),
        ("recharge_orders", "user_id", "users"),
        ("recharge_orders", "wallet_account_id", "wallet_accounts"),
        ("payments", "order_id", "orders"),
        ("payments", "recharge_order_id", "recharge_orders"),
        ("payments", "user_id", "users"),
        ("payment_settlements", "payment_id", "payments"),
        ("payment_settlements", "order_id", "orders"),
        ("refunds", "operator_id", "users"),
        ("refunds", "order_id", "orders"),
        ("refunds", "settlement_id", "payment_settlements"),
        ("wallet_transactions", "operator_id", "users"),
        ("wallet_transactions", "wallet_account_id", "wallet_accounts"),
    )
    for table_name, column_name, referenced_table in expected_relations:
        ddl = _table_ddl(sql, table_name)
        assert (
            f"FOREIGN KEY (`{column_name}`) REFERENCES "
            f"`{referenced_table}` (`id`) ON DELETE RESTRICT"
        ) in ddl

    wallet_transaction = _table_ddl(sql, "wallet_transactions")
    assert "FOREIGN KEY (`source_id`)" not in wallet_transaction


async def test_unique_constraints_and_named_indexes_match_contract() -> None:
    """业务唯一性和稳定分页索引不得在离线迁移中漂移。"""

    sql = await _load_migration().upgrade(None)
    tables = {
        name: _table_ddl(sql, name)
        for name in (
            "wallet_accounts",
            "recharge_orders",
            "payments",
            "payment_settlements",
            "refunds",
            "wallet_transactions",
        )
    }

    assert "`user_id` BIGINT NOT NULL UNIQUE" in tables["wallet_accounts"]
    assert "`recharge_no` VARCHAR(28) NOT NULL UNIQUE" in tables["recharge_orders"]
    assert "`payment_no` VARCHAR(28) NOT NULL UNIQUE" in tables["payments"]
    assert "`payment_id` BIGINT NOT NULL UNIQUE" in tables["payment_settlements"]
    assert "`order_id` BIGINT NOT NULL UNIQUE" in tables["payment_settlements"]
    assert "`refund_no` VARCHAR(28) NOT NULL UNIQUE" in tables["refunds"]
    assert "`order_id` BIGINT NOT NULL UNIQUE" in tables["refunds"]
    assert "`settlement_id` BIGINT NOT NULL UNIQUE" in tables["refunds"]

    expected_indexes = {
        "recharge_orders": (
            "UNIQUE KEY `uidx_recharge_order_idempotency` (`idempotency_key`)",
            "KEY `idx_recharge_order_user_created_id` "
            "(`user_id`, `created_at`, `id`)",
            "KEY `idx_recharge_order_status_created_id` "
            "(`status`, `created_at`, `id`)",
        ),
        "payments": (
            "UNIQUE KEY `uidx_payment_idempotency` (`idempotency_key`)",
            "UNIQUE KEY `uidx_payment_provider_transaction` "
            "(`provider_transaction_id`)",
            "KEY `idx_payment_user_created_id` (`user_id`, `created_at`, `id`)",
            "KEY `idx_payment_order_created_id` (`order_id`, `created_at`, `id`)",
            "KEY `idx_payment_recharge_created_id` "
            "(`recharge_order_id`, `created_at`, `id`)",
            "KEY `idx_payment_status_created_id` (`status`, `created_at`, `id`)",
        ),
        "refunds": (
            "UNIQUE KEY `uidx_refund_idempotency` (`idempotency_key`)",
            "UNIQUE KEY `uidx_refund_provider_reference` (`provider_refund_id`)",
            "KEY `idx_refund_order_created_id` (`order_id`, `created_at`, `id`)",
            "KEY `idx_refund_status_created_id` (`status`, `created_at`, `id`)",
        ),
        "wallet_transactions": (
            "UNIQUE KEY `uidx_wallet_transaction_idempotency` "
            "(`idempotency_key`)",
            "KEY `idx_wallet_transaction_wallet_created_id` "
            "(`wallet_account_id`, `created_at`, `id`)",
            "KEY `idx_wallet_transaction_source_created_id` "
            "(`source_type`, `source_id`, `created_at`, `id`)",
            "KEY `idx_wallet_transaction_type_created_id` "
            "(`transaction_type`, `created_at`, `id`)",
            "KEY `idx_wallet_transaction_created_id` (`created_at`, `id`)",
        ),
    }
    for table_name, index_fragments in expected_indexes.items():
        for fragment in index_fragments:
            assert fragment in tables[table_name]


async def test_downgrade_reverts_comment_then_drops_reverse_dependency_order() -> None:
    """降级按 upgrade 的反向依赖顺序删除资金事实。"""

    migration = _load_migration()
    sql = await migration.downgrade(None)
    statements = _statements(sql)

    assert statements[0] == (
        "ALTER TABLE `inventory_transactions` MODIFY COLUMN "
        "`transaction_type` VARCHAR(40) NOT NULL COMMENT "
        "'OPENING_BALANCE: opening_balance\n"
        "ADMIN_ADJUSTMENT: admin_adjustment\n"
        "ORDER_DEDUCTION: order_deduction\n"
        "ORDER_CANCELLATION_RESTORE: order_cancellation_restore'"
    )
    dropped_tables = [
        statement.split("`")[1]
        for statement in statements[1:]
        if statement.startswith("DROP TABLE IF EXISTS `")
    ]
    assert dropped_tables == [
        "wallet_transactions",
        "refunds",
        "payment_settlements",
        "payments",
        "recharge_orders",
        "wallet_accounts",
    ]
    assert len(statements) == 7
    assert "INSERT INTO" not in sql
    assert "UPDATE `" not in sql
    assert "DELETE FROM" not in sql

    source = inspect.getsource(migration.downgrade).lower()
    assert "removes all wallet/payment/refund facts" in source
    assert "forward fix" in source
    assert "verified backup" in source


def test_models_state_contains_financial_models_and_refund_inventory_contract() -> None:
    """Aerich 快照必须承接六个新 Model 与 Inventory 退款恢复枚举。"""

    state = decompress_dict(_load_migration().MODELS_STATE)
    expected_models = {
        "models.WalletAccount",
        "models.WalletTransaction",
        "models.RechargeOrder",
        "models.Payment",
        "models.PaymentSettlement",
        "models.Refund",
    }
    assert expected_models <= set(state)

    wallet_fields = _fields_by_name(state, "models.WalletAccount")
    assert wallet_fields["balance"]["field_type"] == "StrictDecimalField"
    assert wallet_fields["balance"]["default"] == "0.00"
    assert wallet_fields["user_id"]["unique"] is True

    payment_fields = _fields_by_name(state, "models.Payment")
    assert payment_fields["order_id"]["nullable"] is True
    assert payment_fields["recharge_order_id"]["nullable"] is True

    for model_name in (
        "models.RechargeOrder",
        "models.Payment",
        "models.Refund",
        "models.WalletTransaction",
    ):
        fields_by_name = _fields_by_name(state, model_name)
        idempotency_field = fields_by_name["idempotency_key"]
        assert idempotency_field["field_type"] == "AsciiBinaryCharField"
        assert (
            idempotency_field["db_field_types"]["mysql"]
            == MYSQL_IDEMPOTENCY_FIELD_TYPE
        )

    settlement_fields = _fields_by_name(state, "models.PaymentSettlement")
    assert settlement_fields["payment_id"]["unique"] is True
    assert settlement_fields["order_id"]["unique"] is True

    refund_fields = _fields_by_name(state, "models.Refund")
    assert refund_fields["settlement_id"]["unique"] is True
    assert refund_fields["order_id"]["unique"] is True
    assert refund_fields["inventory_restored"]["field_type"] == "BooleanField"
    assert refund_fields["inventory_restored"]["nullable"] is False
    assert refund_fields["inventory_restored"]["default"] is False

    inventory_fields = _fields_by_name(state, "models.InventoryTransaction")
    inventory_enum = inventory_fields["transaction_type"]
    assert inventory_enum["description"].splitlines() == [
        "OPENING_BALANCE: opening_balance",
        "ADMIN_ADJUSTMENT: admin_adjustment",
        "ORDER_DEDUCTION: order_deduction",
        "ORDER_CANCELLATION_RESTORE: order_cancellation_restore",
        "ORDER_REFUND_RESTORE: order_refund_restore",
    ]
