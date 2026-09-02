"""ProductRepository 聚合详情预加载契约测试。"""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from pytest import MonkeyPatch
from tortoise import connections

from app.common.enums.product import DayType, ProductType
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit
from app.repositories.product_repo import ProductRepository


async def _create_experience_product(
    name: str = "拼豆体验",
    *,
    is_deleted: bool = False,
) -> Product:
    """创建体验商品测试数据。"""

    return await Product.create(
        name=name,
        product_type=ProductType.EXPERIENCE,
        is_deleted=is_deleted,
    )


async def _create_option(
    product: Product,
    *,
    duration: int,
    is_deleted: bool = False,
) -> ExperienceOption:
    """创建 ExperienceOption 测试数据。"""

    return await ExperienceOption.create(
        product=product,
        duration=duration,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("299.00"),
        is_deleted=is_deleted,
    )


async def _create_image(
    product: Product,
    *,
    image_url: str,
    sort: int,
    option: ExperienceOption | None = None,
    is_deleted: bool = False,
) -> ProductImage:
    """创建 Product 公共图或 Option 专属图测试数据。"""

    return await ProductImage.create(
        product=product,
        experience_option=option,
        image_url=image_url,
        sort=sort,
        is_deleted=is_deleted,
    )


async def test_get_product_detail_prefetches_only_active_experience_relations(
) -> None:
    """体验详情分离公共图与 Option 图，并过滤逻辑删除子记录。"""

    product = await _create_experience_product()
    active_option = await _create_option(product, duration=60)
    deleted_option = await _create_option(
        product,
        duration=120,
        is_deleted=True,
    )
    later_public_image = await _create_image(
        product,
        image_url="https://example.com/public-later.jpg",
        sort=20,
    )
    first_public_image = await _create_image(
        product,
        image_url="https://example.com/public-first.jpg",
        sort=10,
    )
    await _create_image(
        product,
        image_url="https://example.com/public-deleted.jpg",
        sort=0,
        is_deleted=True,
    )
    later_option_image = await _create_image(
        product,
        option=active_option,
        image_url="https://example.com/option-later.jpg",
        sort=20,
    )
    first_option_image = await _create_image(
        product,
        option=active_option,
        image_url="https://example.com/option-first.jpg",
        sort=10,
    )
    await _create_image(
        product,
        option=active_option,
        image_url="https://example.com/option-deleted.jpg",
        sort=0,
        is_deleted=True,
    )
    await _create_image(
        product,
        option=deleted_option,
        image_url="https://example.com/deleted-option.jpg",
        sort=0,
    )

    detail = await ProductRepository().get_product_detail(product.id)

    assert detail is not None
    assert list(detail.images) == [first_public_image, later_public_image]
    loaded_options = list(detail.experience_options)
    assert loaded_options == [active_option]
    assert list(loaded_options[0].images) == [
        first_option_image,
        later_option_image,
    ]


async def test_get_product_detail_can_include_deleted_product_but_not_relations(
) -> None:
    """管理端可显式读取已删除 Product，但详情仍隐藏已删除子记录。"""

    product = await _create_experience_product(is_deleted=True)
    active_option = await _create_option(product, duration=60)
    await _create_option(product, duration=120, is_deleted=True)
    active_image = await _create_image(
        product,
        image_url="https://example.com/public.jpg",
        sort=0,
    )
    await _create_image(
        product,
        image_url="https://example.com/deleted.jpg",
        sort=10,
        is_deleted=True,
    )
    repository = ProductRepository()

    assert await repository.get_product_detail(product.id) is None

    detail = await repository.get_product_detail(
        product.id,
        include_deleted=True,
    )

    assert detail is not None
    assert list(detail.experience_options) == [active_option]
    assert list(detail.images) == [active_image]


async def test_get_product_detail_preloads_kit_and_public_images() -> None:
    """套装详情一次返回一对一 Kit 与已排序的公共图片。"""

    product = await Product.create(
        name="新手套装",
        product_type=ProductType.KIT,
    )
    kit = await ProductKit.create(
        product=product,
        price=Decimal("599.00"),
        stock=20,
    )
    later_image = await _create_image(
        product,
        image_url="https://example.com/kit-later.jpg",
        sort=20,
    )
    first_image = await _create_image(
        product,
        image_url="https://example.com/kit-first.jpg",
        sort=10,
    )

    detail = await ProductRepository().get_product_detail(product.id)

    assert detail is not None
    assert detail.kit == kit
    assert list(detail.images) == [first_image, later_image]
    assert list(detail.experience_options) == []


async def test_get_product_detail_has_constant_query_count(
    monkeypatch: MonkeyPatch,
) -> None:
    """Option 数量增加时，详情查询仍保持常量级 SELECT 次数。"""

    product = await _create_experience_product()
    options = [
        await _create_option(product, duration=duration)
        for duration in (60, 120, 180)
    ]
    for option in options:
        await _create_image(
            product,
            option=option,
            image_url=f"https://example.com/options/{option.id}-1.jpg",
            sort=0,
        )
        await _create_image(
            product,
            option=option,
            image_url=f"https://example.com/options/{option.id}-2.jpg",
            sort=10,
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

    detail = await ProductRepository().get_product_detail(product.id)

    assert detail is not None
    loaded_options = list(detail.experience_options)
    loaded_images = [
        image
        for option in loaded_options
        for image in list(option.images)
    ]
    assert len(loaded_options) == 3
    assert len(loaded_images) == 6
    assert 1 <= len(select_queries) <= 4
