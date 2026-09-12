"""桌台开台资格与状态转换的纯业务校验。"""

from datetime import datetime

from app.common.enums.order import OrderStatus
from app.common.enums.table_session import TableSessionStatus
from app.common.exceptions.table_session import (
    TableOrderIneligible,
    TablePaymentWindowExpired,
    TableSessionStatusConflict,
)
from app.repositories.table_session_repo import ExperienceItemSnapshot


def validate_order_eligible(
    *,
    order_id: int,
    order_status: int,
    has_settlement: bool,
    items: list[ExperienceItemSnapshot],
) -> tuple[int, ...]:
    """校验订单可开台并返回 Experience 时长，忽略 Kit 与 quantity。"""

    if order_status != OrderStatus.PENDING.value:
        raise TableOrderIneligible(order_id=order_id, reason="order_not_pending")
    if has_settlement:
        raise TableOrderIneligible(
            order_id=order_id,
            reason="order_already_settled",
        )
    experience_items = [item for item in items if item.is_experience]
    if not experience_items:
        raise TableOrderIneligible(
            order_id=order_id,
            reason="no_experience_item",
        )
    durations: list[int] = []
    for item in experience_items:
        duration = item.duration_minutes
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise TableOrderIneligible(
                order_id=order_id,
                reason="invalid_experience_duration_snapshot",
            )
        durations.append(duration)
    return tuple(durations)


def validate_payment_activation(
    *,
    session_no: str,
    status: TableSessionStatus,
    succeeded_at: datetime,
    payment_deadline_at: datetime,
) -> None:
    if succeeded_at > payment_deadline_at:
        raise TablePaymentWindowExpired(
            session_no=session_no,
            payment_deadline_at=payment_deadline_at,
        )
    if status is not TableSessionStatus.AWAITING_PAYMENT:
        raise TableSessionStatusConflict(
            operation="activate",
            current_status=status,
            required_status=TableSessionStatus.AWAITING_PAYMENT,
        )
