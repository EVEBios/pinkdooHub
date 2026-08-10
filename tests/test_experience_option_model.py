"""ExperienceOption Model 契约测试。"""

from decimal import Decimal

import pytest
from tortoise import connections, fields
from tortoise.exceptions import IntegrityError, ValidationError
from tortoise.fields.relational import ForeignKeyFieldInstance

from app.common.constants.product import (
    PRODUCT_ENUM_MAX_LENGTH,
    PRODUCT_PRICE_DECIMAL_PLACES,
    PRODUCT_PRICE_MAX,
)
from app.common.enums.product import DayType, ProductType
from app.models.experience_option import ExperienceOption
from app.models.product import Product


async def _create_experience_product(name: str = "拼豆体验") -> Product:
    return await Product.create(name=name, product_type=ProductType.EXPERIENCE)


def test_experience_option_metadata_matches_database_contract() -> None:
    """表名、字段、外键和全历史唯一索引应与冻结契约一致。"""

    fields_map = ExperienceOption._meta.fields_map
    product_field = fields_map["product"]

    assert ExperienceOption._meta.db_table == "experience_options"
    assert isinstance(product_field, ForeignKeyFieldInstance)
    assert product_field.source_field == "product_id"
    assert product_field.related_name == "experience_options"
    assert product_field.on_delete == fields.RESTRICT
    assert product_field.null is False

    assert isinstance(fields_map["duration"], fields.IntField)
    assert fields_map["duration"].null is False
    assert isinstance(fields_map["participants"], fields.IntField)
    assert fields_map["participants"].null is False

    assert fields_map["day_type"].enum_type is DayType
    assert fields_map["day_type"].max_length == PRODUCT_ENUM_MAX_LENGTH
    assert fields_map["day_type"].null is False

    assert isinstance(fields_map["price"], fields.DecimalField)
    assert fields_map["price"].max_digits == 10
    assert fields_map["price"].decimal_places == PRODUCT_PRICE_DECIMAL_PLACES
    assert fields_map["price"].null is False

    assert isinstance(fields_map["is_deleted"], fields.BooleanField)
    assert fields_map["is_deleted"].default is False
    assert fields_map["is_deleted"].null is False

    [unique_index] = ExperienceOption._meta.indexes
    assert unique_index.name == "idx_option_unique"
    assert unique_index.fields == [
        "product_id",
        "duration",
        "participants",
        "day_type",
    ]


async def test_experience_option_values_and_reverse_relation_round_trip() -> None:
    """Option 应保留 Decimal、字符串枚举、默认值和 Product 反向关系。"""

    product = await _create_experience_product()
    option = await ExperienceOption.create(
        product=product,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("699.00"),
    )
    loaded = await ExperienceOption.get(id=option.id)
    await product.fetch_related("experience_options")

    assert loaded.product_id == product.id
    assert loaded.duration == 120
    assert loaded.participants == 2
    assert loaded.day_type is DayType.HOLIDAY
    assert loaded.price == Decimal("699.00")
    assert loaded.is_deleted is False
    assert loaded.created_at is not None
    assert loaded.updated_at is not None
    assert [related.id for related in product.experience_options] == [option.id]


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "expected_message"),
    [
        ("duration", 0, "greater or equal to 1"),
        ("participants", 0, "greater or equal to 1"),
        ("price", Decimal("0.00"), "greater or equal to 0.01"),
        (
            "price",
            PRODUCT_PRICE_MAX + Decimal("0.01"),
            "less or equal to 99999.00",
        ),
        ("price", Decimal("1.001"), "Decimal places should be less or equal to 2"),
        ("price", Decimal("NaN"), "Decimal value must be finite"),
    ],
)
async def test_experience_option_rejects_invalid_numeric_boundaries(
    field_name: str,
    invalid_value: object,
    expected_message: str,
) -> None:
    """非 HTTP ORM 写入也必须遵守正整数、价格范围与精度约束。"""

    product = await _create_experience_product()
    payload: dict[str, object] = {
        "product": product,
        "duration": 60,
        "participants": 1,
        "day_type": DayType.WEEKDAY,
        "price": Decimal("299.00"),
    }
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError, match=expected_message):
        await ExperienceOption.create(**payload)


async def test_experience_option_accepts_open_dimensions_and_price_boundaries() -> None:
    """时长和人数不是封闭枚举，合法价格的最小值与最大值都应可保存。"""

    product = await _create_experience_product()
    minimum = await ExperienceOption.create(
        product=product,
        duration=180,
        participants=3,
        day_type=DayType.WEEKDAY,
        price=Decimal("0.01"),
    )
    maximum = await ExperienceOption.create(
        product=product,
        duration=240,
        participants=4,
        day_type=DayType.HOLIDAY,
        price=PRODUCT_PRICE_MAX,
    )

    assert minimum.price == Decimal("0.01")
    assert maximum.price == PRODUCT_PRICE_MAX


async def test_experience_option_rejects_unknown_day_type() -> None:
    """日期类型必须使用冻结的字符串枚举值。"""

    product = await _create_experience_product()

    with pytest.raises(ValueError, match="is not a valid"):
        await ExperienceOption.create(
            product=product,
            duration=60,
            participants=1,
            day_type="weekend",
            price=Decimal("299.00"),
        )


async def test_unique_combination_includes_logically_deleted_rows() -> None:
    """逻辑删除不得释放组合；后续 Service 必须恢复原记录而非 INSERT。"""

    product = await _create_experience_product()
    option = await ExperienceOption.create(
        product=product,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("299.00"),
    )
    option.is_deleted = True
    await option.save(update_fields=["is_deleted"])

    with pytest.raises(IntegrityError):
        await ExperienceOption.create(
            product=product,
            duration=60,
            participants=1,
            day_type=DayType.WEEKDAY,
            price=Decimal("399.00"),
        )

    assert await ExperienceOption.filter(product=product).count() == 1


async def test_same_combination_is_allowed_for_different_products() -> None:
    """组合唯一性以 Product 为边界，不同商品可以使用相同配置。"""

    first_product = await _create_experience_product("体验 A")
    second_product = await _create_experience_product("体验 B")

    for product in (first_product, second_product):
        await ExperienceOption.create(
            product=product,
            duration=60,
            participants=1,
            day_type=DayType.WEEKDAY,
            price=Decimal("299.00"),
        )

    assert await ExperienceOption.all().count() == 2


async def test_product_physical_delete_is_restricted_by_option_foreign_key() -> None:
    """数据库必须阻止绕过 Service 物理删除仍被 Option 引用的 Product。"""

    product = await _create_experience_product()
    await ExperienceOption.create(
        product=product,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("299.00"),
    )

    with pytest.raises(IntegrityError):
        await product.delete()

    assert await Product.filter(id=product.id).exists()


async def test_experience_option_sqlite_ddl_matches_contract() -> None:
    """真实 SQLite DDL 应生成命名唯一索引、外键策略与数据库默认值。"""

    connection = connections.get("default")
    indexes = await connection.execute_query_dict(
        "PRAGMA index_list('experience_options')"
    )
    unique_index = next(item for item in indexes if item["name"] == "idx_option_unique")
    assert unique_index["unique"] == 1

    index_columns = await connection.execute_query_dict(
        "PRAGMA index_info('idx_option_unique')"
    )
    assert [column["name"] for column in index_columns] == [
        "product_id",
        "duration",
        "participants",
        "day_type",
    ]

    foreign_keys = await connection.execute_query_dict(
        "PRAGMA foreign_key_list('experience_options')"
    )
    product_fk = next(item for item in foreign_keys if item["from"] == "product_id")
    assert product_fk["table"] == "products"
    assert product_fk["to"] == "id"
    assert product_fk["on_delete"] == "RESTRICT"

    columns = await connection.execute_query_dict(
        "PRAGMA table_info('experience_options')"
    )
    columns_by_name = {column["name"]: column for column in columns}
    assert columns_by_name["product_id"]["notnull"] == 1
    assert columns_by_name["price"]["notnull"] == 1
    assert columns_by_name["is_deleted"]["notnull"] == 1
    assert columns_by_name["is_deleted"]["dflt_value"] == "0"
