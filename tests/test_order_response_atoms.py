"""Order 响应原子 Schema 契约测试。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.order_response import (
    OrderAmountOut,
    OrderDayTypeOut,
    OrderItemOut,
    OrderStatusValueOut,
    OrderUnitPriceOut,
)
from tests.support.order_response import order_item


class TestOrderAmountOut:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (Decimal("0.01"), "0.01"),
            (Decimal("99"), "99.00"),
            (Decimal("99.0"), "99.00"),
            (Decimal("99999999.99"), "99999999.99"),
        ],
    )
    def test_decimal_serializes_with_two_places(
        self,
        value: Decimal,
        expected: str,
    ) -> None:
        adapter = TypeAdapter(OrderAmountOut)
        validated = adapter.validate_python(value)

        assert adapter.dump_python(validated, mode="json") == expected

    @pytest.mark.parametrize(
        "value",
        [
            "99.00",
            99,
            99.0,
            Decimal("0.00"),
            Decimal("-1.00"),
            Decimal("100000000.00"),
            Decimal("1.001"),
        ],
    )
    def test_invalid_internal_amount_is_rejected(self, value: object) -> None:
        with pytest.raises(ValidationError):
            TypeAdapter(OrderAmountOut).validate_python(value)

    def test_serialization_schema_declares_fixed_string(self) -> None:
        schema = TypeAdapter(OrderAmountOut).json_schema(mode="serialization")

        assert schema["type"] == "string"
        assert schema["pattern"] == r"^\d+\.\d{2}$"


def test_order_unit_price_uses_product_price_upper_bound() -> None:
    adapter = TypeAdapter(OrderUnitPriceOut)

    assert adapter.dump_python(
        adapter.validate_python(Decimal("99999.00")),
        mode="json",
    ) == "99999.00"
    with pytest.raises(ValidationError):
        adapter.validate_python(Decimal("99999.01"))


@pytest.mark.parametrize(
    ("value", "label"),
    [
        ("pending", "待支付"),
        ("paid", "已支付"),
        ("cancelled", "已取消"),
        ("completed", "已完成"),
    ],
)
def test_order_status_value_out_accepts_exact_pairs(
    value: str,
    label: str,
) -> None:
    schema = OrderStatusValueOut.model_validate(
        {"value": value, "label": label, "internal": True}
    )

    assert schema.model_dump(mode="json") == {
        "value": value,
        "label": label,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"value": "pending", "label": "已支付"},
        {"value": 0, "label": "待支付"},
        {"value": "PENDING", "label": "待支付"},
        {"value": "pending", "label": ""},
    ],
)
def test_order_status_value_out_rejects_invalid_pairs(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        OrderStatusValueOut.model_validate(payload)


@pytest.mark.parametrize(
    ("value", "label"),
    [("weekday", "工作日"), ("holiday", "节假日")],
)
def test_order_day_type_out_accepts_exact_pairs(
    value: str,
    label: str,
) -> None:
    schema = OrderDayTypeOut.model_validate(
        {"value": value, "label": label}
    )

    assert schema.model_dump(mode="json") == {
        "value": value,
        "label": label,
    }


def test_order_day_type_out_rejects_mismatched_label() -> None:
    with pytest.raises(ValidationError):
        OrderDayTypeOut.model_validate(
            {"value": "weekday", "label": "节假日"}
        )


def test_order_item_out_serializes_snapshot_and_filters_internal_fields() -> None:
    payload = order_item()
    payload.update(
        {
            "order_id": 101,
            "is_deleted": False,
            "created_at": datetime(2026, 8, 13, tzinfo=timezone.utc),
        }
    )

    schema = OrderItemOut.model_validate(payload)

    assert schema.model_dump(mode="json") == {
        "id": 1001,
        "product_id": 1,
        "experience_option_id": 10,
        "product_name": "拼豆体验",
        "option_duration_minutes": 60,
        "option_participants": 1,
        "option_day_type": {
            "value": "weekday",
            "label": "工作日",
        },
        "product_price": "99.00",
        "quantity": 2,
        "subtotal": "198.00",
    }


def test_order_item_out_rejects_inconsistent_subtotal() -> None:
    payload = order_item()
    payload["subtotal"] = Decimal("197.99")

    with pytest.raises(ValidationError) as exc_info:
        OrderItemOut.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 0),
        ("product_id", True),
        ("experience_option_id", None),
        ("product_name", ""),
        ("option_duration_minutes", 0),
        ("option_participants", False),
        ("quantity", 0),
        ("quantity", 100),
        ("product_price", "99.00"),
        ("subtotal", 198.0),
    ],
)
def test_order_item_out_rejects_invalid_snapshot_fields(
    field: str,
    value: object,
) -> None:
    payload = order_item()
    payload[field] = value

    with pytest.raises(ValidationError):
        OrderItemOut.model_validate(payload)


def test_response_datetime_rejects_naive_or_non_utc_values() -> None:
    payload = order_item()
    assert OrderItemOut.model_validate(payload)

    from app.schemas.order_response import OrderStatusOut
    from tests.support.order_response import status_out

    for value in [
        datetime(2026, 8, 13),
        datetime(
            2026,
            8,
            13,
            tzinfo=timezone(timedelta(hours=8)),
        ),
        "2026-08-13T00:00:00Z",
    ]:
        status_payload = status_out()
        status_payload["updated_at"] = value
        with pytest.raises(ValidationError):
            OrderStatusOut.model_validate(status_payload)
