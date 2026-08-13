"""Product 响应 Schema 测试数据工厂。"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel

Payload = dict[str, Any]
PayloadFactory = Callable[[], Payload]
ResponseSchema = type[BaseModel]

NOW = datetime(2026, 8, 9, 4, 0, tzinfo=timezone.utc)


def product_type(value: str, label: str) -> dict[str, str]:
    return {"value": value, "label": label}


def status(value: str = "draft", label: str = "草稿") -> dict[str, str]:
    return {"value": value, "label": label}


def product_image(image_id: int = 1) -> Payload:
    return {
        "id": image_id,
        "image_url": f"https://example.com/products/{image_id}.jpg",
        "is_cover": True,
        "sort": 0,
    }


def option_image(image_id: int = 20) -> Payload:
    return {
        "id": image_id,
        "image_url": f"https://example.com/options/{image_id}.jpg",
        "sort": 0,
    }


def dimensions() -> Payload:
    return {
        "durations": [{"value": 60, "label": "1小时"}],
        "participants": [{"value": 1, "label": "1人"}],
        "day_types": [{"value": "weekday", "label": "工作日"}],
    }


def option() -> Payload:
    return {
        "id": 11,
        "duration": {"value": 60, "label": "1小时"},
        "participants": {"value": 1, "label": "1人"},
        "day_type": {"value": "weekday", "label": "工作日"},
        "price": Decimal("299.00"),
        "images": [option_image()],
    }


def user_list_item() -> Payload:
    return {
        "id": 1,
        "name": "拼豆体验",
        "product_type": product_type("experience", "拼豆体验"),
        "cover_image": "https://example.com/products/1.jpg",
        "display_price": Decimal("299.00"),
    }


def admin_list_item() -> Payload:
    return {
        "id": 1,
        "name": "拼豆体验",
        "product_type": product_type("experience", "拼豆体验"),
        "status": status(),
        "cover_image": None,
        "display_price": None,
        "updated_at": NOW,
        "is_deleted": False,
    }


def user_experience() -> Payload:
    return {
        "id": 1,
        "name": "拼豆体验",
        "product_type": product_type("experience", "拼豆体验"),
        "description": "选择体验配置",
        "images": [product_image()],
        "dimensions": dimensions(),
        "options": [option()],
    }


def user_kit() -> Payload:
    return {
        "id": 2,
        "name": "拼豆套装",
        "product_type": product_type("kit", "拼豆套装"),
        "description": "适合新手入门",
        "images": [product_image(2)],
        "price": Decimal("599.00"),
        "stock": 20,
        "available": True,
    }


def admin_experience() -> Payload:
    return {
        "id": 3,
        "name": "未完成体验",
        "product_type": product_type("experience", "拼豆体验"),
        "description": None,
        "status": status(),
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


def admin_kit() -> Payload:
    return {
        "id": 4,
        "name": "待完善套装",
        "product_type": product_type("kit", "拼豆套装"),
        "description": None,
        "status": status(),
        "images": [],
        "price": Decimal("99.90"),
        "stock": 0,
        "created_at": NOW,
        "updated_at": NOW,
        "is_deleted": False,
    }


def set_nested(
    payload: Payload,
    path: tuple[str | int, ...],
    value: Any,
) -> None:
    current: Any = payload
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value
