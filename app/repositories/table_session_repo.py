"""固定桌台、开台会话、计时器与当前占用的数据访问。"""

from dataclasses import dataclass
from datetime import datetime

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.functions import Count, Max, Min
from tortoise.queryset import QuerySet

from app.common.enums.order import OrderStatus
from app.common.enums.table_session import TableSessionCloseReason, TableSessionStatus
from app.common.pagination import Page
from app.domain.table_session import TimerSpec
from app.models.order import Order
from app.models.order import OrderItem
from app.models.table_session import (
    StoreTable,
    TableOccupancy,
    TableSession,
    TableSessionTimer,
)


@dataclass(frozen=True, slots=True)
class TableSessionCreateData:
    session_no: str
    table_id: int
    user_id: int
    order_id: int
    claim_idempotency_key: str
    claim_request_fingerprint: str
    claimed_at: datetime
    payment_deadline_at: datetime


@dataclass(frozen=True, slots=True)
class ExperienceItemSnapshot:
    id: int
    product_id: int
    product_name: str
    quantity: int
    duration_minutes: int | None
    participants_per_unit: int | None
    is_experience: bool


def _session_detail_query() -> QuerySet[TableSession]:
    return (
        TableSession.all()
        .select_related("table", "order", "user", "payment", "closed_by_user")
        .prefetch_related("timers", "order__items")
    )


class TableSessionRepository:
    """只执行桌台领域持久化原语，不判断状态机或权限。"""

    async def get_table_by_qr_token(
        self,
        qr_token: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> StoreTable | None:
        query = StoreTable.filter(qr_token=qr_token)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_table_by_id(
        self,
        table_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> StoreTable | None:
        query = StoreTable.filter(id=table_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_table_for_update(
        self,
        table_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> StoreTable | None:
        return await (
            StoreTable.filter(id=table_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def list_tables(
        self,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[StoreTable]:
        query = StoreTable.all().order_by("table_no").prefetch_related(
            "occupancy__session__order"
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return list(await query)

    async def update_table_enabled(
        self,
        table: StoreTable,
        *,
        is_enabled: bool,
        using_db: BaseDBAsyncClient,
    ) -> StoreTable:
        table.is_enabled = is_enabled
        await table.save(
            using_db=using_db,
            update_fields=["is_enabled", "updated_at"],
        )
        return table

    async def create_table(
        self,
        *,
        table_no: str,
        display_name: str,
        qr_token: str,
        using_db: BaseDBAsyncClient,
    ) -> StoreTable:
        return await StoreTable.create(
            table_no=table_no,
            display_name=display_name,
            qr_token=qr_token,
            is_enabled=True,
            using_db=using_db,
        )

    async def bulk_create_tables(
        self,
        *,
        tables: list[tuple[str, str, str]],
        using_db: BaseDBAsyncClient,
    ) -> None:
        await StoreTable.bulk_create(
            [
                StoreTable(
                    table_no=table_no,
                    display_name=display_name,
                    qr_token=qr_token,
                    is_enabled=True,
                )
                for table_no, display_name, qr_token in tables
            ],
            using_db=using_db,
        )

    async def list_table_definitions(self) -> list[StoreTable]:
        return list(await StoreTable.all().order_by("table_no"))

    async def get_session_by_claim_idempotency_key(
        self,
        idempotency_key: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> TableSession | None:
        query = TableSession.filter(claim_idempotency_key=idempotency_key)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_session_by_release_idempotency_key(
        self,
        idempotency_key: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> TableSession | None:
        query = TableSession.filter(release_idempotency_key=idempotency_key)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def session_number_exists(self, session_no: str) -> bool:
        return await TableSession.filter(session_no=session_no).exists()

    async def create_session(
        self,
        *,
        data: TableSessionCreateData,
        using_db: BaseDBAsyncClient,
    ) -> TableSession:
        return await TableSession.create(
            session_no=data.session_no,
            table_id=data.table_id,
            user_id=data.user_id,
            order_id=data.order_id,
            claim_idempotency_key=data.claim_idempotency_key,
            claim_request_fingerprint=data.claim_request_fingerprint,
            claimed_at=data.claimed_at,
            payment_deadline_at=data.payment_deadline_at,
            using_db=using_db,
        )

    async def create_occupancy(
        self,
        *,
        session_id: int,
        table_id: int,
        user_id: int,
        order_id: int,
        using_db: BaseDBAsyncClient,
    ) -> TableOccupancy:
        return await TableOccupancy.create(
            session_id=session_id,
            table_id=table_id,
            user_id=user_id,
            order_id=order_id,
            using_db=using_db,
        )

    async def get_occupancy_by_table_id(
        self,
        table_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> TableOccupancy | None:
        query = TableOccupancy.filter(table_id=table_id).select_related(
            "session", "session__order"
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_occupancy_by_user_id(
        self,
        user_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> TableOccupancy | None:
        query = TableOccupancy.filter(user_id=user_id).select_related("session")
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_occupancy_by_order_id(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> TableOccupancy | None:
        query = TableOccupancy.filter(order_id=order_id).select_related("session")
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def delete_occupancy_by_session_id(
        self,
        session_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> int:
        return await TableOccupancy.filter(session_id=session_id).using_db(
            using_db
        ).delete()

    async def get_session_for_update(
        self,
        session_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> TableSession | None:
        return await (
            TableSession.filter(id=session_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def get_session_by_no_for_update(
        self,
        session_no: str,
        *,
        using_db: BaseDBAsyncClient,
    ) -> TableSession | None:
        return await (
            TableSession.filter(session_no=session_no)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def get_open_session_by_user_id(
        self,
        user_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> TableSession | None:
        query = TableSession.filter(
            user_id=user_id,
            status__in=(
                TableSessionStatus.AWAITING_PAYMENT,
                TableSessionStatus.ACTIVE,
            ),
        ).order_by("-claimed_at", "-id")
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_open_session_by_order_id(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> TableSession | None:
        query = TableSession.filter(
            order_id=order_id,
            status__in=(
                TableSessionStatus.AWAITING_PAYMENT,
                TableSessionStatus.ACTIVE,
            ),
        ).order_by("-claimed_at", "-id")
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_latest_session_by_order_id(
        self,
        order_id: int,
        *,
        user_id: int | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> TableSession | None:
        query = _session_detail_query().filter(order_id=order_id)
        if user_id is not None:
            query = query.filter(user_id=user_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.order_by("-claimed_at", "-id").first()

    async def get_session_detail(
        self,
        session_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> TableSession | None:
        query = _session_detail_query().filter(id=session_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_session_detail_by_no(
        self,
        session_no: str,
        *,
        user_id: int | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> TableSession | None:
        query = _session_detail_query().filter(session_no=session_no)
        if user_id is not None:
            query = query.filter(user_id=user_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_order_item_snapshots(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[ExperienceItemSnapshot]:
        query = OrderItem.filter(order_id=order_id).order_by("id")
        if using_db is not None:
            query = query.using_db(using_db)
        rows = await query.values(
            "id",
            "product_id",
            "product_name",
            "quantity",
            "option_duration_minutes",
            "option_participants",
            "experience_option_id",
        )
        return [
            ExperienceItemSnapshot(
                id=row["id"],
                product_id=row["product_id"],
                product_name=row["product_name"],
                quantity=row["quantity"],
                duration_minutes=row["option_duration_minutes"],
                participants_per_unit=row["option_participants"],
                is_experience=row["experience_option_id"] is not None,
            )
            for row in rows
        ]

    async def update_session_active(
        self,
        session: TableSession,
        *,
        payment_id: int,
        started_at: datetime,
        table_release_at: datetime,
        using_db: BaseDBAsyncClient,
    ) -> TableSession:
        session.status = TableSessionStatus.ACTIVE
        session.payment_id = payment_id
        session.started_at = started_at
        session.table_release_at = table_release_at
        await session.save(
            using_db=using_db,
            update_fields=[
                "status",
                "payment_id",
                "started_at",
                "table_release_at",
                "updated_at",
            ],
        )
        return session

    async def bulk_create_timers(
        self,
        *,
        session_id: int,
        specs: tuple[TimerSpec, ...],
        using_db: BaseDBAsyncClient,
    ) -> None:
        await TableSessionTimer.bulk_create(
            [
                TableSessionTimer(
                    session_id=session_id,
                    duration_minutes=spec.duration_minutes,
                    buffer_minutes=spec.buffer_minutes,
                    started_at=spec.started_at,
                    service_ends_at=spec.service_ends_at,
                    grace_ends_at=spec.grace_ends_at,
                )
                for spec in specs
            ],
            using_db=using_db,
        )

    async def close_session(
        self,
        session: TableSession,
        *,
        reason: TableSessionCloseReason,
        closed_at: datetime,
        closed_by_user_id: int | None,
        admin_close_reason: str | None,
        release_idempotency_key: str | None,
        using_db: BaseDBAsyncClient,
    ) -> TableSession:
        session.status = TableSessionStatus.CLOSED
        session.close_reason = reason
        session.closed_at = closed_at
        session.closed_by_user_id = closed_by_user_id
        session.admin_close_reason = admin_close_reason
        session.release_idempotency_key = release_idempotency_key
        await session.save(
            using_db=using_db,
            update_fields=[
                "status",
                "close_reason",
                "closed_at",
                "closed_by_user_id",
                "admin_close_reason",
                "release_idempotency_key",
                "updated_at",
            ],
        )
        await self.delete_occupancy_by_session_id(session.id, using_db=using_db)
        return session

    async def list_eligible_orders(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
    ) -> Page[Order]:
        query = (
            Order.filter(
                user_id=user_id,
                status=OrderStatus.PENDING.value,
                items__experience_option_id__not_isnull=True,
                payment_settlement__isnull=True,
                table_occupancy__isnull=True,
            )
            .distinct()
            .prefetch_related("items")
        )
        total = await query.count()
        items = await (
            query.order_by("-created_at", "-id")
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return Page[Order](
            items=list(items),
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size,
        )

    async def list_admin_sessions(
        self,
        *,
        page: int,
        page_size: int,
        table_id: int | None = None,
        user_id: int | None = None,
        order_id: int | None = None,
        status: TableSessionStatus | None = None,
        close_reason: TableSessionCloseReason | None = None,
        claimed_from: datetime | None = None,
        claimed_to: datetime | None = None,
    ) -> Page[TableSession]:
        query = TableSession.all()
        if table_id is not None:
            query = query.filter(table_id=table_id)
        if user_id is not None:
            query = query.filter(user_id=user_id)
        if order_id is not None:
            query = query.filter(order_id=order_id)
        if status is not None:
            query = query.filter(status=status)
        if close_reason is not None:
            query = query.filter(close_reason=close_reason)
        if claimed_from is not None:
            query = query.filter(claimed_at__gte=claimed_from)
        if claimed_to is not None:
            query = query.filter(claimed_at__lte=claimed_to)
        total = await query.count()
        rows = await (
            query.select_related("table", "order", "user")
            .annotate(
                timer_count=Count("timers"),
                minimum_duration_minutes=Min("timers__duration_minutes"),
                maximum_duration_minutes=Max("timers__duration_minutes"),
            )
            .order_by("-claimed_at", "-id")
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return Page[TableSession](
            items=list(rows),
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size,
        )

    async def list_due_session_ids(
        self,
        *,
        now: datetime,
        after_id: int,
        limit: int,
    ) -> list[int]:
        awaiting = TableSession.filter(
            id__gt=after_id,
            status=TableSessionStatus.AWAITING_PAYMENT,
            payment_deadline_at__lt=now,
        ).order_by("id").limit(limit).values_list("id", flat=True)
        active = TableSession.filter(
            id__gt=after_id,
            status=TableSessionStatus.ACTIVE,
            table_release_at__lte=now,
        ).order_by("id").limit(limit).values_list("id", flat=True)
        values = sorted(set(await awaiting) | set(await active))
        return values[:limit]

    async def consistency_counts(self) -> dict[str, int]:
        open_statuses = (
            TableSessionStatus.AWAITING_PAYMENT,
            TableSessionStatus.ACTIVE,
        )
        return {
            "open_sessions": await TableSession.filter(status__in=open_statuses).count(),
            "occupancies": await TableOccupancy.all().count(),
            "closed_with_occupancy": await TableSession.filter(
                status=TableSessionStatus.CLOSED,
                occupancy__isnull=False,
            ).count(),
            "awaiting_with_timers": await TableSession.filter(
                status=TableSessionStatus.AWAITING_PAYMENT,
                timers__isnull=False,
            ).distinct().count(),
            "active_without_timers": await TableSession.filter(
                status=TableSessionStatus.ACTIVE,
                timers__isnull=True,
            ).count(),
        }

    async def list_consistency_sessions(
        self,
        *,
        after_id: int,
        limit: int,
    ) -> list[TableSession]:
        return list(
            await TableSession.all()
            .select_related("table", "order", "user", "payment", "closed_by_user")
            .filter(id__gt=after_id)
            .prefetch_related("timers", "order__items", "occupancy")
            .order_by("id")
            .limit(limit)
        )
