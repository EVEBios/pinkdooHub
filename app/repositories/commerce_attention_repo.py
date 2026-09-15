"""订单与桌台提醒的聚合、稳定分页和批量快照读取。"""

from datetime import datetime

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q, Subquery
from tortoise.queryset import QuerySet

from app.common.enums.order import OrderStatus
from app.common.enums.wallet import RefundStatus
from app.models.attention import AttentionEvent
from app.models.order import Order
from app.models.payment import Refund
from app.models.table_session import TableSession


class CommerceAttentionRepository:
    def _unread_orders(self, user_id: int | None, db: BaseDBAsyncClient):
        return AttentionEvent.filter(user_id=user_id, read_at=None, order_id__not_isnull=True).using_db(db).values("order_id")

    def _unread_sessions(self, user_id: int | None, db: BaseDBAsyncClient):
        return AttentionEvent.filter(user_id=user_id, read_at=None, order_id=None, session_id__not_isnull=True).using_db(db).values("session_id")

    def _awaiting(self, now: datetime, db: BaseDBAsyncClient) -> QuerySet[TableSession]:
        # 等于付款截止时刻仍允许可信付款；strict > 才失效，与付款校验一致。
        return TableSession.filter(status="awaiting_payment", payment_deadline_at__gte=now, order__status=OrderStatus.PENDING).using_db(db)

    def order_query(self, *, user_id: int | None, view: str, now: datetime, using_db: BaseDBAsyncClient) -> QuerySet[Order]:
        awaiting_orders = self._awaiting(now, using_db).filter(order_id__not_isnull=True).values("order_id")
        pending = Q(status=OrderStatus.PENDING) & ~Q(id__in=Subquery(awaiting_orders))
        refunds = Refund.filter(status__in=[RefundStatus.PENDING, RefundStatus.SUCCEEDED]).using_db(using_db).values("order_id")
        fulfillment = Q(status=OrderStatus.PAID) & ~Q(id__in=Subquery(refunds))
        query = Order.all().using_db(using_db)
        if user_id is not None:
            query = query.filter(user_id=user_id)
        unread = Q(id__in=Subquery(self._unread_orders(user_id, using_db)))
        if view == "pending":
            condition = pending
        elif view == "fulfillment":
            condition = fulfillment
        elif view == "unread":
            condition = unread
        else:
            condition = pending | (fulfillment if user_id is None else unread)
        return query.filter(condition)

    def session_query(self, *, user_id: int | None, view: str, now: datetime, using_db: BaseDBAsyncClient) -> QuerySet[TableSession]:
        query = TableSession.all().using_db(using_db)
        if user_id is not None:
            query = query.filter(user_id=user_id)
        awaiting = Q(id__in=Subquery(self._awaiting(now, using_db).values("id")))
        unread = Q(id__in=Subquery(self._unread_sessions(user_id, using_db)))
        if view == "pending" or user_id is None:
            condition = awaiting
        elif view == "unread":
            condition = unread
        else:
            condition = awaiting | unread
        return query.filter(condition)

    async def counts(self, *, user_id: int | None, now: datetime, using_db: BaseDBAsyncClient) -> dict[str, int]:
        args = dict(user_id=user_id, now=now, using_db=using_db)
        return {
            "order_pending": await self.order_query(view="pending", **args).count(),
            "order_fulfillment": await self.order_query(view="fulfillment", **args).count() if user_id is None else 0,
            "order_unread": await self.order_query(view="unread", **args).count() if user_id is not None else 0,
            "order_total": await self.order_query(view="all", **args).count(),
            "table_pending": await self.session_query(view="pending", **args).count(),
            "table_unread": await self.session_query(view="unread", **args).count() if user_id is not None else 0,
            "table_total": await self.session_query(view="all", **args).count(),
        }

    async def list_items(self, *, user_id: int | None, scope: str, view: str, now: datetime,
                         page: int, page_size: int, using_db: BaseDBAsyncClient,
                         include_all_sessions: bool = False) -> tuple[list[Order] | list[TableSession], int, list[AttentionEvent], list[TableSession]]:
        args = dict(user_id=user_id, view=view, now=now, using_db=using_db)
        query = self.order_query(**args) if scope == "orders" else self.session_query(**args)
        if include_all_sessions:
            if user_id is None or scope != "tables":
                raise ValueError("Full session list requires a customer and tables scope")
            # 固定业务入口与提醒集合分开，已付款/已读不能使桌台记录消失。
            query = TableSession.filter(user_id=user_id).using_db(using_db)
        total = await query.count()
        query = query.order_by("-created_at", "-id").offset((page - 1) * page_size).limit(page_size)
        if scope == "tables":
            query = query.select_related("table", "order")
        items = list(await query)
        ids = [item.id for item in items]
        events = AttentionEvent.filter(user_id=user_id, read_at=None).using_db(using_db)
        if scope == "orders":
            events = events.filter(order_id__in=ids)
            sessions = await TableSession.filter(order_id__in=ids, status="active", table_release_at__gt=now).using_db(using_db)
        else:
            events = events.filter(session_id__in=ids, order_id=None)
            sessions = []
        return items, total, list(await events.order_by("id")), sessions

    async def order_events(self, order_id: int, user_id: int, *, using_db: BaseDBAsyncClient) -> list[AttentionEvent]:
        return await AttentionEvent.filter(order_id=order_id, user_id=user_id).using_db(using_db).select_related("session").order_by("id")

    async def session_events(self, session_no: str, user_id: int, *, using_db: BaseDBAsyncClient) -> list[AttentionEvent]:
        return await AttentionEvent.filter(session__session_no=session_no, user_id=user_id).using_db(using_db).select_related("session").order_by("id")
