"""综合本地演示数据的全域只读验证与非敏感汇总。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.common.bead_color import is_bead_color_configured
from app.common.constants.reservation import (
    RESERVATION_BOOKING_WINDOW_DAYS,
    RESERVATION_MINIMUM_LEAD_HOURS,
    RESERVATION_WEEKDAY_NUMBERS,
)
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.enums.order import OrderStatus
from app.common.enums.product import KitKind, ProductStatus, ProductType
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationStatus,
    ReservationWeekday,
)
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentStatus,
    RefundStatus,
    WalletStatus,
    WalletTransactionType,
)
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order
from app.models.payment import Payment, PaymentSettlement, Refund
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit
from app.models.product_kit_color import ProductKitColor
from app.models.reservation import Reservation, ReservationSettings, StoreBusinessDay
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction
from app.repositories.wallet_repo import WalletRepository
from app.storage.image import LocalImageStorage
from app.tasks.admin_product_functional_seed import (
    DELETED_KIT_NAME,
    DRAFT_EXPERIENCE_NAME,
    DRAFT_KIT_NAME,
)
from app.tasks.local_demo_support import (
    is_valid_local_image_file,
    LocalDemoSeedError,
    SYNTHETIC_USER_SPECS,
    USER_SPEC_BY_USERNAME,
)
from app.tasks.wallet_reconcile import reconcile_all
from app.validators.reservation_validator import STORE_TIMEZONE


@dataclass(frozen=True, slots=True)
class DemoVerificationSummary:
    synthetic_users: int
    disabled_users: int
    products_by_status: dict[str, int]
    products_by_type: dict[str, int]
    fixed_kits: int
    color_selectable_kits: int
    deleted_products: int
    enabled_demo_colors: int
    orders_by_status: dict[str, int]
    inventory_by_type: dict[str, int]
    wallets: int
    wallet_transactions_by_type: dict[str, int]
    payments_by_method: dict[str, int]
    settlements: int
    refunds: int
    reservations_by_status: dict[str, int]
    reservation_cancellation_reasons: dict[str, int]
    closed_business_days: int
    reopened_business_days: int
    weekly_cancelled_reservations: int
    weekly_closed_weekday: str
    audit_actions: dict[str, int]


def _counter_values(values: Iterable[object]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


async def verify_demo_data(
    *,
    color_product_name: str,
    offline_product_name: str,
    color_count: int,
    order_remarks: dict[str, str],
    expected_order_statuses: dict[str, OrderStatus],
    reservation_expectations: dict[
        str,
        tuple[
            ReservationStatus,
            ReservationRejectionReason | None,
            ReservationCancellationReason | None,
        ],
    ],
    weekly_closed_weekday: ReservationWeekday,
    now_utc: datetime | None = None,
    image_storage: LocalImageStorage,
) -> DemoVerificationSummary:
    """验证全部保留场景及跨域资金、库存、预约和审计不变量。"""

    users = list(
        await User.filter(username__in=set(USER_SPEC_BY_USERNAME)).order_by("id")
    )
    if len(users) != len(SYNTHETIC_USER_SPECS):
        raise LocalDemoSeedError("Synthetic demo user set is incomplete")
    user_by_name = {user.username: user for user in users}
    for spec in SYNTHETIC_USER_SPECS:
        user = user_by_name[spec.username]
        if (
            user.nickname != spec.nickname
            or user.phone != spec.phone
            or UserRole(user.role) is not UserRole.USER
            or UserStatus(user.status) is not spec.expected_status
        ):
            raise LocalDemoSeedError(
                f"Synthetic demo user projection is conflicting: {spec.username}"
            )

    accounts = list(await WalletAccount.filter(user_id__in={u.id for u in users}))
    if len(accounts) != len(users) or any(
        WalletStatus(account.status) is not WalletStatus.ACTIVE
        for account in accounts
    ):
        raise LocalDemoSeedError("Synthetic demo WalletAccount set is incomplete")
    account_by_user_id = {account.user_id: account for account in accounts}
    disabled_account = account_by_user_id[
        user_by_name["localdemo_v1_disabled"].id
    ]
    disabled_has_transactions = await WalletTransaction.filter(
        wallet_account_id=disabled_account.id
    ).exists()
    if disabled_account.balance != Decimal("0.00") or disabled_has_transactions:
        raise LocalDemoSeedError(
            "Disabled synthetic user's wallet must remain untouched"
        )

    functional_products = list(await Product.filter(name__startswith="[LOCAL-FE]"))
    if len(functional_products) != 13 or any(
        ProductStatus(product.status) is not ProductStatus.ONLINE
        or product.is_deleted
        for product in functional_products
    ):
        raise LocalDemoSeedError("Product functional catalog is incomplete")
    admin_expectations = {
        DRAFT_EXPERIENCE_NAME: (ProductType.EXPERIENCE, False),
        DRAFT_KIT_NAME: (ProductType.KIT, False),
        DELETED_KIT_NAME: (ProductType.KIT, True),
    }
    admin_products: list[Product] = []
    for name, (product_type, is_deleted) in admin_expectations.items():
        matches = list(await Product.filter(name=name))
        if len(matches) != 1:
            raise LocalDemoSeedError("ADMIN Product sample set is incomplete")
        product = matches[0]
        if (
            ProductType(product.product_type) is not product_type
            or ProductStatus(product.status) is not ProductStatus.DRAFT
            or product.is_deleted is not is_deleted
        ):
            raise LocalDemoSeedError("ADMIN Product sample projection is invalid")
        admin_products.append(product)

    color_product = await Product.get_or_none(name=color_product_name)
    offline_product = await Product.get_or_none(name=offline_product_name)
    if (
        color_product is None
        or ProductStatus(color_product.status) is not ProductStatus.ONLINE
        or color_product.is_deleted
        or offline_product is None
        or ProductStatus(offline_product.status) is not ProductStatus.OFFLINE
        or offline_product.is_deleted
    ):
        raise LocalDemoSeedError("Local demo Product lifecycle samples are incomplete")
    color_rows = list(
        await ProductKitColor.filter(product_id=color_product.id).prefetch_related(
            "bead_color"
        )
    )
    enabled_colors = [
        row
        for row in color_rows
        if row.is_enabled
        and row.stock_units >= 0
        and row.bead_color.is_active
        and is_bead_color_configured(
            color_code=row.bead_color.color_code,
            name=row.bead_color.name,
            swatch_hex=row.bead_color.swatch_hex,
        )
    ]
    if len(color_rows) != 221 or len(enabled_colors) < color_count:
        raise LocalDemoSeedError("Local demo color Product is incomplete")

    image_products = functional_products + [color_product, offline_product]
    image_product_ids = {product.id for product in image_products}
    image_rows = list(
        await ProductImage.filter(
            product_id__in=image_product_ids,
            is_deleted=False,
        ).order_by("product_id", "id")
    )
    cover_product_ids = {
        image.product_id for image in image_rows if image.is_cover
    }
    if cover_product_ids != image_product_ids:
        raise LocalDemoSeedError("Local demo Product cover set is incomplete")
    for image in image_rows:
        storage_key = image_storage.key_from_url(image.image_url)
        if storage_key is None:
            raise LocalDemoSeedError("Local demo Product image URL is unmanaged")
        image_path = image_storage.root / storage_key
        if image_path.is_symlink() or not image_path.is_file():
            raise LocalDemoSeedError("Local demo Product image file is missing")
        if not is_valid_local_image_file(image_path):
            raise LocalDemoSeedError("Local demo Product image file is invalid")

    owner_id = user_by_name["localdemo_v1_orders"].id
    assisted_id = user_by_name["localdemo_v1_assisted"].id
    order_by_scenario: dict[str, Order] = {}
    for scenario, remark in order_remarks.items():
        expected_owner = (
            assisted_id if scenario == "assisted_wallet_fixed" else owner_id
        )
        matches = list(await Order.filter(user_id=expected_owner, remark=remark))
        if len(matches) != 1:
            raise LocalDemoSeedError(f"Order scenario is incomplete: {scenario}")
        order = matches[0]
        if OrderStatus(order.status) is not expected_order_statuses[scenario]:
            raise LocalDemoSeedError(f"Order scenario status is invalid: {scenario}")
        order_by_scenario[scenario] = order
    order_ids = {order.id for order in order_by_scenario.values()}

    payments = list(await Payment.filter(order_id__in=order_ids))
    settlements = list(await PaymentSettlement.filter(order_id__in=order_ids))
    refunds = list(await Refund.filter(order_id__in=order_ids))
    paid_scenarios = {
        "paid_manual_experience",
        "completed_manual_fixed_refunded",
        "paid_wallet_color",
        "completed_wallet_experience",
        "paid_wallet_mixed_refunded",
        "assisted_wallet_fixed",
    }
    expected_paid_order_ids = {
        order_by_scenario[scenario].id for scenario in paid_scenarios
    }
    expected_refund_order_ids = {
        order_by_scenario["paid_wallet_mixed_refunded"].id,
        order_by_scenario["completed_manual_fixed_refunded"].id,
    }
    if (
        len(payments) != 6
        or len(settlements) != 6
        or len(refunds) != 2
        or {payment.order_id for payment in payments} != expected_paid_order_ids
        or {settlement.order_id for settlement in settlements}
        != expected_paid_order_ids
        or {refund.order_id for refund in refunds} != expected_refund_order_ids
        or any(
            PaymentStatus(payment.status) is not PaymentStatus.SUCCEEDED
            for payment in payments
        )
        or any(
            RefundStatus(refund.status) is not RefundStatus.SUCCEEDED
            for refund in refunds
        )
    ):
        raise LocalDemoSeedError("Payment/Settlement/Refund samples are incomplete")
    payment_methods = Counter(PaymentMethod(payment.method) for payment in payments)
    if payment_methods != Counter(
        {PaymentMethod.WALLET: 4, PaymentMethod.MANUAL: 2}
    ):
        raise LocalDemoSeedError("Payment method coverage is invalid")
    refund_by_order = {refund.order_id: refund for refund in refunds}
    if (
        not refund_by_order[
            order_by_scenario["paid_wallet_mixed_refunded"].id
        ].inventory_restored
        or refund_by_order[
            order_by_scenario["completed_manual_fixed_refunded"].id
        ].inventory_restored
    ):
        raise LocalDemoSeedError("Refund inventory semantics are invalid")

    order_inventory = list(
        await InventoryTransaction.filter(
            source_type=InventorySourceType.ORDER,
            source_id__in=order_ids,
        )
    )
    inventory_types = Counter(
        InventoryTransactionType(row.transaction_type)
        for row in order_inventory
    )
    for required in (
        InventoryTransactionType.ORDER_DEDUCTION,
        InventoryTransactionType.ORDER_CANCELLATION_RESTORE,
        InventoryTransactionType.ORDER_REFUND_RESTORE,
    ):
        if inventory_types[required] < 1:
            raise LocalDemoSeedError("Inventory transaction coverage is incomplete")

    account_ids = {account.id for account in accounts}
    wallet_transactions = list(
        await WalletTransaction.filter(wallet_account_id__in=account_ids)
    )
    wallet_types = Counter(
        WalletTransactionType(row.transaction_type)
        for row in wallet_transactions
    )
    for required in (
        WalletTransactionType.ADMIN_ADJUSTMENT,
        WalletTransactionType.ORDER_PAYMENT,
        WalletTransactionType.REFUND,
    ):
        if wallet_types[required] < 1:
            raise LocalDemoSeedError("Wallet transaction coverage is incomplete")
    reconciliation = await reconcile_all(WalletRepository(), batch_size=100)
    if reconciliation.mismatches or reconciliation.violations:
        raise LocalDemoSeedError("Global wallet reconciliation failed")

    verification_now = datetime.now(timezone.utc) if now_utc is None else now_utc
    if verification_now.tzinfo is None:
        raise LocalDemoSeedError("now_utc must be timezone-aware")
    verification_now = verification_now.astimezone(timezone.utc)
    local_today = verification_now.astimezone(STORE_TIMEZONE).date()
    last_bookable_date = local_today + timedelta(
        days=RESERVATION_BOOKING_WINDOW_DAYS
    )
    minimum_start = verification_now + timedelta(
        hours=RESERVATION_MINIMUM_LEAD_HOURS
    )
    reservations: list[Reservation] = []
    reservation_by_username: dict[str, Reservation] = {}
    for username, expectation in reservation_expectations.items():
        matches = list(
            await Reservation.filter(user_id=user_by_name[username].id).order_by(
                "id"
            )
        )
        if not matches:
            raise LocalDemoSeedError(
                f"Reservation scenario is incomplete: {username}"
            )
        expected_status, expected_rejection, expected_cancellation = expectation
        if expected_status in (
            ReservationStatus.PENDING,
            ReservationStatus.CONFIRMED,
        ):
            current_matches: list[Reservation] = []
            for candidate in matches:
                actual_status = ReservationStatus(candidate.status)
                actual_rejection = (
                    ReservationRejectionReason(candidate.rejection_reason)
                    if candidate.rejection_reason is not None
                    else None
                )
                actual_cancellation = (
                    ReservationCancellationReason(candidate.cancellation_reason)
                    if candidate.cancellation_reason is not None
                    else None
                )
                allowed_historical_statuses = {expected_status}
                if expected_status is ReservationStatus.CONFIRMED:
                    allowed_historical_statuses.add(ReservationStatus.PENDING)
                if (
                    actual_status not in allowed_historical_statuses
                    or actual_rejection is not None
                    or actual_cancellation is not None
                ):
                    raise LocalDemoSeedError(
                        f"Reservation scenario is invalid: {username}"
                    )
                business_date = candidate.scheduled_start_at.astimezone(
                    STORE_TIMEZONE
                ).date()
                if (
                    candidate.scheduled_start_at >= minimum_start
                    and local_today <= business_date <= last_bookable_date
                ):
                    if actual_status is not expected_status:
                        raise LocalDemoSeedError(
                            f"Reservation scenario is incomplete: {username}"
                        )
                    current_matches.append(candidate)
                elif candidate.scheduled_start_at >= minimum_start:
                    raise LocalDemoSeedError(
                        f"Active Reservation scenario is beyond the current "
                        f"booking window: {username}"
                    )
            if len(current_matches) != 1:
                raise LocalDemoSeedError(
                    f"Active Reservation scenario is outside the current "
                    f"booking window: {username}"
                )
            reservation = current_matches[0]
        else:
            if len(matches) != 1:
                raise LocalDemoSeedError(
                    f"Reservation scenario is incomplete: {username}"
                )
            reservation = matches[0]
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
                    f"Reservation scenario is invalid: {username}"
                )
        reservations.append(reservation)
        reservation_by_username[username] = reservation

    closed_reservation = reservation_by_username["localdemo_v1_res_closed"]
    closed_day = await StoreBusinessDay.get(id=closed_reservation.business_day_id)
    if not closed_day.is_closed:
        raise LocalDemoSeedError("Store-closed Reservation day is not closed")
    weekly_reservation = reservation_by_username["localdemo_v1_res_weekly"]
    weekly_day = await StoreBusinessDay.get(id=weekly_reservation.business_day_id)
    if (
        weekly_day.is_closed
        or weekly_day.business_date.weekday()
        != RESERVATION_WEEKDAY_NUMBERS[weekly_closed_weekday]
    ):
        raise LocalDemoSeedError("Weekly-closure Reservation day is invalid")
    customer_cancelled = reservation_by_username["localdemo_v1_res_cancel"]
    reopened_day = await StoreBusinessDay.get(id=customer_cancelled.business_day_id)
    if reopened_day.is_closed:
        raise LocalDemoSeedError("Reopened business day remains closed")
    for action in ("CLOSE_STORE_BUSINESS_DAY", "REOPEN_STORE_BUSINESS_DAY"):
        if not await AuditLog.filter(
            action=action,
            target_type="store_business_day",
            target_id=reopened_day.id,
        ).exists():
            raise LocalDemoSeedError("Close/reopen audit coverage is incomplete")

    settings_rows = list(await ReservationSettings.all())
    if len(settings_rows) != 1 or not settings_rows[0].singleton_key:
        raise LocalDemoSeedError("M7 ReservationSettings singleton is invalid")
    try:
        weekly_closed_enum = ReservationWeekday(
            settings_rows[0].weekly_closed_weekday
        )
    except ValueError as error:
        raise LocalDemoSeedError("M7 weekly closed weekday is invalid") from error
    if weekly_closed_enum is not weekly_closed_weekday:
        raise LocalDemoSeedError("M7 weekly closed weekday did not converge")
    weekly_audit_count = await AuditLog.filter(
        action="UPDATE_WEEKLY_CLOSED_DAY",
        target_type="reservation_settings",
        target_id=settings_rows[0].id,
    ).count()
    if weekly_audit_count < 1:
        raise LocalDemoSeedError("Weekly closure audit coverage is incomplete")

    required_actions = {
        "REGISTER",
        "DISABLE_USER",
        "CREATE_PRODUCT",
        "ONLINE_PRODUCT",
        "OFFLINE_PRODUCT",
        "ADJUST_INVENTORY",
        "ADJUST_WALLET",
        "CREATE_ORDER",
        "CANCEL_ORDER",
        "MARK_ORDER_PAID",
        "COMPLETE_ORDER",
        "PAY_ORDER",
        "REFUND_ORDER",
        "CREATE_RESERVATION",
        "CONFIRM_RESERVATION",
        "REJECT_RESERVATION",
        "CANCEL_RESERVATION",
        "CLOSE_STORE_BUSINESS_DAY",
        "REOPEN_STORE_BUSINESS_DAY",
        "UPDATE_WEEKLY_CLOSED_DAY",
    }
    action_rows = await AuditLog.filter(action__in=required_actions).values_list(
        "action",
        flat=True,
    )
    action_counts = Counter(action_rows)
    missing_actions = required_actions - set(action_counts)
    if missing_actions:
        raise LocalDemoSeedError(
            "Audit coverage is incomplete: " + ", ".join(sorted(missing_actions))
        )

    sample_products = functional_products + admin_products + [
        color_product,
        offline_product,
    ]
    kit_rows = list(
        await ProductKit.filter(
            product_id__in={
                product.id
                for product in sample_products
                if ProductType(product.product_type) is ProductType.KIT
            }
        )
    )
    kit_kinds = Counter(KitKind(kit.kit_kind) for kit in kit_rows)
    return DemoVerificationSummary(
        synthetic_users=len(users),
        disabled_users=sum(
            UserStatus(user.status) is UserStatus.DISABLED for user in users
        ),
        products_by_status=_counter_values(
            ProductStatus(product.status).value for product in sample_products
        ),
        products_by_type=_counter_values(
            ProductType(product.product_type).value for product in sample_products
        ),
        fixed_kits=kit_kinds[KitKind.FIXED],
        color_selectable_kits=kit_kinds[KitKind.COLOR_SELECTABLE],
        deleted_products=sum(product.is_deleted for product in sample_products),
        enabled_demo_colors=len(enabled_colors),
        orders_by_status=_counter_values(
            expected_order_statuses[scenario].name.lower()
            for scenario in order_by_scenario
        ),
        inventory_by_type=_counter_values(
            InventoryTransactionType(row.transaction_type).value
            for row in order_inventory
        ),
        wallets=len(accounts),
        wallet_transactions_by_type=_counter_values(
            WalletTransactionType(row.transaction_type).value
            for row in wallet_transactions
        ),
        payments_by_method=_counter_values(
            PaymentMethod(payment.method).value for payment in payments
        ),
        settlements=len(settlements),
        refunds=len(refunds),
        reservations_by_status=_counter_values(
            ReservationStatus(reservation.status).value
            for reservation in reservations
        ),
        reservation_cancellation_reasons=_counter_values(
            ReservationCancellationReason(reservation.cancellation_reason).value
            for reservation in reservations
            if reservation.cancellation_reason is not None
        ),
        closed_business_days=1,
        reopened_business_days=1,
        weekly_cancelled_reservations=1,
        weekly_closed_weekday=weekly_closed_enum.value,
        audit_actions=dict(sorted(action_counts.items())),
    )
