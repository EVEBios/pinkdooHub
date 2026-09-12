"""桌台计时与自动关闭的无 I/O 领域计算。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from app.common.constants.table_session import TABLE_TIMER_BUFFER_MINUTES
from app.common.enums.table_session import (
    TableSessionCloseReason,
    TableSessionStatus,
    TableTimerPhase,
)


@dataclass(frozen=True, slots=True)
class TimerSpec:
    duration_minutes: int
    buffer_minutes: int
    started_at: datetime
    service_ends_at: datetime
    grace_ends_at: datetime


@dataclass(frozen=True, slots=True)
class AutomaticClose:
    reason: TableSessionCloseReason
    closed_at: datetime


def distinct_experience_durations(
    durations: Iterable[int | None],
) -> tuple[int, ...]:
    """校验并返回去重、升序的 Experience 时长快照。"""

    normalized: set[int] = set()
    for duration in durations:
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise ValueError("experience duration snapshot must be positive")
        normalized.add(duration)
    if not normalized:
        raise ValueError("at least one experience duration is required")
    return tuple(sorted(normalized))


def build_timer_specs(
    durations: Iterable[int | None],
    *,
    started_at: datetime,
) -> tuple[TimerSpec, ...]:
    """按不同分钟生成同时开始的 10 分钟缓冲计时快照。"""

    specs: list[TimerSpec] = []
    for duration in distinct_experience_durations(durations):
        service_ends_at = started_at + timedelta(minutes=duration)
        specs.append(
            TimerSpec(
                duration_minutes=duration,
                buffer_minutes=TABLE_TIMER_BUFFER_MINUTES,
                started_at=started_at,
                service_ends_at=service_ends_at,
                grace_ends_at=service_ends_at
                + timedelta(minutes=TABLE_TIMER_BUFFER_MINUTES),
            )
        )
    return tuple(specs)


def automatic_close_for(
    *,
    status: TableSessionStatus,
    now: datetime,
    payment_deadline_at: datetime,
    table_release_at: datetime | None,
) -> AutomaticClose | None:
    """根据绝对边界推导首次自动关闭事实。"""

    if status is TableSessionStatus.AWAITING_PAYMENT:
        if now > payment_deadline_at:
            return AutomaticClose(
                reason=TableSessionCloseReason.PAYMENT_TIMEOUT,
                closed_at=payment_deadline_at,
            )
        return None
    if (
        status is TableSessionStatus.ACTIVE
        and table_release_at is not None
        and now >= table_release_at
    ):
        return AutomaticClose(
            reason=TableSessionCloseReason.TIME_EXPIRED,
            closed_at=table_release_at,
        )
    return None

def timer_phase(
    *,
    status: TableSessionStatus,
    now: datetime,
    service_ends_at: datetime,
    grace_ends_at: datetime,
) -> TableTimerPhase:
    if status is TableSessionStatus.CLOSED or now >= grace_ends_at:
        return TableTimerPhase.ENDED
    if now >= service_ends_at:
        return TableTimerPhase.GRACE
    return TableTimerPhase.EXPERIENCE


def timer_ended_at(
    *,
    status: TableSessionStatus,
    now: datetime,
    grace_ends_at: datetime,
    closed_at: datetime | None,
) -> datetime | None:
    if status is TableSessionStatus.CLOSED and closed_at is not None:
        return min(grace_ends_at, closed_at)
    if now >= grace_ends_at:
        return grace_ends_at
    return None
