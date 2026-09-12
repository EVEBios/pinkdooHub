"""Product 聚合根 Model 契约测试。"""

import pytest
from tortoise import connections, fields
from tortoise.exceptions import ValidationError

from app.common.constants.product import (
    PRODUCT_DESCRIPTION_MAX_LENGTH,
    PRODUCT_ENUM_MAX_LENGTH,
    PRODUCT_NAME_MAX_LENGTH,
)
from app.common.enums.product import ProductStatus, ProductType
from app.models.product import Product


def test_product_model_metadata_matches_database_contract() -> None:
    """字段、表名与基础约束应匹配冻结后的数据库设计。"""

    fields_map = Product._meta.fields_map

    assert Product._meta.db_table == "products"
    assert isinstance(fields_map["name"], fields.CharField)
    assert fields_map["name"].max_length == PRODUCT_NAME_MAX_LENGTH
    assert fields_map["name"].null is False

    assert fields_map["product_type"].field_type is str
    assert fields_map["product_type"].enum_type is ProductType
    assert fields_map["product_type"].max_length == PRODUCT_ENUM_MAX_LENGTH
    assert fields_map["product_type"].null is False

    assert isinstance(fields_map["description"], fields.TextField)
    assert fields_map["description"].null is True

    assert fields_map["status"].field_type is str
    assert fields_map["status"].enum_type is ProductStatus
    assert fields_map["status"].max_length == PRODUCT_ENUM_MAX_LENGTH
    assert fields_map["status"].default == ProductStatus.DRAFT
    assert fields_map["status"].null is False

    assert isinstance(fields_map["is_deleted"], fields.BooleanField)
    assert fields_map["is_deleted"].default is False
    assert fields_map["is_deleted"].null is False


async def test_product_defaults_and_string_enums_round_trip() -> None:
    """ORM 应自动设置草稿状态、逻辑删除标记和公共时间字段。"""

    product = await Product.create(
        name="拼豆体验",
        product_type=ProductType.EXPERIENCE,
    )
    loaded = await Product.get(id=product.id)

    assert loaded.id > 0
    assert loaded.product_type is ProductType.EXPERIENCE
    assert loaded.description is None
    assert loaded.status is ProductStatus.DRAFT
    assert loaded.is_deleted is False
    assert loaded.created_at is not None
    assert loaded.updated_at is not None


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"name": ""}, "Length of '' 0 < 1"),
        ({"name": "x" * (PRODUCT_NAME_MAX_LENGTH + 1)}, "101 > 100"),
        (
            {"description": "x" * (PRODUCT_DESCRIPTION_MAX_LENGTH + 1)},
            "2001 > 2000",
        ),
    ],
)
async def test_product_model_rejects_invalid_text_boundaries(
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    """绕过 HTTP Schema 的 ORM 写入仍应受到基础字段边界保护。"""

    payload: dict[str, object] = {
        "name": "拼豆体验",
        "product_type": ProductType.EXPERIENCE,
    }
    payload.update(overrides)

    with pytest.raises(ValidationError, match=expected_message):
        await Product.create(**payload)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("product_type", "unknown"),
        ("status", "unknown"),
    ],
)
async def test_product_model_rejects_unknown_enum_values(
    field_name: str,
    invalid_value: str,
) -> None:
    """Product 字符串枚举不得退化为任意裸字符串。"""

    payload: dict[str, object] = {
        "name": "拼豆体验",
        "product_type": ProductType.EXPERIENCE,
    }
    payload[field_name] = invalid_value

    with pytest.raises(ValueError, match="is not a valid"):
        await Product.create(**payload)


async def test_product_status_deleted_index_is_created_with_stable_name() -> None:
    """真实 SQLite DDL 应包含文档约定的复合索引名和列顺序。"""

    connection = connections.get("default")
    indexes = await connection.execute_query_dict("PRAGMA index_list('products')")

    index = next(
        item for item in indexes if item["name"] == "idx_products_status_deleted"
    )
    assert index["unique"] == 0

    columns = await connection.execute_query_dict(
        "PRAGMA index_info('idx_products_status_deleted')"
    )
    assert [column["name"] for column in columns] == ["status", "is_deleted"]


async def test_product_database_defaults_match_contract() -> None:
    """数据库本身也应提供 draft / false 默认值，而不只依赖 ORM。"""

    connection = connections.get("default")
    columns = await connection.execute_query_dict("PRAGMA table_info('products')")
    columns_by_name = {column["name"]: column for column in columns}

    assert columns_by_name["status"]["notnull"] == 1
    assert columns_by_name["status"]["dflt_value"] == "'draft'"
    assert columns_by_name["is_deleted"]["notnull"] == 1
    assert columns_by_name["is_deleted"]["dflt_value"] == "0"
    assert columns_by_name["description"]["notnull"] == 0
