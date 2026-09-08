"""Reservation：真实 MySQL 行锁、店休原子性、重试与索引门槛。"""

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from tortoise import connections
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import OperationalError
from tortoise.transactions import in_transaction

from app.common.constants.reservation import (
    RESERVATION_RETRYABLE_MYSQL_ERROR_CODES,
)
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationScheduleUnavailableReason,
    ReservationStatus,
    ReservationWeekday,
)
from app.common.exceptions.reservation import ReservationScheduleUnavailable
from app.models.audit_log import AuditLog
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.reservation import Reservation, ReservationSettings, StoreBusinessDay
from app.models.user import User
from app.repositories.audit_log_repo import (
    AuditLogCreateData,
    AuditLogRepository,
)
from app.repositories.product_repo import ProductRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.reservation_service import ReservationService
from app.validators.reservation_validator import ReservationValidator


pytestmark = pytest.mark.mysql

FROZEN_NOW = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
BUSINESS_DATE = date(2026, 9, 9)
RESERVATION_MIGRATIONS = list(
    Path("migrations/models").glob("5_*_add_reservations.py")
)
COLOR_SELECTABLE_KIT_MIGRATIONS = list(
    Path("migrations/models").glob("6_*_add_color_selectable_kits.py")
)
RESERVATION_SETTINGS_MIGRATIONS = list(
    Path("migrations/models").glob("7_*_add_reservation_settings.py")
)
BEAD_COLOR_SWATCH_HEX_MIGRATIONS = list(
    Path("migrations/models").glob("8_*_add_bead_color_swatch_hex.py")
)


class _HoldingBusinessDayRepository(ReservationRepository):
    """创建预约取得营业日锁后，等待测试显式放行。"""

    def __init__(self) -> None:
        self.lock_acquired = asyncio.Event()
        self.release = asyncio.Event()

    async def ensure_business_day_for_update(
        self,
        business_date: date,
        *,
        using_db: BaseDBAsyncClient,
    ) -> StoreBusinessDay:
        business_day = await super().ensure_business_day_for_update(
            business_date,
            using_db=using_db,
        )
        self.lock_acquired.set()
        await self.release.wait()
        return business_day


class _RecordingWeeklyClosureRepository(ReservationRepository):
    """记录真实 MySQL 返回的预约锁顺序。"""

    def __init__(self) -> None:
        self.locked_batches: list[list[int]] = []

    async def list_active_for_business_dates_for_update(
        self,
        *,
        business_dates: list[date],
        scheduled_after: datetime,
        using_db: BaseDBAsyncClient,
    ) -> list[Reservation]:
        reservations = await super().list_active_for_business_dates_for_update(
            business_dates=business_dates,
            scheduled_after=scheduled_after,
            using_db=using_db,
        )
        self.locked_batches.append([item.id for item in reservations])
        return reservations


class _HoldingSettingsRepository(_RecordingWeeklyClosureRepository):
    """取得 M7 单例设置锁后等待测试显式放行。"""

    def __init__(self) -> None:
        super().__init__()
        self.lock_acquired = asyncio.Event()
        self.release = asyncio.Event()

    async def get_settings_for_update(
        self,
        *,
        using_db: BaseDBAsyncClient,
    ) -> ReservationSettings:
        settings = await super().get_settings_for_update(using_db=using_db)
        self.lock_acquired.set()
        await self.release.wait()
        return settings


class _TimeoutSignalingReservationRepository(ReservationRepository):
    """将真实行锁等待缩短为一秒，并通知测试释放阻塞事务。"""

    def __init__(self) -> None:
        self.attempts = 0
        self.first_timeout = asyncio.Event()

    async def ensure_business_day_for_update(
        self,
        business_date: date,
        *,
        using_db: BaseDBAsyncClient,
    ) -> StoreBusinessDay:
        self.attempts += 1
        await using_db.execute_query("SET SESSION innodb_lock_wait_timeout = 1")
        try:
            return await super().ensure_business_day_for_update(
                business_date,
                using_db=using_db,
            )
        except OperationalError:
            self.first_timeout.set()
            raise


class _OneShotDeadlockRepository(ReservationRepository):
    """在首个事务已更新店休状态后模拟驱动返回 1213。"""

    def __init__(self) -> None:
        self.attempts = 0

    async def list_active_for_business_day_for_update(
        self,
        *,
        business_day_id: int,
        scheduled_after: datetime,
        using_db: BaseDBAsyncClient,
    ) -> list[Reservation]:
        self.attempts += 1
        if self.attempts == 1:
            raise OperationalError(1213, "deadlock victim")
        return await super().list_active_for_business_day_for_update(
            business_day_id=business_day_id,
            scheduled_after=scheduled_after,
            using_db=using_db,
        )


class _OneShotWeeklyDeadlockRepository(_RecordingWeeklyClosureRepository):
    """在 M7 首个事务已更新设置后模拟驱动返回 1213。"""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    async def list_active_for_business_dates_for_update(
        self,
        *,
        business_dates: list[date],
        scheduled_after: datetime,
        using_db: BaseDBAsyncClient,
    ) -> list[Reservation]:
        self.attempts += 1
        if self.attempts == 1:
            raise OperationalError(1213, "M7 weekly closure deadlock victim")
        return await super().list_active_for_business_dates_for_update(
            business_dates=business_dates,
            scheduled_after=scheduled_after,
            using_db=using_db,
        )


class _FailAfterBatchAudit(AuditLogService):
    async def log_many(
        self,
        entries: list[AuditLogCreateData],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        await super().log_many(entries, using_db=using_db)
        raise RuntimeError("fail after MySQL closure audit")


def _service(
    repository: ReservationRepository | None = None,
    *,
    audit_service: AuditLogService | None = None,
) -> ReservationService:
    return ReservationService(
        repository or ReservationRepository(),
        ProductRepository(),
        UserRepository(),
        audit_service or AuditLogService(AuditLogRepository()),
        now_provider=lambda: FROZEN_NOW,
    )


async def _create_user(number: int) -> User:
    return await User.create(
        username=f"reservation-mysql-{number}",
        password="hashed-password",
        nickname=f"预约 MySQL 用户 {number}",
        phone=f"13855{number:06d}",
    )


async def _create_option() -> tuple[Product, ExperienceOption]:
    product = await Product.create(
        name="MySQL 拼豆体验",
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=60,
        participants=2,
        day_type=DayType.WEEKDAY,
        price=Decimal("88.50"),
    )
    return product, option


async def _create_reservation_record(
    *,
    user: User,
    business_day: StoreBusinessDay,
    product: Product,
    option: ExperienceOption,
    local_start: time,
    status: ReservationStatus = ReservationStatus.PENDING,
) -> Reservation:
    scheduled_start_at = ReservationValidator.build_scheduled_start(
        business_date=business_day.business_date,
        start_time=local_start,
    )
    return await Reservation.create(
        user=user,
        business_day=business_day,
        product=product,
        experience_option=option,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_start_at + timedelta(minutes=option.duration),
        product_name=product.name,
        option_duration_minutes=option.duration,
        option_participants=option.participants,
        option_day_type=option.day_type,
        option_price=option.price,
        status=status,
        confirmed_at=(
            FROZEN_NOW - timedelta(hours=1)
            if status is ReservationStatus.CONFIRMED
            else None
        ),
    )


async def _wait_for_data_lock_wait() -> None:
    """等待 performance_schema 证明第二事务正在等待 InnoDB 行锁。"""

    connection = connections.get("default")
    for _ in range(200):
        rows = await connection.execute_query_dict(
            "SELECT COUNT(*) AS wait_count "
            "FROM performance_schema.data_lock_waits"
        )
        if int(rows[0]["wait_count"]) > 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("expected an observable Reservation row-lock wait")


async def test_create_then_concurrent_closure_leaves_no_active_reservation() -> None:
    customer = await _create_user(1)
    admin = await _create_user(2)
    product, option = await _create_option()
    await StoreBusinessDay.create(
        business_date=BUSINESS_DATE,
        is_closed=False,
    )
    holding_repository = _HoldingBusinessDayRepository()
    create_task = asyncio.create_task(
        _service(holding_repository).create_reservation(
            user_id=customer.id,
            experience_option_id=option.id,
            reservation_date=BUSINESS_DATE,
            start_time="11:00",
            ip_address="127.0.0.1",
        )
    )
    await asyncio.wait_for(holding_repository.lock_acquired.wait(), timeout=5)
    close_task = asyncio.create_task(
        _service().close_store_day(
            BUSINESS_DATE,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )
    )
    try:
        await asyncio.wait_for(_wait_for_data_lock_wait(), timeout=5)
    finally:
        holding_repository.release.set()

    created, closed = await asyncio.wait_for(
        asyncio.gather(create_task, close_task),
        timeout=10,
    )

    stored = await Reservation.get(id=created.id)
    business_day = await StoreBusinessDay.get(business_date=BUSINESS_DATE)
    assert business_day.is_closed is True
    assert ReservationStatus(stored.status) is ReservationStatus.CANCELLED
    assert (
        ReservationCancellationReason(stored.cancellation_reason)
        is ReservationCancellationReason.STORE_CLOSED
    )
    assert closed.newly_cancelled_count == 1
    assert closed.cancelled_pending_count == 1
    assert await AuditLog.filter(action="CREATE_RESERVATION").count() == 1
    assert await AuditLog.filter(action="CANCEL_RESERVATION").count() == 1
    assert await AuditLog.filter(action="CLOSE_STORE_BUSINESS_DAY").count() == 1


async def test_closure_then_concurrent_create_is_rejected_after_lock_wait() -> None:
    customer = await _create_user(11)
    admin = await _create_user(12)
    _, option = await _create_option()
    await StoreBusinessDay.create(
        business_date=BUSINESS_DATE,
        is_closed=False,
    )
    holding_repository = _HoldingBusinessDayRepository()
    close_task = asyncio.create_task(
        _service(holding_repository).close_store_day(
            BUSINESS_DATE,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )
    )
    await asyncio.wait_for(holding_repository.lock_acquired.wait(), timeout=5)
    create_task = asyncio.create_task(
        _service().create_reservation(
            user_id=customer.id,
            experience_option_id=option.id,
            reservation_date=BUSINESS_DATE,
            start_time="11:00",
            ip_address="127.0.0.1",
        )
    )
    try:
        await asyncio.wait_for(_wait_for_data_lock_wait(), timeout=5)
    finally:
        holding_repository.release.set()

    closed = await asyncio.wait_for(close_task, timeout=5)
    with pytest.raises(ReservationScheduleUnavailable) as caught:
        await asyncio.wait_for(create_task, timeout=5)

    business_day = await StoreBusinessDay.get(business_date=BUSINESS_DATE)
    assert business_day.is_closed is True
    assert closed.newly_cancelled_count == 0
    assert caught.value.data == {
        "reason": ReservationScheduleUnavailableReason.STORE_CLOSED.value
    }
    assert not await Reservation.all().exists()
    assert not await AuditLog.filter(action="CREATE_RESERVATION").exists()
    assert await AuditLog.filter(action="CLOSE_STORE_BUSINESS_DAY").count() == 1


async def test_concurrent_same_day_closure_commits_once_and_replays_once() -> None:
    owner = await _create_user(3)
    admin = await _create_user(4)
    product, option = await _create_option()
    business_day = await StoreBusinessDay.create(
        business_date=BUSINESS_DATE,
        is_closed=False,
    )
    reservations = [
        await _create_reservation_record(
            user=owner,
            business_day=business_day,
            product=product,
            option=option,
            local_start=time(11 + number, 0),
            status=(
                ReservationStatus.PENDING
                if number < 3
                else ReservationStatus.CONFIRMED
            ),
        )
        for number in range(5)
    ]
    rejected = await _create_reservation_record(
        user=owner,
        business_day=business_day,
        product=product,
        option=option,
        local_start=time(17, 0),
        status=ReservationStatus.REJECTED,
    )
    rejected.rejection_reason = ReservationRejectionReason.NO_CAPACITY
    rejected.rejected_at = FROZEN_NOW
    await rejected.save(
        update_fields=["rejection_reason", "rejected_at", "updated_at"]
    )
    service = _service()

    first, second = await asyncio.wait_for(
        asyncio.gather(
            service.close_store_day(
                BUSINESS_DATE,
                operator_id=admin.id,
                ip_address="127.0.0.1",
            ),
            service.close_store_day(
                BUSINESS_DATE,
                operator_id=admin.id,
                ip_address="127.0.0.1",
            ),
        ),
        timeout=10,
    )

    assert {first.is_replay, second.is_replay} == {False, True}
    assert {first.newly_cancelled_count, second.newly_cancelled_count} == {0, 5}
    assert sum(
        result.cancelled_pending_count for result in (first, second)
    ) == 3
    assert sum(
        result.cancelled_confirmed_count for result in (first, second)
    ) == 2
    for reservation in reservations:
        await reservation.refresh_from_db()
        assert ReservationStatus(reservation.status) is ReservationStatus.CANCELLED
        assert (
            ReservationCancellationReason(reservation.cancellation_reason)
            is ReservationCancellationReason.STORE_CLOSED
        )
    await rejected.refresh_from_db()
    assert ReservationStatus(rejected.status) is ReservationStatus.REJECTED
    assert rejected.rejection_reason == ReservationRejectionReason.NO_CAPACITY
    assert await StoreBusinessDay.filter(business_date=BUSINESS_DATE).count() == 1
    assert await AuditLog.filter(action="CANCEL_RESERVATION").count() == 5
    assert await AuditLog.filter(action="CLOSE_STORE_BUSINESS_DAY").count() == 1


async def test_closure_batch_and_audits_roll_back_together_on_mysql() -> None:
    owner = await _create_user(5)
    admin = await _create_user(6)
    product, option = await _create_option()
    business_day = await StoreBusinessDay.create(
        business_date=BUSINESS_DATE,
        is_closed=False,
    )
    reservations = [
        await _create_reservation_record(
            user=owner,
            business_day=business_day,
            product=product,
            option=option,
            local_start=time(11 + number, 0),
        )
        for number in range(2)
    ]
    service = _service(
        audit_service=_FailAfterBatchAudit(AuditLogRepository())
    )

    with pytest.raises(RuntimeError, match="fail after MySQL closure audit"):
        await service.close_store_day(
            BUSINESS_DATE,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )

    await business_day.refresh_from_db()
    assert business_day.is_closed is False
    for reservation in reservations:
        await reservation.refresh_from_db()
        assert ReservationStatus(reservation.status) is ReservationStatus.PENDING
        assert reservation.cancellation_reason is None
        assert reservation.cancelled_at is None
    assert not await AuditLog.all().exists()


async def test_real_1205_retries_entire_closure_transaction() -> None:
    owner = await _create_user(7)
    admin = await _create_user(8)
    product, option = await _create_option()
    business_day = await StoreBusinessDay.create(
        business_date=BUSINESS_DATE,
        is_closed=False,
    )
    reservation = await _create_reservation_record(
        user=owner,
        business_day=business_day,
        product=product,
        option=option,
        local_start=time(11, 0),
    )
    blocker_locked = asyncio.Event()
    release_blocker = asyncio.Event()
    repository = _TimeoutSignalingReservationRepository()

    async def hold_business_day_lock() -> None:
        async with in_transaction() as blocker:
            locked = await ReservationRepository().get_business_day_for_update(
                BUSINESS_DATE,
                using_db=blocker,
            )
            assert locked is not None
            blocker_locked.set()
            await release_blocker.wait()

    blocker_task = asyncio.create_task(hold_business_day_lock())
    await asyncio.wait_for(blocker_locked.wait(), timeout=5)
    closure_task = asyncio.create_task(
        _service(repository).close_store_day(
            BUSINESS_DATE,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )
    )
    try:
        await asyncio.wait_for(repository.first_timeout.wait(), timeout=3)
    finally:
        release_blocker.set()
        await asyncio.wait_for(blocker_task, timeout=5)

    result = await asyncio.wait_for(closure_task, timeout=5)

    await business_day.refresh_from_db()
    await reservation.refresh_from_db()
    assert repository.attempts == 2
    assert result.is_replay is False
    assert result.newly_cancelled_count == 1
    assert business_day.is_closed is True
    assert ReservationStatus(reservation.status) is ReservationStatus.CANCELLED
    assert await AuditLog.filter(action="CANCEL_RESERVATION").count() == 1
    assert await AuditLog.filter(action="CLOSE_STORE_BUSINESS_DAY").count() == 1


async def test_1213_rolls_back_first_attempt_then_retries_full_transaction() -> None:
    assert RESERVATION_RETRYABLE_MYSQL_ERROR_CODES == frozenset({1205, 1213})
    owner = await _create_user(9)
    admin = await _create_user(10)
    product, option = await _create_option()
    business_day = await StoreBusinessDay.create(
        business_date=BUSINESS_DATE,
        is_closed=False,
    )
    reservation = await _create_reservation_record(
        user=owner,
        business_day=business_day,
        product=product,
        option=option,
        local_start=time(11, 0),
    )
    repository = _OneShotDeadlockRepository()

    result = await _service(repository).close_store_day(
        BUSINESS_DATE,
        operator_id=admin.id,
        ip_address="127.0.0.1",
    )

    await business_day.refresh_from_db()
    await reservation.refresh_from_db()
    assert repository.attempts == 2
    assert result.newly_cancelled_count == 1
    assert business_day.is_closed is True
    assert ReservationStatus(reservation.status) is ReservationStatus.CANCELLED
    assert await AuditLog.filter(action="CANCEL_RESERVATION").count() == 1
    assert await AuditLog.filter(action="CLOSE_STORE_BUSINESS_DAY").count() == 1


async def test_weekly_closure_serializes_on_settings_and_locks_reservations_by_id() -> None:
    owner = await _create_user(21)
    admin = await _create_user(22)
    product, option = await _create_option()
    later_wednesday_day = await StoreBusinessDay.create(
        business_date=date(2026, 9, 16),
        is_closed=False,
    )
    soon_wednesday_day = await StoreBusinessDay.create(
        business_date=date(2026, 9, 9),
        is_closed=False,
    )
    thursday_day = await StoreBusinessDay.create(
        business_date=date(2026, 9, 10),
        is_closed=False,
    )
    later_wednesday = await _create_reservation_record(
        user=owner,
        business_day=later_wednesday_day,
        product=product,
        option=option,
        local_start=time(11, 0),
    )
    soon_wednesday = await _create_reservation_record(
        user=owner,
        business_day=soon_wednesday_day,
        product=product,
        option=option,
        local_start=time(11, 30),
        status=ReservationStatus.CONFIRMED,
    )
    thursday = await _create_reservation_record(
        user=owner,
        business_day=thursday_day,
        product=product,
        option=option,
        local_start=time(12, 0),
    )
    holding_repository = _HoldingSettingsRepository()
    waiting_repository = _RecordingWeeklyClosureRepository()

    first_task = asyncio.create_task(
        _service(holding_repository).update_weekly_closed_day(
            weekly_closed_weekday=ReservationWeekday.WEDNESDAY,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )
    )
    await asyncio.wait_for(holding_repository.lock_acquired.wait(), timeout=5)
    second_task = asyncio.create_task(
        _service(waiting_repository).update_weekly_closed_day(
            weekly_closed_weekday=ReservationWeekday.THURSDAY,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )
    )
    try:
        await asyncio.wait_for(_wait_for_data_lock_wait(), timeout=5)
    finally:
        holding_repository.release.set()

    first, second = await asyncio.wait_for(
        asyncio.gather(first_task, second_task),
        timeout=10,
    )

    assert first.previous_weekly_closed_weekday is ReservationWeekday.MONDAY
    assert first.newly_cancelled_count == 2
    assert first.cancelled_pending_count == 1
    assert first.cancelled_confirmed_count == 1
    assert second.previous_weekly_closed_weekday is ReservationWeekday.WEDNESDAY
    assert second.newly_cancelled_count == 1
    assert holding_repository.locked_batches == [
        sorted([later_wednesday.id, soon_wednesday.id])
    ]
    assert waiting_repository.locked_batches == [[thursday.id]]
    settings = await ReservationSettings.get(singleton_key=True)
    assert settings.weekly_closed_weekday == ReservationWeekday.THURSDAY
    for reservation in (later_wednesday, soon_wednesday, thursday):
        await reservation.refresh_from_db()
        assert ReservationStatus(reservation.status) is ReservationStatus.CANCELLED
        assert (
            ReservationCancellationReason(reservation.cancellation_reason)
            is ReservationCancellationReason.STORE_CLOSED
        )
    assert await AuditLog.filter(action="CANCEL_RESERVATION").count() == 3
    assert await AuditLog.filter(action="UPDATE_WEEKLY_CLOSED_DAY").count() == 2


async def test_weekly_closure_rolls_back_setting_batch_and_audits_together() -> None:
    owner = await _create_user(23)
    admin = await _create_user(24)
    product, option = await _create_option()
    business_day = await StoreBusinessDay.create(
        business_date=date(2026, 9, 9),
        is_closed=False,
    )
    reservation = await _create_reservation_record(
        user=owner,
        business_day=business_day,
        product=product,
        option=option,
        local_start=time(13, 0),
    )

    with pytest.raises(RuntimeError, match="fail after MySQL closure audit"):
        await _service(
            audit_service=_FailAfterBatchAudit(AuditLogRepository())
        ).update_weekly_closed_day(
            weekly_closed_weekday=ReservationWeekday.WEDNESDAY,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )

    settings = await ReservationSettings.get(singleton_key=True)
    await reservation.refresh_from_db()
    assert settings.weekly_closed_weekday == ReservationWeekday.MONDAY
    assert ReservationStatus(reservation.status) is ReservationStatus.PENDING
    assert reservation.cancellation_reason is None
    assert reservation.cancelled_at is None
    assert not await AuditLog.all().exists()


async def test_weekly_closure_1213_retries_the_entire_m7_transaction() -> None:
    assert RESERVATION_RETRYABLE_MYSQL_ERROR_CODES == frozenset({1205, 1213})
    owner = await _create_user(25)
    admin = await _create_user(26)
    product, option = await _create_option()
    business_day = await StoreBusinessDay.create(
        business_date=date(2026, 9, 9),
        is_closed=False,
    )
    reservation = await _create_reservation_record(
        user=owner,
        business_day=business_day,
        product=product,
        option=option,
        local_start=time(14, 0),
    )
    repository = _OneShotWeeklyDeadlockRepository()

    result = await _service(repository).update_weekly_closed_day(
        weekly_closed_weekday=ReservationWeekday.WEDNESDAY,
        operator_id=admin.id,
        ip_address="127.0.0.1",
    )

    settings = await ReservationSettings.get(singleton_key=True)
    await reservation.refresh_from_db()
    assert repository.attempts == 2
    assert repository.locked_batches == [[reservation.id]]
    assert result.previous_weekly_closed_weekday is ReservationWeekday.MONDAY
    assert result.newly_cancelled_count == 1
    assert settings.weekly_closed_weekday == ReservationWeekday.WEDNESDAY
    assert ReservationStatus(reservation.status) is ReservationStatus.CANCELLED
    assert (
        ReservationCancellationReason(reservation.cancellation_reason)
        is ReservationCancellationReason.STORE_CLOSED
    )
    assert await AuditLog.filter(action="CANCEL_RESERVATION").count() == 1
    assert await AuditLog.filter(action="UPDATE_WEEKLY_CLOSED_DAY").count() == 1


async def test_mysql_migrations_and_explain_use_all_reservation_indexes() -> None:
    assert len(RESERVATION_MIGRATIONS) == 1
    assert len(COLOR_SELECTABLE_KIT_MIGRATIONS) == 1
    assert len(RESERVATION_SETTINGS_MIGRATIONS) == 1
    assert len(BEAD_COLOR_SWATCH_HEX_MIGRATIONS) == 1
    product, option = await _create_option()
    users = [await _create_user(100 + number) for number in range(50)]
    business_days = [
        await StoreBusinessDay.create(
            business_date=BUSINESS_DATE + timedelta(days=number),
            is_closed=False,
        )
        for number in range(10)
    ]
    base_start = datetime(2026, 9, 9, 3, 0, tzinfo=timezone.utc)
    statuses = (
        ReservationStatus.PENDING,
        ReservationStatus.CONFIRMED,
        ReservationStatus.REJECTED,
        ReservationStatus.CANCELLED,
    )
    samples: list[Reservation] = []
    for number in range(5_000):
        scheduled_start = base_start + timedelta(
            days=number % len(business_days),
            minutes=30 * (number % 18),
        )
        status = statuses[number % len(statuses)]
        samples.append(
            Reservation(
                user_id=users[number % len(users)].id,
                business_day_id=(
                    business_days[number % len(business_days)].id
                ),
                product_id=product.id,
                experience_option_id=option.id,
                scheduled_start_at=scheduled_start,
                scheduled_end_at=scheduled_start + timedelta(minutes=60),
                product_name=product.name,
                option_duration_minutes=60,
                option_participants=2,
                option_day_type=DayType.WEEKDAY,
                option_price=Decimal("88.50"),
                status=status,
                rejection_reason=(
                    ReservationRejectionReason.NO_CAPACITY
                    if status is ReservationStatus.REJECTED
                    else None
                ),
                cancellation_reason=(
                    ReservationCancellationReason.CUSTOMER_REQUEST
                    if status is ReservationStatus.CANCELLED
                    else None
                ),
            )
        )
    await Reservation.bulk_create(samples, batch_size=500)

    connection = connections.get("default")
    await connection.execute_query("ANALYZE TABLE store_business_days")
    await connection.execute_query("ANALYZE TABLE reservations")
    version_rows = await connection.execute_query_dict(
        "SELECT VERSION() AS version"
    )
    migration_rows = await connection.execute_query_dict(
        "SELECT version FROM aerich ORDER BY id"
    )
    day_lock_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM store_business_days "
        "WHERE business_date = %s FOR UPDATE",
        [BUSINESS_DATE],
    )
    user_page_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM reservations WHERE user_id = %s "
        "ORDER BY scheduled_start_at DESC, id DESC LIMIT 20",
        [users[0].id],
    )
    user_status_page_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM reservations "
        "WHERE user_id = %s AND status = %s "
        "ORDER BY scheduled_start_at DESC, id DESC LIMIT 20",
        [users[0].id, ReservationStatus.PENDING.value],
    )
    active_user_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT 1 FROM reservations "
        "WHERE user_id = %s AND status IN (%s, %s) "
        "AND scheduled_end_at > %s LIMIT 1",
        [
            users[0].id,
            ReservationStatus.PENDING.value,
            ReservationStatus.CONFIRMED.value,
            FROZEN_NOW,
        ],
    )
    closure_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM reservations "
        "WHERE business_day_id = %s AND status IN (%s, %s) "
        "AND scheduled_start_at > %s ORDER BY id FOR UPDATE",
        [
            business_days[0].id,
            ReservationStatus.PENDING.value,
            ReservationStatus.CONFIRMED.value,
            FROZEN_NOW,
        ],
    )
    status_page_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM reservations WHERE status = %s "
        "ORDER BY scheduled_start_at DESC, id DESC LIMIT 20",
        [ReservationStatus.PENDING.value],
    )

    assert version_rows[0]["version"].startswith("8.0.46")
    assert [row["version"] for row in migration_rows] == [
        "0_20260810101218_init.py",
        "1_20260813130455_add_order_tables.py",
        "2_20260814104655_add_inventory_transactions.py",
        "3_20260902125032_phase95_external_identity.py",
        "4_20260905162243_add_wallet_payment_refund.py",
        RESERVATION_MIGRATIONS[0].name,
        COLOR_SELECTABLE_KIT_MIGRATIONS[0].name,
        RESERVATION_SETTINGS_MIGRATIONS[0].name,
        BEAD_COLOR_SWATCH_HEX_MIGRATIONS[0].name,
    ]
    assert day_lock_plan[0]["key"] == "uidx_store_business_day_date"
    assert user_page_plan[0]["key"] == "idx_reservations_user_start_id"
    assert (
        user_status_page_plan[0]["key"]
        == "idx_reservations_user_status_start_id"
    )
    assert (
        active_user_plan[0]["key"]
        == "idx_reservations_user_status_end_id"
    )
    assert (
        closure_plan[0]["key"]
        == "idx_reservations_day_status_start_id"
    )
    assert status_page_plan[0]["key"] == "idx_reservations_status_start_id"
