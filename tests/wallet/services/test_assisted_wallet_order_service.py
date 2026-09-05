"""管理员按商品代客扣款的真实 SQLite 事务测试。"""

from decimal import Decimal

import pytest

from app.common.enums.inventory import InventoryTransactionType
from app.common.enums.order import OrderStatus
from app.common.enums.product import ProductStatus, ProductType
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import PaymentMethod, PaymentStatus
from app.common.exceptions.wallet import (
    InsufficientWalletBalance,
    PaymentSettlementConflict,
    WalletTransactionConflict,
)
from app.common.exceptions.user import UserDeleted, UserDisabled
from app.core.exceptions import PermissionException
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PaymentSettlement
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import WalletRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderItemInput, OrderService


def _number(prefix: str, value: int) -> str:
    return f"{prefix}{value:026d}"


async def _user(
    username: str,
    *,
    role: UserRole,
    status: UserStatus = UserStatus.NORMAL,
) -> User:
    return await User.create(
        username=username,
        password="hashed-password",
        nickname=username,
        role=role.value,
        status=status.value,
    )


def _service() -> OrderService:
    return OrderService(
        OrderRepository(),
        ProductRepository(),
        InventoryRepository(),
        AuditLogService(AuditLogRepository()),
        user_repository=UserRepository(),
        order_number_generator=lambda: _number("OD", 701),
        payment_repository=PaymentRepository(),
        payment_number_generator=lambda: _number("PY", 701),
        wallet_repository=WalletRepository(),
    )


async def test_assisted_wallet_order_is_atomic_and_strictly_idempotent() -> None:
    admin = await _user("assisted-order-admin", role=UserRole.ADMIN)
    customer = await _user("assisted-order-customer", role=UserRole.USER)
    wallet = await WalletAccount.create(
        user=customer,
        balance=Decimal("100.00"),
    )
    product = await Product.create(
        name="代客扣款套装",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    kit = await ProductKit.create(
        product=product,
        price=Decimal("25.00"),
        stock=3,
    )
    service = _service()
    items = [
        OrderItemInput(
            product_id=product.id,
            experience_option_id=None,
            quantity=2,
        )
    ]

    first = await service.create_assisted_wallet_order(
        operator=admin,
        user_id=customer.id,
        items=items,
        remark="门店代客下单",
        idempotency_key="assisted-once",
        ip_address="127.0.0.1",
    )
    replay = await service.create_assisted_wallet_order(
        operator=admin,
        user_id=customer.id,
        items=items,
        remark="门店代客下单",
        idempotency_key="assisted-once",
        ip_address="127.0.0.1",
    )

    assert first.is_replay is False
    assert replay.is_replay is True
    assert replay.order.id == first.order.id
    assert replay.payment.id == first.payment.id
    assert replay.post_payment_balance == Decimal("50.00")
    assert OrderStatus(first.order.status) is OrderStatus.PAID
    assert first.payment.method is PaymentMethod.WALLET
    assert first.payment.status is PaymentStatus.SUCCEEDED

    await wallet.refresh_from_db()
    await kit.refresh_from_db()
    assert wallet.balance == Decimal("50.00")
    assert kit.stock == 1
    assert await Order.all().count() == 1
    assert await OrderItem.all().count() == 1
    assert await Payment.all().count() == 1
    assert await PaymentSettlement.all().count() == 1
    assert await WalletTransaction.all().count() == 1
    inventory = await InventoryTransaction.get()
    assert inventory.transaction_type is InventoryTransactionType.ORDER_DEDUCTION
    assert inventory.operator_id == admin.id
    assert await AuditLog.filter(target_type="order").count() == 2

    with pytest.raises(WalletTransactionConflict):
        await service.create_assisted_wallet_order(
            operator=admin,
            user_id=customer.id,
            items=[
                OrderItemInput(
                    product_id=product.id,
                    experience_option_id=None,
                    quantity=1,
                )
            ],
            remark="门店代客下单",
            idempotency_key="assisted-once",
            ip_address="127.0.0.1",
        )


@pytest.mark.parametrize(
    ("corruption", "expected_exception"),
    [
        ("transaction_source", WalletTransactionConflict),
        ("settlement_amount", PaymentSettlementConflict),
        ("payment_status", WalletTransactionConflict),
    ],
)
async def test_assisted_wallet_order_replay_rejects_partial_or_conflicting_facts(
    corruption: str,
    expected_exception: type[Exception],
) -> None:
    suffix = corruption[:3]
    admin = await _user(f"replay-admin-{suffix}", role=UserRole.ADMIN)
    customer = await _user(
        f"replay-customer-{suffix}",
        role=UserRole.USER,
    )
    wallet = await WalletAccount.create(user=customer, balance=Decimal("100.00"))
    product = await Product.create(
        name=f"重放完整性套装-{corruption}",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    await ProductKit.create(product=product, price=Decimal("25.00"), stock=2)
    service = _service()
    items = [
        OrderItemInput(
            product_id=product.id,
            experience_option_id=None,
            quantity=1,
        )
    ]
    result = await service.create_assisted_wallet_order(
        operator=admin,
        user_id=customer.id,
        items=items,
        remark="重放完整性",
        idempotency_key="replay-integrity",
        ip_address="127.0.0.1",
    )

    if corruption == "transaction_source":
        await WalletTransaction.filter(wallet_account_id=wallet.id).update(
            source_id=result.order.id + 1
        )
    elif corruption == "settlement_amount":
        await PaymentSettlement.filter(order_id=result.order.id).update(
            amount=Decimal("24.99")
        )
    else:
        await Payment.filter(id=result.payment.id).update(status=PaymentStatus.PENDING)

    with pytest.raises(expected_exception):
        await service.create_assisted_wallet_order(
            operator=admin,
            user_id=customer.id,
            items=items,
            remark="重放完整性",
            idempotency_key="replay-integrity",
            ip_address="127.0.0.1",
        )

    await wallet.refresh_from_db()
    assert wallet.balance == Decimal("75.00")
    assert await Order.all().count() == 1
    assert await WalletTransaction.all().count() == 1


async def test_assisted_wallet_order_insufficient_balance_rolls_back_everything() -> None:
    admin = await _user("assisted-rollback-admin", role=UserRole.ADMIN)
    customer = await _user("assisted-rollback-customer", role=UserRole.USER)
    wallet = await WalletAccount.create(
        user=customer,
        balance=Decimal("10.00"),
    )
    product = await Product.create(
        name="代客回滚套装",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    kit = await ProductKit.create(
        product=product,
        price=Decimal("25.00"),
        stock=3,
    )

    with pytest.raises(InsufficientWalletBalance):
        await _service().create_assisted_wallet_order(
            operator=admin,
            user_id=customer.id,
            items=[
                OrderItemInput(
                    product_id=product.id,
                    experience_option_id=None,
                    quantity=1,
                )
            ],
            remark=None,
            idempotency_key="assisted-insufficient",
            ip_address="127.0.0.1",
        )

    await wallet.refresh_from_db()
    await kit.refresh_from_db()
    assert wallet.balance == Decimal("10.00")
    assert kit.stock == 3
    assert not await Order.all().exists()
    assert not await Payment.all().exists()
    assert not await PaymentSettlement.all().exists()
    assert not await WalletTransaction.all().exists()
    assert not await InventoryTransaction.all().exists()
    assert not await AuditLog.all().exists()


async def test_mark_paid_creates_manual_settlement_for_normal_customer() -> None:
    admin = await _user("manual-payment-admin", role=UserRole.ADMIN)
    customer = await _user("manual-payment-customer", role=UserRole.USER)
    order = await Order.create(
        order_no=_number("OD", 702),
        user=customer,
        total_amount=Decimal("25.00"),
        status=OrderStatus.PENDING.value,
    )

    result = await _service().mark_order_paid(
        order.id,
        operator_id=admin.id,
        ip_address="127.0.0.1",
    )

    payment = await Payment.get(order_id=order.id)
    settlement = await PaymentSettlement.get(order_id=order.id)
    assert OrderStatus(result.status) is OrderStatus.PAID
    assert payment.user_id == customer.id
    assert payment.method is PaymentMethod.MANUAL
    assert payment.status is PaymentStatus.SUCCEEDED
    assert settlement.payment_id == payment.id
    assert settlement.amount == order.total_amount


@pytest.mark.parametrize(
    ("target_role", "target_status", "expected_exception"),
    [
        (UserRole.ADMIN, UserStatus.NORMAL, PermissionException),
        (UserRole.USER, UserStatus.DISABLED, UserDisabled),
        (UserRole.USER, UserStatus.DELETED, UserDeleted),
    ],
)
async def test_mark_paid_rejects_non_customer_or_inactive_financial_target(
    target_role: UserRole,
    target_status: UserStatus,
    expected_exception: type[Exception],
) -> None:
    operator = await _user(
        f"manual-target-operator-{target_role.value}-{target_status.value}",
        role=UserRole.SUPER_ADMIN,
    )
    target = await _user(
        f"manual-target-{target_role.value}-{target_status.value}",
        role=target_role,
        status=target_status,
    )
    order = await Order.create(
        order_no=_number("OD", 703),
        user=target,
        total_amount=Decimal("25.00"),
        status=OrderStatus.PENDING.value,
    )

    with pytest.raises(expected_exception):
        await _service().mark_order_paid(
            order.id,
            operator_id=operator.id,
            ip_address="127.0.0.1",
        )

    await order.refresh_from_db()
    assert OrderStatus(order.status) is OrderStatus.PENDING
    assert not await Payment.all().exists()
    assert not await PaymentSettlement.all().exists()
    assert not await AuditLog.all().exists()


async def test_assisted_and_manual_payment_fail_closed_for_unknown_status() -> None:
    admin = await _user("unknown-assisted-admin", role=UserRole.ADMIN)
    customer = await _user("unknown-assisted-customer", role=UserRole.USER)
    await WalletAccount.create(user=customer, balance=Decimal("100.00"))
    product = await Product.create(
        name="非法状态套装",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    await ProductKit.create(product=product, price=Decimal("25.00"), stock=2)
    order = await Order.create(
        order_no=_number("OD", 704),
        user=customer,
        total_amount=Decimal("25.00"),
        status=OrderStatus.PENDING.value,
    )
    await User.filter(id=customer.id).update(status=99)
    service = _service()

    with pytest.raises(PermissionException):
        await service.create_assisted_wallet_order(
            operator=admin,
            user_id=customer.id,
            items=[
                OrderItemInput(
                    product_id=product.id,
                    experience_option_id=None,
                    quantity=1,
                )
            ],
            remark=None,
            idempotency_key="unknown-assisted-status",
            ip_address="127.0.0.1",
        )
    with pytest.raises(PermissionException):
        await service.mark_order_paid(
            order.id,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )

    await order.refresh_from_db()
    assert OrderStatus(order.status) is OrderStatus.PENDING
    assert await Order.all().count() == 1
    assert not await Payment.all().exists()
    assert not await PaymentSettlement.all().exists()
    assert not await WalletTransaction.all().exists()
    assert not await InventoryTransaction.all().exists()
    assert not await AuditLog.all().exists()
