"""Reservation Service —— 独立体验预约、状态流与店休编排。"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError, OperationalError
from tortoise.transactions import in_transaction

from app.common.constants.reservation import (
    RESERVATION_AUDIT_ACTION_CANCEL,
    RESERVATION_AUDIT_ACTION_CONFIRM,
    RESERVATION_AUDIT_ACTION_CREATE,
    RESERVATION_AUDIT_ACTION_REJECT,
    RESERVATION_AUDIT_TARGET_TYPE,
    RESERVATION_BOOKING_WINDOW_DAYS,
    RESERVATION_MINIMUM_LEAD_HOURS,
    RESERVATION_OPERATION_CANCEL,
    RESERVATION_OPERATION_CONFIRM,
    RESERVATION_OPERATION_REJECT,
    RESERVATION_RETRYABLE_MYSQL_ERROR_CODES,
    RESERVATION_TRANSACTION_MAX_ATTEMPTS,
    STORE_BUSINESS_DAY_AUDIT_ACTION_CLOSE,
    STORE_BUSINESS_DAY_AUDIT_ACTION_REOPEN,
    STORE_BUSINESS_DAY_AUDIT_TARGET_TYPE,
)
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationStatus,
    StoreClosureDateUnavailableReason,
)
from app.common.enums.user import UserRole, UserStatus
from app.common.exceptions.reservation import (
    ReservationCancellationWindowClosed,
    ReservationNotFound,
    ReservationOperationExpired,
    ReservationOptionUnavailable,
    ReservationPhoneRequired,
    ReservationProductUnavailable,
    ReservationStatusConflict,
    StoreClosureDateUnavailable,
    StoreClosureNotFound,
)
from app.common.pagination import Page
from app.models.experience_option import ExperienceOption
from app.models.audit_log import AuditLog
from app.models.product import Product
from app.models.reservation import Reservation, StoreBusinessDay
from app.repositories.audit_log_repo import AuditLogCreateData
from app.repositories.product_repo import ProductRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.utils.database import get_database_error_code
from app.validators.reservation_validator import ReservationValidator, STORE_TIMEZONE

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReservationBookingDate:
    """一个可预约上海当地日期及其开始时段。"""

    date: date
    day_type: DayType
    start_times: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReservationBookingOptions:
    """创建页所需的当前 Option 与服务端日历。"""

    experience_option_id: int
    product_id: int
    product_name: str
    duration_minutes: int
    participants: int
    day_type: DayType
    price: Decimal
    server_now: datetime
    booking_window_end_date: date
    dates: tuple[ReservationBookingDate, ...]


@dataclass(frozen=True, slots=True)
class StoreClosureMutationResult:
    """店休或恢复营业命令的确定性结果。"""

    business_day: StoreBusinessDay
    newly_cancelled_count: int
    cancelled_pending_count: int
    cancelled_confirmed_count: int
    is_replay: bool


class ReservationService:
    """拥有 Reservation 写事务、业务校验与跨 Repository 编排。"""

    def __init__(
        self,
        reservation_repository: ReservationRepository,
        product_repository: ProductRepository,
        user_repository: UserRepository,
        audit_log_service: AuditLogService,
        *,
        validator: ReservationValidator | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.reservation_repository = reservation_repository
        self.product_repository = product_repository
        self.user_repository = user_repository
        self.audit_log_service = audit_log_service
        self.validator = validator or ReservationValidator()
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def get_booking_options(
        self,
        *,
        experience_option_id: int,
    ) -> ReservationBookingOptions:
        """生成当前时刻可选的本地营业日期与半小时时段。"""

        now_utc = self._now()
        option = await self.product_repository.get_option_detail(
            experience_option_id,
            include_deleted=True,
        )
        self._validate_option_available(
            option,
            experience_option_id=experience_option_id,
        )
        assert option is not None
        local_today = now_utc.astimezone(STORE_TIMEZONE).date()
        last_date = local_today + timedelta(days=RESERVATION_BOOKING_WINDOW_DAYS)
        closed_dates = await self.reservation_repository.list_closed_dates(
            date_from=local_today,
            date_to=last_date,
        )
        dates: list[ReservationBookingDate] = []
        for offset in range(RESERVATION_BOOKING_WINDOW_DAYS + 1):
            business_date = local_today + timedelta(days=offset)
            start_times = self.validator.list_available_start_times(
                business_date=business_date,
                duration_minutes=option.duration,
                option_day_type=DayType(option.day_type),
                now_utc=now_utc,
                is_store_closed=business_date in closed_dates,
            )
            if start_times:
                dates.append(
                    ReservationBookingDate(
                        date=business_date,
                        day_type=self.validator.day_type_for_date(business_date),
                        start_times=start_times,
                    )
                )
        return ReservationBookingOptions(
            experience_option_id=option.id,
            product_id=option.product_id,
            product_name=option.product.name,
            duration_minutes=option.duration,
            participants=option.participants,
            day_type=DayType(option.day_type),
            price=option.price,
            server_now=now_utc,
            booking_window_end_date=last_date,
            dates=tuple(dates),
        )

    async def create_reservation(
        self,
        *,
        user_id: int,
        experience_option_id: int,
        reservation_date: date,
        start_time: str,
        ip_address: str,
    ) -> Reservation:
        """创建待门店确认预约并保存当前完整 Option 快照。"""

        now_utc = self._now()
        parsed_start_time = time.fromisoformat(start_time)
        candidate = await self.product_repository.get_option_by_id(
            experience_option_id,
            include_deleted=True,
        )
        if candidate is None:
            raise ReservationOptionUnavailable(
                experience_option_id=experience_option_id
            )

        async def operation() -> Reservation:
            async with in_transaction() as connection:
                locked_user = await self.user_repository.get_for_update(
                    user_id,
                    using_db=connection,
                )
                if (
                    locked_user is None
                    or locked_user.role != UserRole.USER
                    or locked_user.status != UserStatus.NORMAL
                ):
                    raise ReservationNotFound()
                if locked_user.phone is None:
                    raise ReservationPhoneRequired()

                business_day = (
                    await self.reservation_repository.ensure_business_day_for_update(
                        reservation_date,
                        using_db=connection,
                    )
                )
                product = await self.product_repository.get_product_for_update(
                    candidate.product_id,
                    using_db=connection,
                )
                option = await self.product_repository.get_option_for_update(
                    experience_option_id,
                    using_db=connection,
                )
                self._validate_locked_option_available(
                    option,
                    product=product,
                    experience_option_id=experience_option_id,
                )
                assert option is not None and product is not None
                scheduled_start_at, scheduled_end_at = (
                    self.validator.validate_schedule(
                        business_date=reservation_date,
                        start_time=parsed_start_time,
                        duration_minutes=option.duration,
                        option_day_type=DayType(option.day_type),
                        now_utc=now_utc,
                        is_store_closed=business_day.is_closed,
                    )
                )
                reservation = (
                    await self.reservation_repository.create_reservation(
                        user_id=locked_user.id,
                        business_day_id=business_day.id,
                        product_id=product.id,
                        experience_option_id=option.id,
                        scheduled_start_at=scheduled_start_at,
                        scheduled_end_at=scheduled_end_at,
                        product_name=product.name,
                        option_duration_minutes=option.duration,
                        option_participants=option.participants,
                        option_day_type=DayType(option.day_type),
                        option_price=option.price,
                        using_db=connection,
                    )
                )
                await self.audit_log_service.log(
                    operator_id=locked_user.id,
                    action=RESERVATION_AUDIT_ACTION_CREATE,
                    target_type=RESERVATION_AUDIT_TARGET_TYPE,
                    target_id=reservation.id,
                    ip_address=ip_address,
                    using_db=connection,
                )
                return await self._reload(
                    reservation.id,
                    user_id=locked_user.id,
                    using_db=connection,
                )

        return await self._run_transaction_with_retry(
            operation,
            retry_business_date=reservation_date,
        )

    async def list_user_reservations(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
        status: ReservationStatus | None = None,
    ) -> Page[Reservation]:
        return await self.reservation_repository.list_user_reservations(
            user_id=user_id,
            page=page,
            page_size=page_size,
            status=status,
        )

    async def get_user_reservation_detail(
        self,
        reservation_id: int,
        *,
        user_id: int,
    ) -> Reservation:
        return await self._reload(reservation_id, user_id=user_id)

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
        return await self.reservation_repository.list_admin_reservations(
            page=page,
            page_size=page_size,
            status=status,
            business_date=business_date,
            user_id=user_id,
            product_id=product_id,
        )

    async def get_admin_reservation_detail(
        self,
        reservation_id: int,
    ) -> Reservation:
        return await self._reload(reservation_id)

    async def cancel_reservation(
        self,
        reservation_id: int,
        *,
        user_id: int,
        ip_address: str,
    ) -> Reservation:
        now_utc = self._now()

        async def operation() -> Reservation:
            async with in_transaction() as connection:
                reservation = (
                    await self.reservation_repository.get_reservation_for_update(
                        reservation_id,
                        user_id=user_id,
                        using_db=connection,
                    )
                )
                if reservation is None:
                    raise ReservationNotFound()
                current_status = ReservationStatus(reservation.status)
                allowed = (
                    ReservationStatus.PENDING,
                    ReservationStatus.CONFIRMED,
                )
                if current_status not in allowed:
                    raise ReservationStatusConflict(
                        operation=RESERVATION_OPERATION_CANCEL,
                        current_status=current_status,
                        allowed_statuses=allowed,
                    )
                if now_utc > reservation.scheduled_start_at - timedelta(
                    hours=RESERVATION_MINIMUM_LEAD_HOURS
                ):
                    raise ReservationCancellationWindowClosed()
                await self.reservation_repository.update_reservation_state(
                    reservation,
                    status=ReservationStatus.CANCELLED,
                    rejection_reason=None,
                    cancellation_reason=(
                        ReservationCancellationReason.CUSTOMER_REQUEST
                    ),
                    confirmed_at=reservation.confirmed_at,
                    rejected_at=None,
                    cancelled_at=now_utc,
                    using_db=connection,
                )
                await self.audit_log_service.log(
                    operator_id=user_id,
                    action=RESERVATION_AUDIT_ACTION_CANCEL,
                    target_type=RESERVATION_AUDIT_TARGET_TYPE,
                    target_id=reservation.id,
                    ip_address=ip_address,
                    description="reason=customer_request",
                    using_db=connection,
                )
                return await self._reload(
                    reservation.id,
                    user_id=user_id,
                    using_db=connection,
                )

        return await self._run_transaction_with_retry(operation)

    async def confirm_reservation(
        self,
        reservation_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> Reservation:
        return await self._transition_pending_reservation(
            reservation_id,
            operator_id=operator_id,
            ip_address=ip_address,
            target_status=ReservationStatus.CONFIRMED,
        )

    async def reject_reservation(
        self,
        reservation_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> Reservation:
        return await self._transition_pending_reservation(
            reservation_id,
            operator_id=operator_id,
            ip_address=ip_address,
            target_status=ReservationStatus.REJECTED,
        )

    async def _transition_pending_reservation(
        self,
        reservation_id: int,
        *,
        operator_id: int,
        ip_address: str,
        target_status: ReservationStatus,
    ) -> Reservation:
        now_utc = self._now()
        if target_status is ReservationStatus.CONFIRMED:
            operation_name = RESERVATION_OPERATION_CONFIRM
            audit_action = RESERVATION_AUDIT_ACTION_CONFIRM
        else:
            operation_name = RESERVATION_OPERATION_REJECT
            audit_action = RESERVATION_AUDIT_ACTION_REJECT

        async def operation() -> Reservation:
            async with in_transaction() as connection:
                reservation = (
                    await self.reservation_repository.get_reservation_for_update(
                        reservation_id,
                        using_db=connection,
                    )
                )
                if reservation is None:
                    raise ReservationNotFound()
                current_status = ReservationStatus(reservation.status)
                if current_status is not ReservationStatus.PENDING:
                    raise ReservationStatusConflict(
                        operation=operation_name,
                        current_status=current_status,
                        allowed_statuses=(ReservationStatus.PENDING,),
                    )
                if now_utc >= reservation.scheduled_start_at:
                    raise ReservationOperationExpired()
                await self.reservation_repository.update_reservation_state(
                    reservation,
                    status=target_status,
                    rejection_reason=(
                        ReservationRejectionReason.NO_CAPACITY
                        if target_status is ReservationStatus.REJECTED
                        else None
                    ),
                    cancellation_reason=None,
                    confirmed_at=(
                        now_utc
                        if target_status is ReservationStatus.CONFIRMED
                        else None
                    ),
                    rejected_at=(
                        now_utc
                        if target_status is ReservationStatus.REJECTED
                        else None
                    ),
                    cancelled_at=None,
                    using_db=connection,
                )
                await self.audit_log_service.log(
                    operator_id=operator_id,
                    action=audit_action,
                    target_type=RESERVATION_AUDIT_TARGET_TYPE,
                    target_id=reservation.id,
                    ip_address=ip_address,
                    description=(
                        "reason=no_capacity"
                        if target_status is ReservationStatus.REJECTED
                        else None
                    ),
                    using_db=connection,
                )
                return await self._reload(
                    reservation.id,
                    using_db=connection,
                )

        return await self._run_transaction_with_retry(operation)

    async def close_store_day(
        self,
        business_date: date,
        *,
        operator_id: int,
        ip_address: str,
    ) -> StoreClosureMutationResult:
        """设置自定义店休并原子批量取消尚未开始的活跃预约。"""

        now_utc = self._now()
        self._validate_store_closure_date(business_date, now_utc=now_utc)

        async def operation() -> StoreClosureMutationResult:
            async with in_transaction() as connection:
                business_day = (
                    await self.reservation_repository.ensure_business_day_for_update(
                        business_date,
                        using_db=connection,
                    )
                )
                if business_day.is_closed:
                    return StoreClosureMutationResult(
                        business_day=business_day,
                        newly_cancelled_count=0,
                        cancelled_pending_count=0,
                        cancelled_confirmed_count=0,
                        is_replay=True,
                    )
                await self.reservation_repository.update_business_day_state(
                    business_day,
                    is_closed=True,
                    using_db=connection,
                )
                list_for_update = (
                    self.reservation_repository
                    .list_active_for_business_day_for_update
                )
                reservations = await list_for_update(
                    business_day_id=business_day.id,
                    scheduled_after=now_utc,
                    using_db=connection,
                )
                pending_count = sum(
                    ReservationStatus(item.status) is ReservationStatus.PENDING
                    for item in reservations
                )
                confirmed_count = sum(
                    ReservationStatus(item.status) is ReservationStatus.CONFIRMED
                    for item in reservations
                )
                await self.reservation_repository.bulk_cancel_for_store_closure(
                    reservations,
                    cancelled_at=now_utc,
                    using_db=connection,
                )
                audit_entries = [
                    AuditLogCreateData(
                        operator_id=operator_id,
                        action=RESERVATION_AUDIT_ACTION_CANCEL,
                        target_type=RESERVATION_AUDIT_TARGET_TYPE,
                        target_id=reservation.id,
                        ip_address=ip_address,
                        description="reason=store_closed",
                    )
                    for reservation in reservations
                ]
                audit_entries.append(
                    AuditLogCreateData(
                        operator_id=operator_id,
                        action=STORE_BUSINESS_DAY_AUDIT_ACTION_CLOSE,
                        target_type=STORE_BUSINESS_DAY_AUDIT_TARGET_TYPE,
                        target_id=business_day.id,
                        ip_address=ip_address,
                        description=f"cancelled_count={len(reservations)}",
                    )
                )
                await self.audit_log_service.log_many(
                    audit_entries,
                    using_db=connection,
                )
                return StoreClosureMutationResult(
                    business_day=business_day,
                    newly_cancelled_count=len(reservations),
                    cancelled_pending_count=pending_count,
                    cancelled_confirmed_count=confirmed_count,
                    is_replay=False,
                )

        return await self._run_transaction_with_retry(
            operation,
            retry_business_date=business_date,
        )

    async def reopen_store_day(
        self,
        business_date: date,
        *,
        operator_id: int,
        ip_address: str,
    ) -> StoreClosureMutationResult:
        """恢复自定义营业日，但绝不恢复历史已取消预约。"""

        now_utc = self._now()
        self._validate_store_closure_date(business_date, now_utc=now_utc)

        async def operation() -> StoreClosureMutationResult:
            async with in_transaction() as connection:
                business_day = (
                    await self.reservation_repository.get_business_day_for_update(
                        business_date,
                        using_db=connection,
                    )
                )
                if business_day is None or not business_day.is_closed:
                    raise StoreClosureNotFound()
                await self.reservation_repository.update_business_day_state(
                    business_day,
                    is_closed=False,
                    using_db=connection,
                )
                await self.audit_log_service.log(
                    operator_id=operator_id,
                    action=STORE_BUSINESS_DAY_AUDIT_ACTION_REOPEN,
                    target_type=STORE_BUSINESS_DAY_AUDIT_TARGET_TYPE,
                    target_id=business_day.id,
                    ip_address=ip_address,
                    using_db=connection,
                )
                return StoreClosureMutationResult(
                    business_day=business_day,
                    newly_cancelled_count=0,
                    cancelled_pending_count=0,
                    cancelled_confirmed_count=0,
                    is_replay=False,
                )

        return await self._run_transaction_with_retry(operation)

    async def list_store_business_days(
        self,
        *,
        page: int,
        page_size: int,
        date_from: date | None,
        date_to: date | None,
        is_closed: bool | None,
    ) -> Page[StoreBusinessDay]:
        return await self.reservation_repository.list_business_days(
            page=page,
            page_size=page_size,
            date_from=date_from,
            date_to=date_to,
            is_closed=is_closed,
        )

    async def list_reservation_audit_logs(
        self,
        reservation_id: int,
        *,
        page: int,
        page_size: int,
    ) -> Page[AuditLog]:
        await self.get_admin_reservation_detail(reservation_id)
        return await self.audit_log_service.list_logs(
            target_type=RESERVATION_AUDIT_TARGET_TYPE,
            target_id=reservation_id,
            page=page,
            page_size=page_size,
        )

    def _validate_option_available(
        self,
        option: ExperienceOption | None,
        *,
        experience_option_id: int,
    ) -> None:
        if option is None or option.is_deleted:
            raise ReservationOptionUnavailable(
                experience_option_id=experience_option_id
            )
        product = option.product
        if (
            product.is_deleted
            or ProductType(product.product_type) is not ProductType.EXPERIENCE
            or ProductStatus(product.status) is not ProductStatus.ONLINE
        ):
            raise ReservationProductUnavailable(product_id=option.product_id)

    def _validate_locked_option_available(
        self,
        option: ExperienceOption | None,
        *,
        product: Product | None,
        experience_option_id: int,
    ) -> None:
        if option is None or option.is_deleted:
            raise ReservationOptionUnavailable(
                experience_option_id=experience_option_id
            )
        if product is None or option.product_id != product.id:
            raise ReservationOptionUnavailable(
                experience_option_id=experience_option_id
            )
        if (
            product.is_deleted
            or ProductType(product.product_type) is not ProductType.EXPERIENCE
            or ProductStatus(product.status) is not ProductStatus.ONLINE
        ):
            raise ReservationProductUnavailable(product_id=product.id)

    @staticmethod
    def _validate_store_closure_date(
        business_date: date,
        *,
        now_utc: datetime,
    ) -> None:
        local_today = now_utc.astimezone(STORE_TIMEZONE).date()
        if business_date < local_today:
            raise StoreClosureDateUnavailable(
                reason=StoreClosureDateUnavailableReason.PAST_DATE
            )
        if business_date.weekday() == 0:
            raise StoreClosureDateUnavailable(
                reason=StoreClosureDateUnavailableReason.WEEKLY_CLOSED
            )

    async def _reload(
        self,
        reservation_id: int,
        *,
        user_id: int | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Reservation:
        reservation = await self.reservation_repository.get_reservation_detail(
            reservation_id,
            user_id=user_id,
            using_db=using_db,
        )
        if reservation is None:
            raise ReservationNotFound()
        return reservation

    def _now(self) -> datetime:
        value = self.now_provider()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Reservation clock must return an aware datetime")
        return value.astimezone(timezone.utc)

    async def _run_transaction_with_retry(
        self,
        operation: Callable,
        *,
        retry_business_date: date | None = None,
    ):
        for attempt in range(1, RESERVATION_TRANSACTION_MAX_ATTEMPTS + 1):
            try:
                return await operation()
            except IntegrityError as exc:
                if (
                    retry_business_date is None
                    or not self._is_business_day_unique_conflict(exc)
                    or attempt >= RESERVATION_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                if await self.reservation_repository.get_business_day(
                    retry_business_date
                ) is None:
                    raise
                logger.warning(
                    "Retrying reservation transaction after business-day "
                    "creation race: attempt=%d",
                    attempt,
                )
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in RESERVATION_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= RESERVATION_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying reservation transaction after database lock "
                    "error: code=%s attempt=%d",
                    error_code,
                    attempt,
                )
        raise RuntimeError("Reservation transaction retry loop exhausted")

    @staticmethod
    def _is_business_day_unique_conflict(exc: IntegrityError) -> bool:
        detail = str(exc).lower()
        return (
            "uidx_store_business_day_date" in detail
            or "store_business_days.business_date" in detail
        )
