"""站内结果持久化与预约提醒投影查询。"""

from datetime import datetime

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Subquery
from tortoise.functions import Max

from app.common.enums.attention import AttentionEventType
from app.common.pagination import Page
from app.models.attention import AttentionEvent
from app.models.reservation import Reservation


class AttentionRepository:
    async def create_reservation_events(
        self,
        recipients: list[tuple[int, int | None]],
        *,
        event_type: AttentionEventType,
        occurred_at: datetime,
        using_db: BaseDBAsyncClient,
    ) -> None:
        """调用者已持有预约锁；状态机保证同一事件仅首次转态时写入。"""
        if not recipients:
            return
        await AttentionEvent.bulk_create([
            AttentionEvent(
                event_key=f"reservation:{reservation_id}:{event_type.value}",
                event_type=event_type,
                reservation_id=reservation_id,
                user_id=user_id,
                occurred_at=occurred_at,
            )
            for reservation_id, user_id in recipients
        ], using_db=using_db)

    async def count_unread(self, user_id: int | None, *, using_db: BaseDBAsyncClient) -> int:
        ids = AttentionEvent.filter(user_id=user_id, read_at=None).using_db(using_db).values("reservation_id")
        return await Reservation.filter(id__in=Subquery(ids)).using_db(using_db).count()

    async def count_pending(self, *, now: datetime, overdue: bool, using_db: BaseDBAsyncClient) -> int:
        query = Reservation.filter(status="pending").using_db(using_db)
        query = query.filter(scheduled_start_at__lte=now) if overdue else query.filter(scheduled_start_at__gt=now)
        return await query.count()

    async def list_reservations(
        self, *, user_id: int | None, view: str, now: datetime,
        page: int, page_size: int, using_db: BaseDBAsyncClient,
    ) -> Page[Reservation]:
        query = Reservation.all().using_db(using_db)
        if user_id is not None:
            query = query.filter(user_id=user_id)
        if view == "unread":
            ids = AttentionEvent.filter(user_id=user_id, read_at=None).using_db(using_db).values("reservation_id")
            query = query.filter(id__in=Subquery(ids)).annotate(last_event_id=Max("attention_events__id"))
            ordering = ("-last_event_id", "-id")
        else:
            query = query.filter(status="pending")
            query = query.filter(scheduled_start_at__lte=now) if view == "overdue" else query.filter(scheduled_start_at__gt=now)
            ordering = ("scheduled_start_at", "id")
        total = await query.count()
        items = await query.select_related("user").order_by(*ordering).offset((page - 1) * page_size).limit(page_size)
        return Page[Reservation](items=list(items), total=total, page=page, page_size=page_size, pages=(total + page_size - 1) // page_size)

    async def get_events(self, reservation_id: int, user_id: int | None, *, using_db: BaseDBAsyncClient) -> list[AttentionEvent]:
        return await AttentionEvent.filter(reservation_id=reservation_id, user_id=user_id, read_at=None).using_db(using_db).order_by("id")

    async def get_for_read(self, ids: list[int], user_id: int | None, *, using_db: BaseDBAsyncClient) -> list[AttentionEvent]:
        return await AttentionEvent.filter(id__in=ids, user_id=user_id).using_db(using_db).order_by("id").select_for_update()

    async def mark_read(self, ids: list[int], *, reader_id: int, now: datetime, using_db: BaseDBAsyncClient) -> None:
        await AttentionEvent.filter(id__in=ids, read_at=None).using_db(using_db).update(read_at=now, read_by_id=reader_id, updated_at=now)

    async def create_commerce_event(
        self, *, event_type: AttentionEventType, user_id: int,
        order_id: int | None, session_id: int | None, message: str,
        occurred_at: datetime, using_db: BaseDBAsyncClient,
    ) -> None:
        """业务锁内首次成功转态写入；订单结果合并相关桌台，不另记一件。"""
        scope = f"order:{order_id}" if order_id is not None else f"session:{session_id}"
        await AttentionEvent.create(
            event_key=f"{scope}:{event_type.value}", event_type=event_type,
            user_id=user_id, order_id=order_id, session_id=session_id,
            result_message=message, occurred_at=occurred_at, using_db=using_db,
        )

    async def create_wallet_event(
        self, *, transaction_id: int, user_id: int, message: str,
        occurred_at: datetime, using_db: BaseDBAsyncClient,
    ) -> None:
        """不可变流水与唯一事件键一一对应；不复制完整资金流水或内部备注。"""
        await AttentionEvent.create(
            event_key=f"wallet_transaction:{transaction_id}:wallet_adjusted",
            event_type=AttentionEventType.WALLET_ADJUSTED,
            user_id=user_id, result_message=message, occurred_at=occurred_at,
            using_db=using_db,
        )
