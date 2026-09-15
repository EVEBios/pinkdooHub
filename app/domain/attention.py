"""桌台独立结束的安全结果快照；不查询、不写库。"""

from datetime import datetime
from typing import TypedDict

from app.common.enums.attention import AttentionEventType
from app.common.enums.table_session import TableSessionCloseReason


class SessionClosedEvent(TypedDict):
    event_type: AttentionEventType
    user_id: int
    order_id: None
    session_id: int
    message: str
    occurred_at: datetime


def session_closed_event(*, user_id: int | None, session_id: int,
                         reason: TableSessionCloseReason, closed_at: datetime) -> SessionClosedEvent | None:
    if user_id is None:
        return None
    outcomes = {
        TableSessionCloseReason.PAYMENT_TIMEOUT: (
            AttentionEventType.SESSION_PAYMENT_TIMEOUT,
            "占台已超时，本次桌台已释放；当时订单尚未付款，请查看关联订单的最新状态。",
        ),
        TableSessionCloseReason.TIME_EXPIRED: (
            AttentionEventType.SESSION_TIME_EXPIRED,
            "本次体验及缓冲时间已结束，桌台已释放。",
        ),
        TableSessionCloseReason.ADMIN_RELEASED: (
            AttentionEventType.SESSION_ADMIN_RELEASED,
            "门店已释放本次桌台；订单及付款状态请查看关联订单。",
        ),
    }
    result = outcomes.get(reason)
    if result is None:
        return None
    return SessionClosedEvent(event_type=result[0], user_id=user_id, order_id=None,
                              session_id=session_id, message=result[1], occurred_at=closed_at)
