"""Reservation 模块业务边界、展示 Registry 与审计常量。"""

from datetime import time

from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationStatus,
    ReservationWeekday,
)

# 门店营业日历
RESERVATION_TIMEZONE = "Asia/Shanghai"
RESERVATION_OPEN_TIME = time(hour=11)
RESERVATION_CLOSE_TIME = time(hour=20)
RESERVATION_OPEN_TIME_VALUE = "11:00"
RESERVATION_CLOSE_TIME_VALUE = "20:00"
DEFAULT_RESERVATION_WEEKLY_CLOSED_WEEKDAY = ReservationWeekday.MONDAY
RESERVATION_WEEKDAY_NUMBERS = {
    ReservationWeekday.MONDAY: 0,
    ReservationWeekday.TUESDAY: 1,
    ReservationWeekday.WEDNESDAY: 2,
    ReservationWeekday.THURSDAY: 3,
    ReservationWeekday.FRIDAY: 4,
    ReservationWeekday.SATURDAY: 5,
    ReservationWeekday.SUNDAY: 6,
}
RESERVATION_WEEKDAY_LABELS = {
    ReservationWeekday.MONDAY: "周一",
    ReservationWeekday.TUESDAY: "周二",
    ReservationWeekday.WEDNESDAY: "周三",
    ReservationWeekday.THURSDAY: "周四",
    ReservationWeekday.FRIDAY: "周五",
    ReservationWeekday.SATURDAY: "周六",
    ReservationWeekday.SUNDAY: "周日",
}
RESERVATION_MINIMUM_LEAD_HOURS = 3
RESERVATION_SLOT_INTERVAL_MINUTES = 30
RESERVATION_BOOKING_WINDOW_DAYS = 30

# Model / Schema 字段边界
RESERVATION_ENUM_MAX_LENGTH = 32
RESERVATION_LOCAL_TIME_PATTERN = r"^(?:[01]\d|2[0-3]):(?:00|30)$"

# API 展示 Registry
RESERVATION_STATUS_LABELS = {
    ReservationStatus.PENDING: "待门店确认",
    ReservationStatus.CONFIRMED: "已确认",
    ReservationStatus.REJECTED: "未能确认",
    ReservationStatus.CANCELLED: "已取消",
}
RESERVATION_REJECTION_REASON_LABELS = {
    ReservationRejectionReason.NO_CAPACITY: "当前时段无空位",
}
RESERVATION_CANCELLATION_REASON_LABELS = {
    ReservationCancellationReason.CUSTOMER_REQUEST: "顾客取消",
    ReservationCancellationReason.STORE_CLOSED: "门店店休",
}
RESERVATION_CUSTOMER_MESSAGES = {
    ReservationStatus.PENDING: "预约已提交，正在等待门店确认。",
    ReservationStatus.CONFIRMED: (
        "预约已确认，请按预约时间到店。费用以预约时价格为准，"
        "到店支付。"
    ),
    ReservationStatus.REJECTED: (
        "很抱歉，您选择的时段当前已无空位，本次预约未能确认。"
        "您可以选择其他日期或时段重新预约。"
    ),
    ReservationCancellationReason.CUSTOMER_REQUEST: (
        "本次预约已取消。您可以选择其他日期或时段重新预约。"
    ),
    ReservationCancellationReason.STORE_CLOSED: (
        "门店当天休息，本次预约已由门店取消。给您带来不便，"
        "敬请谅解；"
        "您可以选择其他日期重新预约，如需帮助请联系门店。"
    ),
}

# 顺序审计契约
RESERVATION_AUDIT_TARGET_TYPE = "reservation"
STORE_BUSINESS_DAY_AUDIT_TARGET_TYPE = "store_business_day"
RESERVATION_SETTINGS_AUDIT_TARGET_TYPE = "reservation_settings"
RESERVATION_AUDIT_ACTION_CREATE = "CREATE_RESERVATION"
RESERVATION_AUDIT_ACTION_CONFIRM = "CONFIRM_RESERVATION"
RESERVATION_AUDIT_ACTION_REJECT = "REJECT_RESERVATION"
RESERVATION_AUDIT_ACTION_CANCEL = "CANCEL_RESERVATION"
STORE_BUSINESS_DAY_AUDIT_ACTION_CLOSE = "CLOSE_STORE_BUSINESS_DAY"
STORE_BUSINESS_DAY_AUDIT_ACTION_REOPEN = "REOPEN_STORE_BUSINESS_DAY"
RESERVATION_SETTINGS_AUDIT_ACTION_UPDATE_WEEKLY_CLOSED_DAY = (
    "UPDATE_WEEKLY_CLOSED_DAY"
)

# 状态冲突载荷中的稳定操作名
RESERVATION_OPERATION_CONFIRM = "confirm"
RESERVATION_OPERATION_REJECT = "reject"
RESERVATION_OPERATION_CANCEL = "cancel"

# 只对 MySQL 瞬态锁错误重试完整事务
RESERVATION_RETRYABLE_MYSQL_ERROR_CODES = frozenset({1205, 1213})
RESERVATION_TRANSACTION_MAX_ATTEMPTS = 3
