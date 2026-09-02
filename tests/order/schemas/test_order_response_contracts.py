"""Order 组合响应与用户/管理字段隔离契约测试。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from app.common.pagination import Page
from app.schemas.order_response import (
    AdminOrderDetailOut,
    AdminOrderListItemOut,
    OrderDetailOut,
    OrderListItemOut,
    OrderStatusOut,
)
from tests.support.order_response import (
    admin_detail,
    admin_list_item,
    status_out,
    user_detail,
    user_list_item,
)


def test_user_list_item_serializes_exact_whitelist() -> None:
    payload = {
        **user_list_item(),
        "user_id": 7,
        "user_nickname": "Alice",
        "remark": "secret",
        "items": [],
        "password": "secret",
    }

    schema = OrderListItemOut.model_validate(payload)

    assert schema.model_dump(mode="json") == {
        "id": 101,
        "order_no": "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
        "total_amount": "198.00",
        "status": {"value": "pending", "label": "待支付"},
        "item_count": 1,
        "created_at": "2026-08-13T10:30:00Z",
        "updated_at": "2026-08-13T10:30:00Z",
    }


def test_admin_list_item_adds_only_safe_user_fields() -> None:
    payload = {
        **admin_list_item(),
        "username": "alice",
        "phone": "13800138000",
        "password": "secret",
        "token": "token",
    }

    dumped = AdminOrderListItemOut.model_validate(payload).model_dump(
        mode="json"
    )

    assert dumped["user_id"] == 7
    assert dumped["user_nickname"] == "Alice"
    assert not ({"username", "phone", "password", "token"} & dumped.keys())


def test_user_detail_serializes_exact_whitelist_without_user_or_item_count() -> None:
    payload = {
        **admin_detail(),
        "item_count": 1,
        "username": "alice",
        "phone": "13800138000",
    }

    dumped = OrderDetailOut.model_validate(payload).model_dump(mode="json")

    assert set(dumped) == {
        "id",
        "order_no",
        "total_amount",
        "status",
        "remark",
        "items",
        "created_at",
        "updated_at",
    }
    assert not (
        {"user_id", "user_nickname", "username", "phone", "item_count"}
        & dumped.keys()
    )


def test_admin_detail_adds_only_safe_user_fields() -> None:
    payload = {
        **admin_detail(),
        "username": "alice",
        "phone": "13800138000",
        "password": "secret",
    }

    dumped = AdminOrderDetailOut.model_validate(payload).model_dump(
        mode="json"
    )

    assert dumped["user_id"] == 7
    assert dumped["user_nickname"] == "Alice"
    assert not ({"username", "phone", "password"} & dumped.keys())


def test_detail_reads_attributes_and_filters_internal_fields() -> None:
    source = SimpleNamespace(**user_detail(), user_id=7, internal=True)

    dumped = OrderDetailOut.model_validate(source).model_dump(mode="json")

    assert dumped["total_amount"] == "198.00"
    assert "user_id" not in dumped
    assert "internal" not in dumped


def test_detail_rejects_total_that_does_not_match_items() -> None:
    payload = user_detail()
    payload["total_amount"] = Decimal("197.99")

    with pytest.raises(ValidationError) as exc_info:
        OrderDetailOut.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == ()


@pytest.mark.parametrize("items", [[], None])
def test_detail_requires_non_empty_items(items: object) -> None:
    payload = user_detail()
    payload["items"] = items

    with pytest.raises(ValidationError) as exc_info:
        OrderDetailOut.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == ("items",)


@pytest.mark.parametrize("remark", ["", "   ", 1])
def test_detail_rejects_invalid_remark(remark: object) -> None:
    payload = user_detail()
    payload["remark"] = remark

    with pytest.raises(ValidationError):
        OrderDetailOut.model_validate(payload)


@pytest.mark.parametrize(
    ("schema_type", "payload_factory", "field"),
    [
        (OrderListItemOut, user_list_item, "item_count"),
        (OrderListItemOut, user_list_item, "total_amount"),
        (AdminOrderListItemOut, admin_list_item, "user_id"),
        (AdminOrderListItemOut, admin_list_item, "user_nickname"),
        (OrderDetailOut, user_detail, "items"),
        (AdminOrderDetailOut, admin_detail, "user_id"),
        (AdminOrderDetailOut, admin_detail, "user_nickname"),
        (OrderStatusOut, status_out, "updated_at"),
    ],
)
def test_response_schemas_require_explicit_contract_fields(
    schema_type: type[Any],
    payload_factory: Callable[[], dict[str, Any]],
    field: str,
) -> None:
    payload = payload_factory()
    del payload[field]

    with pytest.raises(ValidationError) as exc_info:
        schema_type.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == (field,)


def test_order_list_page_preserves_strict_nested_contract() -> None:
    valid = user_list_item()
    invalid = user_list_item()
    invalid["total_amount"] = "198.00"

    with pytest.raises(ValidationError) as exc_info:
        Page[OrderListItemOut].model_validate(
            {
                "items": [valid, invalid],
                "total": 2,
                "page": 1,
                "page_size": 20,
                "pages": 1,
            }
        )

    assert exc_info.value.errors()[0]["loc"] == (
        "items",
        1,
        "total_amount",
    )


def test_status_out_is_lightweight_and_filters_other_fields() -> None:
    payload = {
        **status_out(),
        "total_amount": Decimal("198.00"),
        "items": [],
        "user_id": 7,
        "remark": "secret",
    }

    assert OrderStatusOut.model_validate(payload).model_dump(mode="json") == {
        "id": 101,
        "order_no": "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
        "status": {"value": "paid", "label": "已支付"},
        "updated_at": "2026-08-13T10:30:00Z",
    }


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 8, 13),
        datetime(
            2026,
            8,
            13,
            tzinfo=timezone(timedelta(hours=8)),
        ),
        "2026-08-13T10:30:00Z",
    ],
)
def test_order_responses_require_internal_utc_datetimes(value: object) -> None:
    payload = user_list_item()
    payload["created_at"] = value

    with pytest.raises(ValidationError):
        OrderListItemOut.model_validate(payload)
