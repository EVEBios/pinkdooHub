"""ProductRepository 子资源父级关系预加载契约测试。"""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from pytest import MonkeyPatch
from tortoise import connections

from app.common.enums.product import DayType, ProductType
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
from app.repositories.product_repo import ProductRepository


async def _create_option(product: Product) -> ExperienceOption:
    """创建带所属 Product 的体验配置。"""

    return await ExperienceOption.create(
        product=product,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("299.00"),
    )


async def test_get_option_by_id_preloads_product() -> None:
    """Service 读取 Option 后可直接检查所属 Product，无需再次查库。"""

    product = await Product.create(
        name="Option 父级商品",
        product_type=ProductType.EXPERIENCE,
    )
    option = await _create_option(product)

    loaded = await ProductRepository().get_option_by_id(option.id)

    assert loaded is not None
    assert loaded.product.id == product.id
    assert loaded.product.product_type is ProductType.EXPERIENCE


async def test_get_image_by_id_preloads_product_and_option() -> None:
    """Service 读取 Option 图片后可直接检查图片归属及所属 Product。"""

    product = await Product.create(
        name="Image 父级商品",
        product_type=ProductType.EXPERIENCE,
    )
    option = await _create_option(product)
    image = await ProductImage.create(
        product=product,
        experience_option=option,
        image_url="https://example.com/option-image.jpg",
    )

    loaded = await ProductRepository().get_image_by_id(image.id)

    assert loaded is not None
    assert loaded.product.id == product.id
    assert loaded.experience_option is not None
    assert loaded.experience_option.id == option.id


async def test_parent_relations_do_not_add_queries_after_repository_returns(
    monkeypatch: MonkeyPatch,
) -> None:
    """两个按 ID 查询各使用一条 SELECT，随后访问父级关系不追加 SQL。"""

    product = await Product.create(
        name="父级查询预算商品",
        product_type=ProductType.EXPERIENCE,
    )
    option = await _create_option(product)
    image = await ProductImage.create(
        product=product,
        experience_option=option,
        image_url="https://example.com/query-budget.jpg",
    )

    connection = connections.get("default")
    original_execute_query: Callable[..., Awaitable[Any]] = (
        connection.execute_query
    )
    select_queries: list[str] = []

    async def capture_query(query: str, values: list[Any] | None = None) -> Any:
        if query.lstrip().upper().startswith("SELECT"):
            select_queries.append(query)
        return await original_execute_query(query, values)

    monkeypatch.setattr(connection, "execute_query", capture_query)

    loaded_option = await ProductRepository().get_option_by_id(option.id)
    loaded_image = await ProductRepository().get_image_by_id(image.id)

    assert loaded_option is not None
    assert loaded_image is not None
    assert loaded_option.product.id == product.id
    assert loaded_image.product.id == product.id
    assert loaded_image.experience_option is not None
    assert loaded_image.experience_option.id == option.id
    assert len(select_queries) == 2
