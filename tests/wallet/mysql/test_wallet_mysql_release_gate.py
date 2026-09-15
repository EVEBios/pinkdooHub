"""Wallet/Payment/Refund 的真实 MySQL 并发、重试与查询计划门槛。"""

import asyncio
from datetime import datetime
from decimal import Decimal

import pytest
from tortoise import connections
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import OperationalError
from tortoise.transactions import in_transaction

from app.common.constants.wallet import FINANCIAL_RETRYABLE_MYSQL_ERROR_CODES
from app.common.enums.inventory import InventoryTransactionType
from app.common.enums.order import OrderStatus
from app.common.enums.product import ProductStatus, ProductType
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    RefundStatus,
    WalletTransactionSourceType,
    WalletTransactionType,
)
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order
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
from app.services.inventory_service import InventoryService
from app.services.order_service import OrderItemInput, OrderService
from app.services.payment_service import PaymentService
from app.services.refund_service import RefundService
from app.services.wallet_service import WalletService


pytestmark = pytest.mark.mysql


class _TimeoutSignalingUserRepository(UserRepository):
    """缩短真实行锁等待，并在第一次 1205 后通知测试释放锁。"""

    def __init__(self) -> None:
        self.attempts = 0
        self.first_timeout = asyncio.Event()

    async def get_for_update(
        self,
        user_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> User | None:
        self.attempts += 1
        await using_db.execute_query("SET SESSION innodb_lock_wait_timeout = 1")
        try:
            return await super().get_for_update(user_id, using_db=using_db)
        except OperationalError:
            self.first_timeout.set()
            raise


class _OneShotRefundDeadlockRepository(PaymentRepository):
    """在首轮退款已写完资金与库存后模拟 MySQL 1213。"""

    def __init__(self) -> None:
        self.attempts = 0

    async def update_refund_status(
        self,
        refund: Refund,
        *,
        status: RefundStatus,
        provider_refund_id: str | None,
        succeeded_at: datetime | None,
        using_db: BaseDBAsyncClient,
    ) -> Refund:
        self.attempts += 1
        updated = await super().update_refund_status(
            refund,
            status=status,
            provider_refund_id=provider_refund_id,
            succeeded_at=succeeded_at,
            using_db=using_db,
        )
        if self.attempts == 1:
            raise OperationalError(1213, "wallet refund deadlock victim")
        return updated


class _HoldingInventoryRepository(InventoryRepository):
    """锁住 Kit，直到跨域退款已经进入真实 InnoDB 等待。"""

    def __init__(self) -> None:
        self.lock_acquired = asyncio.Event()
        self.release = asyncio.Event()

    async def get_kit_for_update(
        self,
        product_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> ProductKit | None:
        kit = await super().get_kit_for_update(
            product_id,
            using_db=using_db,
        )
        self.lock_acquired.set()
        await self.release.wait()
        return kit


def _audit_service() -> AuditLogService:
    return AuditLogService(AuditLogRepository())


def _wallet_service(
    *,
    user_repository: UserRepository | None = None,
) -> WalletService:
    return WalletService(
        WalletRepository(),
        user_repository or UserRepository(),
        _audit_service(),
    )


def _payment_service() -> PaymentService:
    return PaymentService(
        OrderRepository(),
        PaymentRepository(),
        WalletRepository(),
        UserRepository(),
        _audit_service(),
    )


def _refund_service(
    *,
    payment_repository: PaymentRepository | None = None,
) -> RefundService:
    return RefundService(
        OrderRepository(),
        payment_repository or PaymentRepository(),
        WalletRepository(),
        InventoryRepository(),
        UserRepository(),
        _audit_service(),
    )


async def _create_admin_and_customer(
    sequence: int,
    *,
    balance: Decimal = Decimal("100.00"),
) -> tuple[User, User, WalletAccount]:
    admin = await User.create(
        username=f"mysql-wallet-gate-admin-{sequence}",
        password="hashed-password",
        nickname=f"MySQL Wallet Admin {sequence}",
        role=UserRole.ADMIN.value,
        status=UserStatus.NORMAL.value,
    )
    customer = await User.create(
        username=f"mysql-wallet-gate-customer-{sequence}",
        password="hashed-password",
        nickname=f"MySQL Wallet Customer {sequence}",
        role=UserRole.USER.value,
        status=UserStatus.NORMAL.value,
    )
    wallet = await WalletAccount.create(user=customer, balance=balance)
    return admin, customer, wallet


async def _create_pending_order(
    customer: User,
    *,
    sequence: int,
    amount: Decimal = Decimal("25.00"),
) -> Order:
    return await Order.create(
        order_no=f"OD{sequence:026d}",
        user=customer,
        total_amount=amount,
        status=OrderStatus.PENDING.value,
    )


async def _create_paid_kit_order(
    *,
    sequence: int,
) -> tuple[User, User, WalletAccount, ProductKit, Order]:
    admin, customer, wallet = await _create_admin_and_customer(sequence)
    product = await Product.create(
        name=f"MySQL Wallet Gate Kit {sequence}",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    kit = await ProductKit.create(
        product=product,
        price=Decimal("25.00"),
        stock=3,
    )
    order_service = OrderService(
        OrderRepository(),
        ProductRepository(),
        InventoryRepository(),
        _audit_service(),
        user_repository=UserRepository(),
        payment_repository=PaymentRepository(),
        wallet_repository=WalletRepository(),
    )
    result = await order_service.create_assisted_wallet_order(
        operator=admin,
        user_id=customer.id,
        items=[
            OrderItemInput(
                product_id=product.id,
                experience_option_id=None,
                quantity=2,
            )
        ],
        remark="MySQL wallet release gate",
        idempotency_key=f"mysql-wallet-gate-assisted-{sequence}",
        ip_address="127.0.0.1",
    )
    return admin, customer, wallet, kit, result.order


async def _wait_for_data_lock_wait() -> None:
    connection = connections.get("default")
    for _ in range(200):
        rows = await connection.execute_query_dict(
            "SELECT COUNT(*) AS wait_count "
            "FROM performance_schema.data_lock_waits"
        )
        if int(rows[0]["wait_count"]) > 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("expected an observable Wallet/Inventory row-lock wait")


async def test_concurrent_adjustments_serialize_and_same_key_replays_once() -> None:
    admin, customer, wallet = await _create_admin_and_customer(
        1,
        balance=Decimal("0.00"),
    )
    service = _wallet_service()

    distinct = await asyncio.gather(
        service.adjust_balance(
            operator=admin,
            user_id=customer.id,
            change=Decimal("10.00"),
            reason="concurrent adjustment A",
            idempotency_key="mysql-wallet-concurrent-a",
            ip_address="127.0.0.1",
        ),
        service.adjust_balance(
            operator=admin,
            user_id=customer.id,
            change=Decimal("10.00"),
            reason="concurrent adjustment B",
            idempotency_key="mysql-wallet-concurrent-b",
            ip_address="127.0.0.1",
        ),
    )
    same_key = await asyncio.gather(
        *[
            service.adjust_balance(
                operator=admin,
                user_id=customer.id,
                change=Decimal("5.00"),
                reason="concurrent idempotent adjustment",
                idempotency_key="mysql-wallet-concurrent-same",
                ip_address="127.0.0.1",
            )
            for _ in range(2)
        ]
    )

    await wallet.refresh_from_db()
    assert {result.result_balance for result in distinct} == {
        Decimal("10.00"),
        Decimal("20.00"),
    }
    assert sorted(result.is_replay for result in same_key) == [False, True]
    assert {result.result_balance for result in same_key} == {Decimal("25.00")}
    assert wallet.balance == Decimal("25.00")
    assert await WalletTransaction.all().count() == 3
    assert await AuditLog.filter(action="ADJUST_WALLET").count() == 3


async def test_concurrent_wallet_payment_debits_once_and_replays_once() -> None:
    _, customer, wallet = await _create_admin_and_customer(2)
    order = await _create_pending_order(customer, sequence=2)
    service = _payment_service()

    results = await asyncio.gather(
        *[
            service.pay_order_with_wallet(
                order.id,
                user=customer,
                idempotency_key="mysql-wallet-payment-same",
                ip_address="127.0.0.1",
            )
            for _ in range(2)
        ]
    )

    await wallet.refresh_from_db()
    await order.refresh_from_db()
    assert sorted(result.is_replay for result in results) == [False, True]
    assert {result.post_payment_balance for result in results} == {
        Decimal("75.00")
    }
    assert OrderStatus(order.status) is OrderStatus.PAID
    assert wallet.balance == Decimal("75.00")
    assert await Payment.all().count() == 1
    assert await PaymentSettlement.all().count() == 1
    assert await WalletTransaction.filter(
        transaction_type=WalletTransactionType.ORDER_PAYMENT
    ).count() == 1
    assert await AuditLog.filter(action="PAY_ORDER").count() == 1


async def test_concurrent_wallet_refund_restores_funds_and_inventory_once() -> None:
    admin, _, wallet, kit, order = await _create_paid_kit_order(sequence=3)
    service = _refund_service()

    results = await asyncio.gather(
        *[
            service.refund_order(
                order.id,
                operator=admin,
                reason="concurrent full refund",
                idempotency_key="mysql-wallet-refund-same",
                ip_address="127.0.0.1",
            )
            for _ in range(2)
        ]
    )

    await wallet.refresh_from_db()
    await kit.refresh_from_db()
    assert sorted(result.is_replay for result in results) == [False, True]
    assert wallet.balance == Decimal("100.00")
    assert kit.stock == 3
    assert await Refund.all().count() == 1
    assert await WalletTransaction.filter(
        transaction_type=WalletTransactionType.REFUND
    ).count() == 1
    assert await InventoryTransaction.filter(
        transaction_type=InventoryTransactionType.ORDER_REFUND_RESTORE
    ).count() == 1
    assert await AuditLog.filter(action="REFUND_ORDER").count() == 1


async def test_real_1205_retries_wallet_adjustment_in_fresh_transaction() -> None:
    assert FINANCIAL_RETRYABLE_MYSQL_ERROR_CODES == frozenset({1205, 1213})
    admin, customer, wallet = await _create_admin_and_customer(
        4,
        balance=Decimal("0.00"),
    )
    user_repository = _TimeoutSignalingUserRepository()
    service = _wallet_service(user_repository=user_repository)
    blocker_locked = asyncio.Event()
    release_blocker = asyncio.Event()

    async def hold_user_lock() -> None:
        async with in_transaction() as blocker:
            locked = await UserRepository().get_for_update(
                customer.id,
                using_db=blocker,
            )
            assert locked is not None
            blocker_locked.set()
            await release_blocker.wait()

    blocker_task = asyncio.create_task(hold_user_lock())
    await asyncio.wait_for(blocker_locked.wait(), timeout=5)
    adjustment_task = asyncio.create_task(
        service.adjust_balance(
            operator=admin,
            user_id=customer.id,
            change=Decimal("10.00"),
            reason="retry after real 1205",
            idempotency_key="mysql-wallet-real-1205",
            ip_address="127.0.0.1",
        )
    )
    try:
        await asyncio.wait_for(user_repository.first_timeout.wait(), timeout=3)
    finally:
        release_blocker.set()
        await asyncio.wait_for(blocker_task, timeout=5)

    result = await asyncio.wait_for(adjustment_task, timeout=5)

    await wallet.refresh_from_db()
    assert user_repository.attempts == 2
    assert result.is_replay is False
    assert result.result_balance == Decimal("10.00")
    assert wallet.balance == Decimal("10.00")
    assert await WalletTransaction.all().count() == 1
    assert await AuditLog.filter(action="ADJUST_WALLET").count() == 1


async def test_1213_rolls_back_and_retries_entire_refund_transaction() -> None:
    admin, _, wallet, kit, order = await _create_paid_kit_order(sequence=5)
    repository = _OneShotRefundDeadlockRepository()

    result = await _refund_service(payment_repository=repository).refund_order(
        order.id,
        operator=admin,
        reason="retry full refund after 1213",
        idempotency_key="mysql-wallet-refund-1213",
        ip_address="127.0.0.1",
    )

    await wallet.refresh_from_db()
    await kit.refresh_from_db()
    assert repository.attempts == 2
    assert result.is_replay is False
    assert wallet.balance == Decimal("100.00")
    assert kit.stock == 3
    assert await Refund.all().count() == 1
    assert await WalletTransaction.filter(
        transaction_type=WalletTransactionType.REFUND
    ).count() == 1
    assert await InventoryTransaction.filter(
        transaction_type=InventoryTransactionType.ORDER_REFUND_RESTORE
    ).count() == 1
    assert await AuditLog.filter(action="REFUND_ORDER").count() == 1


async def test_inventory_adjustment_and_refund_complete_without_lock_inversion() -> None:
    admin, _, wallet, kit, order = await _create_paid_kit_order(sequence=6)
    holding_repository = _HoldingInventoryRepository()
    inventory_service = InventoryService(
        holding_repository,
        ProductRepository(),
        _audit_service(),
    )

    adjustment_task = asyncio.create_task(
        inventory_service.adjust_stock(
            kit.product_id,
            change=1,
            reason="hold kit before refund",
            operator_id=admin.id,
            ip_address="127.0.0.1",
            idempotency_key="mysql-wallet-cross-domain-adjust",
        )
    )
    await asyncio.wait_for(holding_repository.lock_acquired.wait(), timeout=5)
    refund_task = asyncio.create_task(
        _refund_service().refund_order(
            order.id,
            operator=admin,
            reason="refund waits behind inventory lock",
            idempotency_key="mysql-wallet-cross-domain-refund",
            ip_address="127.0.0.1",
        )
    )
    try:
        await asyncio.wait_for(_wait_for_data_lock_wait(), timeout=5)
    finally:
        holding_repository.release.set()

    adjustment, refund = await asyncio.wait_for(
        asyncio.gather(adjustment_task, refund_task),
        timeout=10,
    )

    await wallet.refresh_from_db()
    await kit.refresh_from_db()
    assert adjustment.stock == 2
    assert refund.inventory_restored is True
    assert wallet.balance == Decimal("100.00")
    assert kit.stock == 4
    assert await InventoryTransaction.all().count() == 3
    assert await Refund.all().count() == 1


async def test_financial_queries_use_frozen_mysql_indexes() -> None:
    admin, customer, wallet = await _create_admin_and_customer(
        7,
        balance=Decimal("0.00"),
    )
    _, other_customer, other_wallet = await _create_admin_and_customer(
        8,
        balance=Decimal("0.00"),
    )
    order = await _create_pending_order(customer, sequence=7)

    transactions: list[WalletTransaction] = []
    for wallet_account in (wallet, other_wallet):
        balance = Decimal("0.00")
        for sequence in range(1_000):
            change = Decimal("1.00") if sequence % 2 == 0 else Decimal("-1.00")
            after_balance = balance + change
            transactions.append(
                WalletTransaction(
                    wallet_account_id=wallet_account.id,
                    transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
                    change_amount=change,
                    before_balance=balance,
                    after_balance=after_balance,
                    source_type=WalletTransactionSourceType.ADMIN,
                    source_id=None,
                    operator_id=admin.id,
                    reason="MySQL EXPLAIN sample",
                    idempotency_key=(
                        f"wallet:mysql:explain:{wallet_account.id}:{sequence}"
                    ),
                )
            )
            balance = after_balance
    await WalletTransaction.bulk_create(transactions, batch_size=500)

    payments: list[Payment] = []
    for payment_user in (customer, other_customer):
        for sequence in range(1_000):
            payments.append(
                Payment(
                    payment_no=f"PY{payment_user.id:08d}{sequence:018d}",
                    user_id=payment_user.id,
                    purpose=PaymentPurpose.ORDER,
                    method=PaymentMethod.MANUAL,
                    amount=Decimal("25.00"),
                    status=PaymentStatus.FAILED,
                    order_id=order.id,
                    recharge_order_id=None,
                    idempotency_key=(
                        f"payment:mysql:explain:{payment_user.id}:{sequence}"
                    ),
                    provider_transaction_id=None,
                    succeeded_at=None,
                )
            )
    await Payment.bulk_create(payments, batch_size=500)

    connection = connections.get("default")
    await connection.execute_query("ANALYZE TABLE wallet_transactions")
    await connection.execute_query("ANALYZE TABLE payments")
    account_lock_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM wallet_accounts WHERE user_id = %s FOR UPDATE",
        [customer.id],
    )
    transaction_key_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM wallet_transactions WHERE idempotency_key = %s",
        [f"wallet:mysql:explain:{wallet.id}:1"],
    )
    wallet_page_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM wallet_transactions "
        "WHERE wallet_account_id = %s "
        "ORDER BY created_at DESC, id DESC LIMIT 20",
        [wallet.id],
    )
    payment_key_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM payments WHERE idempotency_key = %s",
        [f"payment:mysql:explain:{customer.id}:1"],
    )
    payment_page_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM payments WHERE user_id = %s "
        "ORDER BY created_at DESC, id DESC LIMIT 20",
        [customer.id],
    )

    assert account_lock_plan[0]["key"] == "user_id"
    assert transaction_key_plan[0]["key"] == (
        "uidx_wallet_transaction_idempotency"
    )
    assert wallet_page_plan[0]["key"] == (
        "idx_wallet_transaction_wallet_created_id"
    )
    assert payment_key_plan[0]["key"] == "uidx_payment_idempotency"
    assert payment_page_plan[0]["key"] == "idx_payment_user_created_id"
