"""ProductRepository 列表摘要关联预加载契约测试。"""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from pytest import MonkeyPatch
from tortoise import connections
from tortoise.exceptions import NoValuesFetched

from app.common.enums.product import DayType, ProductType
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit
from app.repositories.product_repo import ProductRepository


async def _create_option(
    product: Product,
    *,
    duration: int,
    price: Decimal,
    is_deleted: bool = False,
) -> ExperienceOption:
    """创建列表展示价所需的体验配置。"""

    return await ExperienceOption.create(
        product=product,
        duration=duration,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=price,
        is_deleted=is_deleted,
    )


async def _create_image(
    product: Product,
    *,
    image_url: str,
    sort: int,
    option: ExperienceOption | None = None,
    is_cover: bool = False,
    is_deleted: bool = False,
) -> ProductImage:
    """创建 Product 公共图片或 Option 专属图片。"""

    return await ProductImage.create(
        product=product,
        experience_option=option,
        image_url=image_url,
        is_cover=is_cover,
        sort=sort,
        is_deleted=is_deleted,
    )


async def test_list_products_preloads_only_active_summary_relations() -> None:
    """列表只加载计算封面与展示价所需的有效关联数据。"""

    experience = await Product.create(
        name="列表体验商品",
        product_type=ProductType.EXPERIENCE,
    )
    expensive_option = await _create_option(
        experience,
        duration=120,
        price=Decimal("399.00"),
    )
    cheap_option = await _create_option(
        experience,
        duration=60,
        price=Decimal("299.00"),
    )
    await _create_option(
        experience,
        duration=180,
        price=Decimal("199.00"),
        is_deleted=True,
    )
    later_public_image = await _create_image(
        experience,
        image_url="https://example.com/public-later.jpg",
        sort=20,
    )
    cover = await _create_image(
        experience,
        image_url="https://example.com/cover.jpg",
        sort=10,
        is_cover=True,
    )
    await _create_image(
        experience,
        image_url="https://example.com/deleted-cover.jpg",
        sort=0,
        is_cover=True,
        is_deleted=True,
    )
    await _create_image(
        experience,
        option=cheap_option,
        image_url="https://example.com/option.jpg",
        sort=0,
    )

    kit_product = await Product.create(
        name="列表套装商品",
        product_type=ProductType.KIT,
    )
    kit = await ProductKit.create(
        product=kit_product,
        price=Decimal("599.00"),
        stock=20,
    )

    result = await ProductRepository().list_products(page=1, page_size=20)
    loaded_by_id = {product.id: product for product in result.items}
    loaded_experience = loaded_by_id[experience.id]
    loaded_kit_product = loaded_by_id[kit_product.id]

    assert list(loaded_experience.experience_options) == [
        cheap_option,
        expensive_option,
    ]
    assert list(loaded_experience.images) == [cover, later_public_image]
    assert loaded_kit_product.kit == kit

    with pytest.raises(NoValuesFetched):
        list(loaded_experience.experience_options[0].images)


async def test_list_products_summary_query_count_is_constant(
    monkeypatch: MonkeyPatch,
) -> None:
    """页面内商品数量增加时，列表摘要仍只执行常量级 SELECT。"""

    for number in range(3):
        product = await Product.create(
            name=f"查询预算体验 {number}",
            product_type=ProductType.EXPERIENCE,
        )
        option = await _create_option(
            product,
            duration=60 + number * 30,
            price=Decimal("299.00") + Decimal(number),
        )
        await _create_image(
            product,
            image_url=f"https://example.com/products/{number}.jpg",
            sort=0,
            is_cover=True,
        )
        await _create_image(
            product,
            option=option,
            image_url=f"https://example.com/options/{number}.jpg",
            sort=0,
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

    result = await ProductRepository().list_products(page=1, page_size=20)
    loaded_options = [
        option
        for product in result.items
        for option in list(product.experience_options)
    ]
    loaded_images = [
        image
        for product in result.items
        for image in list(product.images)
    ]

    assert len(loaded_options) == 3
    assert len(loaded_images) == 3
    assert 1 <= len(select_queries) <= 4
