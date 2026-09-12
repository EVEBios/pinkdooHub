"""桌台二维码开台用户端与管理端响应白名单。"""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.common.constants.order import ORDER_NO_PATTERN
from app.common.constants.table_session import (
    TABLE_ADMIN_REASON_MAX_LENGTH,
    TABLE_CLOSE_REASON_LABELS,
    TABLE_DISPLAY_NAME_MAX_LENGTH,
    TABLE_NO_PATTERN,
    TABLE_PAYMENT_WINDOW_MINUTES,
    TABLE_SESSION_NO_PATTERN,
    TABLE_STATUS_LABELS,
    TABLE_TIMER_BUFFER_MINUTES,
    TABLE_TIMER_PHASE_LABELS,
)
from app.common.enums.table_session import (
    AdminTableState,
    TableSessionCloseReason,
    TableSessionStatus,
    TableTimerPhase,
)
from app.common.pagination import Page
from app.schemas.order_response import OrderAmountOut


def _require_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Response datetime must be a datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError("Response datetime must use UTC timezone")
    return value


TableUtcDatetimeOut = Annotated[datetime, BeforeValidator(_require_utc)]


class _TableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class TableEnumOut(_TableOut):
    value: str = Field(strict=True, min_length=1)
    label: str = Field(strict=True, min_length=1)


class TableSummaryOut(_TableOut):
    id: int = Field(strict=True, gt=0)
    table_no: str = Field(strict=True, pattern=TABLE_NO_PATTERN)
    display_name: str = Field(
        strict=True, min_length=1, max_length=TABLE_DISPLAY_NAME_MAX_LENGTH
    )
    is_enabled: bool = Field(strict=True)


class PublicTableCodeOut(_TableOut):
    table_no: str = Field(strict=True, pattern=TABLE_NO_PATTERN)
    display_name: str = Field(
        strict=True, min_length=1, max_length=TABLE_DISPLAY_NAME_MAX_LENGTH
    )
    is_enabled: bool = Field(strict=True)
    is_available: bool = Field(strict=True)


class EligibleDurationGroupOut(_TableOut):
    duration_minutes: int = Field(strict=True, gt=0)
    buffer_minutes: Literal[TABLE_TIMER_BUFFER_MINUTES]
    experience_item_count: int = Field(strict=True, gt=0)
    total_quantity: int = Field(strict=True, gt=0)


class EligibleOrderListItemOut(_TableOut):
    id: int = Field(strict=True, gt=0)
    order_no: str = Field(strict=True, pattern=ORDER_NO_PATTERN)
    total_amount: OrderAmountOut
    created_at: TableUtcDatetimeOut
    experience_item_count: int = Field(strict=True, gt=0)
    kit_item_count: int = Field(strict=True, ge=0)
    duration_groups: list[EligibleDurationGroupOut] = Field(min_length=1)


class TimerExperienceItemOut(_TableOut):
    order_item_id: int = Field(strict=True, gt=0)
    product_id: int = Field(strict=True, gt=0)
    product_name: str = Field(strict=True, min_length=1)
    quantity: int = Field(strict=True, gt=0)
    participants_per_unit: int | None = Field(default=None, strict=True, gt=0)
    total_participants: int | None = Field(default=None, strict=True, gt=0)


class TableSessionTimerOut(_TableOut):
    id: int = Field(strict=True, gt=0)
    duration_minutes: int = Field(strict=True, gt=0)
    buffer_minutes: Literal[TABLE_TIMER_BUFFER_MINUTES]
    started_at: TableUtcDatetimeOut
    service_ends_at: TableUtcDatetimeOut
    grace_ends_at: TableUtcDatetimeOut
    phase: TableEnumOut
    ended_at: TableUtcDatetimeOut | None = None
    experience_items: list[TimerExperienceItemOut] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_timer(self) -> "TableSessionTimerOut":
        if self.phase.value not in TABLE_TIMER_PHASE_LABELS:
            raise ValueError("invalid timer phase")
        if self.phase.label != TABLE_TIMER_PHASE_LABELS[self.phase.value]:
            raise ValueError("timer phase label mismatch")
        if self.service_ends_at != self.started_at + timedelta(
            minutes=self.duration_minutes
        ):
            raise ValueError("timer service end mismatch")
        if self.grace_ends_at != self.service_ends_at + timedelta(
            minutes=self.buffer_minutes
        ):
            raise ValueError("timer grace end mismatch")
        return self


class TableSessionOut(_TableOut):
    session_no: str = Field(strict=True, pattern=TABLE_SESSION_NO_PATTERN)
    table: TableSummaryOut
    order_id: int = Field(strict=True, gt=0)
    order_no: str = Field(strict=True, pattern=ORDER_NO_PATTERN)
    status: TableEnumOut
    claimed_at: TableUtcDatetimeOut
    payment_deadline_at: TableUtcDatetimeOut
    started_at: TableUtcDatetimeOut | None = None
    table_release_at: TableUtcDatetimeOut | None = None
    closed_at: TableUtcDatetimeOut | None = None
    close_reason: TableEnumOut | None = None
    timers: list[TableSessionTimerOut]
    server_now: TableUtcDatetimeOut

    @model_validator(mode="after")
    def validate_session(self) -> "TableSessionOut":
        if self.status.value not in TABLE_STATUS_LABELS:
            raise ValueError("invalid table session status")
        if self.status.label != TABLE_STATUS_LABELS[self.status.value]:
            raise ValueError("table session status label mismatch")
        if self.close_reason is not None:
            if self.close_reason.value not in TABLE_CLOSE_REASON_LABELS:
                raise ValueError("invalid table close reason")
            if (
                self.close_reason.label
                != TABLE_CLOSE_REASON_LABELS[self.close_reason.value]
            ):
                raise ValueError("table close reason label mismatch")
        if self.payment_deadline_at != self.claimed_at + timedelta(
            minutes=TABLE_PAYMENT_WINDOW_MINUTES
        ):
            raise ValueError("table payment deadline mismatch")
        status = TableSessionStatus(self.status.value)
        if status is TableSessionStatus.AWAITING_PAYMENT:
            if (
                self.started_at is not None
                or self.table_release_at is not None
                or self.closed_at is not None
                or self.close_reason is not None
                or self.timers
            ):
                raise ValueError("awaiting payment table session shape mismatch")
        elif status is TableSessionStatus.ACTIVE:
            if (
                self.started_at is None
                or self.table_release_at is None
                or self.closed_at is not None
                or self.close_reason is not None
                or not self.timers
            ):
                raise ValueError("active table session shape mismatch")
        elif self.closed_at is None or self.close_reason is None:
            raise ValueError("closed table session shape mismatch")
        if self.timers:
            if self.started_at is None or self.table_release_at is None:
                raise ValueError("timer parent timestamps are missing")
            if any(timer.started_at != self.started_at for timer in self.timers):
                raise ValueError("timer start does not match table session")
            if len({timer.duration_minutes for timer in self.timers}) != len(
                self.timers
            ):
                raise ValueError("duplicate table timer duration")
            if self.table_release_at != max(
                timer.grace_ends_at for timer in self.timers
            ):
                raise ValueError("table release timestamp mismatch")
        elif self.started_at is not None or self.table_release_at is not None:
            raise ValueError("table session timestamps require timers")
        return self


class AdminTableOut(TableSummaryOut):
    state: AdminTableState
    current_session_no: str | None = Field(
        default=None, pattern=TABLE_SESSION_NO_PATTERN
    )
    current_status: TableEnumOut | None = None
    current_order_no: str | None = Field(default=None, pattern=ORDER_NO_PATTERN)
    current_user_id: int | None = Field(default=None, strict=True, gt=0)
    claimed_at: TableUtcDatetimeOut | None = None
    payment_deadline_at: TableUtcDatetimeOut | None = None
    table_release_at: TableUtcDatetimeOut | None = None


class AdminTableListOut(_TableOut):
    items: list[AdminTableOut] = Field(max_length=30)
    server_now: TableUtcDatetimeOut


class AdminTableSessionListItemOut(_TableOut):
    session_no: str = Field(strict=True, pattern=TABLE_SESSION_NO_PATTERN)
    table: TableSummaryOut
    order_id: int = Field(strict=True, gt=0)
    order_no: str = Field(strict=True, pattern=ORDER_NO_PATTERN)
    user_id: int = Field(strict=True, gt=0)
    user_nickname: str = Field(strict=True, min_length=1)
    status: TableEnumOut
    close_reason: TableEnumOut | None = None
    timer_count: int = Field(strict=True, ge=0)
    minimum_duration_minutes: int | None = Field(default=None, strict=True, gt=0)
    maximum_duration_minutes: int | None = Field(default=None, strict=True, gt=0)
    claimed_at: TableUtcDatetimeOut
    payment_deadline_at: TableUtcDatetimeOut
    started_at: TableUtcDatetimeOut | None = None
    table_release_at: TableUtcDatetimeOut | None = None
    closed_at: TableUtcDatetimeOut | None = None

    @model_validator(mode="after")
    def validate_list_item(self) -> "AdminTableSessionListItemOut":
        if self.status.value not in TABLE_STATUS_LABELS:
            raise ValueError("invalid table session status")
        if self.status.label != TABLE_STATUS_LABELS[self.status.value]:
            raise ValueError("table session status label mismatch")
        if self.close_reason is not None:
            if self.close_reason.value not in TABLE_CLOSE_REASON_LABELS:
                raise ValueError("invalid table close reason")
            if (
                self.close_reason.label
                != TABLE_CLOSE_REASON_LABELS[self.close_reason.value]
            ):
                raise ValueError("table close reason label mismatch")
        has_timers = self.timer_count > 0
        has_range = (
            self.minimum_duration_minutes is not None
            and self.maximum_duration_minutes is not None
        )
        if has_timers != has_range:
            raise ValueError("table timer summary mismatch")
        if (
            has_range
            and self.minimum_duration_minutes > self.maximum_duration_minutes
        ):
            raise ValueError("table timer duration range mismatch")
        status = TableSessionStatus(self.status.value)
        if status is TableSessionStatus.AWAITING_PAYMENT:
            if (
                has_timers
                or self.started_at is not None
                or self.table_release_at is not None
                or self.closed_at is not None
                or self.close_reason is not None
            ):
                raise ValueError("awaiting payment list item shape mismatch")
        elif status is TableSessionStatus.ACTIVE:
            if (
                not has_timers
                or self.started_at is None
                or self.table_release_at is None
                or self.closed_at is not None
                or self.close_reason is not None
            ):
                raise ValueError("active list item shape mismatch")
        elif self.closed_at is None or self.close_reason is None:
            raise ValueError("closed list item shape mismatch")
        return self


class AdminTableSessionOut(TableSessionOut):
    user_id: int = Field(strict=True, gt=0)
    user_nickname: str = Field(strict=True, min_length=1)
    payment_id: int | None = Field(default=None, strict=True, gt=0)
    closed_by_user_id: int | None = Field(default=None, strict=True, gt=0)
    admin_close_reason: str | None = Field(
        default=None,
        strict=True,
        min_length=1,
        max_length=TABLE_ADMIN_REASON_MAX_LENGTH,
    )


EligibleOrderPageOut = Page[EligibleOrderListItemOut]
AdminTableSessionPageOut = Page[AdminTableSessionListItemOut]


def enum_out(value: TableSessionStatus | TableSessionCloseReason | TableTimerPhase) -> TableEnumOut:
    if isinstance(value, TableSessionStatus):
        label = TABLE_STATUS_LABELS[value.value]
    elif isinstance(value, TableSessionCloseReason):
        label = TABLE_CLOSE_REASON_LABELS[value.value]
    else:
        label = TABLE_TIMER_PHASE_LABELS[value.value]
    return TableEnumOut(value=value.value, label=label)
