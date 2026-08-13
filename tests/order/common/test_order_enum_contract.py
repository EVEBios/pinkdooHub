"""Order Enum、字段边界与 Registry 契约测试。"""

import json
import re
from enum import IntEnum

from app.common.constants.order import (
    KIT_ORDERING_REQUIRED_PHASE,
    ORDER_AUDIT_ACTION_CANCEL,
    ORDER_AUDIT_ACTION_COMPLETE,
    ORDER_AUDIT_ACTION_CREATE,
    ORDER_AUDIT_ACTION_MARK_PAID,
    ORDER_AUDIT_TARGET_TYPE,
    ORDER_AMOUNT_MAX,
    ORDER_ITEM_QUANTITY_MAX,
    ORDER_ITEM_QUANTITY_MIN,
    ORDER_ITEMS_MAX_COUNT,
    ORDER_ITEMS_MIN_COUNT,
    ORDER_NO_GENERATION_MAX_ATTEMPTS,
    ORDER_NO_LENGTH,
    ORDER_NO_PATTERN,
    ORDER_NO_PREFIX,
    ORDER_NO_ULID_LENGTH,
    ORDER_REMARK_MAX_LENGTH,
    ORDER_STATUS_LABELS,
    ORDER_STATUS_BY_VALUE,
    ORDER_STATUS_VALUES,
)
from app.common.constants.product import PRODUCT_PRICE_MAX
from app.common.enums.order import OrderStatus


def test_order_status_database_values_match_frozen_contract() -> None:
    """OrderStatus 必须保持 IntEnum 和固定数据库值。"""

    assert issubclass(OrderStatus, IntEnum)
    assert list(OrderStatus) == [
        OrderStatus.PENDING,
        OrderStatus.PAID,
        OrderStatus.CANCELLED,
        OrderStatus.COMPLETED,
    ]
    assert {item.name: item.value for item in OrderStatus} == {
        "PENDING": 0,
        "PAID": 1,
        "CANCELLED": 2,
        "COMPLETED": 3,
    }


def test_order_status_registry_is_complete_and_matches_api_contract() -> None:
    """数据库整数与 API value/label 通过完整 Registry 显式隔离。"""

    assert set(ORDER_STATUS_VALUES) == set(OrderStatus)
    assert set(ORDER_STATUS_LABELS) == set(OrderStatus)
    assert ORDER_STATUS_VALUES == {
        OrderStatus.PENDING: "pending",
        OrderStatus.PAID: "paid",
        OrderStatus.CANCELLED: "cancelled",
        OrderStatus.COMPLETED: "completed",
    }
    assert ORDER_STATUS_BY_VALUE == {
        "pending": OrderStatus.PENDING,
        "paid": OrderStatus.PAID,
        "cancelled": OrderStatus.CANCELLED,
        "completed": OrderStatus.COMPLETED,
    }
    assert ORDER_STATUS_LABELS == {
        OrderStatus.PENDING: "待支付",
        OrderStatus.PAID: "已支付",
        OrderStatus.CANCELLED: "已取消",
        OrderStatus.COMPLETED: "已完成",
    }


def test_order_status_int_enum_does_not_serialize_as_api_value() -> None:
    """固定 IntEnum 的 JSON 行为，防止 Mapper 误把 DB 值当 API value。"""

    assert json.loads(json.dumps({"status": OrderStatus.PENDING})) == {
        "status": 0,
    }
    assert ORDER_STATUS_VALUES[OrderStatus.PENDING] == "pending"


def test_order_request_boundary_constants_match_frozen_contract() -> None:
    assert ORDER_ITEMS_MIN_COUNT == 1
    assert ORDER_ITEMS_MAX_COUNT == 10
    assert ORDER_ITEM_QUANTITY_MIN == 1
    assert ORDER_ITEM_QUANTITY_MAX == 99
    assert ORDER_REMARK_MAX_LENGTH == 500


def test_request_bounds_cannot_overflow_order_decimal_capacity() -> None:
    """组合上限必须保证合法请求计算出的最大总额可存入 DECIMAL(10,2)。"""

    maximum_reachable_total = (
        PRODUCT_PRICE_MAX
        * ORDER_ITEM_QUANTITY_MAX
        * ORDER_ITEMS_MAX_COUNT
    )
    assert maximum_reachable_total == 98999010
    assert maximum_reachable_total <= ORDER_AMOUNT_MAX


def test_order_number_constants_match_frozen_contract() -> None:
    assert ORDER_NO_PREFIX == "OD"
    assert ORDER_NO_ULID_LENGTH == 26
    assert ORDER_NO_LENGTH == 28
    assert ORDER_NO_LENGTH == len(ORDER_NO_PREFIX) + ORDER_NO_ULID_LENGTH
    assert ORDER_NO_PATTERN == r"^OD[0-9A-HJKMNP-TV-Z]{26}$"
    assert ORDER_NO_GENERATION_MAX_ATTEMPTS == 3
    assert re.fullmatch(
        ORDER_NO_PATTERN,
        "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
    )


def test_order_number_pattern_rejects_invalid_values() -> None:
    invalid_values = [
        "01K2M7Y0J7A3N5Q8T4V6W9X2BC",  # 缺少 OD 前缀
        "od01K2M7Y0J7A3N5Q8T4V6W9X2BC",  # 小写前缀
        "OD01K2M7Y0J7A3N5Q8T4V6W9X2BI",  # ULID 排除 I
        "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC0",  # 超长
    ]

    assert all(
        re.fullmatch(ORDER_NO_PATTERN, value) is None
        for value in invalid_values
    )


def test_order_phase_and_audit_constants_match_frozen_contract() -> None:
    assert KIT_ORDERING_REQUIRED_PHASE == "4.3"
    assert ORDER_AUDIT_TARGET_TYPE == "order"
    assert {
        ORDER_AUDIT_ACTION_CREATE,
        ORDER_AUDIT_ACTION_CANCEL,
        ORDER_AUDIT_ACTION_MARK_PAID,
        ORDER_AUDIT_ACTION_COMPLETE,
    } == {
        "CREATE_ORDER",
        "CANCEL_ORDER",
        "MARK_ORDER_PAID",
        "COMPLETE_ORDER",
    }
