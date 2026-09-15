"""首页提醒的只读汇总、精确快照与阅读确认。"""

from collections.abc import Callable
from datetime import datetime, timezone

from tortoise.transactions import in_transaction

from app.common.exceptions.attention import AttentionNotFound
from app.common.constants.attention import ATTENTION_EVENT_LABELS
from app.common.constants.order import ORDER_STATUS_LABELS
from app.common.enums.order import OrderStatus
from app.common.exceptions.order import OrderNotFound
from app.common.exceptions.table_session import TableSessionNotFound
from app.repositories.commerce_attention_repo import CommerceAttentionRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.table_session_repo import TableSessionRepository
from app.schemas.attention import CommerceAttentionItemOut, CommerceAttentionEventOut, CommerceAttentionSnapshotOut
from app.common.exceptions.reservation import ReservationNotFound
from app.common.pagination import Page
from app.models.attention import AttentionEvent
from app.models.reservation import Reservation
from app.repositories.attention_repo import AttentionRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.wallet_attention_repo import WalletAttentionRepository
from app.schemas.attention import WalletAttentionTransactionOut


class AttentionService:
    def __init__(self, repository: AttentionRepository, reservations: ReservationRepository, *, now_provider: Callable[[], datetime] | None = None) -> None:
        self.commerce = CommerceAttentionRepository()
        self.orders = OrderRepository()
        self.tables = TableSessionRepository()
        self.wallet = WalletAttentionRepository()
        self.repository = repository
        self.reservations = reservations
        self._now = now_provider or (lambda: datetime.now(timezone.utc))

    async def summary(self, *, user_id: int | None) -> dict[str, object]:
        now = self._now()
        async with in_transaction() as connection:
            commerce = await self.commerce.counts(user_id=user_id, now=now, using_db=connection)
            unread = await self.repository.count_unread(user_id, using_db=connection)
            wallet_unread = await self.wallet.count_unread(user_id, using_db=connection) if user_id is not None else 0
            actionable = overdue = 0
            if user_id is None:
                actionable = await self.repository.count_pending(now=now, overdue=False, using_db=connection)
                overdue = await self.repository.count_pending(now=now, overdue=True, using_db=connection)
        # 共享结果只针对已取消预约，与 pending 审核集合互斥。
        return dict(server_now=now, reservation_actionable=actionable, reservation_unread=unread, reservation_overdue=overdue, reservation_total=actionable + unread, wallet_unread=wallet_unread, **commerce)

    async def list_wallet(self, *, user_id: int, view: str, page: int, page_size: int) -> Page[CommerceAttentionItemOut]:
        async with in_transaction() as connection:
            events, total = await self.wallet.list_events(user_id, unread=view == "unread", page=page, page_size=page_size, using_db=connection)
        return Page[CommerceAttentionItemOut](items=[CommerceAttentionItemOut(
            id=event.id, scope="wallet", reference=f"余额调整记录 #{event.id}",
            title=event.result_message, status_label=ATTENTION_EVENT_LABELS[event.event_type],
            order_id=None, session_no=None, unread=event.read_at is None,
            created_at=event.occurred_at, payment_deadline_at=None,
        ) for event in events], total=total, page=page, page_size=page_size, pages=(total + page_size - 1) // page_size)

    async def wallet_snapshot(self, *, user_id: int, event_id: int) -> CommerceAttentionSnapshotOut:
        async with in_transaction() as connection:
            result = await self.wallet.get_result(event_id, user_id, using_db=connection)
            if result is None:
                raise AttentionNotFound()
            event, transaction = result
            return CommerceAttentionSnapshotOut(server_now=self._now(), events=[CommerceAttentionEventOut(
                id=event.id, event_type=event.event_type, label=ATTENTION_EVENT_LABELS[event.event_type],
                occurred_at=event.occurred_at, message=event.result_message, session_no=None,
                read=event.read_at is not None, wallet_transaction=WalletAttentionTransactionOut(
                    id=transaction.id, change_amount=transaction.change_amount,
                    before_balance=transaction.before_balance, after_balance=transaction.after_balance,
                    reason=transaction.reason,
                ),
            )])

    async def list_reservations(self, *, user_id: int | None, view: str, page: int, page_size: int) -> Page[Reservation]:
        async with in_transaction() as connection:
            return await self.repository.list_reservations(user_id=user_id, view=view, now=self._now(), page=page, page_size=page_size, using_db=connection)

    async def reservation_snapshot(self, reservation_id: int, *, user_id: int | None) -> tuple[Reservation, list[AttentionEvent], datetime]:
        async with in_transaction() as connection:
            # 与所有预约转态使用同一个锁点，避免旧详情搭配新事件后误清。
            reservation = await self.reservations.get_reservation_for_update(reservation_id, user_id=user_id, using_db=connection)
            if reservation is None:
                raise ReservationNotFound()
            events = await self.repository.get_events(reservation_id, user_id, using_db=connection)
            return reservation, events, self._now()

    async def mark_read(self, ids: list[int], *, user_id: int | None, reader_id: int) -> None:
        async with in_transaction() as connection:
            events = await self.repository.get_for_read(ids, user_id, using_db=connection)
            if len(events) != len(set(ids)):
                raise AttentionNotFound()
            # 只更新明确列出的事件，重复确认保留首次阅读者和时间。
            await self.repository.mark_read(ids, reader_id=reader_id, now=self._now(), using_db=connection)

    async def list_commerce(self, *, user_id: int | None, scope: str, view: str,
                            page: int, page_size: int, include_all_sessions: bool = False) -> Page[CommerceAttentionItemOut]:
        now = self._now()
        async with in_transaction() as connection:
            items, total, events, active = await self.commerce.list_items(
                user_id=user_id, scope=scope, view=view, now=now, page=page,
                page_size=page_size, using_db=connection, include_all_sessions=include_all_sessions,
            )
            unread_ids = {event.order_id if scope == "orders" else event.session_id for event in events}
            active_orders = {session.order_id for session in active}
            result = []
            for item in items:
                if scope == "orders":
                    status = OrderStatus(item.status)
                    label = ("服务中" if item.id in active_orders else "待履约") if status == OrderStatus.PAID and user_id is None else ORDER_STATUS_LABELS[status]
                    result.append(CommerceAttentionItemOut(
                        id=item.id, scope="orders", reference=item.order_no,
                        title=f"订单 · ¥{item.total_amount:.2f}", status_label=label,
                        order_id=item.id, session_no=None, unread=item.id in unread_ids,
                        created_at=item.created_at, payment_deadline_at=None,
                    ))
                else:
                    if item.status == "active" and item.table_release_at is not None and now < item.table_release_at:
                        label = "体验中"
                    elif item.status == "awaiting_payment" and item.payment_deadline_at is not None and now <= item.payment_deadline_at:
                        label = "待付款"
                    else:
                        label = "本次桌台已结束"
                    result.append(CommerceAttentionItemOut(
                        id=item.id, scope="tables", reference=item.session_no,
                        title=item.table.display_name, status_label=label,
                        order_id=item.order_id, session_no=item.session_no,
                        unread=item.id in unread_ids, created_at=item.created_at,
                        payment_deadline_at=item.payment_deadline_at,
                    ))
        return Page[CommerceAttentionItemOut](items=result, total=total, page=page, page_size=page_size,
                                               pages=(total + page_size - 1) // page_size)

    async def commerce_snapshot(self, *, user_id: int, order_id: int | None = None,
                                session_no: str | None = None) -> CommerceAttentionSnapshotOut:
        async with in_transaction() as connection:
            if order_id is not None:
                order = await self.orders.get_order_detail(order_id, user_id=user_id, using_db=connection)
                if order is None:
                    raise OrderNotFound()
                events = await self.commerce.order_events(order_id, user_id, using_db=connection)
            else:
                session = await self.tables.get_session_detail_by_no(session_no, using_db=connection)
                if session is None or session.user_id != user_id:
                    raise TableSessionNotFound()
                events = await self.commerce.session_events(session_no, user_id, using_db=connection)
            # 每条结果有完整不可变摘要，展示后仅确认所列事件，不以最新业务状态覆盖旧结果。
            return CommerceAttentionSnapshotOut(server_now=self._now(), events=[
                CommerceAttentionEventOut(id=event.id, event_type=event.event_type,
                    label=ATTENTION_EVENT_LABELS[event.event_type], message=event.result_message,
                    occurred_at=event.occurred_at, read=event.read_at is not None,
                    session_no=event.session.session_no if event.session_id is not None else None)
                for event in events
            ])
