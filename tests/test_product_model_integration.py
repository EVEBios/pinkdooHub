"""Product Model 注册、关系图与跨数据库 DDL 集成契约。"""

from importlib import import_module
from typing import Any

from tortoise import Tortoise, connections, fields
from tortoise.context import TortoiseContext
from tortoise.fields.relational import (
    BackwardFKRelation,
    BackwardOneToOneRelation,
    ForeignKeyFieldInstance,
    OneToOneFieldInstance,
)

from app.db.indexes import UniqueIndex
from app.models.experience_option import ExperienceOption
from app.models.fields import StrictDecimalField
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit


def _import_deconstructed(path: str) -> type[Any]:
    module_name, class_name = path.rsplit(".", maxsplit=1)
    return getattr(import_module(module_name), class_name)


def test_product_models_are_registered_as_one_orm_app() -> None:
    """四个 Model 必须由 app.models 统一导出并注册。"""

    registered = Tortoise.apps["models"]

    assert registered["Product"] is Product
    assert registered["ExperienceOption"] is ExperienceOption
    assert registered["ProductKit"] is ProductKit
    assert registered["ProductImage"] is ProductImage


def test_product_relation_graph_matches_aggregate_contract() -> None:
    """正向、反向关系名和删除策略共同组成聚合关系契约。"""

    product_fields = Product._meta.fields_map
    option_fields = ExperienceOption._meta.fields_map
    kit_fields = ProductKit._meta.fields_map
    image_fields = ProductImage._meta.fields_map

    assert isinstance(product_fields["experience_options"], BackwardFKRelation)
    assert isinstance(product_fields["kit"], BackwardOneToOneRelation)
    assert isinstance(product_fields["images"], BackwardFKRelation)
    assert isinstance(option_fields["images"], BackwardFKRelation)

    option_product = option_fields["product"]
    assert isinstance(option_product, ForeignKeyFieldInstance)
    assert option_product.related_model is Product
    assert option_product.related_name == "experience_options"
    assert option_product.on_delete == fields.RESTRICT

    kit_product = kit_fields["product"]
    assert isinstance(kit_product, OneToOneFieldInstance)
    assert kit_product.related_model is Product
    assert kit_product.related_name == "kit"
    assert kit_product.on_delete == fields.RESTRICT

    image_product = image_fields["product"]
    assert isinstance(image_product, ForeignKeyFieldInstance)
    assert image_product.related_model is Product
    assert image_product.related_name == "images"
    assert image_product.on_delete == fields.RESTRICT

    image_option = image_fields["experience_option"]
    assert isinstance(image_option, ForeignKeyFieldInstance)
    assert image_option.related_model is ExperienceOption
    assert image_option.related_name == "images"
    assert image_option.on_delete == fields.SET_NULL
    assert image_option.null is True


def test_custom_field_and_index_can_be_reconstructed_for_migrations() -> None:
    """Aerich 所依赖的 deconstruct 信息必须保留自定义类型和参数。"""

    index = ExperienceOption._meta.indexes[0]
    index_path, index_args, index_kwargs = index.deconstruct()
    rebuilt_index = _import_deconstructed(index_path)(*index_args, **index_kwargs)

    assert index_path == "app.db.indexes.UniqueIndex"
    assert isinstance(rebuilt_index, UniqueIndex)
    assert rebuilt_index.name == "idx_option_unique"
    assert rebuilt_index.fields == [
        "product_id",
        "duration",
        "participants",
        "day_type",
    ]

    price = ExperienceOption._meta.fields_map["price"]
    field_path, field_args, field_kwargs = price.deconstruct()
    rebuilt_field = _import_deconstructed(field_path)(*field_args, **field_kwargs)

    assert field_path == "app.models.fields.StrictDecimalField"
    assert isinstance(rebuilt_field, StrictDecimalField)
    assert rebuilt_field.max_digits == 10
    assert rebuilt_field.decimal_places == 2


async def test_sqlite_index_inventory_matches_query_contract() -> None:
    """SQLite 实体库中的命名索引应与查询和唯一性设计完全一致。"""

    connection = connections.get("default")
    expected = {
        "products": {"idx_products_status_deleted"},
        "experience_options": {"idx_option_unique"},
        "product_images": {
            "idx_image_product_sort",
            "idx_image_product_cover",
            "idx_image_option_sort",
        },
    }

    for table_name, expected_names in expected.items():
        indexes = await connection.execute_query_dict(
            f"PRAGMA index_list('{table_name}')"
        )
        named_indexes = {
            index["name"]
            for index in indexes
            if not index["name"].startswith("sqlite_autoindex_")
        }
        assert named_indexes == expected_names


async def test_mysql_schema_generator_matches_production_contract() -> None:
    """离线生成 MySQL DDL，验证生产路径无需连接或改动真实数据库。"""

    mysql_config = {
        "connections": {
            "mysql_contract": "mysql://test:test@127.0.0.1:3306/test"
        },
        "apps": {
            "models": {
                "models": ["app.models"],
                "default_connection": "mysql_contract",
            }
        },
    }
    mysql_context = TortoiseContext()

    with mysql_context:
        await mysql_context.init(config=mysql_config)
        try:
            client = mysql_context.connections.get("mysql_contract")
            ddl = client.schema_generator(client).get_create_schema_sql(safe=False)
        finally:
            await mysql_context.close_connections()

    assert "CREATE TABLE `products`" in ddl
    assert "`product_type` VARCHAR(20) NOT NULL" in ddl
    assert "`status` VARCHAR(20) NOT NULL" in ddl
    assert "DEFAULT 'draft'" in ddl
    assert "KEY `idx_products_status_deleted` (`status`, `is_deleted`)" in ddl

    assert "CREATE TABLE `experience_options`" in ddl
    assert "`price` DECIMAL(10,2) NOT NULL" in ddl
    assert "ON DELETE RESTRICT" in ddl
    assert "UNIQUE KEY `idx_option_unique` (`product_id`, `duration`, `participants`, `day_type`)" in ddl

    assert "CREATE TABLE `product_kits`" in ddl
    assert "`stock` INT NOT NULL DEFAULT 0" in ddl
    assert "`product_id` BIGINT NOT NULL UNIQUE" in ddl

    assert "CREATE TABLE `product_images`" in ddl
    assert "`image_url` VARCHAR(2048) NOT NULL" in ddl
    assert "ON DELETE SET NULL" in ddl
    assert "KEY `idx_image_product_sort` (`product_id`, `sort`)" in ddl
    assert "KEY `idx_image_product_cover` (`product_id`, `is_cover`)" in ddl
    assert "KEY `idx_image_option_sort` (`experience_option_id`, `sort`)" in ddl
