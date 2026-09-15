"""派生待办查询与追加记录；不在读取时生成任务或修改预约。"""
from datetime import datetime
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Subquery
from tortoise.functions import Max
from tortoise.queryset import QuerySet
from app.common.enums.reservation_followup import FOLLOWUP_COMPLETED, FollowupKind, FollowupOutcome
from app.models.reservation import Reservation
from app.models.reservation_followup import ReservationFollowup


class ReservationFollowupRepository:
    def queue(self, kind: FollowupKind, completed: bool, now: datetime, db: BaseDBAsyncClient) -> QuerySet[Reservation]:
        done = ReservationFollowup.filter(kind=kind, outcome__in=FOLLOWUP_COMPLETED).using_db(db).values("reservation_id")
        query = Reservation.all().using_db(db)
        if completed:
            return query.filter(id__in=Subquery(done))
        if kind == FollowupKind.CONTACT:
            query = query.filter(status="cancelled", cancellation_reason="store_closed")
        else:
            query = query.filter(status="pending", scheduled_start_at__lte=now)
        return query.exclude(id__in=Subquery(done))

    async def count(self, kind: FollowupKind, now: datetime, *, using_db: BaseDBAsyncClient) -> int:
        return await self.queue(kind, False, now, using_db).count()

    async def list_queue(self, kind: FollowupKind, completed: bool, now: datetime, page: int, page_size: int, *, using_db: BaseDBAsyncClient) -> tuple[list[Reservation], int, dict[int, ReservationFollowup]]:
        query = self.queue(kind, completed, now, using_db)
        total = await query.count()
        items = await query.select_related("user").order_by("scheduled_start_at", "id").offset((page - 1) * page_size).limit(page_size)
        latest_ids = ReservationFollowup.filter(kind=kind, reservation_id__in=[item.id for item in items]).using_db(using_db).group_by("reservation_id").annotate(last_id=Max("id")).values("last_id")
        latest = await ReservationFollowup.filter(id__in=Subquery(latest_ids)).using_db(using_db)
        return items, total, {item.reservation_id: item for item in latest}

    async def latest(self, reservation_id: int, kind: FollowupKind, *, using_db: BaseDBAsyncClient, lock: bool = False) -> ReservationFollowup | None:
        query = ReservationFollowup.filter(reservation_id=reservation_id, kind=kind).using_db(using_db).order_by("-revision")
        if lock:
            query = query.select_for_update()
        return await query.first()

    async def replay(self, reservation_id: int, kind: FollowupKind, key: str, *, using_db: BaseDBAsyncClient) -> ReservationFollowup | None:
        return await ReservationFollowup.filter(reservation_id=reservation_id, kind=kind, request_key=key).using_db(using_db).select_for_update().first()

    async def append(self, reservation_id: int, kind: FollowupKind, outcome: FollowupOutcome, note: str, revision: int, key: str, operator_id: int, *, using_db: BaseDBAsyncClient) -> ReservationFollowup:
        return await ReservationFollowup.create(reservation_id=reservation_id, kind=kind, outcome=outcome, note=note, revision=revision, request_key=key, operator_id=operator_id, using_db=using_db)

    async def history(self, reservation_id: int, kind: FollowupKind, page: int, page_size: int, *, using_db: BaseDBAsyncClient) -> tuple[list[ReservationFollowup], int]:
        query = ReservationFollowup.filter(reservation_id=reservation_id, kind=kind).using_db(using_db)
        total = await query.count()
        items = await query.order_by("-revision").offset((page - 1) * page_size).limit(page_size)
        return items, total
