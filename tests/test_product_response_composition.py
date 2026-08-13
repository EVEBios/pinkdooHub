"""Product 列表与详情组合响应 Schema 契约测试。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.common.pagination import Page
from app.schemas.product_response import (
    AdminExperienceProductDetailOut,
    AdminKitProductDetailOut,
    AdminProductListItemOut,
    ExperienceProductDetailOut,
    KitProductDetailOut,
    ProductListItemOut,
)

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone(timedelta(hours=8)))


def _product_type(value: str, label: str) -> dict[str, str]:
    return {"value": value, "label": label}


def _status(value: str, label: str) -> dict[str, str]:
    return {"value": value, "label": label}


def _product_image(image_id: int = 1) -> dict[str, object]:
    return {
        "id": image_id,
        "image_url": f"https://example.com/products/{image_id}.jpg",
        "is_cover": True,
        "sort": 0,
    }


def _dimensions() -> dict[str, list[dict[str, object]]]:
    return {
        "durations": [{"value": 60, "label": "1小时"}],
        "participants": [{"value": 1, "label": "1人"}],
        "day_types": [{"value": "weekday", "label": "工作日"}],
    }


def _experience_option() -> dict[str, object]:
    return {
        "id": 11,
        "duration": {"value": 60, "label": "1小时"},
        "participants": {"value": 1, "label": "1人"},
        "day_type": {"value": "weekday", "label": "工作日"},
        "price": Decimal("299.0"),
        "images": [
            {
                "id": 20,
                "image_url": "https://example.com/options/20.jpg",
                "sort": 0,
            }
        ],
    }


def test_user_list_item_composes_with_page() -> None:
    page = Page[ProductListItemOut].model_validate(
        {
            "items": [
                {
                    "id": 1,
                    "name": "拼豆体验",
                    "product_type": _product_type("experience", "拼豆体验"),
                    "cover_image": "https://example.com/products/1.jpg",
                    "display_price": Decimal("299"),
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 20,
            "pages": 1,
        }
    )

    assert page.model_dump(mode="json") == {
        "items": [
            {
                "id": 1,
                "name": "拼豆体验",
                "product_type": {
                    "value": "experience",
                    "label": "拼豆体验",
                },
                "cover_image": "https://example.com/products/1.jpg",
                "display_price": "299.00",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
        "pages": 1,
    }


def test_admin_list_item_allows_incomplete_deleted_draft() -> None:
    schema = AdminProductListItemOut.model_validate(
        {
            "id": 2,
            "name": "待完善套装",
            "product_type": _product_type("kit", "拼豆套装"),
            "status": _status("draft", "草稿"),
            "cover_image": None,
            "display_price": None,
            "updated_at": NOW,
            "is_deleted": True,
        }
    )

    assert schema.model_dump(mode="json") == {
        "id": 2,
        "name": "待完善套装",
        "product_type": {"value": "kit", "label": "拼豆套装"},
        "status": {"value": "draft", "label": "草稿"},
        "cover_image": None,
        "display_price": None,
        "updated_at": "2026-08-09T12:00:00+08:00",
        "is_deleted": True,
    }


def test_user_experience_detail_requires_complete_shape() -> None:
    schema = ExperienceProductDetailOut.model_validate(
        {
            "id": 1,
            "name": "拼豆体验",
            "product_type": _product_type("experience", "拼豆体验"),
            "description": "选择体验配置",
            "images": [_product_image()],
            "dimensions": _dimensions(),
            "options": [_experience_option()],
        }
    )

    dumped = schema.model_dump(mode="json")

    assert dumped["product_type"]["value"] == "experience"
    assert dumped["options"][0]["price"] == "299.00"
    assert dumped["options"][0]["images"][0]["sort"] == 0
    assert dumped["dimensions"]["day_types"][0]["value"] == "weekday"


def test_user_kit_detail_returns_consistent_availability() -> None:
    schema = KitProductDetailOut.model_validate(
        {
            "id": 2,
            "name": "拼豆套装",
            "product_type": _product_type("kit", "拼豆套装"),
            "description": "适合新手入门",
            "images": [_product_image(2)],
            "price": Decimal("599"),
            "stock": 20,
            "available": True,
        }
    )

    dumped = schema.model_dump(mode="json")

    assert dumped["product_type"]["value"] == "kit"
    assert dumped["price"] == "599.00"
    assert dumped["stock"] == 20
    assert dumped["available"] is True


def test_admin_experience_detail_allows_empty_draft_aggregate() -> None:
    schema = AdminExperienceProductDetailOut.model_validate(
        {
            "id": 3,
            "name": "未完成体验",
            "product_type": _product_type("experience", "拼豆体验"),
            "description": None,
            "status": _status("draft", "草稿"),
            "images": [],
            "dimensions": {
                "durations": [],
                "participants": [],
                "day_types": [],
            },
            "options": [],
            "created_at": NOW,
            "updated_at": NOW,
            "is_deleted": False,
        }
    )

    dumped = schema.model_dump(mode="json")

    assert dumped["description"] is None
    assert dumped["images"] == []
    assert dumped["dimensions"]["durations"] == []
    assert dumped["options"] == []
    assert dumped["is_deleted"] is False


def test_admin_kit_detail_returns_raw_stock_without_available() -> None:
    schema = AdminKitProductDetailOut.model_validate(
        {
            "id": 4,
            "name": "库存为零的套装",
            "product_type": _product_type("kit", "拼豆套装"),
            "description": None,
            "status": _status("offline", "已下架"),
            "images": [],
            "price": Decimal("99.9"),
            "stock": 0,
            "created_at": NOW,
            "updated_at": NOW,
            "is_deleted": True,
        }
    )

    dumped = schema.model_dump(mode="json")

    assert dumped["price"] == "99.90"
    assert dumped["stock"] == 0
    assert "available" not in dumped
    assert dumped["is_deleted"] is True
