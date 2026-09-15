"""Reservation 模块命名业务异常。"""

from app.common.enums.reservation import (
    ReservationScheduleUnavailableReason,
    ReservationStatus,
    StoreClosureDateUnavailableReason,
)
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    UnprocessableEntityException,
)


def _validate_positive_id(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


class ReservationNotFound(NotFoundException):
    """预约不存在或对当前用户不可见。"""

    def __init__(self) -> None:
        super().__init__(code=40451, message="Reservation not found")


class StoreClosureNotFound(NotFoundException):
    """目标日期当前没有自定义店休。"""

    def __init__(self) -> None:
        super().__init__(code=40452, message="Store closure not found")


class ReservationStatusConflict(ConflictException):
    """预约当前状态不允许执行指定状态变迁。"""

    def __init__(
        self,
        *,
        operation: str,
        current_status: ReservationStatus,
        allowed_statuses: tuple[ReservationStatus, ...],
    ) -> None:
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation must be a non-empty string")
        if not isinstance(current_status, ReservationStatus):
            raise ValueError("current_status must be a ReservationStatus")
        if not allowed_statuses or any(
            not isinstance(status, ReservationStatus)
            for status in allowed_statuses
        ):
            raise ValueError("allowed_statuses must contain ReservationStatus values")
        super().__init__(
            code=40951,
            message="Reservation status does not allow this operation",
            data={
                "operation": operation,
                "current_status": current_status.value,
                "allowed_statuses": [status.value for status in allowed_statuses],
            },
        )


class ReservationCancellationWindowClosed(ConflictException):
    """顾客已错过提前三小时取消窗口。"""

    def __init__(self) -> None:
        super().__init__(
            code=40952,
            message="Reservation cancellation window is closed",
        )


class ReservationOperationExpired(ConflictException):
    """预约已经开始，门店不能再确认或拒绝。"""

    def __init__(self) -> None:
        super().__init__(
            code=40953,
            message="Reservation operation is no longer available",
        )


class ReservationProductUnavailable(UnprocessableEntityException):
    """预约关联商品不可用。"""

    def __init__(self, *, product_id: int) -> None:
        _validate_positive_id(product_id, field_name="product_id")
        super().__init__(
            code=42251,
            message="Reservation product is unavailable",
            data={"product_id": product_id},
        )


class ReservationOptionUnavailable(UnprocessableEntityException):
    """体验 Option 不存在、已删除或不可预约。"""

    def __init__(self, *, experience_option_id: int) -> None:
        _validate_positive_id(
            experience_option_id,
            field_name="experience_option_id",
        )
        super().__init__(
            code=42252,
            message="Reservation experience option is unavailable",
            data={"experience_option_id": experience_option_id},
        )


class ReservationScheduleUnavailable(UnprocessableEntityException):
    """预约日历或时段不满足业务规则。"""

    def __init__(
        self,
        *,
        reason: ReservationScheduleUnavailableReason,
    ) -> None:
        if not isinstance(reason, ReservationScheduleUnavailableReason):
            raise ValueError(
                "reason must be a ReservationScheduleUnavailableReason"
            )
        super().__init__(
            code=42253,
            message="Reservation schedule is unavailable",
            data={"reason": reason.value},
        )


class ReservationPhoneRequired(UnprocessableEntityException):
    """当前账号缺少门店联系所需手机号。"""

    def __init__(self) -> None:
        super().__init__(
            code=42254,
            message="A current phone number is required to create a reservation",
        )


class StoreClosureDateUnavailable(UnprocessableEntityException):
    """自定义店休日期不可设置或恢复。"""

    def __init__(
        self,
        *,
        reason: StoreClosureDateUnavailableReason,
    ) -> None:
        if not isinstance(reason, StoreClosureDateUnavailableReason):
            raise ValueError(
                "reason must be a StoreClosureDateUnavailableReason"
            )
        super().__init__(
            code=42255,
            message="Store closure date is unavailable",
            data={"reason": reason.value},
        )
