"""ProductKit Model 契约测试。"""

from decimal import Decimal

import pytest
from tortoise import connections, fields
from tortoise.exceptions import IntegrityError, ValidationError
from tortoise.fields.relational import OneToOneFieldInstance

from app.common.constants.product import (
    MIN_STOCK,
    PRODUCT_PRICE_DECIMAL_PLACES,
    PRODUCT_PRICE_MAX,
)
from app.common.constants.inventory import INVENTORY_STOCK_MAX
from app.common.enums.product import ProductType
from app.models.fields import StrictDecimalField
from app.models.product import Product
from app.models.product_kit import ProductKit


async def _create_kit_product(name: str = "新手拼豆套装") -> Product:
    return await Product.create(name=name, product_type=ProductType.KIT)


def test_product_kit_metadata_matches_database_contract() -> None:
    """表名、一对一外键、金额和库存字段应匹配冻结契约。"""

    fields_map = ProductKit._meta.fields_map
    product_field = fields_map["product"]

    assert ProductKit._meta.db_table == "product_kits"
    assert isinstance(product_field, OneToOneFieldInstance)
    assert product_field.source_field == "product_id"
    assert product_field.related_name == "kit"
    assert product_field.on_delete == fields.RESTRICT
    assert product_field.unique is True
    assert product_field.null is False

    assert isinstance(fields_map["price"], StrictDecimalField)
    assert fields_map["price"].max_digits == 10
    assert fields_map["price"].decimal_places == PRODUCT_PRICE_DECIMAL_PLACES
    assert fields_map["price"].null is False

    assert isinstance(fields_map["stock"], fields.IntField)
    assert fields_map["stock"].default == MIN_STOCK
    assert fields_map["stock"].null is False
    assert "is_deleted" not in fields_map
    assert ProductKit._meta.indexes == ()


async def test_product_kit_values_defaults_and_reverse_relation_round_trip() -> None:
    """Kit 应保留 Decimal、库存默认值、时间字段和 Product 单对象反向关系。"""

    product = await _create_kit_product()
    kit = await ProductKit.create(product=product, price=Decimal("599.00"))
    loaded = await ProductKit.get(id=kit.id)
    await product.fetch_related("kit")

    assert loaded.product_id == product.id
    assert loaded.price == Decimal("599.00")
    assert loaded.stock == MIN_STOCK
    assert loaded.created_at is not None
    assert loaded.updated_at is not None
    assert product.kit.id == kit.id


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "expected_message"),
    [
        ("price", Decimal("0.00"), "greater or equal to 0.01"),
        (
            "price",
            PRODUCT_PRICE_MAX + Decimal("0.01"),
            "less or equal to 99999.00",
        ),
        ("price", Decimal("1.001"), "Decimal places should be less or equal to 2"),
        ("price", Decimal("NaN"), "Decimal value must be finite"),
        ("stock", -1, "greater or equal to 0"),
        (
            "stock",
            INVENTORY_STOCK_MAX + 1,
            "less or equal to 999999",
        ),
    ],
)
async def test_product_kit_rejects_invalid_numeric_boundaries(
    field_name: str,
    invalid_value: object,
    expected_message: str,
) -> None:
    """非 HTTP ORM 写入也必须遵守价格和库存边界。"""

    product = await _create_kit_product()
    payload: dict[str, object] = {
        "product": product,
        "price": Decimal("599.00"),
        "stock": 0,
    }
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError, match=expected_message):
        await ProductKit.create(**payload)


async def test_product_kit_accepts_price_and_stock_boundaries() -> None:
    """价格闭区间边界与库存闭区间都应正常保存。"""

    minimum_product = await _create_kit_product("最低价套装")
    maximum_product = await _create_kit_product("最高价套装")
    minimum = await ProductKit.create(
        product=minimum_product,
        price=Decimal("0.01"),
    )
    maximum = await ProductKit.create(
        product=maximum_product,
        price=PRODUCT_PRICE_MAX,
        stock=INVENTORY_STOCK_MAX,
    )

    assert minimum.price == Decimal("0.01")
    assert minimum.stock == 0
    assert maximum.price == PRODUCT_PRICE_MAX
    assert maximum.stock == INVENTORY_STOCK_MAX


async def test_one_product_cannot_have_multiple_product_kits() -> None:
    """一对一约束必须阻止同一个 Product 拥有第二条 Kit 扩展记录。"""

    product = await _create_kit_product()
    await ProductKit.create(product=product, price=Decimal("599.00"))

    with pytest.raises(IntegrityError):
        await ProductKit.create(product=product, price=Decimal("699.00"))

    assert await ProductKit.filter(product=product).count() == 1


async def test_different_products_can_have_independent_product_kits() -> None:
    """一对一唯一性以 Product 为边界，不限制系统中的套装商品数量。"""

    first_product = await _create_kit_product("套装 A")
    second_product = await _create_kit_product("套装 B")

    await ProductKit.create(product=first_product, price=Decimal("499.00"))
    await ProductKit.create(product=second_product, price=Decimal("599.00"))

    assert await ProductKit.all().count() == 2


async def test_product_physical_delete_is_restricted_by_product_kit_foreign_key() -> None:
    """数据库必须阻止物理删除仍被 ProductKit 引用的 Product。"""

    product = await _create_kit_product()
    await ProductKit.create(product=product, price=Decimal("599.00"))

    with pytest.raises(IntegrityError):
        await product.delete()

    assert await Product.filter(id=product.id).exists()


async def test_product_kit_sqlite_ddl_matches_contract() -> None:
    """真实 SQLite DDL 应生成一对一唯一性、RESTRICT FK 和库存默认值。"""

    connection = connections.get("default")
    indexes = await connection.execute_query_dict("PRAGMA index_list('product_kits')")
    unique_indexes = [item for item in indexes if item["unique"] == 1]
    assert len(unique_indexes) == 1

    index_columns = await connection.execute_query_dict(
        f"PRAGMA index_info('{unique_indexes[0]['name']}')"
    )
    assert [column["name"] for column in index_columns] == ["product_id"]

    foreign_keys = await connection.execute_query_dict(
        "PRAGMA foreign_key_list('product_kits')"
    )
    product_fk = next(item for item in foreign_keys if item["from"] == "product_id")
    assert product_fk["table"] == "products"
    assert product_fk["to"] == "id"
    assert product_fk["on_delete"] == "RESTRICT"

    columns = await connection.execute_query_dict("PRAGMA table_info('product_kits')")
    columns_by_name = {column["name"]: column for column in columns}
    assert columns_by_name["product_id"]["notnull"] == 1
    assert columns_by_name["price"]["notnull"] == 1
    assert columns_by_name["stock"]["notnull"] == 1
    assert columns_by_name["stock"]["dflt_value"] == "0"
    assert "is_deleted" not in columns_by_name
