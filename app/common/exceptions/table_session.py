"""桌台二维码开台模块命名业务异常。"""

from datetime import datetime

from app.common.constants.table_session import TABLE_ORDER_INELIGIBLE_REASONS
from app.common.enums.table_session import TableSessionStatus
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    TooManyRequestsException,
    UnprocessableEntityException,
)


class TableCodeNotFound(NotFoundException):
    def __init__(self) -> None:
        super().__init__(code=40461, message="Table code not found")


class TableSessionNotFound(NotFoundException):
    def __init__(self) -> None:
        super().__init__(code=40462, message="Table session not found")


class StoreTableNotFound(NotFoundException):
    def __init__(self) -> None:
        super().__init__(code=40463, message="Store table not found")


class TableUnavailable(ConflictException):
    def __init__(self, *, table_no: str, reason: str) -> None:
        if reason not in {"occupied", "disabled"}:
            raise ValueError("invalid table unavailable reason")
        super().__init__(
            code=40961,
            message="Table is unavailable",
            data={"table_no": table_no, "reason": reason},
        )


class TableSessionStatusConflict(ConflictException):
    def __init__(
        self,
        *,
        operation: str,
        current_status: TableSessionStatus,
        required_status: TableSessionStatus | str,
    ) -> None:
        required = (
            required_status.value
            if isinstance(required_status, TableSessionStatus)
            else required_status
        )
        super().__init__(
            code=40962,
            message="Table session status does not allow this operation",
            data={
                "operation": operation,
                "current_status": current_status.value,
                "required_status": required,
            },
        )


class UserTableSessionConflict(ConflictException):
    def __init__(self) -> None:
        super().__init__(
            code=40963,
            message="User already has an open table session",
        )


class OrderTableSessionConflict(ConflictException):
    def __init__(self, *, order_id: int) -> None:
        super().__init__(
            code=40964,
            message="Order already has an open table session",
            data={"order_id": order_id},
        )


class TableIdempotencyConflict(ConflictException):
    def __init__(self) -> None:
        super().__init__(
            code=40965,
            message="Table idempotency key conflicts with another request",
        )


class TablePaymentWindowExpired(ConflictException):
    def __init__(self, *, session_no: str, payment_deadline_at: datetime) -> None:
        super().__init__(
            code=40966,
            message="Table payment window has expired",
            data={
                "session_no": session_no,
                "payment_deadline_at": payment_deadline_at.isoformat(),
            },
        )


class TableOrderIneligible(UnprocessableEntityException):
    def __init__(self, *, order_id: int, reason: str) -> None:
        if reason not in TABLE_ORDER_INELIGIBLE_REASONS:
            raise ValueError("invalid table order ineligible reason")
        super().__init__(
            code=42261,
            message="Order is not eligible to open a table",
            data={"order_id": order_id, "reason": reason},
        )


class TableRateLimitExceeded(TooManyRequestsException):
    def __init__(self) -> None:
        super().__init__(code=42961, message="Too many table requests")
