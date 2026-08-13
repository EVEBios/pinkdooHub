"""Order Mapper 状态、日期类型与 Item 快照原子映射测试。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.mappers.order import (
    map_order_day_type,
    map_order_item,
    map_order_status_value,
)
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (OrderStatus.PENDING, {"value": "pending", "label": "待支付"}),
        (1, {"value": "paid", "label": "已支付"}),
        (OrderStatus.CANCELLED, {"value": "cancelled", "label": "已取消"}),
        (3, {"value": "completed", "label": "已完成"}),
    ],
)
def test_order_status_mapper_uses_authoritative_registry(
    value: OrderStatus | int,
    expected: dict[str, str],
) -> None:
    assert map_order_status_value(value).model_dump(mode="json") == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (DayType.WEEKDAY, {"value": "weekday", "label": "工作日"}),
        ("holiday", {"value": "holiday", "label": "节假日"}),
    ],
)
def test_order_day_type_mapper_uses_authoritative_registry(
    value: DayType | str,
    expected: dict[str, str],
) -> None:
    assert map_order_day_type(value).model_dump(mode="json") == expected


def _item(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 1001,
        "order_id": 101,
        "product_id": 1,
        "experience_option_id": 11,
        "product_name": "数据库快照商品",
        "option_duration_minutes": 90,
        "option_participants": 2,
        "option_day_type": DayType.HOLIDAY,
        "product_price": Decimal("99.90"),
        "quantity": 2,
        "subtotal": Decimal("199.80"),
        "password": "must-not-leak",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_order_item_mapper_serializes_exact_snapshot_whitelist() -> None:
    result = map_order_item(_item()).model_dump(mode="json")

    assert result == {
        "id": 1001,
        "product_id": 1,
        "experience_option_id": 11,
        "product_name": "数据库快照商品",
        "option_duration_minutes": 90,
        "option_participants": 2,
        "option_day_type": {"value": "holiday", "label": "节假日"},
        "product_price": "99.90",
        "quantity": 2,
        "subtotal": "199.80",
    }
    assert "order_id" not in result
    assert "password" not in result


@pytest.mark.parametrize(
    "overrides",
    [
        {"experience_option_id": None},
        {"option_duration_minutes": None},
        {"option_participants": None},
        {"option_day_type": None},
        {"subtotal": Decimal("199.79")},
        {"product_price": "99.90"},
    ],
)
def test_order_item_mapper_rejects_incomplete_or_inconsistent_snapshot(
    overrides: dict[str, object],
) -> None:
    with pytest.raises((ValueError, ValidationError)):
        map_order_item(_item(**overrides))
