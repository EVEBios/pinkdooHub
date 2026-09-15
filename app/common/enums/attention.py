"""站内结果事件与预约待办视图。"""

from enum import Enum


class AttentionEventType(str, Enum):
    ORDER_ASSISTED_WALLET_PAID = "order_assisted_wallet_paid"
    ORDER_WALLET_REFUNDED = "order_wallet_refunded"
    ORDER_MANUAL_REFUNDED = "order_manual_refunded"
    WALLET_ADJUSTED = "wallet_adjusted"
    ORDER_MANUAL_PAID = "order_manual_paid"
    ORDER_WALLET_PAID = "order_wallet_paid"
    ORDER_COMPLETED = "order_completed"
    SESSION_PAYMENT_TIMEOUT = "session_payment_timeout"
    SESSION_TIME_EXPIRED = "session_time_expired"
    SESSION_ADMIN_RELEASED = "session_admin_released"
    RESERVATION_CONFIRMED = "reservation_confirmed"
    RESERVATION_REJECTED = "reservation_rejected"
    RESERVATION_STORE_CLOSED = "reservation_store_closed"
    RESERVATION_CUSTOMER_CANCELLED = "reservation_customer_cancelled"


class ReservationAttentionView(str, Enum):
    ACTIONABLE = "actionable"
    UNREAD = "unread"
    OVERDUE = "overdue"
