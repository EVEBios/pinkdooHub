"""Wallet v1 在真实 MySQL 8 上的关键资金与库存闭环。"""

from decimal import Decimal

import pytest
from tortoise import connections

from app.common.enums.inventory import InventoryTransactionType
from app.common.enums.order import OrderStatus
from app.common.enums.product import ProductStatus, ProductType
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import RefundStatus, WalletTransactionType
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.payment import Payment, PaymentSettlement, Refund
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
from app.services.refund_service import RefundService
from app.services.wallet_service import WalletService


pytestmark = pytest.mark.mysql

IDEMPOTENCY_TABLES = {
    "payments",
    "recharge_orders",
    "refunds",
    "wallet_transactions",
}


def _audit_service() -> AuditLogService:
    return AuditLogService(AuditLogRepository())


async def test_adjust_assisted_order_and_refund_are_atomic_on_mysql() -> None:
    admin = await User.create(
        username="mysql-wallet-admin",
        password="hashed-password",
        nickname="MySQL Admin",
        role=UserRole.ADMIN.value,
        status=UserStatus.NORMAL.value,
    )
    customer = await User.create(
        username="mysql-wallet-customer",
        password="hashed-password",
        nickname="MySQL Customer",
        role=UserRole.USER.value,
        status=UserStatus.NORMAL.value,
    )
    wallet = await WalletAccount.create(user=customer)
    product = await Product.create(
        name="MySQL 钱包闭环套装",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    kit = await ProductKit.create(
        product=product,
        price=Decimal("25.00"),
        stock=3,
    )

    wallet_service = WalletService(
        WalletRepository(),
        UserRepository(),
        _audit_service(),
    )
    adjustment = await wallet_service.adjust_balance(
        operator=admin,
        user_id=customer.id,
        change=Decimal("100.00"),
        reason="MySQL 资金闭环准备",
        idempotency_key="mysql-wallet-credit",
        ip_address="127.0.0.1",
    )
    assert adjustment.result_balance == Decimal("100.00")

    order_service = OrderService(
        OrderRepository(),
        ProductRepository(),
        InventoryRepository(),
        _audit_service(),
        user_repository=UserRepository(),
        payment_repository=PaymentRepository(),
        wallet_repository=WalletRepository(),
    )
    assisted = await order_service.create_assisted_wallet_order(
        operator=admin,
        user_id=customer.id,
        items=[
            OrderItemInput(
                product_id=product.id,
                experience_option_id=None,
                quantity=2,
            )
        ],
        remark="MySQL 真实代客下单",
        idempotency_key="mysql-assisted-order",
        ip_address="127.0.0.1",
    )
    assert OrderStatus(assisted.order.status) is OrderStatus.PAID
    assert assisted.post_payment_balance == Decimal("50.00")

    refund_service = RefundService(
        OrderRepository(),
        PaymentRepository(),
        WalletRepository(),
        InventoryRepository(),
        UserRepository(),
        _audit_service(),
    )
    refunded = await refund_service.refund_order(
        assisted.order.id,
        operator=admin,
        reason="MySQL 真实全额退款",
        idempotency_key="mysql-order-refund",
        ip_address="127.0.0.1",
    )
    replay = await refund_service.refund_order(
        assisted.order.id,
        operator=admin,
        reason="MySQL 真实全额退款",
        idempotency_key="mysql-order-refund",
        ip_address="127.0.0.1",
    )

    await wallet.refresh_from_db()
    await kit.refresh_from_db()
    assert wallet.balance == Decimal("100.00")
    assert kit.stock == 3
    assert refunded.inventory_restored is True
    assert refunded.refund.status is RefundStatus.SUCCEEDED
    assert replay.is_replay is True
    assert replay.refund.id == refunded.refund.id

    transactions = await WalletTransaction.all().order_by("id")
    assert [item.transaction_type for item in transactions] == [
        WalletTransactionType.ADMIN_ADJUSTMENT,
        WalletTransactionType.ORDER_PAYMENT,
        WalletTransactionType.REFUND,
    ]
    assert [item.after_balance for item in transactions] == [
        Decimal("100.00"),
        Decimal("50.00"),
        Decimal("100.00"),
    ]
    inventory = await InventoryTransaction.all().order_by("id")
    assert [item.transaction_type for item in inventory] == [
        InventoryTransactionType.ORDER_DEDUCTION,
        InventoryTransactionType.ORDER_REFUND_RESTORE,
    ]
    assert await Payment.all().count() == 1
    assert await PaymentSettlement.all().count() == 1
    assert await Refund.all().count() == 1
    assert await AuditLog.all().count() == 4


async def test_idempotency_keys_are_bytewise_case_sensitive_on_mysql() -> None:
    connection = connections.get("default")
    columns = await connection.execute_query_dict(
        """
        SELECT TABLE_NAME AS table_name, COLLATION_NAME AS collation_name
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND COLUMN_NAME = 'idempotency_key'
          AND TABLE_NAME IN (
              'payments',
              'recharge_orders',
              'refunds',
              'wallet_transactions'
          )
        """
    )
    assert {
        row["table_name"]: row["collation_name"] for row in columns
    } == {table_name: "ascii_bin" for table_name in IDEMPOTENCY_TABLES}

    admin = await User.create(
        username="mysql-case-admin",
        password="hashed-password",
        nickname="MySQL Case Admin",
        role=UserRole.ADMIN.value,
        status=UserStatus.NORMAL.value,
    )
    customer = await User.create(
        username="mysql-case-customer",
        password="hashed-password",
        nickname="MySQL Case Customer",
        role=UserRole.USER.value,
        status=UserStatus.NORMAL.value,
    )
    wallet = await WalletAccount.create(user=customer)
    service = WalletService(
        WalletRepository(),
        UserRepository(),
        _audit_service(),
    )

    first = await service.adjust_balance(
        operator=admin,
        user_id=customer.id,
        change=Decimal("10.00"),
        reason="验证大小写幂等键",
        idempotency_key="Case-Sensitive-Key",
        ip_address="127.0.0.1",
    )
    second = await service.adjust_balance(
        operator=admin,
        user_id=customer.id,
        change=Decimal("10.00"),
        reason="验证大小写幂等键",
        idempotency_key="case-sensitive-key",
        ip_address="127.0.0.1",
    )

    await wallet.refresh_from_db()
    assert first.is_replay is False
    assert second.is_replay is False
    assert wallet.balance == Decimal("20.00")
    assert await WalletTransaction.all().count() == 2
