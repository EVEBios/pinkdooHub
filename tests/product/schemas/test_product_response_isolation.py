"""Product 组合响应的字段隔离测试。"""

from decimal import Decimal

from app.schemas.product_response import (
    AdminExperienceProductDetailOut,
    AdminKitProductDetailOut,
    AdminProductListItemOut,
    ExperienceProductDetailOut,
    KitProductDetailOut,
    ProductListItemOut,
)
from tests.support.product_response import (
    NOW,
    admin_experience,
    admin_kit,
    admin_list_item,
    dimensions,
    option,
    product_image,
    status,
    user_experience,
    user_kit,
    user_list_item,
)


def test_user_list_filters_admin_and_detail_fields() -> None:
    payload = user_list_item()
    payload.update(
        {
            "status": status("online", "已上架"),
            "is_deleted": False,
            "description": "不应出现在列表",
            "images": [product_image()],
            "created_at": NOW,
            "updated_at": NOW,
            "stock": 10,
            "token": "must-not-leak",
        }
    )

    dumped = ProductListItemOut.model_validate(payload).model_dump(mode="json")

    assert set(dumped) == {
        "id",
        "name",
        "product_type",
        "cover_image",
        "display_price",
    }


def test_user_experience_filters_admin_and_kit_fields_recursively() -> None:
    payload = user_experience()
    payload.update(
        {
            "status": status("online", "已上架"),
            "is_deleted": False,
            "created_at": NOW,
            "updated_at": NOW,
            "price": Decimal("1.00"),
            "stock": 1,
            "available": True,
        }
    )
    payload["options"][0].update(
        {"product_id": 1, "is_deleted": False, "created_at": NOW}
    )
    payload["options"][0]["images"][0].update(
        {"is_cover": True, "experience_option_id": 11}
    )

    dumped = ExperienceProductDetailOut.model_validate(payload).model_dump(
        mode="json"
    )

    assert set(dumped) == {
        "id",
        "name",
        "product_type",
        "description",
        "images",
        "dimensions",
        "options",
    }
    assert set(dumped["options"][0]) == {
        "id",
        "duration",
        "participants",
        "day_type",
        "price",
        "images",
    }
    assert set(dumped["options"][0]["images"][0]) == {
        "id",
        "image_url",
        "sort",
    }


def test_user_kit_filters_admin_and_internal_fields() -> None:
    payload = user_kit()
    payload.update(
        {
            "status": status("online", "已上架"),
            "is_deleted": False,
            "created_at": NOW,
            "updated_at": NOW,
            "product_kit_id": 99,
            "sold_count": 1000,
            "options": [option()],
        }
    )

    dumped = KitProductDetailOut.model_validate(payload).model_dump(mode="json")

    assert set(dumped) == {
        "id",
        "name",
        "product_type",
        "description",
        "images",
        "price",
        "stock",
        "available",
    }


def test_admin_list_filters_detail_fields() -> None:
    payload = admin_list_item()
    payload.update(
        {
            "description": "列表不需要",
            "images": [product_image()],
            "options": [option()],
            "stock": 10,
            "created_at": NOW,
        }
    )

    dumped = AdminProductListItemOut.model_validate(payload).model_dump(
        mode="json"
    )

    assert set(dumped) == {
        "id",
        "name",
        "product_type",
        "status",
        "cover_image",
        "display_price",
        "updated_at",
        "is_deleted",
    }


def test_admin_experience_filters_kit_fields() -> None:
    payload = admin_experience()
    payload.update(
        {
            "price": Decimal("99.00"),
            "stock": 10,
            "available": True,
            "product_kit_id": 9,
        }
    )

    dumped = AdminExperienceProductDetailOut.model_validate(payload).model_dump(
        mode="json"
    )

    assert "price" not in dumped
    assert "stock" not in dumped
    assert "available" not in dumped
    assert "product_kit_id" not in dumped


def test_admin_kit_filters_user_and_experience_fields() -> None:
    payload = admin_kit()
    payload.update(
        {
            "available": False,
            "dimensions": dimensions(),
            "options": [option()],
            "sold_count": 100,
            "product_kit_id": 9,
        }
    )

    dumped = AdminKitProductDetailOut.model_validate(payload).model_dump(
        mode="json"
    )

    assert "available" not in dumped
    assert "dimensions" not in dumped
    assert "options" not in dumped
    assert "sold_count" not in dumped
    assert "product_kit_id" not in dumped
