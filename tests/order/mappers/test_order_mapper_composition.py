"""Order Mapper 列表、详情、状态与字段隔离组合测试。"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.mappers.order import (
    map_admin_order_detail,
    map_admin_order_page,
    map_order_detail,
    map_order_page,
    map_order_status_response,
)
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType
from app.common.pagination import Page


NOW = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)
ORDER_NO = "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC"


def _item(item_id: int = 1001, *, order_id: int = 101) -> SimpleNamespace:
    return SimpleNamespace(
        id=item_id,
        order_id=order_id,
        product_id=1,
        experience_option_id=11,
        product_name="订单快照商品",
        option_duration_minutes=60,
        option_participants=1,
        option_day_type=DayType.WEEKDAY,
        product_price=Decimal("99.00"),
        quantity=2,
        subtotal=Decimal("198.00"),
    )


def _order(*, with_items: bool, item_count: int = 1) -> SimpleNamespace:
    user = SimpleNamespace(
        id=7,
        nickname="Alice",
        username="private-user",
        phone="13800138000",
        password="must-not-leak",
    )
    return SimpleNamespace(
        id=101,
        order_no=ORDER_NO,
        user_id=7,
        user=user,
        total_amount=Decimal("198.00"),
        status=OrderStatus.PENDING,
        remark="周五晚上到店",
        items=[_item()] if with_items else [],
        item_count=item_count,
        created_at=NOW,
        updated_at=NOW,
        token="must-not-leak",
    )


def test_user_and_admin_pages_preserve_metadata_and_isolate_fields() -> None:
    page = Page(items=[_order(with_items=False)], total=21, page=2, page_size=20, pages=2)

    user_data = map_order_page(page).model_dump(mode="json")
    admin_data = map_admin_order_page(page).model_dump(mode="json")

    assert user_data == {
        "items": [
            {
                "id": 101,
                "order_no": ORDER_NO,
                "status": {"value": "pending", "label": "待支付"},
                "total_amount": "198.00",
                "item_count": 1,
                "created_at": "2026-08-13T10:30:00Z",
                "updated_at": "2026-08-13T10:30:00Z",
            }
        ],
        "total": 21,
        "page": 2,
        "page_size": 20,
        "pages": 2,
    }
    assert admin_data["items"][0]["user_id"] == 7
    assert admin_data["items"][0]["user_nickname"] == "Alice"
    assert not (
        {"username", "phone", "password", "token", "remark", "items"}
        & admin_data["items"][0].keys()
    )


def test_user_and_admin_details_have_distinct_safe_projections() -> None:
    order = _order(with_items=True)

    user_data = map_order_detail(order).model_dump(mode="json")
    admin_data = map_admin_order_detail(order).model_dump(mode="json")

    assert set(user_data) == {
        "id",
        "order_no",
        "status",
        "total_amount",
        "remark",
        "items",
        "created_at",
        "updated_at",
    }
    assert admin_data["user_id"] == 7
    assert admin_data["user_nickname"] == "Alice"
    assert not ({"username", "phone", "password", "token"} & admin_data.keys())
    assert "item_count" not in user_data
    assert "item_count" not in admin_data
    assert user_data["items"][0]["product_price"] == "99.00"


def test_status_response_is_lightweight_and_uses_latest_status() -> None:
    order = _order(with_items=False)
    order.status = OrderStatus.PAID

    assert map_order_status_response(order).model_dump(mode="json") == {
        "id": 101,
        "order_no": ORDER_NO,
        "status": {"value": "paid", "label": "已支付"},
        "updated_at": "2026-08-13T10:30:00Z",
    }


def test_detail_rejects_item_from_another_order() -> None:
    order = _order(with_items=True)
    order.items[0].order_id = 999

    with pytest.raises(ValueError, match="different order"):
        map_order_detail(order)
