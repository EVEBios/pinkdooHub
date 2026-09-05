"""为 M4 前人工确认支付的历史订单重建 Payment/Settlement 事实。

命令默认只预览；显式传入 ``--apply`` 才写库。执行时必须保持应用停写，
并使用 dry-run 输出的 ``through_order_id`` 冻结同一次发布的扫描范围。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from tortoise import Tortoise
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from app.common.constants.order import (
    ORDER_AUDIT_ACTION_MARK_PAID,
    ORDER_AUDIT_TARGET_TYPE,
)
from app.common.constants.wallet import (
    LEGACY_MANUAL_PAYMENT_IDEMPOTENCY_KEY,
    PAYMENT_NO_PATTERN,
)
from app.common.enums.order import OrderStatus
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import PaymentMethod, PaymentPurpose, PaymentStatus
from app.common.financial_number import generate_payment_number
from app.core.logging import setup_logging
from app.db.database import TORTOISE_ORM
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.payment import Payment, PaymentSettlement
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import (
    PaymentCreateData,
    PaymentRepository,
    PaymentSettlementCreateData,
)
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

_ELIGIBLE_STATUSES = (OrderStatus.PAID, OrderStatus.COMPLETED)
_PAYMENT_NUMBER_GENERATION_MAX_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class LegacySettlementBlocker:
    order_id: int
    reason: str


@dataclass(frozen=True, slots=True)
class LegacyManualSettlementTotals:
    through_order_id: int = 0
    scanned: int = 0
    created: int = 0
    would_create: int = 0
    replayed: int = 0
    blockers: tuple[LegacySettlementBlocker, ...] = ()

    @property
    def blocked(self) -> int:
        return len(self.blockers)


@dataclass(frozen=True, slots=True)
class _CreateIntent:
    order: Order
    paid_audit: AuditLog


@dataclass(frozen=True, slots=True)
class _BatchResult:
    scanned: int
    created: int = 0
    would_create: int = 0
    replayed: int = 0
    blockers: tuple[LegacySettlementBlocker, ...] = ()


def _legacy_key(order_id: int) -> str:
    return LEGACY_MANUAL_PAYMENT_IDEMPOTENCY_KEY.format(order_id=order_id)


def _payment_matches(
    payment: Payment,
    *,
    order: Order,
    paid_at: datetime,
) -> bool:
    return (
        payment.user_id == order.user_id
        and payment.purpose == PaymentPurpose.ORDER
        and payment.method == PaymentMethod.MANUAL
        and payment.amount == order.total_amount
        and payment.status == PaymentStatus.SUCCEEDED
        and payment.order_id == order.id
        and payment.recharge_order_id is None
        and payment.idempotency_key == _legacy_key(order.id)
        and payment.provider_transaction_id is None
        and payment.succeeded_at == paid_at
        and re.fullmatch(PAYMENT_NO_PATTERN, payment.payment_no) is not None
    )


def _existing_facts_match(
    *,
    order: Order,
    paid_audit: AuditLog,
    order_payments: list[Payment],
    expected_payment: Payment | None,
    settlement: PaymentSettlement | None,
) -> bool:
    return (
        len(order_payments) == 1
        and expected_payment is not None
        and order_payments[0].id == expected_payment.id
        and settlement is not None
        and settlement.payment_id == expected_payment.id
        and settlement.order_id == order.id
        and settlement.amount == order.total_amount
        and _payment_matches(
            expected_payment,
            order=order,
            paid_at=paid_audit.created_at,
        )
    )


def _blocker_reason(
    *,
    order: Order,
    order_payments: list[Payment],
    expected_payment: Payment | None,
    settlement: PaymentSettlement | None,
) -> str:
    if expected_payment is not None and expected_payment.order_id != order.id:
        return "legacy_idempotency_key_conflict"
    if settlement is None and (order_payments or expected_payment is not None):
        return "partial_payment_without_settlement"
    if settlement is not None and expected_payment is None:
        return "settlement_without_legacy_payment"
    if len(order_payments) > 1:
        return "multiple_payments_for_legacy_order"
    return "inconsistent_existing_payment_settlement"


async def _next_payment_numbers(
    *,
    count: int,
    repository: PaymentRepository,
    generator: Callable[[], str],
    using_db: BaseDBAsyncClient,
) -> list[str]:
    """批量避开进程内重复和已占用 PaymentNo。"""

    numbers: list[str] = []
    reserved: set[str] = set()

    def generate_unique() -> str:
        for _ in range(_PAYMENT_NUMBER_GENERATION_MAX_ATTEMPTS):
            candidate = generator()
            if (
                re.fullmatch(PAYMENT_NO_PATTERN, candidate) is not None
                and candidate not in reserved
            ):
                reserved.add(candidate)
                return candidate
        raise RuntimeError("Unable to generate a unique legacy payment number")

    for _ in range(count):
        numbers.append(generate_unique())

    for _ in range(_PAYMENT_NUMBER_GENERATION_MAX_ATTEMPTS):
        collisions = await repository.get_existing_payment_numbers(
            set(numbers),
            using_db=using_db,
        )
        if not collisions:
            return numbers
        reserved.difference_update(collisions)
        for index, payment_no in enumerate(numbers):
            if payment_no in collisions:
                numbers[index] = generate_unique()
    raise RuntimeError("Legacy payment number collision retry exhausted")


async def _process_batch(
    *,
    orders: list[Order],
    owners: list[User],
    audit_repository: AuditLogRepository,
    payment_repository: PaymentRepository,
    dry_run: bool,
    payment_number_generator: Callable[[], str],
    using_db: BaseDBAsyncClient | None,
) -> _BatchResult:
    order_ids = {order.id for order in orders}
    expected_keys = {_legacy_key(order.id) for order in orders}
    audits = await audit_repository.list_by_action_targets(
        action=ORDER_AUDIT_ACTION_MARK_PAID,
        target_type=ORDER_AUDIT_TARGET_TYPE,
        target_ids=order_ids,
        using_db=using_db,
    )
    order_payments = await payment_repository.list_payments_by_order_ids(
        order_ids,
        using_db=using_db,
    )
    keyed_payments = await payment_repository.list_payments_by_idempotency_keys(
        expected_keys,
        using_db=using_db,
    )
    settlements = await payment_repository.list_settlements_by_order_ids(
        order_ids,
        using_db=using_db,
    )

    audits_by_order_id: dict[int, list[AuditLog]] = defaultdict(list)
    for audit in audits:
        audits_by_order_id[audit.target_id].append(audit)
    payments_by_order_id: dict[int, list[Payment]] = defaultdict(list)
    for payment in order_payments:
        if payment.order_id is not None:
            payments_by_order_id[payment.order_id].append(payment)
    payments_by_key = {payment.idempotency_key: payment for payment in keyed_payments}
    settlements_by_order_id = {
        settlement.order_id: settlement for settlement in settlements
    }
    owners_by_id = {owner.id: owner for owner in owners}

    intents: list[_CreateIntent] = []
    blockers: list[LegacySettlementBlocker] = []
    replayed = 0
    for order in orders:
        owner = owners_by_id.get(order.user_id)
        if owner is None:
            blockers.append(
                LegacySettlementBlocker(
                    order_id=order.id,
                    reason="missing_order_owner",
                )
            )
            continue
        if owner.role != UserRole.USER:
            blockers.append(
                LegacySettlementBlocker(
                    order_id=order.id,
                    reason="non_customer_order_owner",
                )
            )
            continue
        if owner.status not in (
            UserStatus.NORMAL,
            UserStatus.DISABLED,
            UserStatus.DELETED,
        ):
            blockers.append(
                LegacySettlementBlocker(
                    order_id=order.id,
                    reason="invalid_order_owner_status",
                )
            )
            continue

        paid_audits = audits_by_order_id[order.id]
        if len(paid_audits) != 1:
            blockers.append(
                LegacySettlementBlocker(
                    order_id=order.id,
                    reason=(
                        "missing_mark_order_paid_audit"
                        if not paid_audits
                        else "duplicate_mark_order_paid_audit"
                    ),
                )
            )
            continue

        expected_payment = payments_by_key.get(_legacy_key(order.id))
        payments = payments_by_order_id[order.id]
        settlement = settlements_by_order_id.get(order.id)
        has_financial_fact = bool(payments) or expected_payment is not None or (
            settlement is not None
        )
        if has_financial_fact:
            if _existing_facts_match(
                order=order,
                paid_audit=paid_audits[0],
                order_payments=payments,
                expected_payment=expected_payment,
                settlement=settlement,
            ):
                replayed += 1
                continue
            blockers.append(
                LegacySettlementBlocker(
                    order_id=order.id,
                    reason=_blocker_reason(
                        order=order,
                        order_payments=payments,
                        expected_payment=expected_payment,
                        settlement=settlement,
                    ),
                )
            )
            continue
        if owner.status == UserStatus.DELETED:
            blockers.append(
                LegacySettlementBlocker(
                    order_id=order.id,
                    reason="deleted_order_owner",
                )
            )
            continue
        intents.append(_CreateIntent(order=order, paid_audit=paid_audits[0]))

    if dry_run or blockers or not intents:
        return _BatchResult(
            scanned=len(orders),
            would_create=len(intents) if dry_run or blockers else 0,
            replayed=replayed,
            blockers=tuple(blockers),
        )
    if using_db is None:
        raise RuntimeError("Apply mode requires a transaction connection")

    payment_numbers = await _next_payment_numbers(
        count=len(intents),
        repository=payment_repository,
        generator=payment_number_generator,
        using_db=using_db,
    )
    create_data = [
        PaymentCreateData(
            payment_no=payment_no,
            user_id=intent.order.user_id,
            purpose=PaymentPurpose.ORDER,
            method=PaymentMethod.MANUAL,
            amount=intent.order.total_amount,
            order_id=intent.order.id,
            recharge_order_id=None,
            idempotency_key=_legacy_key(intent.order.id),
            status=PaymentStatus.SUCCEEDED,
            provider_transaction_id=None,
            succeeded_at=intent.paid_audit.created_at,
        )
        for intent, payment_no in zip(intents, payment_numbers, strict=True)
    ]
    await payment_repository.bulk_create_payments(
        data=create_data,
        using_db=using_db,
    )
    created_payments = await payment_repository.list_payments_by_idempotency_keys(
        {item.idempotency_key for item in create_data},
        using_db=using_db,
    )
    created_by_key = {
        payment.idempotency_key: payment for payment in created_payments
    }
    if len(created_by_key) != len(intents):
        raise RuntimeError("Legacy manual payments could not be reloaded")
    for intent in intents:
        payment = created_by_key[_legacy_key(intent.order.id)]
        if not _payment_matches(
            payment,
            order=intent.order,
            paid_at=intent.paid_audit.created_at,
        ):
            raise RuntimeError("Created legacy manual payment is inconsistent")
    await payment_repository.bulk_create_settlements(
        data=[
            PaymentSettlementCreateData(
                payment_id=created_by_key[_legacy_key(intent.order.id)].id,
                order_id=intent.order.id,
                amount=intent.order.total_amount,
            )
            for intent in intents
        ],
        using_db=using_db,
    )
    return _BatchResult(
        scanned=len(orders),
        created=len(intents),
        replayed=replayed,
        blockers=tuple(blockers),
    )


async def backfill_all(
    order_repository: OrderRepository,
    audit_repository: AuditLogRepository,
    payment_repository: PaymentRepository,
    user_repository: UserRepository,
    *,
    batch_size: int,
    dry_run: bool,
    through_order_id: int | None = None,
    payment_number_generator: Callable[[], str] = generate_payment_number,
) -> LegacyManualSettlementTotals:
    """按固定上界与 Order ID 游标核验并补齐历史人工结算。"""

    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if not dry_run and through_order_id is None:
        raise ValueError("apply requires an explicit through_order_id")
    if through_order_id is not None and through_order_id < 1:
        raise ValueError("through_order_id must be positive")
    scope_end = (
        await order_repository.get_latest_order_id()
        if through_order_id is None
        else through_order_id
    )
    if not dry_run:
        preflight = await backfill_all(
            order_repository,
            audit_repository,
            payment_repository,
            user_repository,
            batch_size=batch_size,
            dry_run=True,
            through_order_id=scope_end,
            payment_number_generator=payment_number_generator,
        )
        if preflight.blocked:
            return preflight

    totals = LegacyManualSettlementTotals(through_order_id=scope_end)
    after_order_id = 0
    while True:
        if dry_run:
            orders = await order_repository.list_orders_by_status_cursor(
                statuses=_ELIGIBLE_STATUSES,
                after_order_id=after_order_id,
                through_order_id=scope_end,
                limit=batch_size,
            )
            owners = await user_repository.list_by_ids(
                {order.user_id for order in orders}
            )
            batch = await _process_batch(
                orders=orders,
                owners=owners,
                audit_repository=audit_repository,
                payment_repository=payment_repository,
                dry_run=True,
                payment_number_generator=payment_number_generator,
                using_db=None,
            )
        else:
            # 候选读取不加锁，只用于确定应先锁定的 owner 集合；正式处理前
            # 在同一事务内按 User → Order 顺序加锁并重新执行状态查询。
            candidates = await order_repository.list_orders_by_status_cursor(
                statuses=_ELIGIBLE_STATUSES,
                after_order_id=after_order_id,
                through_order_id=scope_end,
                limit=batch_size,
            )
            async with in_transaction() as connection:
                owners = await user_repository.list_by_ids_for_update(
                    {order.user_id for order in candidates},
                    using_db=connection,
                )
                orders = await order_repository.list_orders_by_status_cursor(
                    statuses=_ELIGIBLE_STATUSES,
                    after_order_id=after_order_id,
                    through_order_id=scope_end,
                    limit=batch_size,
                    for_update=True,
                    using_db=connection,
                )
                batch = await _process_batch(
                    orders=orders,
                    owners=owners,
                    audit_repository=audit_repository,
                    payment_repository=payment_repository,
                    dry_run=False,
                    payment_number_generator=payment_number_generator,
                    using_db=connection,
                )

        for blocker in batch.blockers:
            logger.error(
                "Legacy manual settlement blocked: order_id=%d reason=%s",
                blocker.order_id,
                blocker.reason,
            )
        totals = LegacyManualSettlementTotals(
            through_order_id=scope_end,
            scanned=totals.scanned + batch.scanned,
            created=totals.created + batch.created,
            would_create=totals.would_create + batch.would_create,
            replayed=totals.replayed + batch.replayed,
            blockers=totals.blockers + batch.blockers,
        )
        if not dry_run and batch.blockers:
            return totals
        cursor_orders = orders if dry_run else candidates
        if not cursor_orders or len(cursor_orders) < batch_size:
            return totals
        after_order_id = cursor_orders[-1].id


def _positive_order_id(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("order id must be a positive integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("order id must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill verified legacy manual Payment/Settlement facts.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        choices=range(1, 1001),
        metavar="1..1000",
    )
    parser.add_argument(
        "--through-order-id",
        type=_positive_order_id,
        help=(
            "Freeze the inclusive Order ID scope. Reuse the preview value for "
            "--apply. Preview defaults to the current maximum Order ID; apply "
            "requires this option explicitly."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write verified facts. Without this flag the command only previews.",
    )
    return parser


async def run(
    *,
    batch_size: int,
    dry_run: bool,
    through_order_id: int | None,
) -> LegacyManualSettlementTotals:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        return await backfill_all(
            OrderRepository(),
            AuditLogRepository(),
            PaymentRepository(),
            UserRepository(),
            batch_size=batch_size,
            dry_run=dry_run,
            through_order_id=through_order_id,
        )
    finally:
        await Tortoise.close_connections()


def main() -> int:
    args = build_parser().parse_args()
    setup_logging()
    if args.apply and args.through_order_id is None:
        logger.error(
            "--apply requires --through-order-id from the completed preview"
        )
        return 2
    try:
        totals = asyncio.run(
            run(
                batch_size=args.batch_size,
                dry_run=not args.apply,
                through_order_id=args.through_order_id,
            )
        )
    except Exception as error:
        logger.error(
            "Legacy manual settlement backfill failed: error_type=%s",
            type(error).__name__,
        )
        return 1
    logger.info(
        "Legacy manual settlement backfill complete: mode=%s "
        "through_order_id=%d scanned=%d created=%d would_create=%d "
        "replayed=%d blocked=%d",
        "apply" if args.apply else "preview",
        totals.through_order_id,
        totals.scanned,
        totals.created,
        totals.would_create,
        totals.replayed,
        totals.blocked,
    )
    return 2 if totals.blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
