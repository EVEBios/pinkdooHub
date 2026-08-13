"""Product Mapper 列表、详情与 mutation 组合测试。"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.mappers.product import (
    map_admin_experience_product_detail,
    map_admin_kit_product_detail,
    map_admin_product_page,
    map_admin_product_list_item,
    map_deleted_resource,
    map_experience_product_create,
    map_experience_product_detail,
    map_kit_price,
    map_kit_product_create,
    map_kit_product_detail,
    map_kit_stock,
    map_product_basic_info,
    map_product_offline,
    map_product_online,
    map_product_page,
)
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.pagination import Page


NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)


def _image(
    image_id: int,
    *,
    option_id: int | None,
    cover: bool = False,
    product_id: int = 1,
):
    return SimpleNamespace(
        id=image_id,
        image_url=f"https://cdn.example.com/{image_id}.jpg",
        experience_option_id=option_id,
        product_id=product_id,
        is_cover=cover,
        sort=0,
        is_deleted=False,
    )


def _option(option_id: int, *, price: str = "299.00", with_image: bool = True):
    images = [_image(option_id + 100, option_id=option_id)] if with_image else []
    return SimpleNamespace(
        id=option_id,
        product_id=1,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal(price),
        images=images,
        is_deleted=False,
    )


def _product(
    *,
    product_id: int = 1,
    product_type: ProductType = ProductType.EXPERIENCE,
    status: ProductStatus = ProductStatus.ONLINE,
    is_deleted: bool = False,
    images=None,
    options=None,
    kit=None,
    description: str | None = "商品说明",
):
    return SimpleNamespace(
        id=product_id,
        name="拼豆商品",
        product_type=product_type,
        description=description,
        status=status,
        is_deleted=is_deleted,
        images=[] if images is None else images,
        experience_options=[] if options is None else options,
        kit=kit,
        created_at=NOW,
        updated_at=NOW,
        password="must-not-leak",
    )


def test_user_and_admin_pages_preserve_metadata_and_isolate_fields() -> None:
    product = _product(
        images=[_image(10, option_id=None, cover=True)],
        options=[_option(11, price="399.00"), _option(12, price="299.00")],
    )
    page = Page(items=[product], total=21, page=2, page_size=20, pages=2)

    user_dump = map_product_page(page).model_dump(mode="json")
    admin_dump = map_admin_product_page(page).model_dump(mode="json")

    assert user_dump == {
        "items": [{
            "id": 1,
            "name": "拼豆商品",
            "product_type": {"value": "experience", "label": "拼豆体验"},
            "cover_image": "https://cdn.example.com/10.jpg",
            "display_price": "299.00",
        }],
        "total": 21,
        "page": 2,
        "page_size": 20,
        "pages": 2,
    }
    assert admin_dump["items"][0]["status"] == {
        "value": "online",
        "label": "已上架",
    }
    assert admin_dump["items"][0]["is_deleted"] is False


def test_admin_experience_detail_allows_empty_draft() -> None:
    product = _product(
        status=ProductStatus.DRAFT,
        description=None,
        images=[],
        options=[],
    )

    data = map_admin_experience_product_detail(product).model_dump(mode="json")

    assert data["description"] is None
    assert data["images"] == []
    assert data["options"] == []
    assert data["dimensions"] == {
        "durations": [],
        "participants": [],
        "day_types": [],
    }


def test_admin_kit_list_allows_missing_extension_as_null_price() -> None:
    product = _product(
        product_type=ProductType.KIT,
        status=ProductStatus.DRAFT,
        kit=None,
    )

    data = map_admin_product_list_item(product).model_dump(mode="json")

    assert data["display_price"] is None


def test_user_experience_detail_requires_complete_online_aggregate() -> None:
    product = _product(
        images=[_image(10, option_id=None, cover=True)],
        options=[_option(11)],
    )

    data = map_experience_product_detail(product).model_dump(mode="json")

    assert set(data) == {
        "id", "name", "product_type", "description", "images",
        "dimensions", "options",
    }
    assert data["options"][0]["images"][0]["id"] == 111


@pytest.mark.parametrize(
    "product,match",
    [
        (_product(status=ProductStatus.DRAFT), "online product"),
        (_product(is_deleted=True), "deleted product"),
        (_product(images=[], options=[_option(11)]), "no cover image"),
        (
            _product(images=[_image(10, option_id=None, cover=True)], options=[]),
            "at least 1 item",
        ),
        (
            _product(
                images=[_image(10, option_id=None, cover=True)],
                options=[_option(11, with_image=False)],
            ),
            "at least 1 item",
        ),
    ],
)
def test_user_experience_mapper_rejects_incomplete_aggregate(product, match) -> None:
    with pytest.raises((ValueError, ValidationError), match=match):
        map_experience_product_detail(product)


def test_kit_detail_uses_extension_and_derives_availability() -> None:
    kit = SimpleNamespace(id=900, product_id=2, price=Decimal("699.00"), stock=5)
    product = _product(
        product_id=2,
        product_type=ProductType.KIT,
        images=[_image(10, option_id=None, cover=True, product_id=2)],
        kit=kit,
    )

    user = map_kit_product_detail(product).model_dump(mode="json")
    admin = map_admin_kit_product_detail(product).model_dump(mode="json")

    assert user["price"] == "699.00"
    assert user["stock"] == 5
    assert user["available"] is True
    assert "status" not in user
    assert admin["status"] == {"value": "online", "label": "已上架"}


def test_detail_mappers_reject_mismatched_product_types() -> None:
    experience = _product(product_type=ProductType.EXPERIENCE)
    kit = _product(product_type=ProductType.KIT)

    with pytest.raises(ValueError, match="kit product"):
        map_kit_product_detail(experience)
    with pytest.raises(ValueError, match="experience product"):
        map_experience_product_detail(kit)


def test_mutation_mappers_use_strict_whitelists_and_correct_ids() -> None:
    experience = _product(status=ProductStatus.DRAFT)
    kit_product = _product(product_id=2, product_type=ProductType.KIT, status=ProductStatus.DRAFT)
    kit = SimpleNamespace(id=900, product_id=2, price=Decimal("699.00"), stock=20)
    deleted = SimpleNamespace(id=31, is_deleted=True, product_id=1, image_url="secret")

    assert map_experience_product_create(experience).model_dump(mode="json")["status"] == {
        "value": "draft", "label": "草稿",
    }
    assert map_kit_product_create(kit_product).model_dump(mode="json")["id"] == 2
    assert map_product_basic_info(experience).model_dump(mode="json") == {
        "id": 1,
        "name": "拼豆商品",
        "description": "商品说明",
        "updated_at": "2026-08-13T08:00:00Z",
    }

    experience.status = ProductStatus.ONLINE
    assert map_product_online(experience).model_dump(mode="json")["status"]["value"] == "online"
    experience.status = ProductStatus.OFFLINE
    assert map_product_offline(experience).model_dump(mode="json")["status"]["value"] == "offline"
    assert map_deleted_resource(deleted).model_dump(mode="json") == {"id": 31, "is_deleted": True}
    assert map_kit_price(kit).model_dump(mode="json") == {"id": 2, "price": "699.00"}
    assert map_kit_stock(kit).model_dump(mode="json") == {"id": 2, "stock": 20}
