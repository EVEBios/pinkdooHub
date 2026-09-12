"""M9 同桌并发开台的真实 MySQL 行锁与唯一占用门槛。"""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductType
from app.common.enums.user import UserRole
from app.common.exceptions.table_session import (
    TableSessionStatusConflict,
    TableUnavailable,
    UserTableSessionConflict,
)
from app.models.experience_option import ExperienceOption
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.payment import Payment, PaymentSettlement
from app.models.table_session import StoreTable, TableOccupancy, TableSession
from app.models.user import User
from app.models.wallet import WalletAccount
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.table_session_repo import TableSessionRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import WalletRepository
from app.services.audit_log_service import AuditLogService
from app.services.payment_service import PaymentService
from app.services.table_session_service import TableSessionService


pytestmark = pytest.mark.mysql


async def _customer_order(sequence: int) -> tuple[User, Order]:
    user = await User.create(
        username=f"m9-mysql-user-{sequence}",
        password="ci-only-hash",
        nickname=f"M9 user {sequence}",
        role=UserRole.USER.value,
    )
    product = await Product.create(
        name=f"M9 MySQL experience {sequence}",
        product_type=ProductType.EXPERIENCE,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=120,
        participants=2,
        day_type=DayType.WEEKDAY,
        price=Decimal("100.00"),
    )
    order = await Order.create(
        order_no=f"OD{sequence:026d}",
        user=user,
        total_amount=Decimal("100.00"),
        status=OrderStatus.PENDING.value,
    )
    await OrderItem.create(
        order=order,
        product=product,
        experience_option=option,
        product_name=product.name,
        product_price=Decimal("100.00"),
        option_duration_minutes=120,
        option_participants=2,
        option_day_type=DayType.WEEKDAY,
        quantity=1,
        subtotal=Decimal("100.00"),
    )
    return user, order


def _service(sequence: int) -> TableSessionService:
    return TableSessionService(
        TableSessionRepository(),
        OrderRepository(),
        UserRepository(),
        PaymentRepository(),
        AuditLogService(AuditLogRepository()),
        session_number_generator=lambda: f"TS{sequence:026d}",
    )


async def test_concurrent_claims_create_exactly_one_table_occupancy() -> None:
    first_user, first_order = await _customer_order(1)
    second_user, second_order = await _customer_order(2)
    table = await StoreTable.create(
        table_no="T01",
        display_name="T01号桌",
        qr_token="Aa0123456789BbCcDdEeFfGgHhIiJjKk",
    )

    results = await asyncio.gather(
        _service(1).create_session(
            user=first_user,
            qr_token=table.qr_token,
            order_id=first_order.id,
            idempotency_key="mysql-concurrent-first",
            ip_address="127.0.0.1",
        ),
        _service(2).create_session(
            user=second_user,
            qr_token=table.qr_token,
            order_id=second_order.id,
            idempotency_key="mysql-concurrent-second",
            ip_address="127.0.0.1",
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(failures) == 1
    assert isinstance(failures[0], TableUnavailable)
    assert await TableOccupancy.filter(table_id=table.id).count() == 1
    assert await TableSession.filter(table_id=table.id).count() == 1


async def test_concurrent_claims_allow_only_one_table_for_same_user() -> None:
    user, first_order = await _customer_order(3)
    second_order = await Order.create(
        order_no=f"OD{4:026d}",
        user=user,
        total_amount=Decimal("100.00"),
        status=OrderStatus.PENDING.value,
    )
    source_item = await OrderItem.filter(order_id=first_order.id).first()
    assert source_item is not None
    await OrderItem.create(
        order=second_order,
        product_id=source_item.product_id,
        experience_option_id=source_item.experience_option_id,
        product_name=source_item.product_name,
        product_price=source_item.product_price,
        option_duration_minutes=source_item.option_duration_minutes,
        option_participants=source_item.option_participants,
        option_day_type=source_item.option_day_type,
        quantity=1,
        subtotal=Decimal("100.00"),
    )
    first_table = await StoreTable.create(
        table_no="T02",
        display_name="T02号桌",
        qr_token="Bb0123456789AaCcDdEeFfGgHhIiJjKk",
    )
    second_table = await StoreTable.create(
        table_no="T03",
        display_name="T03号桌",
        qr_token="Cc0123456789AaBbDdEeFfGgHhIiJjKk",
    )

    results = await asyncio.gather(
        _service(3).create_session(
            user=user,
            qr_token=first_table.qr_token,
            order_id=first_order.id,
            idempotency_key="mysql-same-user-first",
            ip_address="127.0.0.1",
        ),
        _service(4).create_session(
            user=user,
            qr_token=second_table.qr_token,
            order_id=second_order.id,
            idempotency_key="mysql-same-user-second",
            ip_address="127.0.0.1",
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(failures) == 1
    assert isinstance(failures[0], UserTableSessionConflict)
    assert await TableOccupancy.filter(user_id=user.id).count() == 1
    assert await TableOccupancy.all().count() == 1


async def test_concurrent_claims_allow_only_one_table_for_same_order() -> None:
    user, order = await _customer_order(6)
    first_table = await StoreTable.create(
        table_no="T05",
        display_name="T05号桌",
        qr_token="Ee0123456789AaBbCcDdFfGgHhIiJjKk",
    )
    second_table = await StoreTable.create(
        table_no="T06",
        display_name="T06号桌",
        qr_token="Ff0123456789AaBbCcDdEeGgHhIiJjKk",
    )

    results = await asyncio.gather(
        _service(8).create_session(
            user=user,
            qr_token=first_table.qr_token,
            order_id=order.id,
            idempotency_key="mysql-same-order-first",
            ip_address="127.0.0.1",
        ),
        _service(9).create_session(
            user=user,
            qr_token=second_table.qr_token,
            order_id=order.id,
            idempotency_key="mysql-same-order-second",
            ip_address="127.0.0.1",
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert await TableOccupancy.filter(order_id=order.id).count() == 1
    assert await TableSession.filter(order_id=order.id).count() == 1


async def test_concurrent_same_key_admin_release_is_an_idempotent_replay() -> None:
    user, order = await _customer_order(5)
    table = await StoreTable.create(
        table_no="T04",
        display_name="T04号桌",
        qr_token="Dd0123456789AaBbCcEeFfGgHhIiJjKk",
    )
    session = await _service(5).create_session(
        user=user,
        qr_token=table.qr_token,
        order_id=order.id,
        idempotency_key="mysql-release-claim",
        ip_address="127.0.0.1",
    )
    admin = await User.create(
        username="m9-mysql-admin",
        password="ci-only-hash",
        nickname="M9 admin",
        role=UserRole.ADMIN.value,
    )

    results = await asyncio.gather(
        _service(6).release_session(
            session_no=session.session.session_no,
            operator_id=admin.id,
            reason="internal acceptance release",
            idempotency_key="mysql-release-same-key",
            ip_address="127.0.0.1",
        ),
        _service(7).release_session(
            session_no=session.session.session_no,
            operator_id=admin.id,
            reason="internal acceptance release",
            idempotency_key="mysql-release-same-key",
            ip_address="127.0.0.1",
        ),
    )

    assert {result.is_replay for result in results} == {False, True}
    assert results[0].session.id == results[1].session.id
    assert await TableOccupancy.filter(session_id=session.session.id).count() == 0


async def test_wallet_payment_creates_distinct_mysql_timers_from_snapshots() -> None:
    user, order = await _customer_order(10)
    await WalletAccount.create(user=user, balance=Decimal("500.00"))
    product = await Product.create(
        name="M9 MySQL short experience",
        product_type=ProductType.EXPERIENCE,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=60,
        participants=4,
        day_type=DayType.WEEKDAY,
        price=Decimal("40.00"),
    )
    await OrderItem.create(
        order=order,
        product=product,
        experience_option=option,
        product_name=product.name,
        product_price=Decimal("40.00"),
        option_duration_minutes=60,
        option_participants=4,
        option_day_type=DayType.WEEKDAY,
        quantity=7,
        subtotal=Decimal("280.00"),
    )
    await Order.filter(id=order.id).update(total_amount=Decimal("380.00"))
    table = await StoreTable.create(
        table_no="T07",
        display_name="T07号桌",
        qr_token="Gg0123456789AaBbCcDdEeFfHhIiJjKk",
    )
    table_service = _service(10)
    created = await table_service.create_session(
        user=user,
        qr_token=table.qr_token,
        order_id=order.id,
        idempotency_key="mysql-wallet-timer-claim",
        ip_address="127.0.0.1",
    )
    succeeded_at = created.session.claimed_at + timedelta(minutes=1)
    payment_service = PaymentService(
        OrderRepository(),
        PaymentRepository(),
        WalletRepository(),
        UserRepository(),
        AuditLogService(AuditLogRepository()),
        TableSessionRepository(),
        now_provider=lambda: succeeded_at,
    )

    result = await payment_service.pay_order_with_wallet(
        order.id,
        user=user,
        idempotency_key="mysql-wallet-timer-payment",
        ip_address="127.0.0.1",
        table_session_no=created.session.session_no,
    )

    detail = await TableSessionRepository().get_session_detail(created.session.id)
    assert detail is not None
    assert detail.started_at == result.payment.succeeded_at == succeeded_at
    assert [timer.duration_minutes for timer in detail.timers] == [60, 120]
    assert all(timer.buffer_minutes == 10 for timer in detail.timers)
    assert detail.table_release_at == succeeded_at + timedelta(minutes=130)


async def test_wallet_payment_and_timeout_race_have_one_mysql_winner() -> None:
    user, order = await _customer_order(11)
    await WalletAccount.create(user=user, balance=Decimal("500.00"))
    table = await StoreTable.create(
        table_no="T08",
        display_name="T08号桌",
        qr_token="Hh0123456789AaBbCcDdEeFfGgIiJjKk",
    )
    table_service = _service(11)
    created = await table_service.create_session(
        user=user,
        qr_token=table.qr_token,
        order_id=order.id,
        idempotency_key="mysql-payment-timeout-claim",
        ip_address="127.0.0.1",
    )
    deadline = created.session.payment_deadline_at
    payment_service = PaymentService(
        OrderRepository(),
        PaymentRepository(),
        WalletRepository(),
        UserRepository(),
        AuditLogService(AuditLogRepository()),
        TableSessionRepository(),
        now_provider=lambda: deadline,
    )

    payment_result, sweep_result = await asyncio.gather(
        payment_service.pay_order_with_wallet(
            order.id,
            user=user,
            idempotency_key="mysql-payment-timeout-payment",
            ip_address="127.0.0.1",
            table_session_no=created.session.session_no,
        ),
        table_service.converge_session(
            created.session.id,
            now=deadline + timedelta(microseconds=1),
        ),
        return_exceptions=True,
    )

    detail = await TableSessionRepository().get_session_detail(created.session.id)
    assert detail is not None
    if isinstance(payment_result, BaseException):
        assert isinstance(payment_result, TableSessionStatusConflict)
        assert sweep_result is True
        assert detail.status == "closed"
        assert detail.close_reason == "payment_timeout"
        assert await Payment.filter(order_id=order.id).count() == 0
        assert await PaymentSettlement.filter(order_id=order.id).count() == 0
        assert not await TableOccupancy.filter(order_id=order.id).exists()
    else:
        assert sweep_result is False
        assert detail.status == "active"
        assert detail.payment_id == payment_result.payment.id
        assert await Payment.filter(order_id=order.id).count() == 1
        assert await PaymentSettlement.filter(order_id=order.id).count() == 1
        assert await TableOccupancy.filter(order_id=order.id).count() == 1
