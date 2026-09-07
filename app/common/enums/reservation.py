"""Reservation 模块字符串枚举。"""

from enum import Enum


class ReservationWeekday(str, Enum):
    """可配置的每周固定店休日。"""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class ReservationStatus(str, Enum):
    """预约排期状态；与订单支付状态相互独立。"""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ReservationRejectionReason(str, Enum):
    """门店拒绝预约的受控原因。"""

    NO_CAPACITY = "no_capacity"


class ReservationCancellationReason(str, Enum):
    """取消预约的受控原因。"""

    CUSTOMER_REQUEST = "customer_request"
    STORE_CLOSED = "store_closed"


class ReservationScheduleUnavailableReason(str, Enum):
    """预约时间不可用的稳定机器原因。"""

    MINIMUM_LEAD_TIME = "minimum_lead_time"
    OUTSIDE_BOOKING_WINDOW = "outside_booking_window"
    INVALID_SLOT_INCREMENT = "invalid_slot_increment"
    OUTSIDE_BUSINESS_HOURS = "outside_business_hours"
    WEEKLY_CLOSED = "weekly_closed"
    STORE_CLOSED = "store_closed"
    OPTION_DAY_TYPE_MISMATCH = "option_day_type_mismatch"


class StoreClosureDateUnavailableReason(str, Enum):
    """自定义店休日期不可操作的稳定机器原因。"""

    PAST_DATE = "past_date"
    WEEKLY_CLOSED = "weekly_closed"
