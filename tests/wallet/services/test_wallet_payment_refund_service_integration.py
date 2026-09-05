"""Wallet、Payment、Refund 与注销用例的真实 SQLite 事务测试。"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.common.enums.inventory import InventoryTransactionType
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductType
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    RefundStatus,
    WalletStatus,
    WalletTransactionType,
)
from app.common.exceptions.order import OrderStatusConflict
from app.common.exceptions.user import (
    AccountDeletionBlocked,
    UserDeleted,
    UserDisabled,
)
from app.common.exceptions.wallet import (
    InsufficientWalletBalance,
    PaymentNotFound,
    PaymentSettlementConflict,
    PaymentStatusConflict,
    RefundStatusConflict,
    WalletBalanceExceeded,
    WalletRefundCapacityExceeded,
    WalletTransactionConflict,
)
from app.core.config import settings
from app.core.exceptions import PermissionException, ServiceUnavailableException
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.experience_option import ExperienceOption
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PaymentSettlement, RechargeOrder, Refund
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.external_identity_repo import ExternalIdentityRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import WalletRepository
from app.schemas.user import AccountDeletionRequest
from app.services.account_lifecycle_service import AccountLifecycleService
from app.services.audit_log_service import AuditLogService
from app.services.payment_service import PaymentService
from app.services.refund_service import RefundService
from app.services.wallet_service import WalletService


def _number(prefix: str, sequence: int) -> str:
    return f"{prefix}{sequence:026d}"


async def _create_user(
    username: str,
    *,
    role: UserRole = UserRole.USER,
    status: UserStatus = UserStatus.NORMAL,
    password: str = "hashed-password",
) -> User:
    return await User.create(
        username=username,
        password=password,
        nickname=username,
        role=role.value,
        status=status.value,
    )


async def _create_wallet(
    user: User,
    *,
    balance: Decimal = Decimal("0.00"),
) -> WalletAccount:
    return await WalletAccount.create(user=user, balance=balance)


async def _create_order(
    user: User,
    *,
    sequence: int,
    amount: Decimal = Decimal("50.00"),
    status: OrderStatus = OrderStatus.PENDING,
) -> Order:
    return await Order.create(
        order_no=_number("OD", sequence),
        user=user,
        total_amount=amount,
        status=status.value,
    )


def _services() -> tuple[WalletService, PaymentService, RefundService]:
    user_repository = UserRepository()
    order_repository = OrderRepository()
    payment_repository = PaymentRepository()
    wallet_repository = WalletRepository()
    audit_log_service = AuditLogService(AuditLogRepository())
    return (
        WalletService(
            wallet_repository,
            user_repository,
            audit_log_service,
        ),
        PaymentService(
            order_repository,
            payment_repository,
            wallet_repository,
            user_repository,
            audit_log_service,
        ),
        RefundService(
            order_repository,
            payment_repository,
            wallet_repository,
            InventoryRepository(),
            user_repository,
            audit_log_service,
        ),
    )


async def _seed_wallet_settlement(
    *,
    user: User,
    wallet: WalletAccount,
    sequence: int,
    status: OrderStatus,
    product_type: ProductType,
) -> tuple[Order, ProductKit | None]:
    amount = Decimal("50.00")
    order = await _create_order(
        user,
        sequence=sequence,
        amount=amount,
        status=status,
    )
    product = await Product.create(
        name=f"退款商品-{sequence}",
        product_type=product_type,
    )
    kit: ProductKit | None = None
    option: ExperienceOption | None = None
    if product_type is ProductType.KIT:
        kit = await ProductKit.create(
            product=product,
            price=amount,
            stock=3,
        )
    else:
        option = await ExperienceOption.create(
            product=product,
            duration=60,
            participants=1,
            day_type=DayType.WEEKDAY,
            price=amount,
        )
    await OrderItem.create(
        order=order,
        product=product,
        experience_option=option,
        option_duration_minutes=option.duration if option is not None else None,
        option_participants=option.participants if option is not None else None,
        option_day_type=option.day_type if option is not None else None,
        product_name=product.name,
        product_price=amount,
        quantity=1,
        subtotal=amount,
    )
    payment = await Payment.create(
        payment_no=_number("PY", sequence),
        user=user,
        purpose=PaymentPurpose.ORDER,
        method=PaymentMethod.WALLET,
        amount=amount,
        status=PaymentStatus.SUCCEEDED,
        order=order,
        recharge_order=None,
        idempotency_key=f"payment:seed:{sequence}",
        succeeded_at=datetime.now(timezone.utc),
    )
    await PaymentSettlement.create(
        payment=payment,
        order=order,
        amount=amount,
    )
    await WalletTransaction.create(
        wallet_account=wallet,
        transaction_type=WalletTransactionType.ORDER_PAYMENT,
        change_amount=-amount,
        before_balance=wallet.balance + amount,
        after_balance=wallet.balance,
        source_type="order",
        source_id=order.id,
        operator=user,
        reason="Order stock deduction",
        idempotency_key=f"wallet:seed:payment:{sequence}",
    )
    return order, kit


async def test_admin_adjustment_boundaries_replay_conflict_and_permissions() -> None:
    wallet_service, _, _ = _services()
    admin = await _create_user("wallet-service-admin", role=UserRole.ADMIN)
    normal_operator = await _create_user("wallet-service-non-admin")
    target = await _create_user("wallet-service-target")
    account = await _create_wallet(target)

    with pytest.raises(PermissionException):
        await wallet_service.adjust_balance(
            operator=normal_operator,
            user_id=target.id,
            change=Decimal("1.00"),
            reason="无权限",
            idempotency_key="permission",
            ip_address="127.0.0.1",
        )
    with pytest.raises(WalletBalanceExceeded):
        await wallet_service.adjust_balance(
            operator=admin,
            user_id=target.id,
            change=Decimal("-0.01"),
            reason="越过下界",
            idempotency_key="underflow",
            ip_address="127.0.0.1",
        )

    first = await wallet_service.adjust_balance(
        operator=admin,
        user_id=target.id,
        change=Decimal("1000.00"),
        reason="  填满余额  ",
        idempotency_key="fill",
        ip_address="127.0.0.1",
    )
    replay = await wallet_service.adjust_balance(
        operator=admin,
        user_id=target.id,
        change=Decimal("1000.00"),
        reason="填满余额",
        idempotency_key="fill",
        ip_address="127.0.0.1",
    )

    assert first.is_replay is False
    assert replay.is_replay is True
    assert replay.transaction.id == first.transaction.id
    assert replay.result_balance == Decimal("1000.00")
    with pytest.raises(WalletTransactionConflict):
        await wallet_service.adjust_balance(
            operator=admin,
            user_id=target.id,
            change=Decimal("1000.00"),
            reason="不同原因",
            idempotency_key="fill",
            ip_address="127.0.0.1",
        )
    with pytest.raises(WalletBalanceExceeded):
        await wallet_service.adjust_balance(
            operator=admin,
            user_id=target.id,
            change=Decimal("0.01"),
            reason="越过上界",
            idempotency_key="overflow",
            ip_address="127.0.0.1",
        )

    await account.refresh_from_db()
    assert account.balance == Decimal("1000.00")
    assert await WalletTransaction.all().count() == 1
    assert await AuditLog.filter(action="ADJUST_WALLET").count() == 1


async def test_admin_adjustment_allows_disabled_target_correction() -> None:
    wallet_service, _, _ = _services()
    admin = await _create_user("disabled-target-admin", role=UserRole.ADMIN)
    target = await _create_user(
        "disabled-wallet-target",
        status=UserStatus.DISABLED,
    )
    account = await _create_wallet(target)

    result = await wallet_service.adjust_balance(
        operator=admin,
        user_id=target.id,
        change=Decimal("1.00"),
        reason="禁用用户人工调账",
        idempotency_key="disabled-target",
        ip_address="127.0.0.1",
    )

    await account.refresh_from_db()
    assert result.is_replay is False
    assert account.balance == Decimal("1.00")
    assert await WalletTransaction.all().count() == 1
    assert await AuditLog.filter(action="ADJUST_WALLET").count() == 1


async def test_admin_adjustment_replay_rejects_corrupted_balance_equation() -> None:
    wallet_service, _, _ = _services()
    admin = await _create_user("adjust-replay-admin", role=UserRole.ADMIN)
    target = await _create_user("adjust-replay-target")
    account = await _create_wallet(target)
    result = await wallet_service.adjust_balance(
        operator=admin,
        user_id=target.id,
        change=Decimal("10.00"),
        reason="调账重放完整性",
        idempotency_key="adjust-integrity",
        ip_address="127.0.0.1",
    )
    await WalletTransaction.filter(id=result.transaction.id).update(
        after_balance=Decimal("9.99")
    )

    with pytest.raises(WalletTransactionConflict):
        await wallet_service.adjust_balance(
            operator=admin,
            user_id=target.id,
            change=Decimal("10.00"),
            reason="调账重放完整性",
            idempotency_key="adjust-integrity",
            ip_address="127.0.0.1",
        )

    await account.refresh_from_db()
    assert account.balance == Decimal("10.00")
    assert await WalletTransaction.all().count() == 1
    assert await AuditLog.filter(action="ADJUST_WALLET").count() == 1


async def test_financial_writes_fail_closed_for_unknown_customer_status() -> None:
    wallet_service, payment_service, refund_service = _services()
    admin = await _create_user("unknown-status-admin", role=UserRole.ADMIN)
    target = await _create_user("unknown-status-customer")
    account = await _create_wallet(target, balance=Decimal("100.00"))
    pending_order = await _create_order(target, sequence=69)
    refundable_order, _ = await _seed_wallet_settlement(
        user=target,
        wallet=account,
        sequence=70,
        status=OrderStatus.COMPLETED,
        product_type=ProductType.EXPERIENCE,
    )
    await User.filter(id=target.id).update(status=99)

    with pytest.raises(PermissionException):
        await wallet_service.adjust_balance(
            operator=admin,
            user_id=target.id,
            change=Decimal("1.00"),
            reason="非法状态不得调账",
            idempotency_key="unknown-status-adjustment",
            ip_address="127.0.0.1",
        )
    with pytest.raises(PermissionException):
        await payment_service.pay_order_with_wallet(
            pending_order.id,
            user=target,
            idempotency_key="unknown-status-payment",
            ip_address="127.0.0.1",
        )
    with pytest.raises(PermissionException):
        await refund_service.refund_order(
            refundable_order.id,
            operator=admin,
            reason="非法状态不得退款",
            idempotency_key="unknown-status-refund",
            ip_address="127.0.0.1",
        )

    await account.refresh_from_db()
    await pending_order.refresh_from_db()
    assert account.balance == Decimal("100.00")
    assert OrderStatus(pending_order.status) is OrderStatus.PENDING
    assert not await Payment.filter(order_id=pending_order.id).exists()
    assert not await Refund.filter(order_id=refundable_order.id).exists()
    assert not await AuditLog.filter(
        action__in=("ADJUST_WALLET", "PAY_ORDER", "REFUND_ORDER")
    ).exists()


async def test_positive_adjustment_preserves_full_refund_capacity() -> None:
    wallet_service, _, _ = _services()
    admin = await _create_user("refund-capacity-admin", role=UserRole.ADMIN)
    target = await _create_user("refund-capacity-target")
    account = await _create_wallet(target, balance=Decimal("100.00"))
    await _seed_wallet_settlement(
        user=target,
        wallet=account,
        sequence=77,
        status=OrderStatus.PAID,
        product_type=ProductType.EXPERIENCE,
    )

    allowed = await wallet_service.adjust_balance(
        operator=admin,
        user_id=target.id,
        change=Decimal("850.00"),
        reason="保留 50 元退款空间",
        idempotency_key="capacity-allowed",
        ip_address="127.0.0.1",
    )
    assert allowed.result_balance == Decimal("950.00")

    with pytest.raises(WalletRefundCapacityExceeded):
        await wallet_service.adjust_balance(
            operator=admin,
            user_id=target.id,
            change=Decimal("0.01"),
            reason="不可侵占退款预留",
            idempotency_key="capacity-rejected",
            ip_address="127.0.0.1",
        )

    await account.refresh_from_db()
    assert account.balance == Decimal("950.00")


async def test_wallet_payment_success_replay_and_second_payment_conflict() -> None:
    _, payment_service, _ = _services()
    user = await _create_user("wallet-payment-user")
    account = await _create_wallet(user, balance=Decimal("80.00"))
    order = await _create_order(user, sequence=100, amount=Decimal("50.00"))

    first = await payment_service.pay_order_with_wallet(
        order.id,
        user=user,
        idempotency_key="pay-once",
        ip_address="127.0.0.1",
    )
    replay = await payment_service.pay_order_with_wallet(
        order.id,
        user=user,
        idempotency_key="pay-once",
        ip_address="127.0.0.1",
    )

    assert first.is_replay is False
    assert replay.is_replay is True
    assert replay.payment.id == first.payment.id
    assert replay.post_payment_balance == Decimal("30.00")
    with pytest.raises(OrderStatusConflict):
        await payment_service.pay_order_with_wallet(
            order.id,
            user=user,
            idempotency_key="different-payment",
            ip_address="127.0.0.1",
        )

    await account.refresh_from_db()
    await order.refresh_from_db()
    assert account.balance == Decimal("30.00")
    assert OrderStatus(order.status) is OrderStatus.PAID
    assert await Payment.all().count() == 1
    assert await PaymentSettlement.all().count() == 1
    assert await WalletTransaction.filter(
        transaction_type=WalletTransactionType.ORDER_PAYMENT
    ).count() == 1
    assert await AuditLog.filter(action="PAY_ORDER").count() == 1


@pytest.mark.parametrize("replay_mode", ["locked", "conflict_resolver"])
@pytest.mark.parametrize(
    ("corruption", "expected_exception"),
    [
        ("settlement_amount", PaymentSettlementConflict),
        ("transaction_source", WalletTransactionConflict),
        ("payment_provider", WalletTransactionConflict),
        ("payment_status", PaymentStatusConflict),
    ],
)
async def test_wallet_payment_replay_rejects_conflicting_financial_facts(
    replay_mode: str,
    corruption: str,
    expected_exception: type[Exception],
) -> None:
    _, payment_service, _ = _services()
    suffix = f"{replay_mode[0]}-{corruption[:3]}"
    user = await _create_user(f"pay-replay-{suffix}")
    account = await _create_wallet(user, balance=Decimal("80.00"))
    order = await _create_order(
        user,
        sequence=400 + len(suffix),
        amount=Decimal("50.00"),
    )
    result = await payment_service.pay_order_with_wallet(
        order.id,
        user=user,
        idempotency_key=f"integrity-{suffix}",
        ip_address="127.0.0.1",
    )

    if corruption == "settlement_amount":
        await PaymentSettlement.filter(order_id=order.id).update(
            amount=Decimal("49.99")
        )
    elif corruption == "transaction_source":
        await WalletTransaction.filter(wallet_account_id=account.id).update(
            source_id=order.id + 1
        )
    elif corruption == "payment_provider":
        await Payment.filter(id=result.payment.id).update(
            provider_transaction_id="unexpected-provider-reference"
        )
    else:
        await Payment.filter(id=result.payment.id).update(status=PaymentStatus.PENDING)

    with pytest.raises(expected_exception):
        if replay_mode == "locked":
            await payment_service.pay_order_with_wallet(
                order.id,
                user=user,
                idempotency_key=f"integrity-{suffix}",
                ip_address="127.0.0.1",
            )
        else:
            await payment_service._resolve_wallet_payment_replay(
                order_id=order.id,
                user=user,
                internal_key=f"payment:wallet:integrity-{suffix}",
            )

    await account.refresh_from_db()
    assert account.balance == Decimal("30.00")
    assert await Payment.all().count() == 1
    assert await PaymentSettlement.all().count() == 1
    assert await WalletTransaction.all().count() == 1
    assert await AuditLog.filter(action="PAY_ORDER").count() == 1


async def test_wallet_payment_insufficient_disabled_and_feature_off_are_zero_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, payment_service, _ = _services()
    user = await _create_user("insufficient-payment-user")
    account = await _create_wallet(user, balance=Decimal("49.99"))
    order = await _create_order(user, sequence=110, amount=Decimal("50.00"))

    with pytest.raises(InsufficientWalletBalance):
        await payment_service.pay_order_with_wallet(
            order.id,
            user=user,
            idempotency_key="insufficient",
            ip_address="127.0.0.1",
        )
    user.status = UserStatus.DISABLED.value
    await user.save(update_fields=["status", "updated_at"])
    with pytest.raises(UserDisabled):
        await payment_service.pay_order_with_wallet(
            order.id,
            user=user,
            idempotency_key="disabled",
            ip_address="127.0.0.1",
        )
    user.status = UserStatus.NORMAL.value
    await user.save(update_fields=["status", "updated_at"])
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "wallet_order_payment_enabled", False)
    with pytest.raises(ServiceUnavailableException):
        await payment_service.pay_order_with_wallet(
            order.id,
            user=user,
            idempotency_key="feature-off",
            ip_address="127.0.0.1",
        )

    await account.refresh_from_db()
    await order.refresh_from_db()
    assert account.balance == Decimal("49.99")
    assert OrderStatus(order.status) is OrderStatus.PENDING
    assert not await Payment.all().exists()
    assert not await PaymentSettlement.all().exists()
    assert not await WalletTransaction.all().exists()
    assert not await AuditLog.filter(action="PAY_ORDER").exists()


@pytest.mark.parametrize(
    ("order_status", "product_type", "inventory_restored"),
    [
        (OrderStatus.PAID, ProductType.KIT, True),
        (OrderStatus.PAID, ProductType.EXPERIENCE, False),
        (OrderStatus.COMPLETED, ProductType.KIT, False),
    ],
)
async def test_full_refund_keeps_order_status_and_restores_only_paid_kit(
    order_status: OrderStatus,
    product_type: ProductType,
    inventory_restored: bool,
) -> None:
    _, _, refund_service = _services()
    admin = await _create_user(
        f"refund-admin-{order_status.value}-{product_type.value}",
        role=UserRole.ADMIN,
    )
    user = await _create_user(
        f"refund-user-{order_status.value}-{product_type.value}"
    )
    account = await _create_wallet(user, balance=Decimal("950.00"))
    order, kit = await _seed_wallet_settlement(
        user=user,
        wallet=account,
        sequence=200 + order_status.value * 10 + (1 if product_type is ProductType.KIT else 2),
        status=order_status,
        product_type=product_type,
    )

    first = await refund_service.refund_order(
        order.id,
        operator=admin,
        reason="  顾客申请全额退款  ",
        idempotency_key="refund-once",
        ip_address="127.0.0.1",
    )
    replay = await refund_service.refund_order(
        order.id,
        operator=admin,
        reason="顾客申请全额退款",
        idempotency_key="refund-once",
        ip_address="127.0.0.1",
    )

    assert first.is_replay is False
    assert replay.is_replay is True
    assert replay.refund.id == first.refund.id
    assert first.refund.status is RefundStatus.SUCCEEDED
    assert first.inventory_restored is inventory_restored
    assert replay.inventory_restored is inventory_restored
    await account.refresh_from_db()
    await order.refresh_from_db()
    assert account.balance == Decimal("1000.00")
    assert OrderStatus(order.status) is order_status
    assert await Refund.all().count() == 1
    assert await WalletTransaction.filter(
        transaction_type=WalletTransactionType.REFUND
    ).count() == 1
    assert await AuditLog.filter(action="REFUND_ORDER").count() == 1

    restore_transactions = InventoryTransaction.filter(
        transaction_type=InventoryTransactionType.ORDER_REFUND_RESTORE
    )
    assert await restore_transactions.count() == int(inventory_restored)
    if kit is not None:
        await kit.refresh_from_db()
        assert kit.stock == (4 if inventory_restored else 3)


@pytest.mark.parametrize(
    ("corruption", "expected_exception"),
    [
        ("settlement_amount", WalletTransactionConflict),
        ("payment_provider", WalletTransactionConflict),
        ("order_status", WalletTransactionConflict),
        ("refund_amount", WalletTransactionConflict),
        ("refund_status", RefundStatusConflict),
        ("transaction_source", WalletTransactionConflict),
    ],
)
async def test_refund_replay_rejects_conflicting_financial_facts(
    corruption: str,
    expected_exception: type[Exception],
) -> None:
    _, _, refund_service = _services()
    suffix = corruption[:3]
    admin = await _create_user(f"rr-admin-{suffix}", role=UserRole.ADMIN)
    user = await _create_user(f"rr-user-{suffix}")
    account = await _create_wallet(user, balance=Decimal("950.00"))
    order, _ = await _seed_wallet_settlement(
        user=user,
        wallet=account,
        sequence=600 + len(corruption),
        status=OrderStatus.COMPLETED,
        product_type=ProductType.EXPERIENCE,
    )
    result = await refund_service.refund_order(
        order.id,
        operator=admin,
        reason="退款重放完整性",
        idempotency_key=f"integrity-{suffix}",
        ip_address="127.0.0.1",
    )

    if corruption == "settlement_amount":
        await PaymentSettlement.filter(order_id=order.id).update(
            amount=Decimal("49.99")
        )
    elif corruption == "payment_provider":
        await Payment.filter(id=result.payment.id).update(
            provider_transaction_id="unexpected-provider-reference"
        )
    elif corruption == "order_status":
        await Order.filter(id=order.id).update(status=OrderStatus.CANCELLED)
    elif corruption == "refund_amount":
        await Refund.filter(id=result.refund.id).update(amount=Decimal("49.99"))
    elif corruption == "refund_status":
        await Refund.filter(id=result.refund.id).update(status=RefundStatus.FAILED)
    else:
        await WalletTransaction.filter(
            transaction_type=WalletTransactionType.REFUND
        ).update(source_id=result.refund.id + 1)

    with pytest.raises(expected_exception):
        await refund_service._resolve_refund_replay(
            order_id=order.id,
            operator=admin,
            reason="退款重放完整性",
            internal_key=f"refund:admin:integrity-{suffix}",
        )

    await account.refresh_from_db()
    assert account.balance == Decimal("1000.00")
    assert await Refund.all().count() == 1
    assert await WalletTransaction.filter(
        transaction_type=WalletTransactionType.REFUND
    ).count() == 1
    assert await AuditLog.filter(action="REFUND_ORDER").count() == 1


@pytest.mark.parametrize("corruption", ["settlement_amount", "refund_amount"])
async def test_order_financials_fail_closed_for_conflicting_relations(
    corruption: str,
) -> None:
    _, payment_service, refund_service = _services()
    suffix = corruption[:3]
    admin = await _create_user(f"fin-admin-{suffix}", role=UserRole.ADMIN)
    user = await _create_user(f"fin-user-{suffix}")
    account = await _create_wallet(user, balance=Decimal("950.00"))
    order, _ = await _seed_wallet_settlement(
        user=user,
        wallet=account,
        sequence=700 + len(corruption),
        status=OrderStatus.COMPLETED,
        product_type=ProductType.EXPERIENCE,
    )

    if corruption == "settlement_amount":
        await PaymentSettlement.filter(order_id=order.id).update(
            amount=Decimal("49.99")
        )
    else:
        result = await refund_service.refund_order(
            order.id,
            operator=admin,
            reason="资金查询完整性",
            idempotency_key="financial-integrity",
            ip_address="127.0.0.1",
        )
        await Refund.filter(id=result.refund.id).update(amount=Decimal("49.99"))

    with pytest.raises(PaymentSettlementConflict):
        await payment_service.get_user_order_financials(
            order.id,
            user_id=user.id,
        )


async def test_refund_rejects_settlement_whose_payment_is_not_succeeded() -> None:
    _, _, refund_service = _services()
    admin = await _create_user("invalid-settlement-admin", role=UserRole.ADMIN)
    user = await _create_user("invalid-settlement-user")
    account = await _create_wallet(user)
    order = await _create_order(
        user,
        sequence=299,
        status=OrderStatus.PAID,
    )
    payment = await Payment.create(
        payment_no=_number("PY", 299),
        user=user,
        purpose=PaymentPurpose.ORDER,
        method=PaymentMethod.WALLET,
        amount=order.total_amount,
        status=PaymentStatus.PENDING,
        order=order,
        recharge_order=None,
        idempotency_key="payment:invalid-settlement",
    )
    await PaymentSettlement.create(
        payment=payment,
        order=order,
        amount=order.total_amount,
    )

    with pytest.raises(PaymentNotFound):
        await refund_service.refund_order(
            order.id,
            operator=admin,
            reason="拒绝无效结算",
            idempotency_key="invalid-settlement-refund",
            ip_address="127.0.0.1",
        )

    await account.refresh_from_db()
    assert account.balance == Decimal("0.00")
    assert not await Refund.all().exists()
    assert not await WalletTransaction.all().exists()
    assert not await AuditLog.filter(action="REFUND_ORDER").exists()


@pytest.mark.parametrize("corruption", ["missing_succeeded_at", "provider_reference"])
async def test_refund_rejects_malformed_successful_wallet_payment(
    corruption: str,
) -> None:
    _, _, refund_service = _services()
    suffix = corruption[:3]
    admin = await _create_user(f"malformed-payment-admin-{suffix}", role=UserRole.ADMIN)
    user = await _create_user(f"malformed-payment-user-{suffix}")
    account = await _create_wallet(user, balance=Decimal("950.00"))
    order, _ = await _seed_wallet_settlement(
        user=user,
        wallet=account,
        sequence=800 + len(corruption),
        status=OrderStatus.COMPLETED,
        product_type=ProductType.EXPERIENCE,
    )
    payment = await Payment.get(order_id=order.id)
    if corruption == "missing_succeeded_at":
        await Payment.filter(id=payment.id).update(succeeded_at=None)
    else:
        await Payment.filter(id=payment.id).update(
            provider_transaction_id="unexpected-provider-reference"
        )

    with pytest.raises(PaymentNotFound):
        await refund_service.refund_order(
            order.id,
            operator=admin,
            reason="拒绝畸形成功支付",
            idempotency_key=f"malformed-payment-refund-{suffix}",
            ip_address="127.0.0.1",
        )

    await account.refresh_from_db()
    assert account.balance == Decimal("950.00")
    assert not await Refund.filter(order_id=order.id).exists()
    assert not await WalletTransaction.filter(
        transaction_type=WalletTransactionType.REFUND
    ).exists()
    assert not await AuditLog.filter(action="REFUND_ORDER").exists()


async def test_refund_rejects_deleted_customer_but_preserves_financial_facts() -> None:
    _, _, refund_service = _services()
    admin = await _create_user("deleted-refund-admin", role=UserRole.ADMIN)
    user = await _create_user(
        "deleted-refund-user",
        status=UserStatus.DELETED,
    )
    account = await _create_wallet(user, balance=Decimal("950.00"))
    order, _ = await _seed_wallet_settlement(
        user=user,
        wallet=account,
        sequence=298,
        status=OrderStatus.COMPLETED,
        product_type=ProductType.EXPERIENCE,
    )

    with pytest.raises(UserDeleted):
        await refund_service.refund_order(
            order.id,
            operator=admin,
            reason="已注销用户不得新增资金事实",
            idempotency_key="deleted-customer-refund",
            ip_address="127.0.0.1",
        )

    await account.refresh_from_db()
    assert account.balance == Decimal("950.00")
    assert not await Refund.all().exists()
    assert not await WalletTransaction.filter(
        transaction_type=WalletTransactionType.REFUND
    ).exists()
    assert not await AuditLog.filter(action="REFUND_ORDER").exists()


async def test_unavailable_wechat_entrypoints_leave_all_financial_tables_untouched() -> None:
    _, payment_service, _ = _services()
    user = await _create_user("provider-disabled-user")
    account = await _create_wallet(user, balance=Decimal("10.00"))
    order = await _create_order(user, sequence=300)

    with pytest.raises(ServiceUnavailableException):
        await payment_service.create_recharge_intent(
            user=user,
            amount=Decimal("100.00"),
            idempotency_key="wechat-recharge",
        )
    with pytest.raises(ServiceUnavailableException):
        await payment_service.create_wechat_order_payment(
            order.id,
            user=user,
            idempotency_key="wechat-payment",
        )

    await account.refresh_from_db()
    await order.refresh_from_db()
    assert account.balance == Decimal("10.00")
    assert OrderStatus(order.status) is OrderStatus.PENDING
    assert not await RechargeOrder.all().exists()
    assert not await Payment.all().exists()
    assert not await PaymentSettlement.all().exists()
    assert not await WalletTransaction.all().exists()


class _UnusedProvider:
    async def exchange_code(self, code: str) -> None:
        raise AssertionError("password deletion must not call WeChat")


async def test_account_deletion_is_blocked_by_balance_and_in_flight_payment() -> None:
    user = await _create_user(
        "wallet-deletion-user",
        password=hash_password("12345678"),
    )
    account = await _create_wallet(user, balance=Decimal("1.00"))
    service = AccountLifecycleService(
        UserRepository(),
        OrderRepository(),
        ExternalIdentityRepository(),
        AuditLogService(AuditLogRepository()),
        _UnusedProvider(),
        WalletRepository(),
        PaymentRepository(),
    )
    request = AccountDeletionRequest(
        confirmation="DELETE",
        password="12345678",
    )

    with pytest.raises(AccountDeletionBlocked):
        await service.delete_account(
            user=user,
            data=request,
            ip_address="127.0.0.1",
        )
    account.balance = Decimal("0.00")
    await account.save(update_fields=["balance", "updated_at"])
    completed = await _create_order(
        user,
        sequence=400,
        status=OrderStatus.COMPLETED,
    )
    await Payment.create(
        payment_no=_number("PY", 400),
        user=user,
        purpose=PaymentPurpose.ORDER,
        method=PaymentMethod.WECHAT,
        amount=completed.total_amount,
        status=PaymentStatus.PENDING,
        order=completed,
        recharge_order=None,
        idempotency_key="payment:deletion:pending",
    )
    with pytest.raises(AccountDeletionBlocked):
        await service.delete_account(
            user=user,
            data=request,
            ip_address="127.0.0.1",
        )

    await user.refresh_from_db()
    await account.refresh_from_db()
    assert UserStatus(user.status) is UserStatus.NORMAL
    assert account.status is WalletStatus.ACTIVE
    assert not await AuditLog.filter(action="DELETE_ACCOUNT").exists()


async def test_account_deletion_is_blocked_by_refundable_wallet_payment() -> None:
    user = await _create_user(
        "wallet-refundable-deletion-user",
        password=hash_password("12345678"),
    )
    account = await _create_wallet(user)
    await _seed_wallet_settlement(
        user=user,
        wallet=account,
        sequence=401,
        status=OrderStatus.COMPLETED,
        product_type=ProductType.EXPERIENCE,
    )
    service = AccountLifecycleService(
        UserRepository(),
        OrderRepository(),
        ExternalIdentityRepository(),
        AuditLogService(AuditLogRepository()),
        _UnusedProvider(),
        WalletRepository(),
        PaymentRepository(),
    )

    with pytest.raises(AccountDeletionBlocked):
        await service.delete_account(
            user=user,
            data=AccountDeletionRequest(
                confirmation="DELETE",
                password="12345678",
            ),
            ip_address="127.0.0.1",
        )

    await user.refresh_from_db()
    await account.refresh_from_db()
    assert UserStatus(user.status) is UserStatus.NORMAL
    assert account.status is WalletStatus.ACTIVE
    assert not await AuditLog.filter(action="DELETE_ACCOUNT").exists()
