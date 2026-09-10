"""桌台二维码开台模块枚举。"""

from enum import Enum


class TableSessionStatus(str, Enum):
    AWAITING_PAYMENT = "awaiting_payment"
    ACTIVE = "active"
    CLOSED = "closed"


class TableSessionCloseReason(str, Enum):
    PAYMENT_TIMEOUT = "payment_timeout"
    TIME_EXPIRED = "time_expired"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_COMPLETED = "order_completed"
    REFUNDED = "refunded"
    ADMIN_RELEASED = "admin_released"


class TableTimerPhase(str, Enum):
    EXPERIENCE = "experience"
    GRACE = "grace"
    ENDED = "ended"


class AdminTableState(str, Enum):
    AVAILABLE = "available"
    AWAITING_PAYMENT = "awaiting_payment"
    ACTIVE = "active"
    DISABLED = "disabled"
