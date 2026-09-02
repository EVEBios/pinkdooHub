"""Order 模块命名业务异常。"""

from app.common.constants.order import ORDER_STATUS_VALUES
from app.common.enums.order import OrderStatus
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    UnprocessableEntityException,
)


def _validate_positive_id(value: int, *, field_name: str) -> None:
    """保护命名异常的数据载荷，避免产生无效资源 ID。"""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


class OrderNotFound(NotFoundException):
    """订单不存在或对当前用户不可见。"""

    def __init__(self) -> None:
        super().__init__(code=40411, message="Order not found")


class OrderStatusConflict(ConflictException):
    """订单当前状态不允许执行指定状态变迁。"""

    def __init__(
        self,
        *,
        operation: str,
        current_status: OrderStatus,
        required_status: OrderStatus,
    ) -> None:
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation must be a non-empty string")
        if not isinstance(current_status, OrderStatus):
            raise ValueError("current_status must be an OrderStatus")
        if not isinstance(required_status, OrderStatus):
            raise ValueError("required_status must be an OrderStatus")

        super().__init__(
            code=40921,
            message="Order status does not allow this operation",
            data={
                "operation": operation,
                "current_status": ORDER_STATUS_VALUES[current_status],
                "required_status": ORDER_STATUS_VALUES[required_status],
            },
        )


class OrderProductUnavailable(UnprocessableEntityException):
    """Product 不满足当前 Experience 或 Kit 下单条件。"""

    def __init__(self, *, product_id: int) -> None:
        _validate_positive_id(product_id, field_name="product_id")
        super().__init__(
            code=42231,
            message="Order product is unavailable",
            data={"product_id": product_id},
        )


class OrderOptionUnavailable(UnprocessableEntityException):
    """ExperienceOption 不存在、不可用或不属于指定 Product。"""

    def __init__(
        self,
        *,
        product_id: int,
        experience_option_id: int | None,
    ) -> None:
        _validate_positive_id(product_id, field_name="product_id")
        if experience_option_id is not None:
            _validate_positive_id(
                experience_option_id,
                field_name="experience_option_id",
            )
        super().__init__(
            code=42232,
            message="Order experience option is unavailable",
            data={
                "product_id": product_id,
                "experience_option_id": experience_option_id,
            },
        )
