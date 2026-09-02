"""Order 响应 Schema 测试数据工厂。"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

NOW = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)
ORDER_NO = "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC"


def order_status(
    value: str = "pending",
    label: str = "待支付",
) -> dict[str, str]:
    return {"value": value, "label": label}


def order_item(
    *,
    item_id: int = 1001,
    option_id: int = 10,
    price: Decimal = Decimal("99.00"),
    quantity: int = 2,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "product_id": 1,
        "experience_option_id": option_id,
        "product_name": "拼豆体验",
        "option_duration_minutes": 60,
        "option_participants": 1,
        "option_day_type": {
            "value": "weekday",
            "label": "工作日",
        },
        "product_price": price,
        "quantity": quantity,
        "subtotal": price * quantity,
    }


def user_list_item() -> dict[str, Any]:
    return {
        "id": 101,
        "order_no": ORDER_NO,
        "total_amount": Decimal("198.00"),
        "status": order_status(),
        "item_count": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }


def admin_list_item() -> dict[str, Any]:
    return {
        **user_list_item(),
        "user_id": 7,
        "user_nickname": "Alice",
    }


def user_detail() -> dict[str, Any]:
    item = order_item()
    return {
        "id": 101,
        "order_no": ORDER_NO,
        "total_amount": item["subtotal"],
        "status": order_status(),
        "remark": "周五晚上到店",
        "items": [item],
        "created_at": NOW,
        "updated_at": NOW,
    }


def admin_detail() -> dict[str, Any]:
    return {
        **user_detail(),
        "user_id": 7,
        "user_nickname": "Alice",
    }


def status_out() -> dict[str, Any]:
    return {
        "id": 101,
        "order_no": ORDER_NO,
        "status": order_status("paid", "已支付"),
        "updated_at": NOW,
    }
