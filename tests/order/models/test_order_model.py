"""Order 与 OrderItem Model 契约测试。"""

from decimal import Decimal

import pytest
from tortoise import connections, fields
from tortoise.exceptions import IntegrityError, ValidationError
from tortoise.fields.relational import ForeignKeyFieldInstance

from app.common.constants.order import (
    ORDER_AMOUNT_DECIMAL_PLACES,
    ORDER_AMOUNT_MAX,
    ORDER_ITEM_QUANTITY_MAX,
    ORDER_NO_LENGTH,
    ORDER_REMARK_MAX_LENGTH,
)
from app.common.constants.product import PRODUCT_ENUM_MAX_LENGTH
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductType
from app.models.experience_option import ExperienceOption
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User


async def _create_user(username: str = "order-user") -> User:
    return await User.create(
        username=username,
        password="hashed-password",
        nickname="订单用户",
        phone="13800138000",
    )


async def _create_order(
    *,
    user: User | None = None,
    order_no: str = "OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
) -> Order:
    owner = user or await _create_user()
    return await Order.create(
        order_no=order_no,
        user=owner,
        total_amount=Decimal("598.00"),
        remark="靠窗座位",
    )


async def _create_experience_option() -> tuple[Product, ExperienceOption]:
    product = await Product.create(
        name="双人拼豆体验",
        product_type=ProductType.EXPERIENCE,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("299.00"),
    )
    return product, option


def test_order_metadata_matches_database_contract() -> None:
    """主表字段、外键、默认值和查询索引应匹配冻结设计。"""

    fields_map = Order._meta.fields_map
    user_field = fields_map["user"]

    assert Order._meta.db_table == "orders"
    assert isinstance(fields_map["order_no"], fields.CharField)
    assert fields_map["order_no"].max_length == ORDER_NO_LENGTH
    assert fields_map["order_no"].unique is True
    assert isinstance(user_field, ForeignKeyFieldInstance)
    assert user_field.source_field == "user_id"
    assert user_field.related_name == "orders"
    assert user_field.on_delete == fields.RESTRICT
    assert user_field.null is False

    assert isinstance(fields_map["total_amount"], fields.DecimalField)
    assert fields_map["total_amount"].max_digits == 10
    assert fields_map["total_amount"].decimal_places == ORDER_AMOUNT_DECIMAL_PLACES
    assert isinstance(fields_map["status"], fields.SmallIntField)
    assert fields_map["status"].default == OrderStatus.PENDING.value
    assert type(fields_map["status"].default) is int
    assert fields_map["status"].db_default == OrderStatus.PENDING.value
    assert isinstance(fields_map["remark"], fields.CharField)
    assert fields_map["remark"].max_length == ORDER_REMARK_MAX_LENGTH
    assert fields_map["remark"].null is True

    assert [(index.name, index.fields) for index in Order._meta.indexes] == [
        ("idx_orders_user_created_id", ["user_id", "created_at", "id"]),
        (
            "idx_orders_user_status_created_id",
            ["user_id", "status", "created_at", "id"],
        ),
        ("idx_orders_status_created_id", ["status", "created_at", "id"]),
        ("idx_orders_created_id", ["created_at", "id"]),
    ]


def test_order_item_metadata_matches_database_contract() -> None:
    """明细表应保留历史快照，并允许 Kit Item 的 Option 字段为空。"""

    fields_map = OrderItem._meta.fields_map
    expected_foreign_keys = {
        "order": ("order_id", "items", False),
        "product": ("product_id", "order_items", False),
        "experience_option": ("experience_option_id", "order_items", True),
    }
    for field_name, (source_field, related_name, nullable) in expected_foreign_keys.items():
        relation = fields_map[field_name]
        assert isinstance(relation, ForeignKeyFieldInstance)
        assert relation.source_field == source_field
        assert relation.related_name == related_name
        assert relation.on_delete == fields.RESTRICT
        assert relation.null is nullable

    assert OrderItem._meta.db_table == "order_items"
    assert isinstance(fields_map["option_duration_minutes"], fields.IntField)
    assert fields_map["option_duration_minutes"].null is True
    assert isinstance(fields_map["option_participants"], fields.IntField)
    assert fields_map["option_participants"].null is True
    assert fields_map["option_day_type"].enum_type is DayType
    assert fields_map["option_day_type"].max_length == PRODUCT_ENUM_MAX_LENGTH
    assert fields_map["option_day_type"].null is True
    assert isinstance(fields_map["product_name"], fields.CharField)
    assert isinstance(fields_map["product_price"], fields.DecimalField)
    assert isinstance(fields_map["quantity"], fields.IntField)
    assert isinstance(fields_map["subtotal"], fields.DecimalField)

    [order_items_index] = OrderItem._meta.indexes
    assert order_items_index.name == "idx_order_items_order_id"
    assert order_items_index.fields == ["order_id", "id"]


async def test_order_and_experience_snapshot_round_trip() -> None:
    """订单、Item、Decimal、Enum 及全部反向关系应可真实往返。"""

    user = await _create_user()
    order = await _create_order(user=user)
    product, option = await _create_experience_option()
    item = await OrderItem.create(
        order=order,
        product=product,
        experience_option=option,
        option_duration_minutes=option.duration,
        option_participants=option.participants,
        option_day_type=option.day_type,
        product_name=product.name,
        product_price=option.price,
        quantity=2,
        subtotal=Decimal("598.00"),
    )

    loaded_order = await Order.get(id=order.id)
    loaded_item = await OrderItem.get(id=item.id)
    await user.fetch_related("orders")
    await order.fetch_related("items")
    await product.fetch_related("order_items")
    await option.fetch_related("order_items")

    assert loaded_order.status == OrderStatus.PENDING
    assert loaded_order.total_amount == Decimal("598.00")
    assert loaded_order.remark == "靠窗座位"
    assert loaded_item.option_day_type is DayType.HOLIDAY
    assert loaded_item.product_price == Decimal("299.00")
    assert loaded_item.subtotal == Decimal("598.00")
    assert [related.id for related in user.orders] == [order.id]
    assert [related.id for related in order.items] == [item.id]
    assert [related.id for related in product.order_items] == [item.id]
    assert [related.id for related in option.order_items] == [item.id]


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"order_no": "invalid"}, "does not match regex"),
        ({"total_amount": Decimal("0.00")}, "greater or equal to 0.01"),
        (
            {"total_amount": ORDER_AMOUNT_MAX + Decimal("0.01")},
            "less or equal to 99999999.99",
        ),
        (
            {"total_amount": Decimal("1.001")},
            "Decimal places should be less or equal to 2",
        ),
        ({"status": -1}, "greater or equal to 0"),
        ({"status": 4}, "less or equal to 3"),
        ({"remark": "x" * (ORDER_REMARK_MAX_LENGTH + 1)}, "501 > 500"),
    ],
)
async def test_order_rejects_invalid_field_boundaries(
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    """绕过 HTTP Schema 的订单写入仍应受到基础字段约束保护。"""

    user = await _create_user()
    payload: dict[str, object] = {
        "order_no": "OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "user": user,
        "total_amount": Decimal("299.00"),
    }
    payload.update(overrides)

    with pytest.raises(ValidationError, match=expected_message):
        await Order.create(**payload)


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "expected_message"),
    [
        ("option_duration_minutes", 0, "greater or equal to 1"),
        ("option_participants", 0, "greater or equal to 1"),
        ("product_name", "", "Length of '' 0 < 1"),
        ("product_price", Decimal("0.00"), "greater or equal to 0.01"),
        ("quantity", 0, "greater or equal to 1"),
        ("quantity", ORDER_ITEM_QUANTITY_MAX + 1, "less or equal to 99"),
        ("subtotal", Decimal("0.00"), "greater or equal to 0.01"),
        (
            "subtotal",
            Decimal("1.001"),
            "Decimal places should be less or equal to 2",
        ),
    ],
)
async def test_order_item_rejects_invalid_snapshot_boundaries(
    field_name: str,
    invalid_value: object,
    expected_message: str,
) -> None:
    """Item 数量、配置和金额快照应有独立的 Model 边界。"""

    order = await _create_order()
    product, option = await _create_experience_option()
    payload: dict[str, object] = {
        "order": order,
        "product": product,
        "experience_option": option,
        "option_duration_minutes": 120,
        "option_participants": 2,
        "option_day_type": DayType.HOLIDAY,
        "product_name": product.name,
        "product_price": Decimal("299.00"),
        "quantity": 1,
        "subtotal": Decimal("299.00"),
    }
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError, match=expected_message):
        await OrderItem.create(**payload)


async def test_order_item_allows_nullable_option_snapshot_for_future_kit() -> None:
    """数据库形状支持 Kit 的空 Option 快照，并由 Service 约束 Item 类型。"""

    order = await _create_order()
    product = await Product.create(name="拼豆材料包", product_type=ProductType.KIT)
    item = await OrderItem.create(
        order=order,
        product=product,
        experience_option=None,
        option_duration_minutes=None,
        option_participants=None,
        option_day_type=None,
        product_name=product.name,
        product_price=Decimal("99.00"),
        quantity=1,
        subtotal=Decimal("99.00"),
    )

    loaded = await OrderItem.get(id=item.id)
    assert loaded.experience_option_id is None
    assert loaded.option_duration_minutes is None
    assert loaded.option_participants is None
    assert loaded.option_day_type is None


async def test_order_number_is_unique() -> None:
    """订单号数据库唯一约束是生成冲突重试之外的最终兜底。"""

    user = await _create_user()
    await _create_order(user=user)

    with pytest.raises(IntegrityError):
        await _create_order(user=user)


async def test_order_foreign_keys_restrict_physical_deletion() -> None:
    """订单历史链中的 User、Order、Product 与 Option 均不得被物理删除。"""

    user = await _create_user()
    order = await _create_order(user=user)
    product, option = await _create_experience_option()
    await OrderItem.create(
        order=order,
        product=product,
        experience_option=option,
        option_duration_minutes=120,
        option_participants=2,
        option_day_type=DayType.HOLIDAY,
        product_name=product.name,
        product_price=Decimal("299.00"),
        quantity=1,
        subtotal=Decimal("299.00"),
    )

    for protected in (user, order, option, product):
        with pytest.raises(IntegrityError):
            await protected.delete()


async def test_order_sqlite_ddl_matches_named_index_and_fk_contract() -> None:
    """真实 SQLite DDL 应保留命名索引、列顺序、默认值与删除策略。"""

    connection = connections.get("default")
    expected_indexes = {
        "idx_orders_user_created_id": ["user_id", "created_at", "id"],
        "idx_orders_user_status_created_id": [
            "user_id",
            "status",
            "created_at",
            "id",
        ],
        "idx_orders_status_created_id": ["status", "created_at", "id"],
        "idx_orders_created_id": ["created_at", "id"],
    }
    indexes = await connection.execute_query_dict("PRAGMA index_list('orders')")
    index_names = {index["name"] for index in indexes}
    assert expected_indexes.keys() <= index_names
    for index_name, expected_columns in expected_indexes.items():
        columns = await connection.execute_query_dict(
            f"PRAGMA index_info('{index_name}')"
        )
        assert [column["name"] for column in columns] == expected_columns

    item_indexes = await connection.execute_query_dict(
        "PRAGMA index_list('order_items')"
    )
    assert "idx_order_items_order_id" in {index["name"] for index in item_indexes}
    item_index_columns = await connection.execute_query_dict(
        "PRAGMA index_info('idx_order_items_order_id')"
    )
    assert [column["name"] for column in item_index_columns] == ["order_id", "id"]

    order_foreign_keys = await connection.execute_query_dict(
        "PRAGMA foreign_key_list('orders')"
    )
    assert [
        (foreign_key["from"], foreign_key["table"], foreign_key["on_delete"])
        for foreign_key in order_foreign_keys
    ] == [("user_id", "users", "RESTRICT")]

    item_foreign_keys = await connection.execute_query_dict(
        "PRAGMA foreign_key_list('order_items')"
    )
    assert {
        (foreign_key["from"], foreign_key["table"], foreign_key["on_delete"])
        for foreign_key in item_foreign_keys
    } == {
        ("order_id", "orders", "RESTRICT"),
        ("product_id", "products", "RESTRICT"),
        ("experience_option_id", "experience_options", "RESTRICT"),
    }

    order_columns = await connection.execute_query_dict("PRAGMA table_info('orders')")
    order_columns_by_name = {column["name"]: column for column in order_columns}
    assert order_columns_by_name["status"]["notnull"] == 1
    assert order_columns_by_name["status"]["dflt_value"] == "0"
    assert order_columns_by_name["remark"]["notnull"] == 0

    item_columns = await connection.execute_query_dict(
        "PRAGMA table_info('order_items')"
    )
    item_columns_by_name = {column["name"]: column for column in item_columns}
    for nullable_field in (
        "experience_option_id",
        "option_duration_minutes",
        "option_participants",
        "option_day_type",
    ):
        assert item_columns_by_name[nullable_field]["notnull"] == 0
