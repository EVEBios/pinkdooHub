"""Seed and verify data in the disposable performance MySQL instance."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Mapping

from tortoise import Tortoise
from tortoise.transactions import in_transaction

from app.common.constants.product import COLOR_SELECTABLE_SALE_UNIT_GRAMS
from app.common.constants.order import (
    ORDER_AUDIT_ACTION_CANCEL,
    ORDER_AUDIT_ACTION_CREATE,
)
from app.common.constants.inventory import (
    INVENTORY_ORDER_COLOR_DEDUCTION_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_COLOR_RESTORE_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_DEDUCTION_REASON,
    INVENTORY_ORDER_RESTORE_REASON,
)
from app.common.constants.wallet import (
    ASSISTED_WALLET_ORDER_IDEMPOTENCY_PREFIX,
    ASSISTED_WALLET_ORDER_TRANSACTION_KEY,
    PAYMENT_AUDIT_ACTION_PAY_ORDER,
    ASSISTED_WALLET_ORDER_PAYMENT_REASON,
    WALLET_ORDER_PAYMENT_REASON,
    WALLET_ORDER_TRANSACTION_KEY,
    WALLET_PAYMENT_IDEMPOTENCY_PREFIX,
)
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.enums.order import OrderStatus
from app.common.enums.product import KitKind, ProductStatus, ProductType
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    WalletStatus,
    WalletTransactionSourceType,
    WalletTransactionType,
)
from app.core.config import settings
from app.core.security import hash_password
from app.db.database import TORTOISE_ORM
from app.models.audit_log import AuditLog
from app.models.bead_color import BeadColor
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PaymentSettlement
from app.models.payment import RechargeOrder, Refund
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit
from app.models.product_kit_color import ProductKitColor
from app.models.user import User
from app.models.reservation import Reservation
from app.models.wallet import WalletAccount, WalletTransaction
from app.repositories.wallet_repo import WalletRepository
from app.tasks.mard_catalog import EXPECTED_COLOR_COUNT, load_manifest
from app.tasks.wallet_reconcile import reconcile_all
from scripts.performance.config import (
    DATABASE_NAME,
    DATABASE_USER,
    MAX_WRITE_JOURNEYS_PER_RUN,
    RUN_ID_PATTERN,
)


SEED_ENABLE_ENV = "PERFORMANCE_SEED_ENABLED"
RUN_ID_ENV = "PERFORMANCE_RUN_ID"
PERSONA_PASSWORD_PATH = Path("/run/secrets/persona_password")
CUSTOMER_COUNT = 10
FIXED_PRODUCT_COUNT = 8
OPENING_COLOR_STOCK = 999_999
OPENING_FIXED_STOCK = 10_000
WALLET_OPENING_BALANCE = Decimal("1000.00")
UNIT_PRICE = Decimal("0.01")
COLOR_PRODUCT_NAME = "Performance 221 Color Kit"
SMALL_COLOR_PRODUCT_NAME = "Performance 3 Color Kit"
MAX_WRITE_JOURNEYS_PER_USER_PHASE = 600
WRITE_PAYMENT_EXTERNAL_KEY_PATTERN = re.compile(
    r"^perf-(?P<run_id>[0-9]{8}t[0-9]{6})-"
    r"(?P<phase>ramp|warmup|measured)-"
    r"r(?P<round_number>[1-5])-"
    r"v(?P<vus>5|10)-"
    r"u(?P<user_index>0|[1-9])-"
    r"j(?P<journey_number>[1-9][0-9]{0,2})-"
    r"(?P<kind>pay|assisted)$"
)
PERFORMANCE_CUSTOMER_PATTERN = re.compile(
    r"^perf_user_(?P<number>0[1-9]|10)$"
)
MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "tasks"
    / "manifests"
    / "mard_221.json"
)


class PerformanceSeedError(RuntimeError):
    """Safe seed or reconciliation failure without row contents."""


@dataclass(frozen=True, slots=True)
class SeedSummary:
    run_id: str
    users: int
    products: int
    bead_colors: int
    product_kit_colors: int
    opening_inventory_transactions: int
    wallet_accounts: int
    opening_wallet_transactions: int
    color_product_id: int
    small_color_product_id: int


@dataclass(frozen=True, slots=True)
class WriteJourneyIdentity:
    phase: str
    round_number: int
    vus: int
    user_index: int
    journey_number: int


def _parse_write_payment_identity(
    idempotency_key: object,
    *,
    run_id: str,
) -> tuple[WriteJourneyIdentity, str] | None:
    """Parse one stored D key without returning or reporting its raw value."""

    if not isinstance(idempotency_key, str):
        return None
    if idempotency_key.startswith(WALLET_PAYMENT_IDEMPOTENCY_PREFIX):
        external_key = idempotency_key.removeprefix(
            WALLET_PAYMENT_IDEMPOTENCY_PREFIX
        )
        expected_kind = "pay"
    elif idempotency_key.startswith(
        ASSISTED_WALLET_ORDER_IDEMPOTENCY_PREFIX
    ):
        external_key = idempotency_key.removeprefix(
            ASSISTED_WALLET_ORDER_IDEMPOTENCY_PREFIX
        )
        expected_kind = "assisted"
    else:
        return None
    match = WRITE_PAYMENT_EXTERNAL_KEY_PATTERN.fullmatch(external_key)
    if (
        match is None
        or match.group("run_id") != run_id
        or match.group("kind") != expected_kind
    ):
        return None
    vus = int(match.group("vus"))
    user_index = int(match.group("user_index"))
    journey_number = int(match.group("journey_number"))
    if (
        user_index >= vus
        or user_index >= CUSTOMER_COUNT
        or journey_number > MAX_WRITE_JOURNEYS_PER_USER_PHASE
    ):
        return None
    return (
        WriteJourneyIdentity(
            phase=match.group("phase"),
            round_number=int(match.group("round_number")),
            vus=vus,
            user_index=user_index,
            journey_number=journey_number,
        ),
        expected_kind,
    )


def _performance_customer_index(username: object) -> int | None:
    if not isinstance(username, str):
        return None
    match = PERFORMANCE_CUSTOMER_PATTERN.fullmatch(username)
    return int(match.group("number")) - 1 if match is not None else None


def _write_payment_pairs_are_complete(
    normal: set[WriteJourneyIdentity],
    assisted: set[WriteJourneyIdentity],
    *,
    expected_write_journeys: int,
) -> bool:
    journeys_by_worker: defaultdict[
        tuple[str, int, int, int], list[int]
    ] = defaultdict(list)
    for identity in normal:
        journeys_by_worker[
            (
                identity.phase,
                identity.round_number,
                identity.vus,
                identity.user_index,
            )
        ].append(identity.journey_number)
    sequences_are_contiguous = all(
        sorted(journey_numbers)
        == list(range(1, len(journey_numbers) + 1))
        for journey_numbers in journeys_by_worker.values()
    )
    return (
        len(normal) == expected_write_journeys
        and len(assisted) == expected_write_journeys
        and normal == assisted
        and sequences_are_contiguous
    )


def validate_target(environment: Mapping[str, str]) -> str:
    """Fail closed unless the process points at the exact disposable topology."""

    expected = {
        SEED_ENABLE_ENV: "1",
        "APP_ENV": "production",
        "DB_ENGINE": "mysql",
        "DB_HOST": "mysql",
        "DB_PORT": "3306",
        "DB_NAME": DATABASE_NAME,
        "DB_USER": DATABASE_USER,
        "PAYMENT_PROVIDER": "disabled",
        "WALLET_TOPUP_ENABLED": "false",
    }
    for key, value in expected.items():
        if environment.get(key) != value:
            raise PerformanceSeedError(f"performance target rejected: {key}")
    run_id = environment.get(RUN_ID_ENV, "")
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise PerformanceSeedError("performance run ID is invalid")
    if not PERSONA_PASSWORD_PATH.is_file():
        raise PerformanceSeedError("performance persona Secret is unavailable")
    if Path(settings.product_image_upload_dir) != Path("/data/images"):
        raise PerformanceSeedError("performance image volume is unavailable")
    return run_id


async def _require_empty_business_database() -> None:
    counts = (
        await User.all().count(),
        await Product.all().count(),
        await Order.all().count(),
        await Payment.all().count(),
        await RechargeOrder.all().count(),
        await Refund.all().count(),
        await Reservation.all().count(),
        await WalletAccount.all().count(),
        await InventoryTransaction.all().count(),
        await AuditLog.all().count(),
    )
    if any(counts):
        raise PerformanceSeedError("performance business database is not empty")


async def _require_mard_catalog() -> list[BeadColor]:
    colors = list(await BeadColor.all().order_by("slot_no"))
    manifest = load_manifest(MANIFEST)
    if len(colors) != EXPECTED_COLOR_COUNT:
        raise PerformanceSeedError("performance MARD catalog is incomplete")
    for row, expected in zip(colors, manifest):
        if (
            row.slot_no,
            row.color_code,
            row.name,
            row.swatch_hex,
            row.sort,
            row.is_active,
        ) != (
            expected.slot_no,
            expected.color_code,
            expected.name,
            expected.hex,
            expected.sort,
            True,
        ):
            raise PerformanceSeedError("performance MARD catalog differs")
        if not row.swatch_image_url:
            raise PerformanceSeedError("performance MARD image URL is missing")
    return colors


async def _create_opening_transaction(
    *,
    product_id: int,
    quantity: int,
    key: str,
    kit_color_id: int | None = None,
) -> InventoryTransaction:
    return InventoryTransaction(
        product_id=product_id,
        kit_color_id=kit_color_id,
        transaction_type=InventoryTransactionType.OPENING_BALANCE,
        change_quantity=quantity,
        before_quantity=0,
        after_quantity=quantity,
        source_type=InventorySourceType.MIGRATION,
        source_id=None,
        operator_id=None,
        reason="Performance synthetic opening balance",
        idempotency_key=key,
    )


async def seed(run_id: str, password: str) -> SeedSummary:
    """Create deterministic synthetic personas, products, balances and ledgers."""

    await _require_empty_business_database()
    colors = await _require_mard_catalog()
    password_hash = hash_password(password)
    image_url = colors[0].swatch_image_url
    assert image_url is not None

    async with in_transaction() as connection:
        admin = await User.create(
            username="perf_admin",
            password=password_hash,
            nickname="Performance Admin",
            phone="13999000000",
            role=UserRole.ADMIN.value,
            status=UserStatus.NORMAL.value,
            using_db=connection,
        )
        customers: list[User] = []
        for number in range(1, CUSTOMER_COUNT + 1):
            customer = await User.create(
                username=f"perf_user_{number:02d}",
                password=password_hash,
                nickname=f"Performance User {number:02d}",
                phone=f"1399900{number:04d}",
                role=UserRole.USER.value,
                status=UserStatus.NORMAL.value,
                using_db=connection,
            )
            account = await WalletAccount.create(
                user_id=customer.id,
                balance=WALLET_OPENING_BALANCE,
                status=WalletStatus.ACTIVE,
                using_db=connection,
            )
            await WalletTransaction.create(
                wallet_account_id=account.id,
                transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
                change_amount=WALLET_OPENING_BALANCE,
                before_balance=Decimal("0.00"),
                after_balance=WALLET_OPENING_BALANCE,
                source_type=WalletTransactionSourceType.ADMIN,
                source_id=admin.id,
                operator_id=admin.id,
                reason="Performance synthetic opening balance",
                idempotency_key=f"performance:seed:wallet:{number:02d}",
                using_db=connection,
            )
            customers.append(customer)

        opening_transactions: list[InventoryTransaction] = []
        for number in range(1, FIXED_PRODUCT_COUNT + 1):
            product = await Product.create(
                name=f"Performance Fixed Kit {number:02d}",
                product_type=ProductType.KIT,
                description="Synthetic fixed kit for isolated capacity testing",
                status=ProductStatus.ONLINE,
                is_deleted=False,
                using_db=connection,
            )
            await ProductKit.create(
                product_id=product.id,
                price=UNIT_PRICE,
                stock=OPENING_FIXED_STOCK,
                kit_kind=KitKind.FIXED,
                sale_unit_grams=None,
                using_db=connection,
            )
            await ProductImage.create(
                product_id=product.id,
                image_url=image_url,
                is_cover=True,
                sort=0,
                is_deleted=False,
                using_db=connection,
            )
            opening_transactions.append(
                await _create_opening_transaction(
                    product_id=product.id,
                    quantity=OPENING_FIXED_STOCK,
                    key=f"performance:seed:fixed:{product.id}",
                )
            )

        async def create_color_product(
            *,
            name: str,
            enabled_colors: list[BeadColor],
        ) -> Product:
            product = await Product.create(
                name=name,
                product_type=ProductType.KIT,
                description="Synthetic selectable kit for isolated capacity testing",
                status=ProductStatus.ONLINE,
                is_deleted=False,
                using_db=connection,
            )
            await ProductKit.create(
                product_id=product.id,
                price=UNIT_PRICE,
                stock=None,
                kit_kind=KitKind.COLOR_SELECTABLE,
                sale_unit_grams=COLOR_SELECTABLE_SALE_UNIT_GRAMS,
                using_db=connection,
            )
            await ProductImage.create(
                product_id=product.id,
                image_url=image_url,
                is_cover=True,
                sort=0,
                is_deleted=False,
                using_db=connection,
            )
            await ProductKitColor.bulk_create(
                [
                    ProductKitColor(
                        product_id=product.id,
                        bead_color_id=color.id,
                        is_enabled=True,
                        stock_units=OPENING_COLOR_STOCK,
                    )
                    for color in enabled_colors
                ],
                using_db=connection,
            )
            stored = list(
                await ProductKitColor.filter(product_id=product.id)
                .using_db(connection)
                .order_by("bead_color_id")
            )
            if len(stored) != len(enabled_colors):
                raise PerformanceSeedError("performance color rows were not created")
            for row in stored:
                opening_transactions.append(
                    await _create_opening_transaction(
                        product_id=product.id,
                        kit_color_id=row.id,
                        quantity=OPENING_COLOR_STOCK,
                        key=f"performance:seed:color:{row.id}",
                    )
                )
            return product

        color_product = await create_color_product(
            name=COLOR_PRODUCT_NAME,
            enabled_colors=colors,
        )
        small_color_product = await create_color_product(
            name=SMALL_COLOR_PRODUCT_NAME,
            enabled_colors=colors[:3],
        )
        await InventoryTransaction.bulk_create(
            opening_transactions,
            using_db=connection,
        )

    return SeedSummary(
        run_id=run_id,
        users=1 + len(customers),
        products=FIXED_PRODUCT_COUNT + 2,
        bead_colors=len(colors),
        product_kit_colors=EXPECTED_COLOR_COUNT + 3,
        opening_inventory_transactions=len(opening_transactions),
        wallet_accounts=len(customers),
        opening_wallet_transactions=len(customers),
        color_product_id=color_product.id,
        small_color_product_id=small_color_product.id,
    )


async def snapshot(run_id: str) -> dict[str, object]:
    """Return only non-sensitive counts used to bind later reconciliation."""

    return {
        "run_id": run_id,
        "audit_logs": await AuditLog.all().count(),
        "bead_colors": await BeadColor.all().count(),
        "inventory_transactions": await InventoryTransaction.all().count(),
        "order_items": await OrderItem.all().count(),
        "orders": await Order.all().count(),
        "orders_cancelled": await Order.filter(
            status=OrderStatus.CANCELLED.value
        ).count(),
        "orders_paid": await Order.filter(status=OrderStatus.PAID.value).count(),
        "payments": await Payment.all().count(),
        "recharge_orders": await RechargeOrder.all().count(),
        "refunds": await Refund.all().count(),
        "reservations": await Reservation.all().count(),
        "products": await Product.all().count(),
        "product_images": await ProductImage.all().count(),
        "product_kits": await ProductKit.all().count(),
        "product_kit_colors": await ProductKitColor.all().count(),
        "settlements": await PaymentSettlement.all().count(),
        "users": await User.all().count(),
        "wallet_accounts": await WalletAccount.all().count(),
        "wallet_transactions": await WalletTransaction.all().count(),
        "static_fixture_sha256": await _static_fixture_digest(),
    }


async def _static_fixture_digest() -> str:
    """Hash immutable fixture projections while excluding expected D balances."""

    projections = {
        "users": await User.all().order_by("id").values(
            "id", "username", "nickname", "phone", "avatar", "role", "status",
            "auth_version", "deleted_at",
        ),
        "products": await Product.all().order_by("id").values(
            "id", "name", "product_type", "description", "status", "is_deleted",
        ),
        "product_kits": await ProductKit.all().order_by("id").values(
            "id", "product_id", "price", "kit_kind", "sale_unit_grams",
        ),
        "product_kit_colors": await ProductKitColor.all().order_by("id").values(
            "id", "product_id", "bead_color_id", "is_enabled",
        ),
        "product_images": await ProductImage.all().order_by("id").values(
            "id", "product_id", "experience_option_id", "image_url", "is_cover",
            "sort", "is_deleted",
        ),
        "bead_colors": await BeadColor.all().order_by("id").values(
            "id", "slot_no", "color_code", "name", "swatch_hex",
            "swatch_image_url", "sort", "is_active",
        ),
        "wallet_accounts": await WalletAccount.all().order_by("id").values(
            "id", "user_id", "status",
        ),
    }
    canonical = json.dumps(
        projections,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _verify_inventory_chains() -> int:
    transactions = list(
        await InventoryTransaction.all().order_by(
            "product_id", "kit_color_id", "created_at", "id"
        )
    )
    chains: dict[tuple[str, int], list[InventoryTransaction]] = defaultdict(list)
    for row in transactions:
        key = (
            ("color", row.kit_color_id)
            if row.kit_color_id is not None
            else ("fixed", row.product_id)
        )
        chains[key].append(row)

    fixed_balances = {
        row.product_id: row.stock
        for row in await ProductKit.filter(kit_kind=KitKind.FIXED).all()
    }
    color_balances = {
        row.id: row.stock_units for row in await ProductKitColor.all()
    }
    violations = 0
    for key, rows in chains.items():
        previous = 0
        for row in rows:
            if row.before_quantity != previous:
                violations += 1
            if row.before_quantity + row.change_quantity != row.after_quantity:
                violations += 1
            previous = row.after_quantity
        expected = (
            color_balances[key[1]]
            if key[0] == "color"
            else fixed_balances[key[1]]
        )
        if previous != expected:
            violations += 1
    expected_keys = {
        *(("fixed", key) for key in fixed_balances),
        *(("color", key) for key in color_balances),
    }
    if set(chains) != expected_keys:
        violations += 1
    return violations


async def _verify_write_links(
    run_id: str,
    expected_write_journeys: int,
) -> int:
    """Verify that equal row counts cannot conceal cross-domain mis-linking."""

    target_product = await Product.get_or_none(name=COLOR_PRODUCT_NAME)
    if target_product is None:
        return 1
    target_color = await ProductKitColor.filter(
        product_id=target_product.id
    ).order_by("bead_color_id").first()
    if target_color is None:
        return 1
    target_bead_color = await BeadColor.get_or_none(id=target_color.bead_color_id)
    if target_bead_color is None:
        return 1

    orders = list(await Order.all().order_by("id"))
    items_by_order: dict[int, list[OrderItem]] = defaultdict(list)
    for item in await OrderItem.all().order_by("id"):
        items_by_order[item.order_id].append(item)
    payments_by_order: dict[int, list[Payment]] = defaultdict(list)
    for payment in await Payment.all().order_by("id"):
        if payment.order_id is not None:
            payments_by_order[payment.order_id].append(payment)
    settlements_by_order: dict[int, list[PaymentSettlement]] = defaultdict(list)
    for settlement in await PaymentSettlement.all().order_by("id"):
        settlements_by_order[settlement.order_id].append(settlement)
    wallet_transactions_by_order: dict[int, list[WalletTransaction]] = defaultdict(
        list
    )
    for transaction in await WalletTransaction.filter(
        source_type=WalletTransactionSourceType.ORDER
    ).order_by("id"):
        if transaction.source_id is not None:
            wallet_transactions_by_order[transaction.source_id].append(transaction)
    inventory_by_order: dict[int, list[InventoryTransaction]] = defaultdict(list)
    for transaction in await InventoryTransaction.filter(
        source_type=InventorySourceType.ORDER
    ).order_by("id"):
        if transaction.source_id is not None:
            inventory_by_order[transaction.source_id].append(transaction)
    wallet_user_by_account = {
        account.id: account.user_id for account in await WalletAccount.all()
    }
    admin_ids = set(
        await User.filter(role=UserRole.ADMIN.value).values_list("id", flat=True)
    )
    customer_rows = list(
        await User.filter(role=UserRole.USER.value).values("id", "username")
    )
    customer_ids = {
        int(row["id"])
        for row in customer_rows
        if isinstance(row.get("id"), int)
    }
    customer_id_by_index: dict[int, int] = {}
    customer_mapping_invalid = False
    for row in customer_rows:
        customer_index = _performance_customer_index(row.get("username"))
        customer_id = row.get("id")
        if (
            customer_index is None
            or not isinstance(customer_id, int)
            or customer_index in customer_id_by_index
        ):
            customer_mapping_invalid = True
            continue
        customer_id_by_index[customer_index] = customer_id
    if set(customer_id_by_index) != set(range(CUSTOMER_COUNT)):
        customer_mapping_invalid = True
    audits_by_order: dict[int, list[AuditLog]] = defaultdict(list)
    for audit in await AuditLog.filter(target_type="order").order_by("id"):
        audits_by_order[audit.target_id].append(audit)

    violations = int(customer_mapping_invalid)
    normal_paid = 0
    assisted_paid = 0
    cancelled = 0
    normal_journey_identities: set[WriteJourneyIdentity] = set()
    assisted_journey_identities: set[WriteJourneyIdentity] = set()
    for order in orders:
        items = items_by_order[order.id]
        payments = payments_by_order[order.id]
        settlements = settlements_by_order[order.id]
        wallet_transactions = wallet_transactions_by_order[order.id]
        inventory = inventory_by_order[order.id]
        audits = audits_by_order[order.id]
        if (
            len(items) != 1
            or items[0].product_id != target_product.id
            or items[0].kit_color_id != target_color.id
            or order.user_id not in customer_ids
        ):
            violations += 1
            continue
        item = items[0]
        if (
            item.experience_option_id is not None
            or item.option_duration_minutes is not None
            or item.option_participants is not None
            or item.option_day_type is not None
            or item.product_name != COLOR_PRODUCT_NAME
            or item.kit_color_code != target_bead_color.color_code
            or item.kit_color_name != target_bead_color.name
            or item.kit_color_slot_no != target_bead_color.slot_no
            or item.sale_unit_grams != COLOR_SELECTABLE_SALE_UNIT_GRAMS
            or item.product_price != UNIT_PRICE
            or item.quantity != 1
            or item.subtotal != UNIT_PRICE
            or order.total_amount != UNIT_PRICE
            or order.remark != "Synthetic isolated performance journey"
        ):
            violations += 1
        deduction_key = INVENTORY_ORDER_COLOR_DEDUCTION_IDEMPOTENCY_KEY.format(
            order_id=order.id,
            product_id=item.product_id,
            kit_color_id=item.kit_color_id,
        )
        deductions = [
            row
            for row in inventory
            if row.transaction_type is InventoryTransactionType.ORDER_DEDUCTION
        ]
        if (
            len(deductions) != 1
            or deductions[0].product_id != item.product_id
            or deductions[0].kit_color_id != item.kit_color_id
            or deductions[0].source_id != order.id
            or deductions[0].source_type is not InventorySourceType.ORDER
            or deductions[0].idempotency_key != deduction_key
            or deductions[0].change_quantity != -item.quantity
            or deductions[0].reason != INVENTORY_ORDER_DEDUCTION_REASON
        ):
            violations += 1

        status = OrderStatus(order.status)
        if status is OrderStatus.CANCELLED:
            cancelled += 1
            restore_key = INVENTORY_ORDER_COLOR_RESTORE_IDEMPOTENCY_KEY.format(
                order_id=order.id,
                product_id=item.product_id,
                kit_color_id=item.kit_color_id,
            )
            restores = [
                row
                for row in inventory
                if row.transaction_type
                is InventoryTransactionType.ORDER_CANCELLATION_RESTORE
            ]
            if (
                payments
                or settlements
                or wallet_transactions
                or len(inventory) != 2
                or len(restores) != 1
                or restores[0].source_id != order.id
                or restores[0].product_id != item.product_id
                or restores[0].kit_color_id != item.kit_color_id
                or restores[0].idempotency_key != restore_key
                or restores[0].change_quantity != item.quantity
                or restores[0].reason != INVENTORY_ORDER_RESTORE_REASON
                or any(row.operator_id != order.user_id for row in inventory)
                or len(audits) != 2
                or [row.action for row in audits]
                != [ORDER_AUDIT_ACTION_CREATE, ORDER_AUDIT_ACTION_CANCEL]
                or any(row.operator_id != order.user_id for row in audits)
            ):
                violations += 1
            continue

        if status is not OrderStatus.PAID:
            violations += 1
            continue
        if (
            len(payments) != 1
            or len(settlements) != 1
            or len(wallet_transactions) != 1
            or len(inventory) != 1
            or len(audits) != 2
            or [row.action for row in audits]
            != [ORDER_AUDIT_ACTION_CREATE, PAYMENT_AUDIT_ACTION_PAY_ORDER]
        ):
            violations += 1
            continue
        payment = payments[0]
        settlement = settlements[0]
        wallet_transaction = wallet_transactions[0]
        parsed_identity = _parse_write_payment_identity(
            payment.idempotency_key,
            run_id=run_id,
        )
        if parsed_identity is None:
            violations += 1
            continue
        journey_identity, payment_kind = parsed_identity
        is_normal = payment_kind == "pay"
        identity_set = (
            normal_journey_identities
            if is_normal
            else assisted_journey_identities
        )
        if journey_identity in identity_set:
            violations += 1
        identity_set.add(journey_identity)
        expected_operator = order.user_id if is_normal else audits[0].operator_id
        if is_normal:
            normal_paid += 1
        else:
            assisted_paid += 1
        expected_wallet_key = (
            WALLET_ORDER_TRANSACTION_KEY
            if is_normal
            else ASSISTED_WALLET_ORDER_TRANSACTION_KEY
        ).format(payment_id=payment.id, order_id=order.id)
        expected_wallet_reason = (
            WALLET_ORDER_PAYMENT_REASON
            if is_normal
            else ASSISTED_WALLET_ORDER_PAYMENT_REASON
        )
        if (
            payment.user_id != order.user_id
            or payment.order_id != order.id
            or payment.recharge_order_id is not None
            or payment.purpose is not PaymentPurpose.ORDER
            or payment.method is not PaymentMethod.WALLET
            or payment.status is not PaymentStatus.SUCCEEDED
            or payment.amount != order.total_amount
            or payment.provider_transaction_id is not None
            or payment.succeeded_at is None
            or settlement.payment_id != payment.id
            or settlement.order_id != order.id
            or settlement.amount != order.total_amount
            or wallet_user_by_account.get(wallet_transaction.wallet_account_id)
            != order.user_id
            or wallet_transaction.transaction_type
            is not WalletTransactionType.ORDER_PAYMENT
            or wallet_transaction.source_type is not WalletTransactionSourceType.ORDER
            or wallet_transaction.source_id != order.id
            or wallet_transaction.change_amount != -order.total_amount
            or wallet_transaction.before_balance + wallet_transaction.change_amount
            != wallet_transaction.after_balance
            or wallet_transaction.idempotency_key != expected_wallet_key
            or wallet_transaction.reason != expected_wallet_reason
            or wallet_transaction.operator_id != expected_operator
            or inventory[0].operator_id != expected_operator
            or inventory[0].reason != INVENTORY_ORDER_DEDUCTION_REASON
            or any(row.operator_id != expected_operator for row in audits)
            or (
                payment_kind == "assisted"
                and expected_operator not in admin_ids
            )
            or customer_id_by_index.get(journey_identity.user_index)
            != order.user_id
        ):
            violations += 1

    if (
        cancelled != expected_write_journeys
        or normal_paid != expected_write_journeys
        or assisted_paid != expected_write_journeys
        or not _write_payment_pairs_are_complete(
            normal_journey_identities,
            assisted_journey_identities,
            expected_write_journeys=expected_write_journeys,
        )
        or set(items_by_order) != {order.id for order in orders}
        or set(inventory_by_order) != {order.id for order in orders}
        or set(audits_by_order) != {order.id for order in orders}
    ):
        violations += 1
    return violations


def expected_reconciliation_counts(expected_write_journeys: int) -> dict[str, int]:
    """Return the frozen fixture plus exact write deltas for one full D journey."""

    expected_opening_inventory = FIXED_PRODUCT_COUNT + EXPECTED_COLOR_COUNT + 3
    return {
        "audit_logs": CUSTOMER_COUNT + 1 + 6 * expected_write_journeys,
        "bead_colors": EXPECTED_COLOR_COUNT,
        "orders": 3 * expected_write_journeys,
        "order_items": 3 * expected_write_journeys,
        "orders_cancelled": expected_write_journeys,
        "orders_paid": 2 * expected_write_journeys,
        "payments": 2 * expected_write_journeys,
        "product_images": FIXED_PRODUCT_COUNT + 2,
        "product_kits": FIXED_PRODUCT_COUNT + 2,
        "product_kit_colors": EXPECTED_COLOR_COUNT + 3,
        "products": FIXED_PRODUCT_COUNT + 2,
        "recharge_orders": 0,
        "refunds": 0,
        "reservations": 0,
        "settlements": 2 * expected_write_journeys,
        "users": CUSTOMER_COUNT + 1,
        "wallet_accounts": CUSTOMER_COUNT,
        "wallet_transactions": CUSTOMER_COUNT + 2 * expected_write_journeys,
        "inventory_transactions": (
            expected_opening_inventory + 4 * expected_write_journeys
        ),
    }


def expected_audit_action_counts(expected_write_journeys: int) -> dict[str, int]:
    """Freeze login setup and the six audit actions from every D journey."""

    counts = {
        "LOGIN": CUSTOMER_COUNT + 1,
        ORDER_AUDIT_ACTION_CREATE: 3 * expected_write_journeys,
        ORDER_AUDIT_ACTION_CANCEL: expected_write_journeys,
        PAYMENT_AUDIT_ACTION_PAY_ORDER: 2 * expected_write_journeys,
    }
    # Audit aggregation contains only actions that actually have rows.  Omitting
    # zero-count write actions keeps the pre-D continuation checkpoint equivalent
    # to the real database projection instead of manufacturing absent keys.
    return {action: count for action, count in counts.items() if count > 0}


async def verify(
    run_id: str,
    expected_write_journeys: int,
    expected_static_fixture_sha256: str,
) -> dict[str, object]:
    """Verify exact write counts plus wallet/inventory immutable chains."""

    if not 0 <= expected_write_journeys <= MAX_WRITE_JOURNEYS_PER_RUN:
        raise PerformanceSeedError(
            "expected journey count is outside the bounded verifier capacity"
        )
    if re.fullmatch(r"[0-9a-f]{64}", expected_static_fixture_sha256) is None:
        raise PerformanceSeedError("expected static fixture digest is invalid")
    current = await snapshot(run_id)
    expected = expected_reconciliation_counts(expected_write_journeys)
    mismatches = sum(current[key] != value for key, value in expected.items())
    static_fixture_mismatches = int(
        current["static_fixture_sha256"] != expected_static_fixture_sha256
    )
    expected_audit_actions = expected_audit_action_counts(
        expected_write_journeys
    )
    # Tortoise's aggregate projection is deliberately avoided here: this verifier
    # runs only after the bounded synthetic profile, so loading action strings keeps
    # the contract backend-neutral and exposes no descriptions or PII.
    actual_audit_actions: dict[str, int] = defaultdict(int)
    for action in await AuditLog.all().values_list("action", flat=True):
        actual_audit_actions[str(action)] += 1
    audit_action_mismatches = int(actual_audit_actions != expected_audit_actions)
    wallet = await reconcile_all(WalletRepository(), batch_size=100)
    inventory_violations = await _verify_inventory_chains()
    write_link_violations = await _verify_write_links(
        run_id,
        expected_write_journeys,
    )
    await _require_mard_catalog()
    non_succeeded_payments = await Payment.exclude(
        status=PaymentStatus.SUCCEEDED
    ).count()
    result = {
        "run_id": run_id,
        "expected_write_journeys": expected_write_journeys,
        "count_mismatches": mismatches,
        "static_fixture_mismatches": static_fixture_mismatches,
        "audit_action_mismatches": audit_action_mismatches,
        "inventory_violations": inventory_violations,
        "write_link_violations": write_link_violations,
        "non_succeeded_payments": non_succeeded_payments,
        "wallet_mismatches": wallet.mismatches,
        "wallet_violations": wallet.violations,
        "wallet_scanned": wallet.scanned,
        "passed": (
            mismatches == 0
            and static_fixture_mismatches == 0
            and audit_action_mismatches == 0
            and inventory_violations == 0
            and write_link_violations == 0
            and non_succeeded_payments == 0
            and wallet.mismatches == 0
            and wallet.violations == 0
        ),
        "counts": current,
        "expected_counts": expected,
        "audit_actions": dict(sorted(actual_audit_actions.items())),
        "expected_audit_actions": dict(sorted(expected_audit_actions.items())),
        "write_audit_logs": current["audit_logs"] - (CUSTOMER_COUNT + 1),
        "expected_write_audit_logs": 6 * expected_write_journeys,
    }
    if not result["passed"]:
        raise PerformanceSeedError("performance data reconciliation failed")
    return result


async def forensic_snapshot(
    run_id: str,
    expected_write_journeys: int,
) -> dict[str, object]:
    """Best-effort integrity evidence for an interrupted or failed D profile."""

    if not 0 <= expected_write_journeys <= MAX_WRITE_JOURNEYS_PER_RUN:
        raise PerformanceSeedError(
            "expected journey count is outside the bounded verifier capacity"
        )
    current = await snapshot(run_id)
    wallet = await reconcile_all(WalletRepository(), batch_size=100)
    inventory_violations = await _verify_inventory_chains()
    write_link_violations = await _verify_write_links(
        run_id,
        expected_write_journeys,
    )
    actual_audit_actions: dict[str, int] = defaultdict(int)
    for action in await AuditLog.all().values_list("action", flat=True):
        actual_audit_actions[str(action)] += 1
    non_succeeded_payments = await Payment.exclude(
        status=PaymentStatus.SUCCEEDED
    ).count()
    return {
        "run_id": run_id,
        "mode": "failure-forensic",
        "expected_completed_write_journeys": expected_write_journeys,
        "counts": current,
        "audit_actions": dict(sorted(actual_audit_actions.items())),
        "inventory_violations": inventory_violations,
        "write_link_violations": write_link_violations,
        "non_succeeded_payments": non_succeeded_payments,
        "wallet_mismatches": wallet.mismatches,
        "wallet_violations": wallet.violations,
        "wallet_scanned": wallet.scanned,
        "fully_reconciled": (
            inventory_violations == 0
            and write_link_violations == 0
            and non_succeeded_payments == 0
            and wallet.mismatches == 0
            and wallet.violations == 0
        ),
        "interpretation": (
            "A false result is retained as failure evidence and does not block cleanup"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed_parser = subparsers.add_parser("seed")
    seed_parser.add_argument("--apply", action="store_true")
    subparsers.add_parser("snapshot")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--expected-write-journeys", type=int, required=True)
    verify_parser.add_argument("--expected-static-fixture-sha256", required=True)
    forensic_parser = subparsers.add_parser("forensic")
    forensic_parser.add_argument("--expected-write-journeys", type=int, required=True)
    return parser


async def run(arguments: argparse.Namespace) -> dict[str, object]:
    run_id = validate_target(os.environ)
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        if arguments.command == "seed":
            if not arguments.apply:
                raise PerformanceSeedError("seed requires explicit --apply")
            password = PERSONA_PASSWORD_PATH.read_text(encoding="utf-8").strip()
            if len(password) < 20:
                raise PerformanceSeedError("performance persona Secret is too short")
            return asdict(await seed(run_id, password))
        if arguments.command == "snapshot":
            return await snapshot(run_id)
        if arguments.command == "verify":
            return await verify(
                run_id,
                arguments.expected_write_journeys,
                arguments.expected_static_fixture_sha256,
            )
        return await forensic_snapshot(run_id, arguments.expected_write_journeys)
    finally:
        await Tortoise.close_connections()


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        result = asyncio.run(run(arguments))
    except PerformanceSeedError as error:
        print(f"Performance data task refused: {error}")
        return 2
    except Exception as error:
        print(
            "Performance data task failed safely: "
            f"error_type={type(error).__name__}"
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
