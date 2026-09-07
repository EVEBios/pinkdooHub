"""Reservation 定向测试共享的最小数据构造器。"""

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationStatus,
)
from app.common.enums.user import UserRole, UserStatus
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.reservation import Reservation, StoreBusinessDay
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.reservation_service import ReservationService
from app.validators.reservation_validator import ReservationValidator

FROZEN_NOW = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
FROZEN_LOCAL_DATE = date(2026, 9, 8)  # Tuesday in Asia/Shanghai.


def make_service(*, now: datetime = FROZEN_NOW) -> ReservationService:
    """创建使用真实 Repository、但时钟固定的 ReservationService。"""

    return ReservationService(
        ReservationRepository(),
        ProductRepository(),
        UserRepository(),
        AuditLogService(AuditLogRepository()),
        now_provider=lambda: now,
    )


async def create_user(
    suffix: str,
    *,
    phone: str | None = "13800138000",
    role: UserRole = UserRole.USER,
    status: UserStatus = UserStatus.NORMAL,
    password: str = "hashed-password",
) -> User:
    """创建测试用户；调用方负责在同一测试内传入唯一 suffix/phone。"""

    digest = hashlib.sha256(suffix.encode("utf-8")).hexdigest()[:8]
    return await User.create(
        username=f"r-{suffix[:20]}-{digest}",
        password=password,
        nickname=f"预约用户{suffix}"[:32],
        phone=phone,
        role=int(role),
        status=int(status),
    )


async def create_option(
    suffix: str,
    *,
    duration: int = 60,
    participants: int = 2,
    day_type: DayType = DayType.WEEKDAY,
    price: Decimal = Decimal("88.50"),
    product_type: ProductType = ProductType.EXPERIENCE,
    product_status: ProductStatus = ProductStatus.ONLINE,
    product_deleted: bool = False,
    option_deleted: bool = False,
) -> tuple[Product, ExperienceOption]:
    """创建一个 Product/ExperienceOption 组合。"""

    product = await Product.create(
        name=f"预约体验{suffix}",
        product_type=product_type,
        status=product_status,
        is_deleted=product_deleted,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=duration,
        participants=participants,
        day_type=day_type,
        price=price,
        is_deleted=option_deleted,
    )
    return product, option


async def create_reservation_record(
    *,
    user: User,
    product: Product,
    option: ExperienceOption,
    business_date: date = FROZEN_LOCAL_DATE,
    local_start: time = time(11, 0),
    status: ReservationStatus = ReservationStatus.PENDING,
    rejection_reason: ReservationRejectionReason | None = None,
    cancellation_reason: ReservationCancellationReason | None = None,
    confirmed_at: datetime | None = None,
    rejected_at: datetime | None = None,
    cancelled_at: datetime | None = None,
) -> Reservation:
    """直接构造预约历史，供状态、店休和 Mapper 场景使用。"""

    business_day, _ = await StoreBusinessDay.get_or_create(
        business_date=business_date,
        defaults={"is_closed": False},
    )
    scheduled_start_at = ReservationValidator.build_scheduled_start(
        business_date=business_date,
        start_time=local_start,
    )
    scheduled_end_at = scheduled_start_at + timedelta(minutes=option.duration)
    return await Reservation.create(
        user=user,
        business_day=business_day,
        product=product,
        experience_option=option,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        product_name=product.name,
        option_duration_minutes=option.duration,
        option_participants=option.participants,
        option_day_type=option.day_type,
        option_price=option.price,
        status=status,
        rejection_reason=rejection_reason,
        cancellation_reason=cancellation_reason,
        confirmed_at=confirmed_at,
        rejected_at=rejected_at,
        cancelled_at=cancelled_at,
    )
