"""Inventory 模块命名业务异常。"""

from app.common.constants.inventory import (
    INVENTORY_CHANGE_MAX,
    INVENTORY_CHANGE_MIN,
    INVENTORY_STOCK_MAX,
    INVENTORY_STOCK_MIN,
)
from app.common.enums.product import KitKind
from app.core.exceptions import BusinessException, ConflictException


def _validate_integer(value: int, *, field_name: str) -> None:
    """保护异常载荷，拒绝 bool 和非整数。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")


def _validate_positive_integer(value: int, *, field_name: str) -> None:
    _validate_integer(value, field_name=field_name)
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


class InventoryKitKindMismatch(BusinessException):
    """库存端点与 Kit 的余额权威类型不匹配。"""

    def __init__(self, *, expected: KitKind, actual: KitKind) -> None:
        super().__init__(
            code=40031,
            message="Kit kind does not match this inventory operation",
            data={"expected": expected.value, "actual": actual.value},
        )


class InsufficientStock(ConflictException):
    """Kit 可售库存小于本次订单请求数量。"""

    def __init__(
        self,
        *,
        product_id: int,
        requested_quantity: int,
        kit_color_id: int | None = None,
    ) -> None:
        _validate_positive_integer(product_id, field_name="product_id")
        _validate_positive_integer(
            requested_quantity,
            field_name="requested_quantity",
        )
        if kit_color_id is not None:
            _validate_positive_integer(kit_color_id, field_name="kit_color_id")
        data = {
            "product_id": product_id,
            "requested_quantity": requested_quantity,
        }
        if kit_color_id is not None:
            data["kit_color_id"] = kit_color_id
        super().__init__(
            code=40931,
            message="Insufficient stock",
            data=data,
        )


class InventoryBalanceExceeded(ConflictException):
    """管理员调整后的余额超出冻结范围。"""

    def __init__(
        self,
        *,
        product_id: int,
        before_quantity: int,
        change_quantity: int,
        kit_color_id: int | None = None,
    ) -> None:
        _validate_positive_integer(product_id, field_name="product_id")
        if kit_color_id is not None:
            _validate_positive_integer(kit_color_id, field_name="kit_color_id")
        _validate_integer(before_quantity, field_name="before_quantity")
        _validate_integer(change_quantity, field_name="change_quantity")
        if not INVENTORY_STOCK_MIN <= before_quantity <= INVENTORY_STOCK_MAX:
            raise ValueError("before_quantity must be within the stock range")
        if not INVENTORY_CHANGE_MIN <= change_quantity <= INVENTORY_CHANGE_MAX:
            raise ValueError("change_quantity must be within the change range")
        if change_quantity == 0:
            raise ValueError("change_quantity must not be zero")
        after_quantity = before_quantity + change_quantity
        if INVENTORY_STOCK_MIN <= after_quantity <= INVENTORY_STOCK_MAX:
            raise ValueError("adjusted balance must exceed the stock range")

        data = {
            "product_id": product_id,
            "before_quantity": before_quantity,
            "change_quantity": change_quantity,
            "minimum": INVENTORY_STOCK_MIN,
            "maximum": INVENTORY_STOCK_MAX,
        }
        if kit_color_id is not None:
            data["kit_color_id"] = kit_color_id
        super().__init__(
            code=40932,
            message="Inventory balance exceeds the allowed range",
            data=data,
        )


class InventoryTransactionConflict(ConflictException):
    """幂等键已经绑定到另一个规范化请求。"""

    def __init__(self) -> None:
        super().__init__(
            code=40933,
            message="Inventory idempotency key conflicts with another request",
        )
