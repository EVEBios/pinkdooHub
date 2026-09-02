"""InventoryTransaction Model 与 SQLite DDL 契约测试。"""

from decimal import Decimal

import pytest
from tortoise import connections, fields
from tortoise.exceptions import IntegrityError, ValidationError
from tortoise.fields.relational import ForeignKeyFieldInstance

from app.common.constants.inventory import (
    INVENTORY_CHANGE_MAX,
    INVENTORY_CHANGE_MIN,
    INVENTORY_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
    INVENTORY_REASON_MAX_LENGTH,
    INVENTORY_SOURCE_TYPE_MAX_LENGTH,
    INVENTORY_STOCK_MAX,
    INVENTORY_TRANSACTION_TYPE_MAX_LENGTH,
)
from app.common.enums.inventory import InventorySourceType, InventoryTransactionType
from app.common.enums.product import ProductType
from app.db.indexes import UniqueIndex
from app.models.inventory_transaction import InventoryTransaction
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User

_UNSET_OPERATOR = object()


async def _create_kit_product(name: str = "库存流水套装") -> Product:
    product = await Product.create(name=name, product_type=ProductType.KIT)
    await ProductKit.create(product=product, price=Decimal("99.00"), stock=10)
    return product


async def _create_operator(username: str = "inventory-admin") -> User:
    return await User.create(
        username=username,
        password="hashed-password",
        nickname="库存管理员",
        phone="13800138000",
    )


async def _create_transaction(
    *,
    product: Product | None = None,
    operator: User | None | object = _UNSET_OPERATOR,
    idempotency_key: str = "inventory:admin:test:adjust:product:1",
    **overrides: object,
) -> InventoryTransaction:
    target = product or await _create_kit_product()
    actor = await _create_operator() if operator is _UNSET_OPERATOR else operator
    payload: dict[str, object] = {
        "product": target,
        "transaction_type": InventoryTransactionType.ADMIN_ADJUSTMENT,
        "change_quantity": -2,
        "before_quantity": 10,
        "after_quantity": 8,
        "source_type": InventorySourceType.ADMIN,
        "source_id": None,
        "operator": actor,
        "reason": "盘点调整",
        "idempotency_key": idempotency_key,
    }
    payload.update(overrides)
    return await InventoryTransaction.create(**payload)


def test_inventory_transaction_metadata_matches_database_contract() -> None:
    """字段、外键、Enum 容量和命名索引必须匹配冻结设计。"""

    fields_map = InventoryTransaction._meta.fields_map
    product_field = fields_map["product"]
    operator_field = fields_map["operator"]

    assert InventoryTransaction._meta.db_table == "inventory_transactions"
    assert isinstance(product_field, ForeignKeyFieldInstance)
    assert product_field.source_field == "product_id"
    assert product_field.related_name == "inventory_transactions"
    assert product_field.on_delete == fields.RESTRICT
    assert product_field.null is False

    assert fields_map["transaction_type"].enum_type is InventoryTransactionType
    assert (
        fields_map["transaction_type"].max_length
        == INVENTORY_TRANSACTION_TYPE_MAX_LENGTH
    )
    assert isinstance(fields_map["change_quantity"], fields.IntField)
    assert isinstance(fields_map["before_quantity"], fields.IntField)
    assert isinstance(fields_map["after_quantity"], fields.IntField)
    assert fields_map["source_type"].enum_type is InventorySourceType
    assert fields_map["source_type"].max_length == INVENTORY_SOURCE_TYPE_MAX_LENGTH
    assert isinstance(fields_map["source_id"], fields.BigIntField)
    assert fields_map["source_id"].null is True

    assert isinstance(operator_field, ForeignKeyFieldInstance)
    assert operator_field.source_field == "operator_id"
    assert operator_field.related_name == "operated_inventory_transactions"
    assert operator_field.on_delete == fields.RESTRICT
    assert operator_field.null is True
    assert fields_map["reason"].max_length == INVENTORY_REASON_MAX_LENGTH
    assert (
        fields_map["idempotency_key"].max_length
        == INVENTORY_IDEMPOTENCY_KEY_DB_MAX_LENGTH
    )
    assert fields_map["idempotency_key"].unique is False

    indexes = InventoryTransaction._meta.indexes
    assert isinstance(indexes[0], UniqueIndex)
    assert [(index.name, index.fields) for index in indexes] == [
        ("uidx_inventory_idempotency_key", ["idempotency_key"]),
        (
            "idx_inventory_product_created_id",
            ["product_id", "created_at", "id"],
        ),
        (
            "idx_inventory_source_created_id",
            ["source_type", "source_id", "created_at", "id"],
        ),
        (
            "idx_inventory_type_created_id",
            ["transaction_type", "created_at", "id"],
        ),
        ("idx_inventory_created_id", ["created_at", "id"]),
    ]


async def test_inventory_transaction_round_trip_and_reverse_relations() -> None:
    """流水应保留 Enum、数量、来源、操作人和 BaseModel 时间字段。"""

    product = await _create_kit_product()
    operator = await _create_operator()
    transaction = await _create_transaction(product=product, operator=operator)
    loaded = await InventoryTransaction.get(id=transaction.id)
    await product.fetch_related("inventory_transactions")
    await operator.fetch_related("operated_inventory_transactions")

    assert loaded.product_id == product.id
    assert loaded.transaction_type is InventoryTransactionType.ADMIN_ADJUSTMENT
    assert loaded.change_quantity == -2
    assert loaded.before_quantity == 10
    assert loaded.after_quantity == 8
    assert loaded.source_type is InventorySourceType.ADMIN
    assert loaded.source_id is None
    assert loaded.operator_id == operator.id
    assert loaded.reason == "盘点调整"
    assert loaded.created_at is not None
    assert loaded.updated_at is not None
    assert [item.id for item in product.inventory_transactions] == [transaction.id]
    assert [item.id for item in operator.operated_inventory_transactions] == [
        transaction.id
    ]


async def test_opening_balance_allows_nullable_source_and_operator() -> None:
    """迁移期初流水允许无业务单据、无操作人，但来源和原因仍必填。"""

    product = await _create_kit_product()
    transaction = await _create_transaction(
        product=product,
        transaction_type=InventoryTransactionType.OPENING_BALANCE,
        change_quantity=10,
        before_quantity=0,
        after_quantity=10,
        source_type=InventorySourceType.MIGRATION,
        source_id=None,
        operator=None,
        reason="Inventory opening balance migration",
        idempotency_key=f"inventory:opening:product:{product.id}",
    )

    loaded = await InventoryTransaction.get(id=transaction.id)
    assert loaded.source_id is None
    assert loaded.operator_id is None


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "expected_message"),
    [
        ("change_quantity", INVENTORY_CHANGE_MIN - 1, "greater or equal"),
        ("change_quantity", 0, "must not be zero"),
        ("change_quantity", INVENTORY_CHANGE_MAX + 1, "less or equal"),
        ("before_quantity", -1, "greater or equal"),
        ("before_quantity", INVENTORY_STOCK_MAX + 1, "less or equal"),
        ("after_quantity", -1, "greater or equal"),
        ("after_quantity", INVENTORY_STOCK_MAX + 1, "less or equal"),
        ("source_id", 0, "greater or equal"),
        ("reason", "", "Length of '' 0 < 1"),
        ("idempotency_key", "", "Length of '' 0 < 1"),
    ],
)
async def test_inventory_transaction_rejects_invalid_field_boundaries(
    field_name: str,
    invalid_value: object,
    expected_message: str,
) -> None:
    """绕过 HTTP Schema 的 ORM 写入仍须满足单字段安全边界。"""

    with pytest.raises(ValidationError, match=expected_message):
        await _create_transaction(**{field_name: invalid_value})


async def test_idempotency_key_is_unique() -> None:
    """数据库唯一约束必须阻止重复业务事件产生第二条流水。"""

    product = await _create_kit_product()
    operator = await _create_operator()
    key = "inventory:admin:repeat:adjust:product:1"
    await _create_transaction(
        product=product,
        operator=operator,
        idempotency_key=key,
    )

    with pytest.raises(IntegrityError):
        await _create_transaction(
            product=product,
            operator=operator,
            idempotency_key=key,
        )

    assert await InventoryTransaction.filter(idempotency_key=key).count() == 1


async def test_inventory_foreign_keys_restrict_physical_deletion() -> None:
    """商品和已记录操作人都不能在流水仍存在时被物理删除。"""

    product = await _create_kit_product()
    operator = await _create_operator()
    await _create_transaction(product=product, operator=operator)

    with pytest.raises(IntegrityError):
        await product.delete()
    with pytest.raises(IntegrityError):
        await operator.delete()

    assert await Product.filter(id=product.id).exists()
    assert await User.filter(id=operator.id).exists()


async def test_inventory_transaction_sqlite_ddl_matches_contract() -> None:
    """SQLite 临时 Schema 应生成命名索引、唯一性、NULL 和 RESTRICT FK。"""

    connection = connections.get("default")
    indexes = await connection.execute_query_dict(
        "PRAGMA index_list('inventory_transactions')"
    )
    indexes_by_name = {item["name"]: item for item in indexes}
    expected_index_columns = {
        "uidx_inventory_idempotency_key": ["idempotency_key"],
        "idx_inventory_product_created_id": ["product_id", "created_at", "id"],
        "idx_inventory_source_created_id": [
            "source_type",
            "source_id",
            "created_at",
            "id",
        ],
        "idx_inventory_type_created_id": [
            "transaction_type",
            "created_at",
            "id",
        ],
        "idx_inventory_created_id": ["created_at", "id"],
    }
    assert set(indexes_by_name) == set(expected_index_columns)
    assert indexes_by_name["uidx_inventory_idempotency_key"]["unique"] == 1
    for index_name, expected_columns in expected_index_columns.items():
        index_columns = await connection.execute_query_dict(
            f"PRAGMA index_info('{index_name}')"
        )
        assert [column["name"] for column in index_columns] == expected_columns

    foreign_keys = await connection.execute_query_dict(
        "PRAGMA foreign_key_list('inventory_transactions')"
    )
    foreign_keys_by_column = {item["from"]: item for item in foreign_keys}
    assert set(foreign_keys_by_column) == {"product_id", "operator_id"}
    assert foreign_keys_by_column["product_id"]["table"] == "products"
    assert foreign_keys_by_column["operator_id"]["table"] == "users"
    assert foreign_keys_by_column["product_id"]["on_delete"] == "RESTRICT"
    assert foreign_keys_by_column["operator_id"]["on_delete"] == "RESTRICT"

    columns = await connection.execute_query_dict(
        "PRAGMA table_info('inventory_transactions')"
    )
    columns_by_name = {column["name"]: column for column in columns}
    assert columns_by_name["product_id"]["notnull"] == 1
    assert columns_by_name["source_type"]["notnull"] == 1
    assert columns_by_name["source_id"]["notnull"] == 0
    assert columns_by_name["operator_id"]["notnull"] == 0
    assert columns_by_name["reason"]["notnull"] == 1
    assert columns_by_name["idempotency_key"]["notnull"] == 1
    assert "order_id" not in columns_by_name
