"""Reservation Repository —— 预约与营业日数据访问。"""

from datetime import date, datetime
from decimal import Decimal

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.queryset import QuerySet

from app.common.enums.product import DayType
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationStatus,
    ReservationWeekday,
)
from app.common.pagination import Page
from app.models.reservation import Reservation, ReservationSettings, StoreBusinessDay


class ReservationRepository:
    """预约数据访问层，不包含权限、状态机或时间业务判断。"""

    async def get_business_day(
        self,
        business_date: date,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> StoreBusinessDay | None:
        query = StoreBusinessDay.filter(business_date=business_date)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def ensure_business_day_for_update(
        self,
        business_date: date,
        *,
        using_db: BaseDBAsyncClient,
    ) -> StoreBusinessDay:
        """按需创建并锁定一日一行的营业日权威记录。"""

        await StoreBusinessDay.get_or_create(
            business_date=business_date,
            defaults={"is_closed": False},
            using_db=using_db,
        )
        return await (
            StoreBusinessDay.filter(business_date=business_date)
            .using_db(using_db)
            .select_for_update()
            .get()
        )

    async def get_business_day_for_update(
        self,
        business_date: date,
        *,
        using_db: BaseDBAsyncClient,
    ) -> StoreBusinessDay | None:
        return await (
            StoreBusinessDay.filter(business_date=business_date)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def update_business_day_state(
        self,
        business_day: StoreBusinessDay,
        *,
        is_closed: bool,
        using_db: BaseDBAsyncClient,
    ) -> StoreBusinessDay:
        business_day.is_closed = is_closed
        await business_day.save(
            using_db=using_db,
            update_fields=["is_closed", "updated_at"],
        )
        return business_day

    async def list_closed_dates(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> set[date]:
        values = await StoreBusinessDay.filter(
            business_date__gte=date_from,
            business_date__lte=date_to,
            is_closed=True,
        ).values_list("business_date", flat=True)
        return set(values)

    async def list_business_days(
        self,
        *,
        page: int,
        page_size: int,
        date_from: date | None = None,
        date_to: date | None = None,
        is_closed: bool | None = True,
    ) -> Page[StoreBusinessDay]:
        query = StoreBusinessDay.all()
        if date_from is not None:
            query = query.filter(business_date__gte=date_from)
        if date_to is not None:
            query = query.filter(business_date__lte=date_to)
        if is_closed is not None:
            query = query.filter(is_closed=is_closed)
        total = await query.count()
        items = await (
            query.order_by("business_date", "id")
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return Page[StoreBusinessDay](
            items=list(items),
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size,
        )

    async def create_reservation(
        self,
        *,
        user_id: int,
        business_day_id: int,
        product_id: int,
        experience_option_id: int,
        scheduled_start_at: datetime,
        scheduled_end_at: datetime,
        product_name: str,
        option_duration_minutes: int,
        option_participants: int,
        option_day_type: DayType,
        option_price: Decimal,
        using_db: BaseDBAsyncClient,
    ) -> Reservation:
        return await Reservation.create(
            user_id=user_id,
            business_day_id=business_day_id,
            product_id=product_id,
            experience_option_id=experience_option_id,
            scheduled_start_at=scheduled_start_at,
            scheduled_end_at=scheduled_end_at,
            product_name=product_name,
            option_duration_minutes=option_duration_minutes,
            option_participants=option_participants,
            option_day_type=option_day_type,
            option_price=option_price,
            using_db=using_db,
        )

    async def get_reservation_detail(
        self,
        reservation_id: int,
        *,
        user_id: int | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Reservation | None:
        query = Reservation.filter(id=reservation_id).select_related("user")
        if user_id is not None:
            query = query.filter(user_id=user_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_reservation_for_update(
        self,
        reservation_id: int,
        *,
        user_id: int | None = None,
        using_db: BaseDBAsyncClient,
    ) -> Reservation | None:
        query = Reservation.filter(id=reservation_id).using_db(using_db)
        if user_id is not None:
            query = query.filter(user_id=user_id)
        return await query.select_for_update().first()

    async def update_reservation_state(
        self,
        reservation: Reservation,
        *,
        status: ReservationStatus,
        rejection_reason: ReservationRejectionReason | None,
        cancellation_reason: ReservationCancellationReason | None,
        confirmed_at: datetime | None,
        rejected_at: datetime | None,
        cancelled_at: datetime | None,
        using_db: BaseDBAsyncClient,
    ) -> Reservation:
        reservation.status = status
        reservation.rejection_reason = rejection_reason
        reservation.cancellation_reason = cancellation_reason
        reservation.confirmed_at = confirmed_at
        reservation.rejected_at = rejected_at
        reservation.cancelled_at = cancelled_at
        await reservation.save(
            using_db=using_db,
            update_fields=[
                "status",
                "rejection_reason",
                "cancellation_reason",
                "confirmed_at",
                "rejected_at",
                "cancelled_at",
                "updated_at",
            ],
        )
        return reservation

    async def list_user_reservations(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
        status: ReservationStatus | None = None,
    ) -> Page[Reservation]:
        query = Reservation.filter(user_id=user_id)
        if status is not None:
            query = query.filter(status=status.value)
        return await self._paginate_reservations(
            query,
            page=page,
            page_size=page_size,
            include_user=False,
        )

    async def list_admin_reservations(
        self,
        *,
        page: int,
        page_size: int,
        status: ReservationStatus | None = None,
        business_date: date | None = None,
        user_id: int | None = None,
        product_id: int | None = None,
    ) -> Page[Reservation]:
        query = Reservation.all()
        if status is not None:
            query = query.filter(status=status.value)
        if business_date is not None:
            query = query.filter(business_day__business_date=business_date)
        if user_id is not None:
            query = query.filter(user_id=user_id)
        if product_id is not None:
            query = query.filter(product_id=product_id)
        return await self._paginate_reservations(
            query,
            page=page,
            page_size=page_size,
            include_user=True,
        )

    async def _paginate_reservations(
        self,
        query: QuerySet[Reservation],
        *,
        page: int,
        page_size: int,
        include_user: bool,
    ) -> Page[Reservation]:
        total = await query.count()
        item_query = query
        if include_user:
            item_query = item_query.select_related("user")
        items = await (
            item_query.order_by("-scheduled_start_at", "-id")
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return Page[Reservation](
            items=list(items),
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size,
        )

    async def list_active_for_business_day_for_update(
        self,
        *,
        business_day_id: int,
        scheduled_after: datetime,
        using_db: BaseDBAsyncClient,
    ) -> list[Reservation]:
        return list(
            await Reservation.filter(
                business_day_id=business_day_id,
                status__in=[
                    ReservationStatus.PENDING.value,
                    ReservationStatus.CONFIRMED.value,
                ],
                scheduled_start_at__gt=scheduled_after,
            )
            .using_db(using_db)
            .order_by("id")
            .select_for_update()
        )

    async def list_active_for_business_dates_for_update(
        self,
        *,
        business_dates: list[date],
        scheduled_after: datetime,
        using_db: BaseDBAsyncClient,
    ) -> list[Reservation]:
        if not business_dates:
            return []
        return list(
            await Reservation.filter(
                business_day__business_date__in=business_dates,
                status__in=[
                    ReservationStatus.PENDING.value,
                    ReservationStatus.CONFIRMED.value,
                ],
                scheduled_start_at__gt=scheduled_after,
            )
            .using_db(using_db)
            .order_by("id")
            .select_for_update()
        )

    async def bulk_cancel_for_store_closure(
        self,
        reservations: list[Reservation],
        *,
        cancelled_at: datetime,
        using_db: BaseDBAsyncClient,
    ) -> None:
        if not reservations:
            return
        for reservation in reservations:
            reservation.status = ReservationStatus.CANCELLED
            reservation.rejection_reason = None
            reservation.cancellation_reason = (
                ReservationCancellationReason.STORE_CLOSED
            )
            reservation.cancelled_at = cancelled_at
            reservation.updated_at = cancelled_at
        await Reservation.bulk_update(
            reservations,
            fields=[
                "status",
                "rejection_reason",
                "cancellation_reason",
                "cancelled_at",
                "updated_at",
            ],
            using_db=using_db,
        )

    async def has_active_reservations_for_user(
        self,
        user_id: int,
        *,
        now_utc: datetime,
        using_db: BaseDBAsyncClient | None = None,
    ) -> bool:
        query = Reservation.filter(
            user_id=user_id,
            status__in=[
                ReservationStatus.PENDING.value,
                ReservationStatus.CONFIRMED.value,
            ],
            scheduled_end_at__gt=now_utc,
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.exists()

    async def get_settings(
        self,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ReservationSettings:
        """读取单例设置；开发库首次使用时补建默认值。"""

        settings, _ = await ReservationSettings.get_or_create(
            singleton_key=True,
            defaults={"weekly_closed_weekday": ReservationWeekday.MONDAY},
            using_db=using_db,
        )
        return settings

    async def get_settings_for_update(
        self,
        *,
        using_db: BaseDBAsyncClient,
    ) -> ReservationSettings:
        await self.get_settings(using_db=using_db)
        return await (
            ReservationSettings.filter(singleton_key=True)
            .using_db(using_db)
            .select_for_update()
            .get()
        )

    async def update_weekly_closed_weekday(
        self,
        settings: ReservationSettings,
        *,
        weekly_closed_weekday: ReservationWeekday,
        using_db: BaseDBAsyncClient,
    ) -> ReservationSettings:
        settings.weekly_closed_weekday = weekly_closed_weekday
        await settings.save(
            using_db=using_db,
            update_fields=["weekly_closed_weekday", "updated_at"],
        )
        return settings
