"""Phase 4.3.11：真实 MySQL 行锁、竞争、原子性与索引门槛。"""

import asyncio
from decimal import Decimal
from itertools import count

import pytest
from tortoise import connections
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import OperationalError
from tortoise.transactions import in_transaction

from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.enums.order import OrderStatus
from app.common.enums.product import ProductStatus, ProductType
from app.common.exceptions import InsufficientStock, OrderStatusConflict
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import (
    InventoryRepository,
    InventoryTransactionCreateData,
)
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.inventory_service import InventoryService
from app.services.order_service import OrderItemInput, OrderService


pytestmark = pytest.mark.mysql


class _TwoPartyBarrier:
    """让两个协程在真正执行锁 SQL 前同时放行。"""

    def __init__(self) -> None:
        self._arrivals = 0
        self._mutex = asyncio.Lock()
        self._open = asyncio.Event()

    async def wait(self) -> None:
        async with self._mutex:
            self._arrivals += 1
            if self._arrivals == 2:
                self._open.set()
        await self._open.wait()


class _BarrierInventoryRepository(InventoryRepository):
    def __init__(self, barrier: _TwoPartyBarrier) -> None:
        self._barrier = barrier

    async def get_kit_for_update(
        self,
        product_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> ProductKit | None:
        await self._barrier.wait()
        return await super().get_kit_for_update(
            product_id,
            using_db=using_db,
        )

    async def get_kits_for_update(
        self,
        product_ids: set[int],
        *,
        using_db: BaseDBAsyncClient,
    ) -> list[ProductKit]:
        await self._barrier.wait()
        return await super().get_kits_for_update(
            product_ids,
            using_db=using_db,
        )


class _BarrierOrderRepository(OrderRepository):
    def __init__(self, barrier: _TwoPartyBarrier) -> None:
        self._barrier = barrier

    async def get_order_for_update(
        self,
        order_id: int,
        *,
        user_id: int | None = None,
        using_db: BaseDBAsyncClient,
    ) -> Order | None:
        await self._barrier.wait()
        return await super().get_order_for_update(
            order_id,
            user_id=user_id,
            using_db=using_db,
        )


class _HoldingInventoryRepository(InventoryRepository):
    """取得单 Kit 行锁后等待测试显式放行。"""

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


class _TimeoutSignalingInventoryRepository(InventoryRepository):
    """把真实锁等待超时缩短到 1 秒，并通知测试释放阻塞者。"""

    def __init__(self) -> None:
        self.attempts = 0
        self.first_timeout = asyncio.Event()

    async def get_kit_for_update(
        self,
        product_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> ProductKit | None:
        self.attempts += 1
        await using_db.execute_query("SET SESSION innodb_lock_wait_timeout = 1")
        try:
            return await super().get_kit_for_update(
                product_id,
                using_db=using_db,
            )
        except OperationalError:
            self.first_timeout.set()
            raise


def _audit_service() -> AuditLogService:
    return AuditLogService(AuditLogRepository())


def _inventory_service(
    repository: InventoryRepository,
) -> InventoryService:
    return InventoryService(
        repository,
        ProductRepository(),
        _audit_service(),
    )


def _order_service(
    inventory_repository: InventoryRepository,
    *,
    order_repository: OrderRepository | None = None,
) -> OrderService:
    sequence = count(1)
    return OrderService(
        order_repository or OrderRepository(),
        ProductRepository(),
        inventory_repository,
        _audit_service(),
        order_number_generator=lambda: f"OD{next(sequence):026d}",
    )


async def _create_user(number: int) -> User:
    return await User.create(
        username=f"mysql-user-{number}",
        password="hashed-password",
        nickname=f"MySQL 用户 {number}",
        phone=f"13844{number:06d}",
    )


async def _create_online_kit(
    number: int,
    *,
    stock: int,
) -> ProductKit:
    product = await Product.create(
        name=f"MySQL 并发 Kit {number}",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    return await ProductKit.create(
        product=product,
        price=Decimal(f"{number + 10}.00"),
        stock=stock,
    )


def _kit_item(kit: ProductKit, *, quantity: int = 1) -> OrderItemInput:
    return OrderItemInput(
        product_id=kit.product_id,
        experience_option_id=None,
        quantity=quantity,
    )


async def _wait_for_data_lock_wait() -> None:
    """等待 performance_schema 证明第二事务正在等行锁。"""

    connection = connections.get("default")
    for _ in range(200):
        rows = await connection.execute_query_dict(
            "SELECT COUNT(*) AS wait_count "
            "FROM performance_schema.data_lock_waits"
        )
        if int(rows[0]["wait_count"]) > 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("expected an observable InnoDB row-lock wait")


async def test_concurrent_distinct_adjustments_do_not_lose_updates() -> None:
    operator = await _create_user(1)
    kit = await _create_online_kit(1, stock=0)
    service = _inventory_service(
        _BarrierInventoryRepository(_TwoPartyBarrier())
    )

    first, second = await asyncio.gather(
        service.adjust_stock(
            kit.product_id,
            change=1,
            reason="并发入库 A",
            operator_id=operator.id,
            ip_address="127.0.0.1",
            idempotency_key="mysql-distinct-a",
        ),
        service.adjust_stock(
            kit.product_id,
            change=1,
            reason="并发入库 B",
            operator_id=operator.id,
            ip_address="127.0.0.1",
            idempotency_key="mysql-distinct-b",
        ),
    )

    await kit.refresh_from_db()
    assert kit.stock == 2
    assert {first.stock, second.stock} == {1, 2}
    assert not first.is_replay
    assert not second.is_replay
    assert await InventoryTransaction.all().count() == 2
    assert await AuditLog.filter(action="ADJUST_INVENTORY").count() == 2


async def test_concurrent_same_adjustment_commits_once_and_replays_once() -> None:
    operator = await _create_user(2)
    kit = await _create_online_kit(2, stock=0)
    service = _inventory_service(
        _BarrierInventoryRepository(_TwoPartyBarrier())
    )
    request = {
        "change": 3,
        "reason": "同键并发入库",
        "operator_id": operator.id,
        "ip_address": "127.0.0.1",
        "idempotency_key": "mysql-same-key",
    }

    first, second = await asyncio.gather(
        service.adjust_stock(kit.product_id, **request),
        service.adjust_stock(kit.product_id, **request),
    )

    await kit.refresh_from_db()
    assert kit.stock == 3
    assert {first.is_replay, second.is_replay} == {False, True}
    assert first.transaction.id == second.transaction.id
    assert first.stock == second.stock == 3
    assert await InventoryTransaction.all().count() == 1
    assert await AuditLog.filter(action="ADJUST_INVENTORY").count() == 1


async def test_last_item_concurrent_orders_allow_exactly_one_commit() -> None:
    customer = await _create_user(3)
    kit = await _create_online_kit(3, stock=1)
    service = _order_service(
        _BarrierInventoryRepository(_TwoPartyBarrier())
    )

    results = await asyncio.gather(
        service.create_order(
            user_id=customer.id,
            items=[_kit_item(kit)],
            remark="最后一件 A",
            ip_address="127.0.0.1",
        ),
        service.create_order(
            user_id=customer.id,
            items=[_kit_item(kit)],
            remark="最后一件 B",
            ip_address="127.0.0.1",
        ),
        return_exceptions=True,
    )

    successes = [result for result in results if isinstance(result, Order)]
    failures = [result for result in results if isinstance(result, BaseException)]
    await kit.refresh_from_db()
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], InsufficientStock)
    assert kit.stock == 0
    assert await Order.all().count() == 1
    assert await OrderItem.all().count() == 1
    assert (
        await InventoryTransaction.filter(
            transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        ).count()
        == 1
    )
    assert await AuditLog.filter(action="CREATE_ORDER").count() == 1


async def test_reversed_multi_kit_orders_use_stable_lock_order() -> None:
    customer = await _create_user(4)
    first_kit = await _create_online_kit(4, stock=2)
    second_kit = await _create_online_kit(5, stock=2)
    service = _order_service(
        _BarrierInventoryRepository(_TwoPartyBarrier())
    )

    results = await asyncio.wait_for(
        asyncio.gather(
            service.create_order(
                user_id=customer.id,
                items=[_kit_item(first_kit), _kit_item(second_kit)],
                remark="正向锁序",
                ip_address="127.0.0.1",
            ),
            service.create_order(
                user_id=customer.id,
                items=[_kit_item(second_kit), _kit_item(first_kit)],
                remark="反向请求顺序",
                ip_address="127.0.0.1",
            ),
        ),
        timeout=10,
    )

    await first_kit.refresh_from_db()
    await second_kit.refresh_from_db()
    assert len(results) == 2
    assert first_kit.stock == second_kit.stock == 0
    assert await Order.all().count() == 2
    assert await OrderItem.all().count() == 4
    assert (
        await InventoryTransaction.filter(
            transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        ).count()
        == 4
    )


async def test_same_order_concurrent_cancel_restores_exactly_once() -> None:
    customer = await _create_user(5)
    kit = await _create_online_kit(6, stock=2)
    created = await _order_service(InventoryRepository()).create_order(
        user_id=customer.id,
        items=[_kit_item(kit)],
        remark=None,
        ip_address="127.0.0.1",
    )
    cancel_service = _order_service(
        InventoryRepository(),
        order_repository=_BarrierOrderRepository(_TwoPartyBarrier()),
    )

    results = await asyncio.gather(
        cancel_service.cancel_order(
            created.id,
            user_id=customer.id,
            ip_address="127.0.0.1",
        ),
        cancel_service.cancel_order(
            created.id,
            user_id=customer.id,
            ip_address="127.0.0.1",
        ),
        return_exceptions=True,
    )

    successes = [result for result in results if isinstance(result, Order)]
    failures = [result for result in results if isinstance(result, BaseException)]
    await kit.refresh_from_db()
    await created.refresh_from_db()
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], OrderStatusConflict)
    assert created.status == OrderStatus.CANCELLED.value
    assert kit.stock == 2
    assert (
        await InventoryTransaction.filter(
            transaction_type=(
                InventoryTransactionType.ORDER_CANCELLATION_RESTORE
            ),
        ).count()
        == 1
    )
    assert await AuditLog.filter(action="CANCEL_ORDER").count() == 1


async def test_adjustment_blocks_order_then_order_sees_committed_balance() -> None:
    operator = await _create_user(6)
    customer = await _create_user(7)
    kit = await _create_online_kit(7, stock=1)
    holding_repository = _HoldingInventoryRepository()
    adjustment_service = _inventory_service(holding_repository)
    order_service = _order_service(InventoryRepository())

    adjustment_task = asyncio.create_task(
        adjustment_service.adjust_stock(
            kit.product_id,
            change=1,
            reason="竞争前补货",
            operator_id=operator.id,
            ip_address="127.0.0.1",
            idempotency_key="mysql-adjust-vs-order",
        )
    )
    await asyncio.wait_for(holding_repository.lock_acquired.wait(), timeout=5)
    order_task = asyncio.create_task(
        order_service.create_order(
            user_id=customer.id,
            items=[_kit_item(kit, quantity=2)],
            remark="等待补货提交",
            ip_address="127.0.0.1",
        )
    )
    await asyncio.wait_for(_wait_for_data_lock_wait(), timeout=5)
    holding_repository.release.set()
    adjustment, order = await asyncio.gather(adjustment_task, order_task)

    await kit.refresh_from_db()
    assert adjustment.stock == 2
    assert isinstance(order, Order)
    assert kit.stock == 0
    assert await InventoryTransaction.all().count() == 2
    assert await AuditLog.filter(action="ADJUST_INVENTORY").count() == 1
    assert await AuditLog.filter(action="CREATE_ORDER").count() == 1


async def test_real_lock_wait_timeout_retries_with_fresh_transaction() -> None:
    operator = await _create_user(9)
    kit = await _create_online_kit(10, stock=0)
    repository = _TimeoutSignalingInventoryRepository()
    service = _inventory_service(repository)
    blocker_locked = asyncio.Event()
    release_blocker = asyncio.Event()

    async def hold_row_lock() -> None:
        async with in_transaction() as blocker:
            locked = await InventoryRepository().get_kit_for_update(
                kit.product_id,
                using_db=blocker,
            )
            assert locked is not None
            blocker_locked.set()
            await release_blocker.wait()

    blocker_task = asyncio.create_task(hold_row_lock())
    await asyncio.wait_for(blocker_locked.wait(), timeout=5)
    adjustment_task = asyncio.create_task(
        service.adjust_stock(
            kit.product_id,
            change=2,
            reason="真实 1205 后重试",
            operator_id=operator.id,
            ip_address="127.0.0.1",
            idempotency_key="mysql-real-1205-retry",
        )
    )
    try:
        await asyncio.wait_for(repository.first_timeout.wait(), timeout=3)
    finally:
        release_blocker.set()
        await asyncio.wait_for(blocker_task, timeout=5)

    result = await asyncio.wait_for(adjustment_task, timeout=5)

    await kit.refresh_from_db()
    assert repository.attempts == 2
    assert result.stock == 2
    assert not result.is_replay
    assert kit.stock == 2
    assert await InventoryTransaction.all().count() == 1
    assert await AuditLog.filter(action="ADJUST_INVENTORY").count() == 1


async def test_mysql_version_migrations_and_explain_use_expected_indexes() -> None:
    operator = await _create_user(8)
    kit = await _create_online_kit(8, stock=0)
    sample_kit = await _create_online_kit(9, stock=0)
    await _inventory_service(InventoryRepository()).adjust_stock(
        kit.product_id,
        change=1,
        reason="索引计划样本",
        operator_id=operator.id,
        ip_address="127.0.0.1",
        idempotency_key="mysql-explain-sample",
    )
    connection = connections.get("default")
    balance = 1
    samples: list[InventoryTransactionCreateData] = []
    for number in range(5_000):
        change = 1 if number % 2 == 0 else -1
        after = balance + change
        samples.append(
            InventoryTransactionCreateData(
                product_id=sample_kit.product_id,
                transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
                change_quantity=change,
                before_quantity=balance,
                after_quantity=after,
                source_type=InventorySourceType.ADMIN,
                source_id=None,
                operator_id=operator.id,
                reason="EXPLAIN 合法基数样本",
                idempotency_key=f"inventory:mysql:explain:{number}",
            )
        )
        balance = after
    await InventoryRepository().bulk_create_transactions(
        transactions=samples,
    )
    await connection.execute_query("ANALYZE TABLE inventory_transactions")

    version_rows = await connection.execute_query_dict(
        "SELECT VERSION() AS version"
    )
    migration_rows = await connection.execute_query_dict(
        "SELECT version FROM aerich ORDER BY id"
    )
    lock_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM product_kits "
        "WHERE product_id IN (%s) ORDER BY product_id FOR UPDATE",
        [kit.product_id],
    )
    product_page_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM inventory_transactions "
        "WHERE product_id = %s ORDER BY created_at DESC, id DESC LIMIT 20",
        [kit.product_id],
    )
    global_page_plan = await connection.execute_query_dict(
        "EXPLAIN SELECT * FROM inventory_transactions "
        "ORDER BY created_at DESC, id DESC LIMIT 20"
    )

    assert version_rows[0]["version"].startswith("8.0.46")
    assert [row["version"] for row in migration_rows] == [
        "0_20260810101218_init.py",
        "1_20260813130455_add_order_tables.py",
        "2_20260814104655_add_inventory_transactions.py",
    ]
    assert lock_plan[0]["key"] == "product_id"
    assert product_page_plan[0]["key"] == "idx_inventory_product_created_id"
    assert global_page_plan[0]["key"] == "idx_inventory_created_id"
