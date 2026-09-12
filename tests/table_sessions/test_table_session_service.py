from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductType
from app.common.enums.table_session import (
    TableSessionCloseReason,
    TableSessionStatus,
)
from app.common.enums.user import UserRole
from app.common.exceptions.table_session import (
    TableIdempotencyConflict,
    TableOrderIneligible,
    TablePaymentWindowExpired,
)
from app.core.config import settings
from app.core.exceptions import ServiceUnavailableException
from app.models.experience_option import ExperienceOption
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PaymentSettlement
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.table_session import StoreTable, TableOccupancy, TableSessionTimer
from app.models.user import User
from app.models.wallet import WalletAccount
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.table_session_repo import TableSessionRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import WalletRepository
from app.services.audit_log_service import AuditLogService
from app.services.payment_service import PaymentService
from app.services.order_service import OrderService
from app.services.table_session_service import TableSessionService
from app.tasks.table_reconcile import reconcile


def _number(prefix: str, sequence: int) -> str:
    return f"{prefix}{sequence:026d}"


async def _user(name: str, *, balance: str = "500.00") -> User:
    user = await User.create(
        username=name,
        password="hashed-password",
        nickname=name,
        role=UserRole.USER.value,
    )
    await WalletAccount.create(user=user, balance=Decimal(balance))
    return user


async def _order(
    user: User,
    *,
    sequence: int,
    durations: list[tuple[int, int]],
    include_kit: bool = False,
) -> Order:
    order = await Order.create(
        order_no=_number("OD", sequence),
        user=user,
        total_amount=Decimal("100.00"),
        status=OrderStatus.PENDING.value,
    )
    for index, (duration, quantity) in enumerate(durations, start=1):
        product = await Product.create(
            name=f"体验-{sequence}-{index}",
            product_type=ProductType.EXPERIENCE,
        )
        option = await ExperienceOption.create(
            product=product,
            duration=duration,
            participants=2,
            day_type=DayType.WEEKDAY,
            price=Decimal("20.00"),
        )
        await OrderItem.create(
            order=order,
            product=product,
            experience_option=option,
            product_name=product.name,
            product_price=Decimal("20.00"),
            option_duration_minutes=duration,
            option_participants=2,
            option_day_type=DayType.WEEKDAY,
            quantity=quantity,
            subtotal=Decimal("20.00") * quantity,
        )
    if include_kit:
        product = await Product.create(
            name=f"材料包-{sequence}",
            product_type=ProductType.KIT,
        )
        await ProductKit.create(product=product, price=Decimal("20.00"), stock=10)
        await OrderItem.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=Decimal("20.00"),
            quantity=3,
            subtotal=Decimal("60.00"),
        )
    return order


def _services(
    *,
    now: datetime,
    payment_now: datetime | None = None,
) -> tuple[TableSessionService, PaymentService]:
    table_repository = TableSessionRepository()
    order_repository = OrderRepository()
    payment_repository = PaymentRepository()
    user_repository = UserRepository()
    audit = AuditLogService(AuditLogRepository())
    sequence = iter(range(1, 100))
    return (
        TableSessionService(
            table_repository,
            order_repository,
            user_repository,
            payment_repository,
            audit,
            now_provider=lambda: now,
            session_number_generator=lambda: _number("TS", next(sequence)),
        ),
        PaymentService(
            order_repository,
            payment_repository,
            WalletRepository(),
            user_repository,
            audit,
            table_repository,
            now_provider=lambda: payment_now or now,
        ),
    )


def _manual_order_service(*, now: datetime) -> OrderService:
    return OrderService(
        OrderRepository(),
        ProductRepository(),
        InventoryRepository(),
        AuditLogService(AuditLogRepository()),
        user_repository=UserRepository(),
        payment_repository=PaymentRepository(),
        wallet_repository=WalletRepository(),
        table_session_repository=TableSessionRepository(),
        now_provider=lambda: now,
        payment_number_generator=lambda: _number("PY", 88),
    )


async def test_claim_and_wallet_payment_create_distinct_shared_timers() -> None:
    now = datetime.now(timezone.utc)
    user = await _user("table-customer")
    order = await _order(
        user,
        sequence=1,
        durations=[(120, 2), (120, 1), (60, 4)],
        include_kit=True,
    )
    table = await StoreTable.create(
        table_no="T01",
        display_name="T01号桌",
        qr_token="Aa0123456789BbCcDdEeFfGgHhIiJjKk",
    )
    table_service, payment_service = _services(now=now)

    created = await table_service.create_session(
        user=user,
        qr_token=table.qr_token,
        order_id=order.id,
        idempotency_key="claim-1",
        ip_address="127.0.0.1",
    )
    replay = await table_service.create_session(
        user=user,
        qr_token=table.qr_token,
        order_id=order.id,
        idempotency_key="claim-1",
        ip_address="127.0.0.1",
    )
    assert replay.is_replay is True
    assert replay.session.id == created.session.id
    assert created.session.payment_deadline_at == now + timedelta(minutes=15)

    paid = await payment_service.pay_order_with_wallet(
        order.id,
        user=user,
        idempotency_key="wallet-pay-1",
        ip_address="127.0.0.1",
        table_session_no=created.session.session_no,
    )
    session = await table_service.get_current_session(user_id=user.id)
    assert session is not None
    assert TableSessionStatus(session.status) is TableSessionStatus.ACTIVE
    assert session.started_at == paid.payment.succeeded_at
    assert [timer.duration_minutes for timer in session.timers] == [60, 120]
    assert all(timer.buffer_minutes == 10 for timer in session.timers)
    assert session.table_release_at == paid.payment.succeeded_at + timedelta(
        minutes=130
    )
    assert await TableOccupancy.filter(session_id=session.id).exists()
    consistency = await reconcile(TableSessionRepository())
    assert consistency["scanned"] == 1
    assert consistency["violations"] == 0


async def test_pure_kit_cannot_claim_table() -> None:
    now = datetime.now(timezone.utc)
    user = await _user("kit-only-customer")
    order = await _order(user, sequence=2, durations=[], include_kit=True)
    table = await StoreTable.create(
        table_no="T02",
        display_name="T02号桌",
        qr_token="Zz0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    table_service, _ = _services(now=now)

    with pytest.raises(TableOrderIneligible) as exc_info:
        await table_service.create_session(
            user=user,
            qr_token=table.qr_token,
            order_id=order.id,
            idempotency_key="kit-only",
            ip_address="127.0.0.1",
        )
    assert exc_info.value.data == {
        "order_id": order.id,
        "reason": "no_experience_item",
    }


async def test_wallet_payment_accepts_exact_deadline_and_rejects_later_time() -> None:
    claimed_at = datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc)
    deadline = claimed_at + timedelta(minutes=15)
    exact_user = await _user("exact-deadline-customer")
    exact_order = await _order(exact_user, sequence=10, durations=[(120, 3)])
    exact_table = await StoreTable.create(
        table_no="T06",
        display_name="T06号桌",
        qr_token="Tt0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    exact_table_service, exact_payment_service = _services(
        now=claimed_at,
        payment_now=deadline,
    )
    exact_session = await exact_table_service.create_session(
        user=exact_user,
        qr_token=exact_table.qr_token,
        order_id=exact_order.id,
        idempotency_key="exact-deadline-claim",
        ip_address="127.0.0.1",
    )

    paid = await exact_payment_service.pay_order_with_wallet(
        exact_order.id,
        user=exact_user,
        idempotency_key="exact-deadline-payment",
        ip_address="127.0.0.1",
        table_session_no=exact_session.session.session_no,
    )

    exact_detail = await TableSessionRepository().get_session_detail(
        exact_session.session.id
    )
    assert exact_detail is not None
    assert exact_detail.started_at == paid.payment.succeeded_at == deadline
    assert [timer.duration_minutes for timer in exact_detail.timers] == [120]

    late_user = await _user("late-deadline-customer")
    late_order = await _order(late_user, sequence=11, durations=[(60, 1)])
    late_table = await StoreTable.create(
        table_no="T07",
        display_name="T07号桌",
        qr_token="Uu0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    late_table_service, late_payment_service = _services(
        now=claimed_at,
        payment_now=deadline + timedelta(microseconds=1),
    )
    late_session = await late_table_service.create_session(
        user=late_user,
        qr_token=late_table.qr_token,
        order_id=late_order.id,
        idempotency_key="late-deadline-claim",
        ip_address="127.0.0.1",
    )

    with pytest.raises(TablePaymentWindowExpired):
        await late_payment_service.pay_order_with_wallet(
            late_order.id,
            user=late_user,
            idempotency_key="late-deadline-payment",
            ip_address="127.0.0.1",
            table_session_no=late_session.session.session_no,
        )

    await late_order.refresh_from_db()
    late_account = await WalletAccount.get(user_id=late_user.id)
    late_detail = await TableSessionRepository().get_session_detail(
        late_session.session.id
    )
    assert late_detail is not None
    assert late_order.status == OrderStatus.PENDING.value
    assert late_account.balance == Decimal("500.00")
    assert TableSessionStatus(late_detail.status) is TableSessionStatus.AWAITING_PAYMENT
    assert list(late_detail.timers) == []
    assert await Payment.all().count() == 1
    assert await PaymentSettlement.all().count() == 1


async def test_late_sessionless_payment_releases_table_but_explicit_history_fails() -> None:
    claimed_at = datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc)
    late_at = claimed_at + timedelta(minutes=15, microseconds=1)

    ordinary_user = await _user("late-ordinary-payment-customer")
    ordinary_order = await _order(ordinary_user, sequence=12, durations=[(60, 1)])
    ordinary_table = await StoreTable.create(
        table_no="T08",
        display_name="T08号桌",
        qr_token="Vv0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    ordinary_table_service, ordinary_payment_service = _services(
        now=claimed_at,
        payment_now=late_at,
    )
    ordinary_session = await ordinary_table_service.create_session(
        user=ordinary_user,
        qr_token=ordinary_table.qr_token,
        order_id=ordinary_order.id,
        idempotency_key="late-ordinary-claim",
        ip_address="127.0.0.1",
    )

    paid = await ordinary_payment_service.pay_order_with_wallet(
        ordinary_order.id,
        user=ordinary_user,
        idempotency_key="late-ordinary-payment",
        ip_address="127.0.0.1",
    )

    ordinary_detail = await TableSessionRepository().get_session_detail(
        ordinary_session.session.id
    )
    assert ordinary_detail is not None
    assert paid.order.status == OrderStatus.PAID.value
    assert ordinary_detail.close_reason is TableSessionCloseReason.PAYMENT_TIMEOUT
    assert list(ordinary_detail.timers) == []
    assert not await TableOccupancy.filter(session_id=ordinary_detail.id).exists()

    explicit_user = await _user("late-explicit-history-customer")
    explicit_order = await _order(explicit_user, sequence=13, durations=[(90, 1)])
    explicit_table = await StoreTable.create(
        table_no="T09",
        display_name="T09号桌",
        qr_token="Ww0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    explicit_table_service, explicit_payment_service = _services(
        now=claimed_at,
        payment_now=late_at,
    )
    explicit_session = await explicit_table_service.create_session(
        user=explicit_user,
        qr_token=explicit_table.qr_token,
        order_id=explicit_order.id,
        idempotency_key="late-explicit-claim",
        ip_address="127.0.0.1",
    )
    assert await explicit_table_service.converge_session(
        explicit_session.session.id,
        now=late_at,
    )

    with pytest.raises(TablePaymentWindowExpired):
        await explicit_payment_service.pay_order_with_wallet(
            explicit_order.id,
            user=explicit_user,
            idempotency_key="late-explicit-history-payment",
            ip_address="127.0.0.1",
            table_session_no=explicit_session.session.session_no,
        )

    await explicit_order.refresh_from_db()
    assert explicit_order.status == OrderStatus.PENDING.value
    assert await Payment.filter(order_id=explicit_order.id).count() == 0
    assert await PaymentSettlement.filter(order_id=explicit_order.id).count() == 0


async def test_manual_payment_at_exact_deadline_activates_same_timer_contract() -> None:
    claimed_at = datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc)
    deadline = claimed_at + timedelta(minutes=15)
    customer = await _user("manual-table-customer")
    admin = await User.create(
        username="manual-table-admin",
        password="hashed-password",
        nickname="manual-table-admin",
        role=UserRole.ADMIN.value,
    )
    order = await _order(
        customer,
        sequence=16,
        durations=[(120, 2), (120, 1), (60, 5)],
        include_kit=True,
    )
    table = await StoreTable.create(
        table_no="T12",
        display_name="T12号桌",
        qr_token="Zz0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    table_service, _ = _services(now=claimed_at)
    created = await table_service.create_session(
        user=customer,
        qr_token=table.qr_token,
        order_id=order.id,
        idempotency_key="manual-payment-claim",
        ip_address="127.0.0.1",
    )

    paid = await _manual_order_service(now=deadline).mark_order_paid(
        order.id,
        operator_id=admin.id,
        ip_address="127.0.0.1",
        table_session_no=created.session.session_no,
    )

    detail = await TableSessionRepository().get_session_detail(created.session.id)
    assert detail is not None
    assert paid.status == OrderStatus.PAID.value
    assert detail.started_at == deadline
    assert [timer.duration_minutes for timer in detail.timers] == [60, 120]
    assert detail.table_release_at == deadline + timedelta(minutes=130)


async def test_claim_feature_flag_preserves_replay_and_safe_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    user = await _user("feature-flag-customer")
    first_order = await _order(user, sequence=14, durations=[(60, 1)])
    second_order = await _order(user, sequence=15, durations=[(90, 1)])
    first_table = await StoreTable.create(
        table_no="T10",
        display_name="T10号桌",
        qr_token="Xx0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    second_table = await StoreTable.create(
        table_no="T11",
        display_name="T11号桌",
        qr_token="Yy0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    service, _ = _services(now=now)
    created = await service.create_session(
        user=user,
        qr_token=first_table.qr_token,
        order_id=first_order.id,
        idempotency_key="feature-flag-original",
        ip_address="127.0.0.1",
    )
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "table_session_claims_enabled", False)

    replay = await service.create_session(
        user=user,
        qr_token=first_table.qr_token,
        order_id=first_order.id,
        idempotency_key="feature-flag-original",
        ip_address="127.0.0.1",
    )
    assert replay.is_replay is True
    assert replay.session.id == created.session.id
    assert (await service.get_current_session(user_id=user.id)) is not None

    with pytest.raises(ServiceUnavailableException):
        await service.create_session(
            user=user,
            qr_token=second_table.qr_token,
            order_id=second_order.id,
            idempotency_key="feature-flag-new",
            ip_address="127.0.0.1",
        )

    with pytest.raises(TableIdempotencyConflict):
        await service.create_session(
            user=user,
            qr_token=second_table.qr_token,
            order_id=second_order.id,
            idempotency_key="feature-flag-original",
            ip_address="127.0.0.1",
        )


async def test_payment_timeout_releases_table_and_allows_rebind() -> None:
    claimed_at = datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc)
    user = await _user("timeout-customer")
    first_order = await _order(user, sequence=3, durations=[(60, 1)])
    second_order = await _order(user, sequence=4, durations=[(90, 1)])
    table = await StoreTable.create(
        table_no="T03",
        display_name="T03号桌",
        qr_token="Qq0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    table_service, _ = _services(now=claimed_at)
    first = await table_service.create_session(
        user=user,
        qr_token=table.qr_token,
        order_id=first_order.id,
        idempotency_key="timeout-first",
        ip_address="127.0.0.1",
    )

    closed = await table_service.converge_session(
        first.session.id,
        now=claimed_at + timedelta(minutes=15, microseconds=1),
    )
    assert closed is True
    first_detail = await TableSessionRepository().get_session_detail(first.session.id)
    assert first_detail is not None
    assert first_detail.close_reason is TableSessionCloseReason.PAYMENT_TIMEOUT
    assert not await TableOccupancy.filter(table_id=table.id).exists()

    second = await table_service.create_session(
        user=user,
        qr_token=table.qr_token,
        order_id=second_order.id,
        idempotency_key="timeout-second",
        ip_address="127.0.0.1",
    )
    assert second.session.order_id == second_order.id


async def test_claim_rechecks_target_occupancy_after_lock_boundary() -> None:
    claimed_at = datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc)
    first_user = await _user("boundary-first-customer")
    second_user = await _user("boundary-second-customer")
    first_order = await _order(first_user, sequence=7, durations=[(60, 1)])
    second_order = await _order(second_user, sequence=8, durations=[(90, 1)])
    table = await StoreTable.create(
        table_no="T04",
        display_name="T04号桌",
        qr_token="Rr0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    first_service, _ = _services(now=claimed_at)
    first = await first_service.create_session(
        user=first_user,
        qr_token=table.qr_token,
        order_id=first_order.id,
        idempotency_key="boundary-first",
        ip_address="127.0.0.1",
    )

    deadline = claimed_at + timedelta(minutes=15)
    clock = iter(
        (
            deadline,
            deadline + timedelta(microseconds=1),
            deadline + timedelta(microseconds=1),
        )
    )
    second_service = TableSessionService(
        TableSessionRepository(),
        OrderRepository(),
        UserRepository(),
        PaymentRepository(),
        AuditLogService(AuditLogRepository()),
        now_provider=lambda: next(clock),
        session_number_generator=lambda: _number("TS", 99),
    )

    second = await second_service.create_session(
        user=second_user,
        qr_token=table.qr_token,
        order_id=second_order.id,
        idempotency_key="boundary-second",
        ip_address="127.0.0.1",
    )

    first_detail = await TableSessionRepository().get_session_detail(first.session.id)
    assert first_detail is not None
    assert first_detail.close_reason is TableSessionCloseReason.PAYMENT_TIMEOUT
    assert second.session.order_id == second_order.id
    assert await TableOccupancy.filter(table_id=table.id).count() == 1


async def test_reconcile_rejects_occupancy_whose_dimensions_do_not_match_session() -> None:
    now = datetime.now(timezone.utc)
    owner = await _user("reconcile-owner")
    other = await _user("reconcile-other")
    order = await _order(owner, sequence=9, durations=[(60, 1)])
    table = await StoreTable.create(
        table_no="T05",
        display_name="T05号桌",
        qr_token="Ss0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    service, _ = _services(now=now)
    created = await service.create_session(
        user=owner,
        qr_token=table.qr_token,
        order_id=order.id,
        idempotency_key="reconcile-mismatch",
        ip_address="127.0.0.1",
    )
    await TableOccupancy.filter(session_id=created.session.id).update(
        user_id=other.id,
    )

    result = await reconcile(TableSessionRepository())

    assert result["scanned"] == 1
    assert result["violations"] == 1


async def test_reconcile_checks_closed_session_timer_history() -> None:
    now = datetime.now(timezone.utc)
    owner = await _user("reconcile-closed-owner")
    order = await _order(owner, sequence=10, durations=[(60, 2)])
    table = await StoreTable.create(
        table_no="T13",
        display_name="T13号桌",
        qr_token="Tt0123456789AaBbCcDdEeFfGgHhIiJj",
    )
    service, payment_service = _services(now=now)
    created = await service.create_session(
        user=owner,
        qr_token=table.qr_token,
        order_id=order.id,
        idempotency_key="reconcile-closed-history",
        ip_address="127.0.0.1",
    )
    await payment_service.pay_order_with_wallet(
        order.id,
        user=owner,
        idempotency_key="reconcile-closed-payment",
        ip_address="127.0.0.1",
        table_session_no=created.session.session_no,
    )
    await service.converge_session(
        created.session.id,
        now=now + timedelta(minutes=70),
    )
    timer = await TableSessionTimer.get(session_id=created.session.id)
    await TableSessionTimer.filter(id=timer.id).update(buffer_minutes=9)

    result = await reconcile(TableSessionRepository())

    assert result["scanned"] == 1
    assert result["violations"] == 2
