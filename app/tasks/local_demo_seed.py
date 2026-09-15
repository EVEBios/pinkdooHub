"""Prepare and verify comprehensive local-development demo data.

The command is deliberately limited to the repository-local SQLite database in
``development``.  Apply mode requires two explicit flags, creates a consistent
SQLite backup through the backup API, and stores passwords for *new synthetic
accounts only* in an ignored, mode-0600 JSON file.  Passwords are never logged.

The seed is resumable rather than globally atomic: every scenario owns a stable
username, order remark, or idempotency key.  A complete matching scenario is
reused, an incomplete scenario is advanced through the public service method,
and conflicting reserved data stops the command without rewriting it.  Expired
active Reservation samples remain as history; apply creates one new current
sample through ReservationService when the booking window has moved forward.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import io
import json
import logging
from pathlib import Path
from typing import Final

from tortoise import Tortoise
from tortoise.transactions import in_transaction

from app.common.bead_color import is_bead_color_configured
from app.common.constants.reservation import (
    DEFAULT_RESERVATION_WEEKLY_CLOSED_WEEKDAY,
    RESERVATION_AUDIT_ACTION_CANCEL,
    RESERVATION_BOOKING_WINDOW_DAYS,
    RESERVATION_MINIMUM_LEAD_HOURS,
    RESERVATION_SETTINGS_AUDIT_ACTION_UPDATE_WEEKLY_CLOSED_DAY,
    RESERVATION_SETTINGS_AUDIT_TARGET_TYPE,
    RESERVATION_WEEKDAY_NUMBERS,
)
from app.common.enums.order import OrderStatus
from app.common.enums.product import (
    KitKind,
    ProductStatus,
    ProductType,
)
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationStatus,
    ReservationWeekday,
)
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import (
    WalletStatus,
)
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.security import hash_password, verify_password
from app.db.database import TORTOISE_ORM
from app.models.audit_log import AuditLog
from app.models.bead_color import BeadColor
from app.models.order import Order
from app.models.product import Product
from app.models.product_kit_color import ProductKitColor
from app.models.reservation import Reservation, ReservationSettings, StoreBusinessDay
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import WalletRepository
from app.services.admin_user_service import AdminUserService
from app.services.audit_log_service import AuditLogService
from app.services.inventory_service import InventoryService
from app.services.order_service import OrderItemInput, OrderService
from app.services.payment_service import PaymentService
from app.services.product_service import ProductService
from app.services.refund_service import RefundService
from app.services.reservation_service import ReservationService
from app.services.wallet_service import WalletService
from app.storage.image import LocalImageStorage
from app.tasks.admin_product_functional_seed import (
    seed_admin_product_samples,
)
from app.tasks.product_functional_seed import (
    IN_STOCK_KIT_SEED_NAME,
    LOCAL_IP,
    MULTI_OPTION_SEED_NAME,
    PNG_BYTES,
    assert_local_seed_allowed,
    repair_legacy_seed_images,
    seed_in_stock_kit,
    seed_products,
)
from app.tasks.local_demo_support import (
    DEFAULT_BACKUP_DIR,
    DEFAULT_CREDENTIALS_FILE,
    LocalDemoSeedError,
    SYNTHETIC_USER_SPECS,
    SyntheticUserSpec,
    assert_path_in_repository,
    create_sqlite_backup,
    prepare_credentials,
    validate_credentials_path,
    verify_sqlite_integrity,
)
from app.tasks.local_demo_verify import (
    DemoVerificationSummary,
    verify_demo_data as run_demo_verifier,
)
from app.validators.reservation_validator import STORE_TIMEZONE


logger = logging.getLogger(__name__)

SEED_VERSION: Final = "v1"
SEED_PREFIX: Final = f"[LOCAL-DEMO:{SEED_VERSION}]"
COLOR_PRODUCT_NAME: Final = f"{SEED_PREFIX} 自选颜色 Kit"
OFFLINE_PRODUCT_NAME: Final = f"{SEED_PREFIX} 已下架固定 Kit"
COLOR_COUNT: Final = 3
DEMO_SWATCH_HEXES: Final = ("#C96F9A", "#73A8D6", "#E6BE63")
COLOR_INITIAL_STOCK: Final = 50
FIXED_SUPPLY_CHANGE: Final = 50
FIXED_SUPPLY_KEY: Final = "local-demo-v1-fixed-supply"
FIXED_SUPPLY_REASON: Final = "Local demo fixed Kit supply"
DEMO_WEEKLY_CLOSED_WEEKDAY: Final = ReservationWeekday.WEDNESDAY
ACTIVE_RESERVATION_STATUSES: Final = frozenset(
    {ReservationStatus.PENDING, ReservationStatus.CONFIRMED}
)


ORDER_REMARKS: Final = {
    "pending_fixed": f"{SEED_PREFIX} order:pending-fixed",
    "cancelled_mixed": f"{SEED_PREFIX} order:cancelled-mixed",
    "paid_manual_experience": f"{SEED_PREFIX} order:paid-manual-experience",
    "completed_manual_fixed_refunded": (
        f"{SEED_PREFIX} order:completed-manual-fixed-refunded"
    ),
    "paid_wallet_color": f"{SEED_PREFIX} order:paid-wallet-color",
    "completed_wallet_experience": (
        f"{SEED_PREFIX} order:completed-wallet-experience"
    ),
    "paid_wallet_mixed_refunded": (
        f"{SEED_PREFIX} order:paid-wallet-mixed-refunded"
    ),
    "assisted_wallet_fixed": f"{SEED_PREFIX} order:assisted-wallet-fixed",
}
EXPECTED_ORDER_STATUSES: Final = {
    "pending_fixed": OrderStatus.PENDING,
    "cancelled_mixed": OrderStatus.CANCELLED,
    "paid_manual_experience": OrderStatus.PAID,
    "completed_manual_fixed_refunded": OrderStatus.COMPLETED,
    "paid_wallet_color": OrderStatus.PAID,
    "completed_wallet_experience": OrderStatus.COMPLETED,
    "paid_wallet_mixed_refunded": OrderStatus.PAID,
    "assisted_wallet_fixed": OrderStatus.PAID,
}
RESERVATION_EXPECTATIONS: Final = {
    "localdemo_v1_res_pending": (
        ReservationStatus.PENDING,
        None,
        None,
    ),
    "localdemo_v1_res_confirmed": (
        ReservationStatus.CONFIRMED,
        None,
        None,
    ),
    "localdemo_v1_res_rejected": (
        ReservationStatus.REJECTED,
        ReservationRejectionReason.NO_CAPACITY,
        None,
    ),
    "localdemo_v1_res_cancel": (
        ReservationStatus.CANCELLED,
        None,
        ReservationCancellationReason.CUSTOMER_REQUEST,
    ),
    "localdemo_v1_res_closed": (
        ReservationStatus.CANCELLED,
        None,
        ReservationCancellationReason.STORE_CLOSED,
    ),
    "localdemo_v1_res_weekly": (
        ReservationStatus.CANCELLED,
        None,
        ReservationCancellationReason.STORE_CLOSED,
    ),
}


def _suppress_dependency_debug_logs() -> None:
    """Keep ORM bind parameters, including password hashes, out of CLI logs."""

    for logger_name in ("aiosqlite", "passlib", "tortoise"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


@dataclass(frozen=True, slots=True)
class DemoServices:
    product: ProductService
    inventory: InventoryService
    order: OrderService
    wallet: WalletService
    payment: PaymentService
    refund: RefundService
    reservation: ReservationService
    admin_user: AdminUserService


@dataclass(frozen=True, slots=True)
class DemoProducts:
    experience_product_id: int
    experience_option_id: int
    fixed_product_id: int
    color_product_id: int
    color_ids: tuple[int, ...]


def _services(
    *,
    now_provider: Callable[[], datetime] | None = None,
) -> DemoServices:
    user_repository = UserRepository()
    product_repository = ProductRepository()
    inventory_repository = InventoryRepository()
    order_repository = OrderRepository()
    payment_repository = PaymentRepository()
    wallet_repository = WalletRepository()
    reservation_repository = ReservationRepository()
    audit_log_service = AuditLogService(AuditLogRepository())
    return DemoServices(
        product=ProductService(product_repository, audit_log_service),
        inventory=InventoryService(
            inventory_repository,
            product_repository,
            audit_log_service,
        ),
        order=OrderService(
            order_repository,
            product_repository,
            inventory_repository,
            audit_log_service,
            user_repository=user_repository,
            payment_repository=payment_repository,
            wallet_repository=wallet_repository,
        ),
        wallet=WalletService(
            wallet_repository,
            user_repository,
            audit_log_service,
            payment_repository,
        ),
        payment=PaymentService(
            order_repository,
            payment_repository,
            wallet_repository,
            user_repository,
            audit_log_service,
        ),
        refund=RefundService(
            order_repository,
            payment_repository,
            wallet_repository,
            inventory_repository,
            user_repository,
            audit_log_service,
        ),
        reservation=ReservationService(
            reservation_repository,
            product_repository,
            user_repository,
            audit_log_service,
            now_provider=now_provider,
        ),
        admin_user=AdminUserService(user_repository, audit_log_service),
    )


async def _validate_operator(username: str) -> User:
    operator = await UserRepository().get_by_username(username)
    if operator is None:
        raise LocalDemoSeedError("Operator user was not found")
    if UserRole(operator.role) not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise LocalDemoSeedError("Operator must have ADMIN or SUPER_ADMIN role")
    if operator.status != UserStatus.NORMAL:
        raise LocalDemoSeedError("Operator must be enabled")
    return operator


async def _preflight_reservation_configuration(
    *,
    operator: User,
    now_utc: datetime,
) -> None:
    """Protect an existing local weekly-closure configuration before writes."""

    settings_rows = list(await ReservationSettings.all())
    if len(settings_rows) != 1 or not settings_rows[0].singleton_key:
        raise LocalDemoSeedError("M7 ReservationSettings singleton is invalid")
    settings_row = settings_rows[0]
    current_weekday = ReservationWeekday(settings_row.weekly_closed_weekday)
    settings_audits = list(
        await AuditLog.filter(
            action=RESERVATION_SETTINGS_AUDIT_ACTION_UPDATE_WEEKLY_CLOSED_DAY,
            target_type=RESERVATION_SETTINGS_AUDIT_TARGET_TYPE,
            target_id=settings_row.id,
        ).order_by("id")
    )

    weekly_user = await User.get_or_none(username="localdemo_v1_res_weekly")
    weekly_reservations = (
        []
        if weekly_user is None
        else list(await Reservation.filter(user_id=weekly_user.id).order_by("id"))
    )
    if len(weekly_reservations) > 1:
        raise LocalDemoSeedError("Reserved weekly-closure user owns multiple rows")
    weekly_reservation = weekly_reservations[0] if weekly_reservations else None

    if current_weekday is DEFAULT_RESERVATION_WEEKLY_CLOSED_WEEKDAY:
        if settings_audits:
            raise LocalDemoSeedError(
                "Existing weekly-closure history is not owned by this demo seed"
            )
        if weekly_reservation is not None and (
            ReservationStatus(weekly_reservation.status)
            is not ReservationStatus.PENDING
            or weekly_reservation.cancellation_reason is not None
            or _reservation_local_date(weekly_reservation).weekday()
            != RESERVATION_WEEKDAY_NUMBERS[DEMO_WEEKLY_CLOSED_WEEKDAY]
        ):
            raise LocalDemoSeedError(
                "Reserved weekly-closure Reservation is conflicting"
            )
        allowed_active_ids = (
            frozenset()
            if weekly_reservation is None
            else frozenset({weekly_reservation.id})
        )
    elif current_weekday is DEMO_WEEKLY_CLOSED_WEEKDAY:
        expected_description = (
            "from=monday;to=wednesday;cancelled_count=1"
        )
        if (
            weekly_reservation is None
            or ReservationStatus(weekly_reservation.status)
            is not ReservationStatus.CANCELLED
            or weekly_reservation.cancellation_reason
            is not ReservationCancellationReason.STORE_CLOSED
            or _reservation_local_date(weekly_reservation).weekday()
            != RESERVATION_WEEKDAY_NUMBERS[DEMO_WEEKLY_CLOSED_WEEKDAY]
            or len(settings_audits) != 1
            or settings_audits[0].operator_id != operator.id
            or settings_audits[0].description != expected_description
            or not await AuditLog.filter(
                action=RESERVATION_AUDIT_ACTION_CANCEL,
                target_type="reservation",
                target_id=weekly_reservation.id,
                operator_id=operator.id,
                description="reason=store_closed",
            ).exists()
        ):
            raise LocalDemoSeedError(
                "Existing Wednesday closure is not owned by this demo seed"
            )
        allowed_active_ids = frozenset()
    else:
        raise LocalDemoSeedError(
            "Existing weekly closed day must not be overwritten by demo data"
        )

    local_today = now_utc.astimezone(STORE_TIMEZONE).date()
    matching_dates = [
        local_today + timedelta(days=offset)
        for offset in range(RESERVATION_BOOKING_WINDOW_DAYS + 1)
        if (local_today + timedelta(days=offset)).weekday()
        == RESERVATION_WEEKDAY_NUMBERS[DEMO_WEEKLY_CLOSED_WEEKDAY]
    ]
    active_ids = frozenset(
        await Reservation.filter(
            business_day__business_date__in=matching_dates,
            status__in=[
                ReservationStatus.PENDING.value,
                ReservationStatus.CONFIRMED.value,
            ],
            scheduled_start_at__gt=now_utc,
        ).values_list("id", flat=True)
    )
    if active_ids != allowed_active_ids:
        raise LocalDemoSeedError(
            "Changing the weekly closed day would affect non-demo Reservations"
        )


async def _create_synthetic_user(
    spec: SyntheticUserSpec,
    *,
    password: str,
) -> User:
    user_repository = UserRepository()
    wallet_repository = WalletRepository()
    audit_log_service = AuditLogService(AuditLogRepository())
    async with in_transaction() as connection:
        user = await user_repository.create(
            username=spec.username,
            password=hash_password(password),
            nickname=spec.nickname,
            phone=spec.phone,
            role=UserRole.USER.value,
            status=UserStatus.NORMAL.value,
            using_db=connection,
        )
        await wallet_repository.create_account(
            user_id=user.id,
            using_db=connection,
        )
        await audit_log_service.log(
            operator_id=user.id,
            action="REGISTER",
            target_type="user",
            target_id=user.id,
            ip_address=LOCAL_IP,
            using_db=connection,
        )
    return user


def _validate_synthetic_user(
    user: User,
    spec: SyntheticUserSpec,
    *,
    password: str,
) -> None:
    if (
        user.username != spec.username
        or user.nickname != spec.nickname
        or user.phone != spec.phone
        or UserRole(user.role) is not UserRole.USER
        or user.status == UserStatus.DELETED
        or user.password is None
        or not verify_password(password, user.password)
    ):
        raise LocalDemoSeedError(
            f"Reserved synthetic user is conflicting: {spec.username}"
        )


async def ensure_synthetic_users(
    *,
    operator: User,
    passwords: dict[str, str],
    admin_user_service: AdminUserService,
) -> dict[str, User]:
    """Create or validate script-owned customers without touching existing users."""

    users: dict[str, User] = {}
    repository = UserRepository()
    for spec in SYNTHETIC_USER_SPECS:
        password = passwords[spec.username]
        user = await repository.get_by_username(spec.username)
        phone_owner = await repository.get_by_phone(spec.phone)
        if user is None:
            if phone_owner is not None:
                raise LocalDemoSeedError(
                    f"Synthetic phone is already in use: {spec.username}"
                )
            user = await _create_synthetic_user(spec, password=password)
        elif phone_owner is None or phone_owner.id != user.id:
            raise LocalDemoSeedError(
                f"Reserved synthetic user phone is conflicting: {spec.username}"
            )
        _validate_synthetic_user(user, spec, password=password)

        account = await WalletRepository().get_account_by_user_id(user.id)
        if (
            account is None
            or WalletStatus(account.status) is not WalletStatus.ACTIVE
        ):
            raise LocalDemoSeedError(
                f"Reserved synthetic user wallet is conflicting: {spec.username}"
            )
        if spec.expected_status is UserStatus.DISABLED:
            if UserStatus(user.status) is UserStatus.NORMAL:
                await admin_user_service.disable_user(operator, user.id, LOCAL_IP)
                user = await repository.get_by_id(user.id)
                assert user is not None
            if UserStatus(user.status) is not UserStatus.DISABLED:
                raise LocalDemoSeedError(
                    f"Reserved synthetic disabled user is conflicting: {spec.username}"
                )
        elif UserStatus(user.status) is not UserStatus.NORMAL:
            raise LocalDemoSeedError(
                f"Reserved synthetic user must remain enabled: {spec.username}"
            )
        users[spec.username] = user
    return users


async def _exact_product(service: ProductService, name: str) -> Product | None:
    page = await service.list_admin_products(
        page=1,
        page_size=100,
        keyword=name,
        include_deleted=True,
    )
    exact = [product for product in page.items if product.name == name]
    if len(exact) > 1:
        raise LocalDemoSeedError(f"Reserved Product name is not unique: {name}")
    return exact[0] if exact else None


async def _store_product_cover(
    service: ProductService,
    storage: LocalImageStorage,
    *,
    product_id: int,
    operator_id: int,
) -> None:
    """Save a tiny valid PNG and compensate it if DB registration fails."""

    stored = storage.save(
        io.BytesIO(PNG_BYTES),
        declared_media_type="image/png",
    )
    try:
        await service.create_product_image(
            product_id,
            image_url=stored.url,
            is_cover=True,
            sort=0,
            operator_id=operator_id,
            ip_address=LOCAL_IP,
        )
    except BaseException:
        storage.delete(stored.key)
        raise


async def _ensure_offline_product(
    services: DemoServices,
    storage: LocalImageStorage,
    *,
    operator_id: int,
) -> int:
    product = await _exact_product(services.product, OFFLINE_PRODUCT_NAME)
    common = {"operator_id": operator_id, "ip_address": LOCAL_IP}
    if product is None:
        product = await services.product.create_kit_product(
            name=OFFLINE_PRODUCT_NAME,
            description="本地管理端筛选与生命周期演示数据。",
            price=Decimal("18.00"),
            **common,
        )
    if (
        ProductType(product.product_type) is not ProductType.KIT
        or product.is_deleted
        or product.status not in (
            ProductStatus.DRAFT,
            ProductStatus.ONLINE,
            ProductStatus.OFFLINE,
        )
    ):
        raise LocalDemoSeedError("Reserved offline Product is conflicting")
    detail = await services.product.get_admin_product_detail(
        product.id,
        product_type=ProductType.KIT,
    )
    if KitKind(detail.kit.kit_kind) is not KitKind.FIXED:
        raise LocalDemoSeedError("Reserved offline Product Kit kind is conflicting")
    if not list(detail.images):
        await _store_product_cover(
            services.product,
            storage,
            product_id=product.id,
            operator_id=operator_id,
        )
    if ProductStatus(product.status) is ProductStatus.DRAFT:
        product = await services.product.online_product(product.id, **common)
    if ProductStatus(product.status) is ProductStatus.ONLINE:
        product = await services.product.offline_product(product.id, **common)
    if ProductStatus(product.status) is not ProductStatus.OFFLINE:
        raise LocalDemoSeedError("Reserved offline Product did not converge")
    return product.id


async def _configured_colors_for_demo(
    services: DemoServices,
    *,
    operator_id: int,
) -> list[BeadColor]:
    configured_candidates = list(
        await BeadColor.filter(
            is_active=True,
            color_code__not_isnull=True,
            name__not_isnull=True,
            swatch_hex__not_isnull=True,
        )
        .order_by("slot_no")
    )
    configured = [
        color
        for color in configured_candidates
        if is_bead_color_configured(
            color_code=color.color_code,
            name=color.name,
            swatch_hex=color.swatch_hex,
        )
    ][:COLOR_COUNT]
    if len(configured) >= COLOR_COUNT:
        return configured

    configured_ids = {color.id for color in configured}
    blank = list(
        await BeadColor.filter(
            color_code__isnull=True,
            name__isnull=True,
            is_active=False,
        )
        .exclude(id__in=configured_ids)
        .order_by("slot_no")
        .limit(COLOR_COUNT - len(configured))
    )
    if len(configured) + len(blank) < COLOR_COUNT:
        raise LocalDemoSeedError(
            "At least three configured active or completely blank color slots "
            "are required"
        )
    for color_index, color in enumerate(blank, start=len(configured)):
        updated = await services.product.update_bead_color(
            color.id,
            updates={
                "color_code": f"LOCAL{color.slot_no:03d}",
                "name": f"本地演示色 {color.slot_no:03d}",
                "swatch_hex": (
                    color.swatch_hex
                    or DEMO_SWATCH_HEXES[color_index % len(DEMO_SWATCH_HEXES)]
                ),
                "sort": color.slot_no,
                "is_active": True,
            },
            operator_id=operator_id,
            ip_address=LOCAL_IP,
        )
        configured.append(updated)
    return sorted(configured, key=lambda color: color.slot_no)


async def _ensure_color_product(
    services: DemoServices,
    storage: LocalImageStorage,
    *,
    operator_id: int,
) -> tuple[int, tuple[int, ...]]:
    product = await _exact_product(services.product, COLOR_PRODUCT_NAME)
    common = {"operator_id": operator_id, "ip_address": LOCAL_IP}
    if product is None:
        product = await services.product.create_kit_product(
            name=COLOR_PRODUCT_NAME,
            description="本地自选颜色、库存、订单与退款联调数据。",
            price=Decimal("3.00"),
            kit_kind=KitKind.COLOR_SELECTABLE,
            **common,
        )
    if (
        ProductType(product.product_type) is not ProductType.KIT
        or product.is_deleted
        or product.status not in (
            ProductStatus.DRAFT,
            ProductStatus.ONLINE,
            ProductStatus.OFFLINE,
        )
    ):
        raise LocalDemoSeedError("Reserved color Product is conflicting")
    detail = await services.product.get_admin_product_detail(
        product.id,
        product_type=ProductType.KIT,
    )
    if (
        KitKind(detail.kit.kit_kind) is not KitKind.COLOR_SELECTABLE
        or detail.kit.sale_unit_grams != 10
        or detail.kit.stock is not None
        or len(list(detail.kit_colors)) != 221
    ):
        raise LocalDemoSeedError("Reserved color Product aggregate is conflicting")

    colors = await _configured_colors_for_demo(
        services,
        operator_id=operator_id,
    )
    mapping_by_bead_id = {
        mapping.bead_color_id: mapping for mapping in detail.kit_colors
    }
    selected_mappings: list[ProductKitColor] = []
    if ProductStatus(product.status) is ProductStatus.ONLINE:
        enabled = sorted(
            (mapping for mapping in detail.kit_colors if mapping.is_enabled),
            key=lambda mapping: mapping.bead_color.slot_no,
        )
        if len(enabled) < COLOR_COUNT:
            raise LocalDemoSeedError(
                "Reserved Online color Product has too few enabled colors"
            )
        selected_mappings = enabled[:COLOR_COUNT]
    else:
        for color in colors:
            mapping = mapping_by_bead_id[color.id]
            if not mapping.is_enabled:
                mapping = await services.product.update_product_kit_color(
                    mapping.id,
                    is_enabled=True,
                    **common,
                )
            selected_mappings.append(mapping)

    if not list(detail.images):
        await _store_product_cover(
            services.product,
            storage,
            product_id=product.id,
            operator_id=operator_id,
        )
    for mapping in selected_mappings:
        await services.inventory.adjust_color_stock(
            product.id,
            mapping.id,
            change=COLOR_INITIAL_STOCK,
            reason="Local demo color stock supply",
            operator_id=operator_id,
            ip_address=LOCAL_IP,
            idempotency_key=(
                f"local-demo-v1-color-supply-slot-{mapping.bead_color.slot_no}"
            ),
        )
    if ProductStatus(product.status) is not ProductStatus.ONLINE:
        await services.product.online_product(product.id, **common)

    refreshed = await services.product.get_admin_product_detail(
        product.id,
        product_type=ProductType.KIT,
    )
    refreshed_by_id = {mapping.id: mapping for mapping in refreshed.kit_colors}
    for mapping in selected_mappings:
        current = refreshed_by_id[mapping.id]
        if not current.is_enabled or current.stock_units < 1:
            raise LocalDemoSeedError("Reserved demo color stock was consumed")
    return product.id, tuple(mapping.id for mapping in selected_mappings)


async def ensure_demo_products(
    services: DemoServices,
    storage: LocalImageStorage,
    *,
    operator_id: int,
) -> DemoProducts:
    await repair_legacy_seed_images(services.product, storage)
    await seed_products(services.product, storage, operator_id=operator_id)
    await seed_in_stock_kit(
        services.product,
        services.inventory,
        operator_id=operator_id,
    )
    await seed_admin_product_samples(services.product, operator_id=operator_id)
    await _ensure_offline_product(services, storage, operator_id=operator_id)
    color_product_id, color_ids = await _ensure_color_product(
        services,
        storage,
        operator_id=operator_id,
    )

    fixed = await _exact_product(services.product, IN_STOCK_KIT_SEED_NAME)
    experience = await _exact_product(services.product, MULTI_OPTION_SEED_NAME)
    if fixed is None or experience is None:
        raise LocalDemoSeedError("Required Product functional seed is missing")
    experience_detail = await services.product.get_admin_product_detail(
        experience.id,
        product_type=ProductType.EXPERIENCE,
    )
    options = sorted(experience_detail.experience_options, key=lambda item: item.id)
    if len(options) < 2:
        raise LocalDemoSeedError("Multi-option Experience seed is incomplete")
    await services.inventory.adjust_stock(
        fixed.id,
        change=FIXED_SUPPLY_CHANGE,
        reason=FIXED_SUPPLY_REASON,
        operator_id=operator_id,
        ip_address=LOCAL_IP,
        idempotency_key=FIXED_SUPPLY_KEY,
    )
    fixed_detail = await services.product.get_admin_product_detail(
        fixed.id,
        product_type=ProductType.KIT,
    )
    if fixed_detail.kit.stock is None or fixed_detail.kit.stock < 5:
        raise LocalDemoSeedError("Reserved fixed Kit stock was consumed")
    return DemoProducts(
        experience_product_id=experience.id,
        experience_option_id=options[0].id,
        fixed_product_id=fixed.id,
        color_product_id=color_product_id,
        color_ids=color_ids,
    )


async def _order_by_scenario(
    services: DemoServices,
    *,
    user_id: int,
    scenario: str,
    items: list[OrderItemInput],
) -> Order:
    remark = ORDER_REMARKS[scenario]
    matches = list(await Order.filter(user_id=user_id, remark=remark))
    if len(matches) > 1:
        raise LocalDemoSeedError(f"Reserved Order scenario is duplicated: {scenario}")
    if not matches:
        return await services.order.create_order(
            user_id=user_id,
            items=items,
            remark=remark,
            ip_address=LOCAL_IP,
        )
    detail = await services.order.get_user_order_detail(
        matches[0].id,
        user_id=user_id,
    )
    expected = [
        (
            item.product_id,
            item.experience_option_id,
            item.kit_color_id,
            item.quantity,
        )
        for item in items
    ]
    actual = [
        (
            item.product_id,
            item.experience_option_id,
            item.kit_color_id,
            item.quantity,
        )
        for item in detail.items
    ]
    if actual != expected:
        raise LocalDemoSeedError(f"Reserved Order scenario is conflicting: {scenario}")
    return detail


async def _mark_paid_if_pending(
    services: DemoServices,
    order: Order,
    *,
    operator_id: int,
) -> Order:
    status = OrderStatus(order.status)
    if status is OrderStatus.PENDING:
        return await services.order.mark_order_paid(
            order.id,
            operator_id=operator_id,
            ip_address=LOCAL_IP,
        )
    if status not in (OrderStatus.PAID, OrderStatus.COMPLETED):
        raise LocalDemoSeedError("Manual-payment Order has an invalid status")
    return order


async def _complete_if_paid(
    services: DemoServices,
    order: Order,
    *,
    operator_id: int,
) -> Order:
    status = OrderStatus(order.status)
    if status is OrderStatus.PAID:
        return await services.order.complete_order(
            order.id,
            operator_id=operator_id,
            ip_address=LOCAL_IP,
        )
    if status is not OrderStatus.COMPLETED:
        raise LocalDemoSeedError("Completed Order scenario has an invalid status")
    return order


async def ensure_demo_orders_and_financials(
    services: DemoServices,
    products: DemoProducts,
    users: dict[str, User],
    *,
    operator: User,
) -> dict[str, Order]:
    owner = users["localdemo_v1_orders"]
    assisted_owner = users["localdemo_v1_assisted"]
    fixed_item = OrderItemInput(products.fixed_product_id, None, 1)
    experience_item = OrderItemInput(
        products.experience_product_id,
        products.experience_option_id,
        1,
    )
    first_color_item = OrderItemInput(
        products.color_product_id,
        None,
        2,
        products.color_ids[0],
    )
    second_color_item = OrderItemInput(
        products.color_product_id,
        None,
        1,
        products.color_ids[1],
    )

    for username, change, key in (
        ("localdemo_v1_orders", Decimal("600.00"), "orders-initial"),
        ("localdemo_v1_assisted", Decimal("200.00"), "assisted-initial"),
    ):
        await services.wallet.adjust_balance(
            operator=operator,
            user_id=users[username].id,
            change=change,
            reason="Local demo opening wallet adjustment",
            idempotency_key=f"local-demo-v1-{key}",
            ip_address=LOCAL_IP,
        )

    orders: dict[str, Order] = {}
    orders["pending_fixed"] = await _order_by_scenario(
        services,
        user_id=owner.id,
        scenario="pending_fixed",
        items=[fixed_item],
    )
    cancelled = await _order_by_scenario(
        services,
        user_id=owner.id,
        scenario="cancelled_mixed",
        items=[fixed_item, first_color_item],
    )
    if OrderStatus(cancelled.status) is OrderStatus.PENDING:
        cancelled = await services.order.cancel_order(
            cancelled.id,
            user_id=owner.id,
            ip_address=LOCAL_IP,
        )
    if OrderStatus(cancelled.status) is not OrderStatus.CANCELLED:
        raise LocalDemoSeedError("Cancelled Order scenario has an invalid status")
    orders["cancelled_mixed"] = cancelled

    paid_manual = await _order_by_scenario(
        services,
        user_id=owner.id,
        scenario="paid_manual_experience",
        items=[experience_item],
    )
    orders["paid_manual_experience"] = await _mark_paid_if_pending(
        services,
        paid_manual,
        operator_id=operator.id,
    )

    completed_manual = await _order_by_scenario(
        services,
        user_id=owner.id,
        scenario="completed_manual_fixed_refunded",
        items=[fixed_item],
    )
    completed_manual = await _mark_paid_if_pending(
        services,
        completed_manual,
        operator_id=operator.id,
    )
    completed_manual = await _complete_if_paid(
        services,
        completed_manual,
        operator_id=operator.id,
    )
    await services.refund.refund_order(
        completed_manual.id,
        operator=operator,
        reason="Local demo completed manual refund",
        idempotency_key="local-demo-v1-refund-completed-manual",
        ip_address=LOCAL_IP,
    )
    orders["completed_manual_fixed_refunded"] = completed_manual

    paid_wallet_color = await _order_by_scenario(
        services,
        user_id=owner.id,
        scenario="paid_wallet_color",
        items=[first_color_item],
    )
    await services.payment.pay_order_with_wallet(
        paid_wallet_color.id,
        user=owner,
        idempotency_key="local-demo-v1-pay-color",
        ip_address=LOCAL_IP,
    )
    orders["paid_wallet_color"] = await services.order.get_user_order_detail(
        paid_wallet_color.id,
        user_id=owner.id,
    )

    completed_wallet = await _order_by_scenario(
        services,
        user_id=owner.id,
        scenario="completed_wallet_experience",
        items=[experience_item],
    )
    await services.payment.pay_order_with_wallet(
        completed_wallet.id,
        user=owner,
        idempotency_key="local-demo-v1-pay-completed-experience",
        ip_address=LOCAL_IP,
    )
    completed_wallet = await services.order.get_user_order_detail(
        completed_wallet.id,
        user_id=owner.id,
    )
    completed_wallet = await _complete_if_paid(
        services,
        completed_wallet,
        operator_id=operator.id,
    )
    orders["completed_wallet_experience"] = completed_wallet

    refunded_wallet = await _order_by_scenario(
        services,
        user_id=owner.id,
        scenario="paid_wallet_mixed_refunded",
        items=[fixed_item, second_color_item],
    )
    await services.payment.pay_order_with_wallet(
        refunded_wallet.id,
        user=owner,
        idempotency_key="local-demo-v1-pay-mixed-refund",
        ip_address=LOCAL_IP,
    )
    await services.refund.refund_order(
        refunded_wallet.id,
        operator=operator,
        reason="Local demo paid wallet refund",
        idempotency_key="local-demo-v1-refund-paid-wallet",
        ip_address=LOCAL_IP,
    )
    orders["paid_wallet_mixed_refunded"] = (
        await services.order.get_user_order_detail(
            refunded_wallet.id,
            user_id=owner.id,
        )
    )

    assisted = await services.order.create_assisted_wallet_order(
        operator=operator,
        user_id=assisted_owner.id,
        items=[fixed_item],
        remark=ORDER_REMARKS["assisted_wallet_fixed"],
        idempotency_key="local-demo-v1-assisted-fixed",
        ip_address=LOCAL_IP,
    )
    orders["assisted_wallet_fixed"] = assisted.order

    await services.wallet.adjust_balance(
        operator=operator,
        user_id=owner.id,
        change=Decimal("-5.00"),
        reason="Local demo negative adjustment",
        idempotency_key="local-demo-v1-orders-negative",
        ip_address=LOCAL_IP,
    )
    return orders


def _reservation_local_date(reservation: Reservation) -> date:
    return reservation.scheduled_start_at.astimezone(STORE_TIMEZONE).date()


def _is_in_current_booking_window(
    reservation: Reservation,
    *,
    now_utc: datetime,
) -> bool:
    local_today = now_utc.astimezone(STORE_TIMEZONE).date()
    business_date = _reservation_local_date(reservation)
    return (
        reservation.scheduled_start_at
        >= now_utc + timedelta(hours=RESERVATION_MINIMUM_LEAD_HOURS)
        and local_today
        <= business_date
        <= local_today + timedelta(days=RESERVATION_BOOKING_WINDOW_DAYS)
    )


async def _assert_store_day_close_is_demo_only(
    business_date: date,
    *,
    allowed_reservation_ids: frozenset[int],
    now_utc: datetime,
) -> None:
    """Refuse a local demo closure that would cancel another reservation."""

    affected_ids = set(
        await Reservation.filter(
            business_day__business_date=business_date,
            status__in=[
                ReservationStatus.PENDING.value,
                ReservationStatus.CONFIRMED.value,
            ],
            scheduled_start_at__gt=now_utc,
        ).values_list("id", flat=True)
    )
    if affected_ids != set(allowed_reservation_ids):
        raise LocalDemoSeedError(
            "Closing the demo business day would affect non-demo Reservations"
        )


async def _create_reservation_on_unused_date(
    service: ReservationService,
    *,
    user_id: int,
    option_ids: tuple[int, ...],
    used_dates: set[date],
    required_weekday: ReservationWeekday | None = None,
    excluded_weekdays: frozenset[ReservationWeekday] = frozenset(),
    prefer_latest_date: bool = False,
) -> Reservation:
    required_number = (
        RESERVATION_WEEKDAY_NUMBERS[required_weekday]
        if required_weekday is not None
        else None
    )
    excluded_numbers = {
        RESERVATION_WEEKDAY_NUMBERS[weekday] for weekday in excluded_weekdays
    }
    for option_id in option_ids:
        booking = await service.get_booking_options(
            experience_option_id=option_id,
        )
        booking_dates = (
            reversed(booking.dates) if prefer_latest_date else booking.dates
        )
        for booking_date in booking_dates:
            weekday_number = booking_date.date.weekday()
            if (
                booking_date.date in used_dates
                or weekday_number in excluded_numbers
                or (
                    required_number is not None
                    and weekday_number != required_number
                )
            ):
                continue
            reservation = await service.create_reservation(
                user_id=user_id,
                experience_option_id=option_id,
                reservation_date=booking_date.date,
                start_time=booking_date.start_times[0],
                ip_address=LOCAL_IP,
            )
            used_dates.add(booking_date.date)
            return reservation
    raise LocalDemoSeedError("No distinct reservation date is available")


async def _ensure_reservation(
    services: DemoServices,
    *,
    user: User,
    option_ids: tuple[int, ...],
    used_dates: set[date],
    expected_status: ReservationStatus,
    now_utc: datetime,
    required_weekday: ReservationWeekday | None = None,
    excluded_weekdays: frozenset[ReservationWeekday] = frozenset(),
) -> Reservation:
    reservations = list(await Reservation.filter(user_id=user.id).order_by("id"))
    if expected_status in ACTIVE_RESERVATION_STATUSES:
        resumable_statuses = {expected_status}
        if expected_status is ReservationStatus.CONFIRMED:
            resumable_statuses.add(ReservationStatus.PENDING)
        current_reservations: list[Reservation] = []
        minimum_start = now_utc + timedelta(
            hours=RESERVATION_MINIMUM_LEAD_HOURS
        )
        for existing in reservations:
            business_date = _reservation_local_date(existing)
            if (
                required_weekday is not None
                and business_date.weekday()
                != RESERVATION_WEEKDAY_NUMBERS[required_weekday]
            ) or business_date.weekday() in {
                RESERVATION_WEEKDAY_NUMBERS[weekday]
                for weekday in excluded_weekdays
            }:
                raise LocalDemoSeedError("Reserved Reservation date is conflicting")
            current_status = ReservationStatus(existing.status)
            if (
                current_status not in resumable_statuses
                or existing.rejection_reason is not None
                or existing.cancellation_reason is not None
            ):
                raise LocalDemoSeedError(
                    "Reserved active Reservation history is conflicting"
                )
            if _is_in_current_booking_window(existing, now_utc=now_utc):
                current_reservations.append(existing)
            elif existing.scheduled_start_at >= minimum_start:
                raise LocalDemoSeedError(
                    "Reserved active Reservation is beyond the booking window"
                )
            used_dates.add(business_date)
        if len(current_reservations) > 1:
            raise LocalDemoSeedError(
                "Reserved active Reservation user owns multiple current rows"
            )
        if current_reservations:
            return current_reservations[0]
        return await _create_reservation_on_unused_date(
            services.reservation,
            user_id=user.id,
            option_ids=option_ids,
            used_dates=used_dates,
            required_weekday=required_weekday,
            excluded_weekdays=excluded_weekdays,
            prefer_latest_date=True,
        )

    if len(reservations) > 1:
        raise LocalDemoSeedError("Reserved Reservation user owns multiple rows")
    if reservations:
        existing = reservations[0]
        business_date = _reservation_local_date(existing)
        if (
            required_weekday is not None
            and business_date.weekday()
            != RESERVATION_WEEKDAY_NUMBERS[required_weekday]
        ) or business_date.weekday() in {
            RESERVATION_WEEKDAY_NUMBERS[weekday]
            for weekday in excluded_weekdays
        }:
            raise LocalDemoSeedError("Reserved Reservation date is conflicting")
        used_dates.add(business_date)
        return existing
    return await _create_reservation_on_unused_date(
        services.reservation,
        user_id=user.id,
        option_ids=option_ids,
        used_dates=used_dates,
        required_weekday=required_weekday,
        excluded_weekdays=excluded_weekdays,
    )


async def ensure_demo_reservations(
    services: DemoServices,
    users: dict[str, User],
    products: DemoProducts,
    *,
    operator_id: int,
    now_utc: datetime,
) -> dict[str, Reservation]:
    experience = await services.product.get_admin_product_detail(
        products.experience_product_id,
        product_type=ProductType.EXPERIENCE,
    )
    option_ids = tuple(option.id for option in experience.experience_options)
    used_dates: set[date] = set()
    result: dict[str, Reservation] = {}

    weekly_username = "localdemo_v1_res_weekly"
    for username in RESERVATION_EXPECTATIONS:
        is_weekly_scenario = username == weekly_username
        reservation = await _ensure_reservation(
            services,
            user=users[username],
            option_ids=option_ids,
            used_dates=used_dates,
            expected_status=RESERVATION_EXPECTATIONS[username][0],
            now_utc=now_utc,
            required_weekday=(
                DEMO_WEEKLY_CLOSED_WEEKDAY if is_weekly_scenario else None
            ),
            excluded_weekdays=(
                frozenset()
                if is_weekly_scenario
                else frozenset({DEMO_WEEKLY_CLOSED_WEEKDAY})
            ),
        )
        result[username] = reservation

    for username, reservation in result.items():
        if username == weekly_username:
            continue
        current = ReservationStatus(reservation.status)
        if username == "localdemo_v1_res_confirmed":
            if current is ReservationStatus.PENDING:
                reservation = await services.reservation.confirm_reservation(
                    reservation.id,
                    operator_id=operator_id,
                    ip_address=LOCAL_IP,
                )
        elif username == "localdemo_v1_res_rejected":
            if current is ReservationStatus.PENDING:
                reservation = await services.reservation.reject_reservation(
                    reservation.id,
                    operator_id=operator_id,
                    ip_address=LOCAL_IP,
                )
        elif username == "localdemo_v1_res_cancel":
            if current in (ReservationStatus.PENDING, ReservationStatus.CONFIRMED):
                reservation = await services.reservation.cancel_reservation(
                    reservation.id,
                    user_id=users[username].id,
                    ip_address=LOCAL_IP,
                )
            business_date = _reservation_local_date(reservation)
            business_day = await StoreBusinessDay.get(business_date=business_date)
            close_count = await AuditLog.filter(
                action="CLOSE_STORE_BUSINESS_DAY",
                target_type="store_business_day",
                target_id=business_day.id,
                operator_id=operator_id,
            ).count()
            reopen_count = await AuditLog.filter(
                action="REOPEN_STORE_BUSINESS_DAY",
                target_type="store_business_day",
                target_id=business_day.id,
                operator_id=operator_id,
            ).count()
            if business_day.is_closed:
                await services.reservation.reopen_store_day(
                    business_date,
                    operator_id=operator_id,
                    ip_address=LOCAL_IP,
                )
            elif not close_count and not reopen_count:
                await _assert_store_day_close_is_demo_only(
                    business_date,
                    allowed_reservation_ids=frozenset(),
                    now_utc=now_utc,
                )
                await services.reservation.close_store_day(
                    business_date,
                    operator_id=operator_id,
                    ip_address=LOCAL_IP,
                )
                await services.reservation.reopen_store_day(
                    business_date,
                    operator_id=operator_id,
                    ip_address=LOCAL_IP,
                )
            elif close_count != reopen_count:
                raise LocalDemoSeedError("Reopened business-day audit is conflicting")
        elif username == "localdemo_v1_res_closed":
            if current is ReservationStatus.PENDING:
                business_date = _reservation_local_date(reservation)
                await _assert_store_day_close_is_demo_only(
                    business_date,
                    allowed_reservation_ids=frozenset({reservation.id}),
                    now_utc=now_utc,
                )
                await services.reservation.close_store_day(
                    business_date,
                    operator_id=operator_id,
                    ip_address=LOCAL_IP,
                )
                reservation = await services.reservation.get_admin_reservation_detail(
                    reservation.id
                )
        result[username] = reservation

    weekly_reservation = result[weekly_username]
    settings_rows = list(await ReservationSettings.all())
    if len(settings_rows) != 1:
        raise LocalDemoSeedError("M7 ReservationSettings singleton is invalid")
    current_weekday = ReservationWeekday(
        settings_rows[0].weekly_closed_weekday
    )
    current_weekly_status = ReservationStatus(weekly_reservation.status)
    if current_weekday is DEMO_WEEKLY_CLOSED_WEEKDAY:
        if (
            current_weekly_status is not ReservationStatus.CANCELLED
            or weekly_reservation.cancellation_reason
            is not ReservationCancellationReason.STORE_CLOSED
        ):
            raise LocalDemoSeedError(
                "Weekly closure setting exists without its reserved cancellation"
            )
    else:
        if current_weekly_status is not ReservationStatus.PENDING:
            raise LocalDemoSeedError(
                "Reserved weekly-closure Reservation is not pending"
            )
        local_today = now_utc.astimezone(STORE_TIMEZONE).date()
        matching_dates = [
            local_today + timedelta(days=offset)
            for offset in range(RESERVATION_BOOKING_WINDOW_DAYS + 1)
            if (local_today + timedelta(days=offset)).weekday()
            == RESERVATION_WEEKDAY_NUMBERS[DEMO_WEEKLY_CLOSED_WEEKDAY]
        ]
        affected = list(
            await Reservation.filter(
                business_day__business_date__in=matching_dates,
                status__in=[
                    ReservationStatus.PENDING.value,
                    ReservationStatus.CONFIRMED.value,
                ],
                scheduled_start_at__gt=now_utc,
            ).order_by("id")
        )
        if {reservation.id for reservation in affected} != {
            weekly_reservation.id
        }:
            raise LocalDemoSeedError(
                "Changing the weekly closed day would affect non-demo Reservations"
            )
        mutation = await services.reservation.update_weekly_closed_day(
            weekly_closed_weekday=DEMO_WEEKLY_CLOSED_WEEKDAY,
            operator_id=operator_id,
            ip_address=LOCAL_IP,
        )
        if mutation.is_replay or mutation.newly_cancelled_count != 1:
            raise LocalDemoSeedError("Weekly closure mutation did not converge")
        weekly_reservation = (
            await services.reservation.get_admin_reservation_detail(
                weekly_reservation.id
            )
        )
        result[weekly_username] = weekly_reservation

    audit_count_before_replay = await AuditLog.filter(
        action="UPDATE_WEEKLY_CLOSED_DAY",
        target_type="reservation_settings",
        target_id=settings_rows[0].id,
    ).count()
    replay = await services.reservation.update_weekly_closed_day(
        weekly_closed_weekday=DEMO_WEEKLY_CLOSED_WEEKDAY,
        operator_id=operator_id,
        ip_address=LOCAL_IP,
    )
    audit_count_after_replay = await AuditLog.filter(
        action="UPDATE_WEEKLY_CLOSED_DAY",
        target_type="reservation_settings",
        target_id=settings_rows[0].id,
    ).count()
    if (
        not replay.is_replay
        or replay.newly_cancelled_count
        or audit_count_after_replay != audit_count_before_replay
    ):
        raise LocalDemoSeedError("Weekly closure replay produced a write")

    for username, reservation in result.items():
        expected_status, expected_rejection, expected_cancellation = (
            RESERVATION_EXPECTATIONS[username]
        )
        actual_rejection = (
            ReservationRejectionReason(reservation.rejection_reason)
            if reservation.rejection_reason is not None
            else None
        )
        actual_cancellation = (
            ReservationCancellationReason(reservation.cancellation_reason)
            if reservation.cancellation_reason is not None
            else None
        )
        if (
            ReservationStatus(reservation.status) is not expected_status
            or actual_rejection is not expected_rejection
            or actual_cancellation is not expected_cancellation
        ):
            raise LocalDemoSeedError(
                f"Reserved Reservation scenario is conflicting: {username}"
            )
    return result


async def verify_demo_data(
    *,
    now_utc: datetime | None = None,
    image_storage: LocalImageStorage | None = None,
) -> DemoVerificationSummary:
    """Run the dedicated read-only verifier with this seed contract."""

    storage = image_storage or LocalImageStorage(
        root=Path(settings.product_image_upload_dir),
        base_url=settings.product_image_base_url,
    )
    return await run_demo_verifier(
        color_product_name=COLOR_PRODUCT_NAME,
        offline_product_name=OFFLINE_PRODUCT_NAME,
        color_count=COLOR_COUNT,
        order_remarks=ORDER_REMARKS,
        expected_order_statuses=EXPECTED_ORDER_STATUSES,
        reservation_expectations=RESERVATION_EXPECTATIONS,
        weekly_closed_weekday=DEMO_WEEKLY_CLOSED_WEEKDAY,
        now_utc=now_utc,
        image_storage=storage,
    )


async def seed_local_demo_data(
    *,
    operator_username: str,
    credentials_file: Path,
    storage_root: Path,
    storage_base_url: str,
    now_provider: Callable[[], datetime] | None = None,
) -> DemoVerificationSummary:
    """Resume all local scenarios, then run the read-only verifier."""

    now_utc = (
        now_provider() if now_provider is not None else datetime.now(timezone.utc)
    )
    if now_utc.tzinfo is None:
        raise LocalDemoSeedError("now_provider must return a timezone-aware datetime")
    now_utc = now_utc.astimezone(timezone.utc)
    operator = await _validate_operator(operator_username)
    await _preflight_reservation_configuration(
        operator=operator,
        now_utc=now_utc,
    )
    credential_bundle = await prepare_credentials(credentials_file)
    services = _services(now_provider=lambda: now_utc)
    users = await ensure_synthetic_users(
        operator=operator,
        passwords=credential_bundle.passwords,
        admin_user_service=services.admin_user,
    )
    storage = LocalImageStorage(root=storage_root, base_url=storage_base_url)
    products = await ensure_demo_products(
        services,
        storage,
        operator_id=operator.id,
    )
    await ensure_demo_orders_and_financials(
        services,
        products,
        users,
        operator=operator,
    )
    await ensure_demo_reservations(
        services,
        users,
        products,
        operator_id=operator.id,
        now_utc=now_utc,
    )
    return await verify_demo_data(now_utc=now_utc, image_storage=storage)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--operator-username")
    parser.add_argument(
        "--confirm-local-only",
        action="store_true",
        help="Confirm this is ignored local-development data only.",
    )
    parser.add_argument(
        "--credentials-file",
        type=Path,
        default=DEFAULT_CREDENTIALS_FILE,
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=DEFAULT_BACKUP_DIR,
    )
    return parser


async def _run_apply(arguments: argparse.Namespace) -> DemoVerificationSummary:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        return await seed_local_demo_data(
            operator_username=arguments.operator_username,
            credentials_file=arguments.credentials_file,
            storage_root=Path(settings.product_image_upload_dir),
            storage_base_url=settings.product_image_base_url,
        )
    finally:
        await Tortoise.close_connections()


async def _run_verify() -> DemoVerificationSummary:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        return await verify_demo_data()
    finally:
        await Tortoise.close_connections()


def _summary_for_log(summary: DemoVerificationSummary) -> str:
    return json.dumps(
        {
            "synthetic_users": summary.synthetic_users,
            "disabled_users": summary.disabled_users,
            "products_by_status": summary.products_by_status,
            "products_by_type": summary.products_by_type,
            "fixed_kits": summary.fixed_kits,
            "color_selectable_kits": summary.color_selectable_kits,
            "deleted_products": summary.deleted_products,
            "enabled_demo_colors": summary.enabled_demo_colors,
            "orders_by_status": summary.orders_by_status,
            "inventory_by_type": summary.inventory_by_type,
            "wallets": summary.wallets,
            "wallet_transactions_by_type": summary.wallet_transactions_by_type,
            "payments_by_method": summary.payments_by_method,
            "settlements": summary.settlements,
            "refunds": summary.refunds,
            "reservations_by_status": summary.reservations_by_status,
            "reservation_cancellation_reasons": (
                summary.reservation_cancellation_reasons
            ),
            "closed_business_days": summary.closed_business_days,
            "reopened_business_days": summary.reopened_business_days,
            "weekly_cancelled_reservations": (
                summary.weekly_cancelled_reservations
            ),
            "weekly_closed_weekday": summary.weekly_closed_weekday,
            "audit_actions": summary.audit_actions,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def main() -> int:
    arguments = build_parser().parse_args()
    setup_logging()
    _suppress_dependency_debug_logs()
    configured_database = Path(settings.db_sqlite_path)
    database = configured_database
    backup: Path | None = None
    try:
        if settings.app_env != "development":
            raise LocalDemoSeedError("APP_ENV must be development")
        if settings.db_engine != "sqlite":
            raise LocalDemoSeedError("DB_ENGINE must be sqlite")
        if configured_database.is_symlink():
            raise LocalDemoSeedError("SQLite database must not be a symlink")
        database = assert_path_in_repository(
            configured_database,
            label="SQLite database",
        )
        if not database.is_file():
            raise LocalDemoSeedError("SQLite database does not exist")
        assert_path_in_repository(
            Path(settings.product_image_upload_dir),
            label="Image upload directory",
        )
        if arguments.apply:
            if arguments.operator_username is None:
                raise LocalDemoSeedError("--operator-username is required for apply")
            assert_local_seed_allowed(
                app_env=settings.app_env,
                db_engine=settings.db_engine,
                db_sqlite_path=settings.db_sqlite_path,
                upload_dir=settings.product_image_upload_dir,
                apply=True,
                confirm_local_only=arguments.confirm_local_only,
            )
            validate_credentials_path(arguments.credentials_file)
            backup = create_sqlite_backup(database, arguments.backup_dir)
            summary = asyncio.run(_run_apply(arguments))
            verify_sqlite_integrity(database)
            logger.info(
                "Local demo seed complete: backup=%s summary=%s",
                backup,
                _summary_for_log(summary),
            )
        else:
            summary = asyncio.run(_run_verify())
            verify_sqlite_integrity(database)
            logger.info("Local demo verification passed: %s", _summary_for_log(summary))
    except (LocalDemoSeedError, RuntimeError) as error:
        if backup is None:
            logger.error("Local demo data command refused: %s", error)
        else:
            logger.error(
                "Local demo data command refused: %s backup=%s",
                error,
                backup,
            )
        return 2
    except Exception as error:
        if backup is None:
            logger.error(
                "Local demo data command failed safely: error_type=%s",
                type(error).__name__,
            )
        else:
            logger.error(
                "Local demo data command failed safely: error_type=%s backup=%s",
                type(error).__name__,
                backup,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
