"""ProductImage Model 契约测试。"""

from decimal import Decimal

import pytest
from tortoise import connections, fields
from tortoise.exceptions import IntegrityError, ValidationError
from tortoise.fields.relational import ForeignKeyFieldInstance
from tortoise.indexes import Index

from app.common.constants.product import (
    MIN_IMAGE_SORT,
    PRODUCT_IMAGE_URL_MAX_LENGTH,
)
from app.common.enums.product import DayType, ProductType
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage


async def _create_experience_product(name: str = "拼豆体验") -> Product:
    return await Product.create(name=name, product_type=ProductType.EXPERIENCE)


async def _create_option(product: Product) -> ExperienceOption:
    return await ExperienceOption.create(
        product=product,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("299.00"),
    )


def test_product_image_metadata_matches_database_contract() -> None:
    """字段、两类外键、默认值与稳定命名索引应匹配冻结契约。"""

    fields_map = ProductImage._meta.fields_map
    product_field = fields_map["product"]
    option_field = fields_map["experience_option"]

    assert ProductImage._meta.db_table == "product_images"
    assert isinstance(product_field, ForeignKeyFieldInstance)
    assert product_field.source_field == "product_id"
    assert product_field.related_name == "images"
    assert product_field.on_delete == fields.RESTRICT
    assert product_field.null is False

    assert isinstance(option_field, ForeignKeyFieldInstance)
    assert option_field.source_field == "experience_option_id"
    assert option_field.related_name == "images"
    assert option_field.on_delete == fields.SET_NULL
    assert option_field.null is True

    assert isinstance(fields_map["image_url"], fields.CharField)
    assert fields_map["image_url"].max_length == PRODUCT_IMAGE_URL_MAX_LENGTH
    assert fields_map["image_url"].null is False
    assert fields_map["is_cover"].default is False
    assert fields_map["sort"].default == MIN_IMAGE_SORT
    assert fields_map["is_deleted"].default is False

    indexes = ProductImage._meta.indexes
    assert all(isinstance(index, Index) for index in indexes)
    assert [(index.name, index.fields) for index in indexes] == [
        ("idx_image_product_sort", ["product_id", "sort"]),
        ("idx_image_product_cover", ["product_id", "is_cover"]),
        ("idx_image_option_sort", ["experience_option_id", "sort"]),
    ]


async def test_product_public_image_defaults_and_reverse_relation_round_trip() -> None:
    """不关联 Option 的图片应作为 Product 公共图并使用字段默认值。"""

    product = await _create_experience_product()
    image = await ProductImage.create(
        product=product,
        image_url="https://cdn.example.com/products/1/cover.jpg",
    )
    loaded = await ProductImage.get(id=image.id)
    await product.fetch_related("images")

    assert loaded.product_id == product.id
    assert loaded.experience_option_id is None
    assert loaded.is_cover is False
    assert loaded.sort == MIN_IMAGE_SORT
    assert loaded.is_deleted is False
    assert loaded.created_at is not None
    assert loaded.updated_at is not None
    assert [related.id for related in product.images] == [image.id]


async def test_option_image_relations_round_trip() -> None:
    """Option 专属图应同时保留 Product 与 ExperienceOption 关系。"""

    product = await _create_experience_product()
    option = await _create_option(product)
    image = await ProductImage.create(
        product=product,
        experience_option=option,
        image_url="https://cdn.example.com/options/1/first.jpg",
        sort=10,
    )
    loaded = await ProductImage.get(id=image.id)
    await option.fetch_related("images")

    assert loaded.product_id == product.id
    assert loaded.experience_option_id == option.id
    assert loaded.sort == 10
    assert [related.id for related in option.images] == [image.id]


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"image_url": ""}, "Length of '' 0 < 1"),
        (
            {"image_url": "x" * (PRODUCT_IMAGE_URL_MAX_LENGTH + 1)},
            "2049 > 2048",
        ),
        ({"sort": -1}, "greater or equal to 0"),
    ],
)
async def test_product_image_rejects_invalid_field_boundaries(
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    """非 HTTP ORM 写入也必须遵守 URL 与排序基础边界。"""

    product = await _create_experience_product()
    payload: dict[str, object] = {
        "product": product,
        "image_url": "https://cdn.example.com/products/1/image.jpg",
    }
    payload.update(overrides)

    with pytest.raises(ValidationError, match=expected_message):
        await ProductImage.create(**payload)


async def test_product_image_accepts_maximum_url_length_and_non_negative_sort() -> None:
    """URL 最大长度、零排序和正排序均应正常保存。"""

    product = await _create_experience_product()
    first = await ProductImage.create(
        product=product,
        image_url="x" * PRODUCT_IMAGE_URL_MAX_LENGTH,
    )
    second = await ProductImage.create(
        product=product,
        image_url="https://cdn.example.com/products/1/second.jpg",
        sort=20,
    )

    assert len(first.image_url) == PRODUCT_IMAGE_URL_MAX_LENGTH
    assert first.sort == 0
    assert second.sort == 20


async def test_logical_delete_preserves_product_and_option_relations() -> None:
    """图片逻辑删除只改变标记，不应破坏任何外键关系。"""

    product = await _create_experience_product()
    option = await _create_option(product)
    image = await ProductImage.create(
        product=product,
        experience_option=option,
        image_url="https://cdn.example.com/options/1/deleted.jpg",
    )
    image.is_deleted = True
    await image.save(update_fields=["is_deleted"])
    loaded = await ProductImage.get(id=image.id)

    assert loaded.is_deleted is True
    assert loaded.product_id == product.id
    assert loaded.experience_option_id == option.id


async def test_option_physical_delete_sets_image_relation_to_null() -> None:
    """异常物理删除 Option 时应保留图片，并由 FK 将 Option 关系置空。"""

    product = await _create_experience_product()
    option = await _create_option(product)
    image = await ProductImage.create(
        product=product,
        experience_option=option,
        image_url="https://cdn.example.com/options/1/orphan-fallback.jpg",
    )

    await option.delete()
    loaded = await ProductImage.get(id=image.id)

    assert loaded.product_id == product.id
    assert loaded.experience_option_id is None


async def test_product_physical_delete_is_restricted_by_image_foreign_key() -> None:
    """数据库必须阻止物理删除仍被 ProductImage 引用的 Product。"""

    product = await _create_experience_product()
    await ProductImage.create(
        product=product,
        image_url="https://cdn.example.com/products/1/keep.jpg",
    )

    with pytest.raises(IntegrityError):
        await product.delete()

    assert await Product.filter(id=product.id).exists()


async def test_product_image_sqlite_ddl_matches_contract() -> None:
    """真实 SQLite DDL 应包含三个普通索引、两种 FK 策略和数据库默认值。"""

    connection = connections.get("default")
    indexes = await connection.execute_query_dict("PRAGMA index_list('product_images')")
    indexes_by_name = {index["name"]: index for index in indexes}
    expected_indexes = {
        "idx_image_product_sort": ["product_id", "sort"],
        "idx_image_product_cover": ["product_id", "is_cover"],
        "idx_image_option_sort": ["experience_option_id", "sort"],
    }
    for index_name, expected_columns in expected_indexes.items():
        assert indexes_by_name[index_name]["unique"] == 0
        index_columns = await connection.execute_query_dict(
            f"PRAGMA index_info('{index_name}')"
        )
        assert [column["name"] for column in index_columns] == expected_columns

    foreign_keys = await connection.execute_query_dict(
        "PRAGMA foreign_key_list('product_images')"
    )
    foreign_keys_by_column = {foreign_key["from"]: foreign_key for foreign_key in foreign_keys}
    product_fk = foreign_keys_by_column["product_id"]
    option_fk = foreign_keys_by_column["experience_option_id"]
    assert (product_fk["table"], product_fk["to"], product_fk["on_delete"]) == (
        "products",
        "id",
        "RESTRICT",
    )
    assert (option_fk["table"], option_fk["to"], option_fk["on_delete"]) == (
        "experience_options",
        "id",
        "SET NULL",
    )

    columns = await connection.execute_query_dict("PRAGMA table_info('product_images')")
    columns_by_name = {column["name"]: column for column in columns}
    assert columns_by_name["product_id"]["notnull"] == 1
    assert columns_by_name["experience_option_id"]["notnull"] == 0
    assert columns_by_name["image_url"]["notnull"] == 1
    assert columns_by_name["is_cover"]["dflt_value"] == "0"
    assert columns_by_name["sort"]["dflt_value"] == "0"
    assert columns_by_name["is_deleted"]["dflt_value"] == "0"
