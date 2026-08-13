"""Product Mapper 与真实 Repository 聚合的零 SQL 集成测试。"""

from decimal import Decimal

import pytest
from tortoise import connections

from app.api.mappers.product import (
    map_admin_experience_product_detail,
    map_admin_product_page,
    map_experience_product_detail,
    map_product_page,
)
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
from app.repositories.product_repo import ProductRepository


def _snapshot(product: Product) -> tuple[object, ...]:
    """记录 Mapper 可见聚合，确认映射不修改 ORM 对象或关系列表。"""

    return (
        product.id,
        product.name,
        product.description,
        product.product_type,
        product.status,
        product.is_deleted,
        tuple(
            (
                image.id,
                image.image_url,
                image.is_cover,
                image.sort,
                image.experience_option_id,
            )
            for image in product.images
        ),
        tuple(
            (
                option.id,
                option.duration,
                option.participants,
                option.day_type,
                option.price,
                tuple(
                    (
                        image.id,
                        image.image_url,
                        image.is_cover,
                        image.sort,
                        image.experience_option_id,
                    )
                    for image in option.images
                ),
            )
            for option in product.experience_options
        ),
    )


async def _create_online_experience() -> int:
    product = await Product.create(
        name="真实聚合体验",
        product_type=ProductType.EXPERIENCE,
        description="用于验证 Mapper 零 SQL",
        status=ProductStatus.ONLINE,
    )
    later_image = await ProductImage.create(
        product=product,
        image_url="https://example.com/later.jpg",
        sort=20,
    )
    cover = await ProductImage.create(
        product=product,
        image_url="https://example.com/cover.jpg",
        is_cover=True,
        sort=10,
    )
    first_option = await ExperienceOption.create(
        product=product,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("399.00"),
    )
    second_option = await ExperienceOption.create(
        product=product,
        duration=60,
        participants=2,
        day_type=DayType.WEEKDAY,
        price=Decimal("299.00"),
    )
    first_option_later_image = await ProductImage.create(
        product=product,
        experience_option=first_option,
        image_url="https://example.com/option-later.jpg",
        sort=20,
    )
    first_option_first_image = await ProductImage.create(
        product=product,
        experience_option=first_option,
        image_url="https://example.com/option-first.jpg",
        sort=10,
    )
    await ProductImage.create(
        product=product,
        experience_option=second_option,
        image_url="https://example.com/option-second.jpg",
        sort=0,
    )

    assert later_image.id < cover.id
    assert first_option_later_image.id < first_option_first_image.id
    return product.id


@pytest.mark.asyncio
async def test_repository_detail_maps_without_sql_or_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_id = await _create_online_experience()
    product = await ProductRepository().get_product_detail(product_id)
    assert product is not None
    before = _snapshot(product)

    connection = connections.get("default")

    def fail_on_query(*args: object, **kwargs: object) -> None:
        raise AssertionError("Product Mapper must not execute SQL")

    monkeypatch.setattr(connection, "execute_query", fail_on_query)

    data = map_experience_product_detail(product).model_dump(mode="json")

    assert data["images"] == [
        {
            "id": product.images[0].id,
            "image_url": "https://example.com/cover.jpg",
            "is_cover": True,
            "sort": 10,
        },
        {
            "id": product.images[1].id,
            "image_url": "https://example.com/later.jpg",
            "is_cover": False,
            "sort": 20,
        },
    ]
    assert data["dimensions"] == {
        "durations": [
            {"value": 60, "label": "1小时"},
            {"value": 120, "label": "2小时"},
        ],
        "participants": [{"value": 2, "label": "2人"}],
        "day_types": [
            {"value": "weekday", "label": "工作日"},
            {"value": "holiday", "label": "节假日"},
        ],
    }
    assert data["options"][1]["images"][0]["image_url"] == (
        "https://example.com/option-first.jpg"
    )
    assert _snapshot(product) == before


@pytest.mark.asyncio
async def test_repository_pages_map_without_additional_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _create_online_experience()
    repository = ProductRepository()
    online_page = await repository.list_products(
        page=1,
        page_size=20,
        status=ProductStatus.ONLINE,
    )
    admin_page = await repository.list_products(page=1, page_size=20)

    connection = connections.get("default")

    def fail_on_query(*args: object, **kwargs: object) -> None:
        raise AssertionError("Product Mapper must not execute SQL")

    monkeypatch.setattr(connection, "execute_query", fail_on_query)

    user = map_product_page(online_page).model_dump(mode="json")
    admin = map_admin_product_page(admin_page).model_dump(mode="json")

    assert user["items"][0]["display_price"] == "299.00"
    assert user["items"][0]["cover_image"] == "https://example.com/cover.jpg"
    assert admin["items"][0]["status"]["value"] == "online"


@pytest.mark.asyncio
async def test_admin_draft_empty_aggregate_maps_from_repository() -> None:
    product = await Product.create(
        name="未完成草稿",
        product_type=ProductType.EXPERIENCE,
        description=None,
    )
    loaded = await ProductRepository().get_product_detail(
        product.id,
        include_deleted=True,
    )
    assert loaded is not None

    data = map_admin_experience_product_detail(loaded).model_dump(mode="json")

    assert data["images"] == []
    assert data["options"] == []
    assert data["dimensions"] == {
        "durations": [],
        "participants": [],
        "day_types": [],
    }
