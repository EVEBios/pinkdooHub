"""历史人工支付 Payment/Settlement 受控回填测试。"""

import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from tortoise.backends.base.client import BaseDBAsyncClient

from app.common.constants.order import (
    ORDER_AUDIT_ACTION_MARK_PAID,
    ORDER_AUDIT_TARGET_TYPE,
)
from app.common.constants.wallet import LEGACY_MANUAL_PAYMENT_IDEMPOTENCY_KEY
from app.common.enums.order import OrderStatus
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import PaymentMethod, PaymentPurpose, PaymentStatus
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.payment import Payment, PaymentSettlement
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.user_repo import UserRepository
from app.tasks import legacy_manual_settlement_backfill as command
from app.tasks.legacy_manual_settlement_backfill import (
    LegacyManualSettlementTotals,
    LegacySettlementBlocker,
    backfill_all,
)


def _number(value: int) -> str:
    return f"PY{value:026d}"


def _generator(values: list[str]) -> Iterator[str]:
    yield from values


async def _user(
    username: str,
    role: UserRole = UserRole.USER,
    status: UserStatus = UserStatus.NORMAL,
) -> User:
    return await User.create(
        username=username,
        password="hashed-password",
        nickname=username,
        role=role.value,
        status=status.value,
    )


async def _order(user: User, *, sequence: int, status: OrderStatus) -> Order:
    return await Order.create(
        order_no=f"OD{sequence:026d}",
        user=user,
        total_amount=Decimal(f"{sequence}.00"),
        status=status.value,
        remark=None,
    )


async def _paid_audit(order: Order, operator: User) -> AuditLog:
    return await AuditLog.create(
        operator_id=operator.id,
        action=ORDER_AUDIT_ACTION_MARK_PAID,
        target_type=ORDER_AUDIT_TARGET_TYPE,
        target_id=order.id,
        ip_address="127.0.0.1",
    )


def _repositories() -> tuple[
    OrderRepository,
    AuditLogRepository,
    PaymentRepository,
    UserRepository,
]:
    return (
        OrderRepository(),
        AuditLogRepository(),
        PaymentRepository(),
        UserRepository(),
    )


class _LateDuplicateAuditRepository(AuditLogRepository):
    """仅在 apply 的锁内复验阶段模拟新增重复审计。"""

    async def list_by_action_targets(
        self,
        *,
        action: str,
        target_type: str,
        target_ids: set[int],
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[AuditLog]:
        audits = await super().list_by_action_targets(
            action=action,
            target_type=target_type,
            target_ids=target_ids,
            using_db=using_db,
        )
        if using_db is not None and audits:
            return [*audits, audits[0]]
        return audits


async def test_preview_apply_and_exact_replay_use_historical_audit_time() -> None:
    operator = await _user("legacy-settlement-admin", UserRole.ADMIN)
    customer = await _user("legacy-settlement-customer")
    paid = await _order(customer, sequence=11, status=OrderStatus.PAID)
    completed = await _order(customer, sequence=12, status=OrderStatus.COMPLETED)
    audits = {
        paid.id: await _paid_audit(paid, operator),
        completed.id: await _paid_audit(completed, operator),
    }
    (
        order_repository,
        audit_repository,
        payment_repository,
        user_repository,
    ) = _repositories()

    preview = await backfill_all(
        order_repository,
        audit_repository,
        payment_repository,
        user_repository,
        batch_size=1,
        dry_run=True,
    )

    assert preview.through_order_id == completed.id
    assert preview.scanned == preview.would_create == 2
    assert preview.created == preview.replayed == preview.blocked == 0
    assert not await Payment.all().exists()
    assert not await PaymentSettlement.all().exists()

    numbers = _generator([_number(101), _number(102)])
    applied = await backfill_all(
        order_repository,
        audit_repository,
        payment_repository,
        user_repository,
        batch_size=2,
        dry_run=False,
        through_order_id=preview.through_order_id,
        payment_number_generator=lambda: next(numbers),
    )

    assert applied.scanned == applied.created == 2
    assert applied.would_create == applied.replayed == applied.blocked == 0
    payments = await Payment.all().order_by("order_id")
    settlements = await PaymentSettlement.all().order_by("order_id")
    assert len(payments) == len(settlements) == 2
    for payment, settlement, order in zip(
        payments,
        settlements,
        (paid, completed),
        strict=True,
    ):
        assert payment.user_id == customer.id
        assert payment.purpose is PaymentPurpose.ORDER
        assert payment.method is PaymentMethod.MANUAL
        assert payment.status is PaymentStatus.SUCCEEDED
        assert payment.amount == order.total_amount
        assert payment.order_id == order.id
        assert payment.recharge_order_id is None
        assert payment.provider_transaction_id is None
        assert payment.idempotency_key == (
            LEGACY_MANUAL_PAYMENT_IDEMPOTENCY_KEY.format(order_id=order.id)
        )
        assert payment.succeeded_at == audits[order.id].created_at
        assert settlement.payment_id == payment.id
        assert settlement.order_id == order.id
        assert settlement.amount == order.total_amount

    replay = await backfill_all(
        order_repository,
        audit_repository,
        payment_repository,
        user_repository,
        batch_size=2,
        dry_run=False,
        through_order_id=preview.through_order_id,
        payment_number_generator=lambda: (_ for _ in ()).throw(
            AssertionError("exact replay must not generate another PaymentNo")
        ),
    )
    assert replay.scanned == replay.replayed == 2
    assert replay.created == replay.would_create == replay.blocked == 0
    assert await Payment.all().count() == 2
    assert await PaymentSettlement.all().count() == 2


async def test_apply_is_globally_zero_write_when_preflight_finds_blockers() -> None:
    operator = await _user("legacy-blocker-admin", UserRole.ADMIN)
    customer = await _user("legacy-blocker-customer")
    missing_audit = await _order(customer, sequence=21, status=OrderStatus.PAID)
    duplicate_audit = await _order(
        customer,
        sequence=22,
        status=OrderStatus.COMPLETED,
    )
    await _paid_audit(duplicate_audit, operator)
    await _paid_audit(duplicate_audit, operator)
    partial = await _order(customer, sequence=23, status=OrderStatus.PAID)
    partial_audit = await _paid_audit(partial, operator)
    await Payment.create(
        payment_no=_number(201),
        user=customer,
        purpose=PaymentPurpose.ORDER,
        method=PaymentMethod.MANUAL,
        amount=partial.total_amount,
        status=PaymentStatus.SUCCEEDED,
        order=partial,
        recharge_order=None,
        idempotency_key=LEGACY_MANUAL_PAYMENT_IDEMPOTENCY_KEY.format(
            order_id=partial.id
        ),
        provider_transaction_id=None,
        succeeded_at=partial_audit.created_at,
    )
    clean = await _order(customer, sequence=24, status=OrderStatus.PAID)
    await _paid_audit(clean, operator)
    numbers = _generator([_number(202)])

    totals = await backfill_all(
        *_repositories(),
        batch_size=4,
        dry_run=False,
        through_order_id=clean.id,
        payment_number_generator=lambda: next(numbers),
    )

    assert totals.scanned == 4
    assert totals.created == 0
    assert totals.would_create == 1
    assert totals.replayed == 0
    assert totals.blocked == 3
    assert {(item.order_id, item.reason) for item in totals.blockers} == {
        (missing_audit.id, "missing_mark_order_paid_audit"),
        (duplicate_audit.id, "duplicate_mark_order_paid_audit"),
        (partial.id, "partial_payment_without_settlement"),
    }
    assert await Payment.filter(order_id=clean.id).count() == 0
    assert await PaymentSettlement.filter(order_id=clean.id).count() == 0
    assert await PaymentSettlement.filter(order_id=partial.id).count() == 0


async def test_apply_stops_with_current_batch_zero_write_on_late_blocker() -> None:
    operator = await _user("legacy-late-admin", UserRole.ADMIN)
    customer = await _user("legacy-late-customer")
    order = await _order(customer, sequence=25, status=OrderStatus.PAID)
    await _paid_audit(order, operator)

    totals = await backfill_all(
        OrderRepository(),
        _LateDuplicateAuditRepository(),
        PaymentRepository(),
        UserRepository(),
        batch_size=10,
        dry_run=False,
        through_order_id=order.id,
        payment_number_generator=lambda: _number(205),
    )

    assert totals.scanned == 1
    assert totals.created == totals.replayed == 0
    assert totals.would_create == 0
    assert totals.blockers == (
        LegacySettlementBlocker(
            order_id=order.id,
            reason="duplicate_mark_order_paid_audit",
        ),
    )
    assert not await Payment.filter(order_id=order.id).exists()
    assert not await PaymentSettlement.filter(order_id=order.id).exists()


async def test_owner_rules_allow_disabled_history_but_block_staff_and_deleted() -> None:
    operator = await _user("legacy-owner-super", UserRole.SUPER_ADMIN)
    disabled = await _user(
        "legacy-owner-disabled",
        status=UserStatus.DISABLED,
    )
    disabled_order = await _order(
        disabled,
        sequence=26,
        status=OrderStatus.PAID,
    )
    await _paid_audit(disabled_order, operator)
    disabled_result = await backfill_all(
        *_repositories(),
        batch_size=10,
        dry_run=False,
        through_order_id=disabled_order.id,
        payment_number_generator=lambda: _number(206),
    )
    assert disabled_result.created == 1

    privileged = await _user("legacy-owner-admin", UserRole.ADMIN)
    privileged_order = await _order(
        privileged,
        sequence=27,
        status=OrderStatus.PAID,
    )
    await _paid_audit(privileged_order, operator)
    deleted = await _user(
        "legacy-owner-deleted",
        status=UserStatus.DELETED,
    )
    deleted_order = await _order(
        deleted,
        sequence=28,
        status=OrderStatus.COMPLETED,
    )
    await _paid_audit(deleted_order, operator)
    invalid_status = await User.create(
        username="legacy-owner-invalid-status",
        password="hashed-password",
        nickname="legacy-owner-invalid-status",
        role=UserRole.USER.value,
        status=99,
    )
    invalid_status_order = await _order(
        invalid_status,
        sequence=30,
        status=OrderStatus.PAID,
    )
    await _paid_audit(invalid_status_order, operator)

    blocked = await backfill_all(
        *_repositories(),
        batch_size=10,
        dry_run=False,
        through_order_id=invalid_status_order.id,
        payment_number_generator=lambda: (_ for _ in ()).throw(
            AssertionError("blocked scope must not generate another PaymentNo")
        ),
    )

    assert blocked.created == 0
    assert blocked.replayed == 1
    assert {(item.order_id, item.reason) for item in blocked.blockers} == {
        (privileged_order.id, "non_customer_order_owner"),
        (deleted_order.id, "deleted_order_owner"),
        (invalid_status_order.id, "invalid_order_owner_status"),
    }
    assert not await Payment.filter(order_id=privileged_order.id).exists()
    assert not await Payment.filter(order_id=deleted_order.id).exists()
    assert not await Payment.filter(order_id=invalid_status_order.id).exists()


async def test_deleted_owner_exact_fact_remains_a_safe_replay() -> None:
    operator = await _user("legacy-deleted-replay-admin", UserRole.ADMIN)
    customer = await _user("legacy-deleted-replay-customer")
    order = await _order(customer, sequence=29, status=OrderStatus.PAID)
    await _paid_audit(order, operator)
    await backfill_all(
        *_repositories(),
        batch_size=10,
        dry_run=False,
        through_order_id=order.id,
        payment_number_generator=lambda: _number(209),
    )
    customer.status = UserStatus.DELETED.value
    await customer.save(update_fields=["status", "updated_at"])

    replay = await backfill_all(
        *_repositories(),
        batch_size=10,
        dry_run=False,
        through_order_id=order.id,
        payment_number_generator=lambda: (_ for _ in ()).throw(
            AssertionError("exact replay must not create a new fact")
        ),
    )

    assert replay.scanned == replay.replayed == 1
    assert replay.created == replay.would_create == replay.blocked == 0
    assert await Payment.filter(order_id=order.id).count() == 1
    assert await PaymentSettlement.filter(order_id=order.id).count() == 1


async def test_payment_number_collision_is_retried_in_one_batch() -> None:
    operator = await _user("legacy-number-admin", UserRole.ADMIN)
    customer = await _user("legacy-number-customer")
    existing_order = await _order(customer, sequence=31, status=OrderStatus.PENDING)
    await Payment.create(
        payment_no=_number(301),
        user=customer,
        purpose=PaymentPurpose.ORDER,
        method=PaymentMethod.MANUAL,
        amount=existing_order.total_amount,
        status=PaymentStatus.PENDING,
        order=existing_order,
        recharge_order=None,
        idempotency_key="payment:test:existing-number",
    )
    candidate = await _order(customer, sequence=32, status=OrderStatus.PAID)
    await _paid_audit(candidate, operator)
    numbers = _generator([_number(301), _number(302)])

    totals = await backfill_all(
        *_repositories(),
        batch_size=10,
        dry_run=False,
        through_order_id=candidate.id,
        payment_number_generator=lambda: next(numbers),
    )

    assert totals.created == 1
    created = await Payment.get(order_id=candidate.id)
    assert created.payment_no == _number(302)


def test_cli_defaults_to_preview_and_returns_nonzero_for_blockers(
    monkeypatch,
) -> None:
    assert command.build_parser().parse_args([]).apply is False

    async def blocked_run(**_: object) -> LegacyManualSettlementTotals:
        return LegacyManualSettlementTotals(
            through_order_id=9,
            scanned=1,
            blockers=(LegacySettlementBlocker(order_id=9, reason="conflict"),),
        )

    monkeypatch.setattr(command, "run", blocked_run)
    monkeypatch.setattr(command, "setup_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", ["legacy-manual-settlement-backfill"])

    assert command.main() == 2


async def test_apply_requires_explicit_preview_upper_bound() -> None:
    with pytest.raises(ValueError, match="explicit through_order_id"):
        await backfill_all(
            *_repositories(),
            batch_size=10,
            dry_run=False,
        )


def test_cli_rejects_apply_without_preview_upper_bound(monkeypatch) -> None:
    monkeypatch.setattr(command, "setup_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", ["legacy-manual-settlement-backfill", "--apply"])
    monkeypatch.setattr(
        command,
        "run",
        lambda **_: (_ for _ in ()).throw(AssertionError("must not open database")),
    )

    assert command.main() == 2
