"""Order 用户端与管理端查询 Schema 契约测试。"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.order import AdminOrderListQuery, OrderListQuery


@pytest.mark.parametrize(
    "status",
    ["pending", "paid", "cancelled", "completed"],
)
def test_user_order_query_accepts_api_status_values(status: str) -> None:
    schema = OrderListQuery.model_validate(
        {"page": "2", "page_size": "50", "status": status}
    )

    assert schema.model_dump() == {
        "page": 2,
        "page_size": 50,
        "status": status,
    }


@pytest.mark.parametrize("status", [0, "0", "PENDING", "draft", ""])
def test_user_order_query_rejects_database_or_unknown_status(
    status: object,
) -> None:
    with pytest.raises(ValidationError):
        OrderListQuery.model_validate({"status": status})


def test_user_order_query_rejects_admin_filters() -> None:
    with pytest.raises(ValidationError) as exc_info:
        OrderListQuery.model_validate({"user_id": "7"})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_admin_order_query_accepts_all_frozen_filters() -> None:
    schema = AdminOrderListQuery.model_validate(
        {
            "page": "1",
            "page_size": "20",
            "status": "paid",
            "order_no": "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
            "product_name": " 星空拼豆 ",
            "user_id": "7",
            "created_from": "2026-08-13T00:00:00Z",
            "created_to": "2026-08-14T00:00:00+00:00",
        }
    )

    assert schema.status == "paid"
    assert schema.product_name == "星空拼豆"
    assert schema.user_id == 7
    assert schema.created_from == datetime(
        2026,
        8,
        13,
        tzinfo=timezone.utc,
    )
    assert schema.created_to == datetime(
        2026,
        8,
        14,
        tzinfo=timezone.utc,
    )


@pytest.mark.parametrize(
    "order_no",
    [
        "01K2M7Y0J7A3N5Q8T4V6W9X2BC",
        "od01K2M7Y0J7A3N5Q8T4V6W9X2BC",
        "OD01K2M7Y0J7A3N5Q8T4V6W9X2BI",
    ],
)
def test_admin_order_query_rejects_invalid_order_number(
    order_no: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AdminOrderListQuery.model_validate({"order_no": order_no})

    assert exc_info.value.errors()[0]["loc"] == ("order_no",)


@pytest.mark.parametrize("product_name", ["", "   ", "拼" * 101])
def test_admin_order_query_rejects_invalid_product_name(
    product_name: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AdminOrderListQuery.model_validate({"product_name": product_name})

    assert exc_info.value.errors()[0]["loc"] == ("product_name",)


@pytest.mark.parametrize("user_id", ["0", "-1", "abc", 0, True])
def test_admin_order_query_rejects_invalid_user_id(user_id: object) -> None:
    with pytest.raises(ValidationError):
        AdminOrderListQuery.model_validate({"user_id": user_id})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("created_from", "2026-08-13T00:00:00"),
        ("created_to", "2026-08-14T08:00:00+08:00"),
    ],
)
def test_admin_order_query_requires_explicit_utc_datetime(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AdminOrderListQuery.model_validate({field: value})

    assert exc_info.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    ("created_from", "created_to"),
    [
        ("2026-08-13T00:00:00Z", "2026-08-13T00:00:00Z"),
        ("2026-08-14T00:00:00Z", "2026-08-13T00:00:00Z"),
    ],
)
def test_admin_order_query_requires_strictly_increasing_range(
    created_from: str,
    created_to: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AdminOrderListQuery.model_validate(
            {"created_from": created_from, "created_to": created_to}
        )

    assert exc_info.value.errors()[0]["loc"] == ()


def test_admin_order_query_allows_one_sided_time_range() -> None:
    lower = AdminOrderListQuery.model_validate(
        {"created_from": "2026-08-13T00:00:00Z"}
    )
    upper = AdminOrderListQuery.model_validate(
        {"created_to": "2026-08-14T00:00:00Z"}
    )

    assert lower.created_from is not None and lower.created_to is None
    assert upper.created_from is None and upper.created_to is not None


def test_admin_order_query_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        AdminOrderListQuery.model_validate({"sort_by": "created_at"})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
