"""Reservation 用户端、管理端与营业日响应白名单。"""

from datetime import date, datetime, timedelta
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from app.common.constants.product import (
    DAY_TYPE_LABELS,
    MIN_DURATION_MINUTES,
    MIN_PARTICIPANTS,
    PRODUCT_NAME_MAX_LENGTH,
)
from app.common.constants.reservation import (
    RESERVATION_BOOKING_WINDOW_DAYS,
    RESERVATION_CANCELLATION_REASON_LABELS,
    RESERVATION_CLOSE_TIME_VALUE,
    RESERVATION_CUSTOMER_MESSAGES,
    RESERVATION_LOCAL_TIME_PATTERN,
    RESERVATION_MINIMUM_LEAD_HOURS,
    RESERVATION_OPEN_TIME_VALUE,
    RESERVATION_REJECTION_REASON_LABELS,
    RESERVATION_SLOT_INTERVAL_MINUTES,
    RESERVATION_STATUS_LABELS,
    RESERVATION_TIMEZONE,
)
from app.common.constants.validation import (
    NICKNAME_MAX_LENGTH,
    NICKNAME_MIN_LENGTH,
    PHONE_PATTERN,
)
from app.common.enums.product import DayType
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationStatus,
)
from app.schemas.product_response import ProductPriceOut


def _require_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Response datetime must be a datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError("Response datetime must use UTC timezone")
    return value


ReservationUtcDatetimeOut = Annotated[datetime, BeforeValidator(_require_utc)]
ReservationLocalTimeOut = Annotated[
    str,
    Field(strict=True, pattern=RESERVATION_LOCAL_TIME_PATTERN),
]


class _ReservationOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


class ReservationStatusOut(_ReservationOut):
    value: ReservationStatus
    label: str = Field(strict=True, min_length=1)

    @model_validator(mode="after")
    def validate_pair(self) -> "ReservationStatusOut":
        if self.label != RESERVATION_STATUS_LABELS[self.value]:
            raise ValueError("Reservation status label does not match value")
        return self


class ReservationDayTypeOut(_ReservationOut):
    value: DayType
    label: str = Field(strict=True, min_length=1)

    @model_validator(mode="after")
    def validate_pair(self) -> "ReservationDayTypeOut":
        if self.label != DAY_TYPE_LABELS[self.value]:
            raise ValueError("Reservation day type label does not match value")
        return self


class ReservationRejectionReasonOut(_ReservationOut):
    value: ReservationRejectionReason
    label: str = Field(strict=True, min_length=1)

    @model_validator(mode="after")
    def validate_pair(self) -> "ReservationRejectionReasonOut":
        if self.label != RESERVATION_REJECTION_REASON_LABELS[self.value]:
            raise ValueError("Reservation rejection reason label does not match value")
        return self


class ReservationCancellationReasonOut(_ReservationOut):
    value: ReservationCancellationReason
    label: str = Field(strict=True, min_length=1)

    @model_validator(mode="after")
    def validate_pair(self) -> "ReservationCancellationReasonOut":
        if self.label != RESERVATION_CANCELLATION_REASON_LABELS[self.value]:
            raise ValueError(
                "Reservation cancellation reason label does not match value"
            )
        return self


class _ReservationBaseOut(_ReservationOut):
    id: int = Field(strict=True, gt=0)
    product_id: int = Field(strict=True, gt=0)
    experience_option_id: int = Field(strict=True, gt=0)
    product_name: str = Field(
        strict=True,
        min_length=1,
        max_length=PRODUCT_NAME_MAX_LENGTH,
    )
    duration_minutes: int = Field(strict=True, ge=MIN_DURATION_MINUTES)
    participants: int = Field(strict=True, ge=MIN_PARTICIPANTS)
    day_type: ReservationDayTypeOut
    price: ProductPriceOut
    status: ReservationStatusOut
    rejection_reason: ReservationRejectionReasonOut | None = None
    cancellation_reason: ReservationCancellationReasonOut | None = None
    customer_message: str = Field(strict=True, min_length=1)
    reservation_date: date
    start_time: ReservationLocalTimeOut
    end_time: str = Field(strict=True, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    scheduled_start_at: ReservationUtcDatetimeOut
    scheduled_end_at: ReservationUtcDatetimeOut
    cancellation_deadline_at: ReservationUtcDatetimeOut
    confirmed_at: ReservationUtcDatetimeOut | None = None
    rejected_at: ReservationUtcDatetimeOut | None = None
    cancelled_at: ReservationUtcDatetimeOut | None = None
    created_at: ReservationUtcDatetimeOut
    updated_at: ReservationUtcDatetimeOut

    @model_validator(mode="after")
    def validate_state_and_times(self) -> "_ReservationBaseOut":
        if self.scheduled_end_at <= self.scheduled_start_at:
            raise ValueError("Reservation end must be later than start")
        if self.cancellation_deadline_at != self.scheduled_start_at - timedelta(
            hours=RESERVATION_MINIMUM_LEAD_HOURS
        ):
            raise ValueError("Cancellation deadline does not match reservation start")

        status = self.status.value
        if status is ReservationStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.rejection_reason,
                    self.cancellation_reason,
                    self.confirmed_at,
                    self.rejected_at,
                    self.cancelled_at,
                )
            ):
                raise ValueError("Pending reservation contains terminal state fields")
            expected_message = RESERVATION_CUSTOMER_MESSAGES[status]
        elif status is ReservationStatus.CONFIRMED:
            if (
                self.confirmed_at is None
                or self.rejection_reason is not None
                or self.cancellation_reason is not None
                or self.rejected_at is not None
                or self.cancelled_at is not None
            ):
                raise ValueError("Confirmed reservation state fields are inconsistent")
            expected_message = RESERVATION_CUSTOMER_MESSAGES[status]
        elif status is ReservationStatus.REJECTED:
            if (
                self.rejection_reason is None
                or self.rejection_reason.value
                is not ReservationRejectionReason.NO_CAPACITY
                or self.rejected_at is None
                or self.cancellation_reason is not None
                or self.confirmed_at is not None
                or self.cancelled_at is not None
            ):
                raise ValueError("Rejected reservation state fields are inconsistent")
            expected_message = RESERVATION_CUSTOMER_MESSAGES[status]
        else:
            if (
                self.cancellation_reason is None
                or self.cancelled_at is None
                or self.rejection_reason is not None
                or self.rejected_at is not None
            ):
                raise ValueError("Cancelled reservation state fields are inconsistent")
            expected_message = RESERVATION_CUSTOMER_MESSAGES[
                self.cancellation_reason.value
            ]
        if self.customer_message != expected_message:
            raise ValueError("Customer message does not match reservation state")
        return self


class ReservationOut(_ReservationBaseOut):
    """用户端列表、详情和状态变迁响应，不包含任何 User 字段。"""


class AdminReservationListItemOut(_ReservationBaseOut):
    """管理端列表额外包含当前用户摘要和后端掩码手机号。"""

    user_id: int = Field(strict=True, gt=0)
    user_nickname: str = Field(
        strict=True,
        min_length=NICKNAME_MIN_LENGTH,
        max_length=NICKNAME_MAX_LENGTH,
    )
    user_phone_masked: str | None = Field(default=None, strict=True)


class AdminReservationDetailOut(_ReservationBaseOut):
    """管理端详情返回当前完整手机号；该字段不是预约快照。"""

    user_id: int = Field(strict=True, gt=0)
    user_nickname: str = Field(
        strict=True,
        min_length=NICKNAME_MIN_LENGTH,
        max_length=NICKNAME_MAX_LENGTH,
    )
    user_phone: str | None = Field(default=None, strict=True, pattern=PHONE_PATTERN)


class ReservationBookingDateOut(_ReservationOut):
    """一个可预约上海本地日期及其半小时时段。"""

    date: date
    day_type: ReservationDayTypeOut
    start_times: list[ReservationLocalTimeOut] = Field(min_length=1)


class ReservationBookingOptionsOut(_ReservationOut):
    """服务端生成的当前 Option 可预约日期/时间选择集。"""

    experience_option_id: int = Field(strict=True, gt=0)
    product_id: int = Field(strict=True, gt=0)
    product_name: str = Field(
        strict=True,
        min_length=1,
        max_length=PRODUCT_NAME_MAX_LENGTH,
    )
    duration_minutes: int = Field(strict=True, ge=MIN_DURATION_MINUTES)
    participants: int = Field(strict=True, ge=MIN_PARTICIPANTS)
    day_type: ReservationDayTypeOut
    price: ProductPriceOut
    timezone: str = Field(strict=True, pattern=rf"^{RESERVATION_TIMEZONE}$")
    server_now: ReservationUtcDatetimeOut
    booking_window_end_date: date
    minimum_lead_hours: int = Field(
        default=RESERVATION_MINIMUM_LEAD_HOURS,
        strict=True,
        ge=RESERVATION_MINIMUM_LEAD_HOURS,
        le=RESERVATION_MINIMUM_LEAD_HOURS,
    )
    slot_interval_minutes: int = Field(
        default=RESERVATION_SLOT_INTERVAL_MINUTES,
        strict=True,
        ge=RESERVATION_SLOT_INTERVAL_MINUTES,
        le=RESERVATION_SLOT_INTERVAL_MINUTES,
    )
    booking_window_days: int = Field(
        default=RESERVATION_BOOKING_WINDOW_DAYS,
        strict=True,
        ge=RESERVATION_BOOKING_WINDOW_DAYS,
        le=RESERVATION_BOOKING_WINDOW_DAYS,
    )
    opens_at: str = Field(default=RESERVATION_OPEN_TIME_VALUE, strict=True)
    closes_at: str = Field(default=RESERVATION_CLOSE_TIME_VALUE, strict=True)
    dates: list[ReservationBookingDateOut]


class StoreBusinessDayOut(_ReservationOut):
    id: int = Field(strict=True, gt=0)
    business_date: date
    is_closed: bool = Field(strict=True)
    created_at: ReservationUtcDatetimeOut
    updated_at: ReservationUtcDatetimeOut


class StoreClosureMutationOut(StoreBusinessDayOut):
    newly_cancelled_count: int = Field(strict=True, ge=0)
    cancelled_pending_count: int = Field(strict=True, ge=0)
    cancelled_confirmed_count: int = Field(strict=True, ge=0)
    is_replay: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_counts(self) -> "StoreClosureMutationOut":
        if self.newly_cancelled_count != (
            self.cancelled_pending_count + self.cancelled_confirmed_count
        ):
            raise ValueError("Store closure cancellation counts do not add up")
        if self.is_replay and self.newly_cancelled_count != 0:
            raise ValueError("Store closure replay cannot cancel reservations")
        return self
