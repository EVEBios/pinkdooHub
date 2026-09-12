"""InventoryRepository 锁定、余额和流水写入契约测试。"""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from pytest import MonkeyPatch
from tortoise import connections
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.common.enums.inventory import InventorySourceType, InventoryTransactionType
from app.common.enums.product import ProductType
from app.models.inventory_transaction import InventoryTransaction
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.repositories.inventory_repo import (
    InventoryRepository,
    InventoryStockUpdateData,
    InventoryTransactionCreateData,
)


async def _create_operator() -> User:
    return await User.create(
        username="inventory-repo-admin",
        password="hashed-password",
        nickname="库存仓储管理员",
        phone="13800138000",
    )


async def _create_kit(name: str, stock: int) -> ProductKit:
    product = await Product.create(name=name, product_type=ProductType.KIT)
    return await ProductKit.create(
        product=product,
        price=Decimal("99.00"),
        stock=stock,
    )


def _transaction_data(
    kit: ProductKit,
    *,
    key: str,
    operator_id: int | None = None,
    change: int = -2,
) -> InventoryTransactionCreateData:
    return InventoryTransactionCreateData(
        product_id=kit.product_id,
        transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
        change_quantity=change,
        before_quantity=10,
        after_quantity=10 + change,
        source_type=InventorySourceType.ADMIN,
        source_id=None,
        operator_id=operator_id,
        reason="仓储写入测试",
        idempotency_key=key,
    )


async def test_get_single_kit_for_update_and_missing() -> None:
    """单余额锁读取返回 ProductKit，资源不存在时保持 None。"""

    kit = await _create_kit("单 Kit 锁", 10)
    repository = InventoryRepository()

    async with in_transaction() as connection:
        locked = await repository.get_kit_for_update(
            kit.product_id,
            using_db=connection,
        )
        missing = await repository.get_kit_for_update(
            kit.product_id + 999,
            using_db=connection,
        )

    assert locked is not None
    assert locked.id == kit.id
    assert locked.stock == 10
    assert missing is None


async def test_get_multiple_kits_for_update_deduplicates_and_orders() -> None:
    """多 Kit 锁定应去重并按 Product ID 升序返回。"""

    first = await _create_kit("锁顺序 A", 10)
    second = await _create_kit("锁顺序 B", 20)
    third = await _create_kit("锁顺序 C", 30)

    async with in_transaction() as connection:
        locked = await InventoryRepository().get_kits_for_update(
            {third.product_id, first.product_id, second.product_id},
            using_db=connection,
        )

    assert [kit.product_id for kit in locked] == sorted(
        {first.product_id, second.product_id, third.product_id}
    )


async def test_get_multiple_kits_for_update_empty_set_executes_no_sql(
    monkeypatch: MonkeyPatch,
) -> None:
    """空锁集合应直接返回，不向数据库发送无意义查询。"""

    connection = connections.get("default")
    original_execute_query: Callable[..., Awaitable[Any]] = connection.execute_query
    calls = 0

    async def capture_query(query: str, values: list[Any] | None = None) -> Any:
        nonlocal calls
        calls += 1
        return await original_execute_query(query, values)

    monkeypatch.setattr(connection, "execute_query", capture_query)

    async with in_transaction() as transaction_connection:
        result = await InventoryRepository().get_kits_for_update(
            set(),
            using_db=transaction_connection,
        )

    assert result == []
    assert calls == 0


async def test_update_stock_uses_caller_transaction_and_rolls_back() -> None:
    """余额写入只持久化调用方给定值，并随外层事务完整回滚。"""

    kit = await _create_kit("余额回滚", 10)
    repository = InventoryRepository()

    with pytest.raises(RuntimeError, match="rollback stock"):
        async with in_transaction() as connection:
            locked = await repository.get_kit_for_update(
                kit.product_id,
                using_db=connection,
            )
            assert locked is not None
            updated = await repository.update_stock(
                locked,
                stock=7,
                using_db=connection,
            )
            assert updated.stock == 7
            raise RuntimeError("rollback stock")

    stored = await ProductKit.get(id=kit.id)
    assert stored.stock == 10


async def test_bulk_update_stocks_joins_outer_rollback() -> None:
    """多 Kit 最终余额加入调用方事务并在后续失败时一起回滚。"""

    first = await _create_kit("批量余额 A", 10)
    second = await _create_kit("批量余额 B", 20)
    repository = InventoryRepository()

    with pytest.raises(RuntimeError, match="rollback bulk stock"):
        async with in_transaction() as transaction_connection:
            locked = await repository.get_kits_for_update(
                {first.product_id, second.product_id},
                using_db=transaction_connection,
            )
            await repository.bulk_update_stocks(
                updates=[
                    InventoryStockUpdateData(locked[0], 7),
                    InventoryStockUpdateData(locked[1], 15),
                ],
                using_db=transaction_connection,
            )
            raise RuntimeError("rollback bulk stock")

    assert (await ProductKit.get(id=first.id)).stock == 10
    assert (await ProductKit.get(id=second.id)).stock == 20


async def test_empty_bulk_stock_update_executes_no_sql(
    monkeypatch: MonkeyPatch,
) -> None:
    """空余额集合直接返回，不生成批量 UPDATE。"""

    connection = connections.get("default")
    calls = 0
    original_execute_query = connection.execute_query

    async def capture_query(query: str, values: list[Any] | None = None) -> Any:
        nonlocal calls
        calls += 1
        return await original_execute_query(query, values)

    monkeypatch.setattr(connection, "execute_query", capture_query)
    async with in_transaction() as transaction_connection:
        await InventoryRepository().bulk_update_stocks(
            updates=[],
            using_db=transaction_connection,
        )

    assert calls == 0


async def test_create_transaction_preserves_all_fields() -> None:
    """单条写入应显式保存调用方准备的完整流水字段。"""

    operator = await _create_operator()
    kit = await _create_kit("单条流水", 10)
    data = _transaction_data(
        kit,
        key="inventory:admin:single:adjust:product:1",
        operator_id=operator.id,
    )

    created = await InventoryRepository().create_transaction(data=data)
    stored = await InventoryTransaction.get(id=created.id)

    assert stored.product_id == kit.product_id
    assert stored.transaction_type is data.transaction_type
    assert stored.change_quantity == data.change_quantity
    assert stored.before_quantity == data.before_quantity
    assert stored.after_quantity == data.after_quantity
    assert stored.source_type is data.source_type
    assert stored.source_id is None
    assert stored.operator_id == operator.id
    assert stored.reason == data.reason
    assert stored.idempotency_key == data.idempotency_key


async def test_balance_and_transaction_share_outer_rollback() -> None:
    """Repository 原语可加入同一外层事务并一起回滚。"""

    operator = await _create_operator()
    kit = await _create_kit("余额流水回滚", 10)
    repository = InventoryRepository()
    transaction_id: int | None = None

    with pytest.raises(RuntimeError, match="rollback inventory"):
        async with in_transaction() as connection:
            locked = await repository.get_kit_for_update(
                kit.product_id,
                using_db=connection,
            )
            assert locked is not None
            await repository.update_stock(
                locked,
                stock=8,
                using_db=connection,
            )
            transaction = await repository.create_transaction(
                data=_transaction_data(
                    kit,
                    key="inventory:admin:rollback:adjust:product:1",
                    operator_id=operator.id,
                ),
                using_db=connection,
            )
            transaction_id = transaction.id
            raise RuntimeError("rollback inventory")

    assert (await ProductKit.get(id=kit.id)).stock == 10
    assert transaction_id is not None
    assert not await InventoryTransaction.filter(id=transaction_id).exists()


async def test_bulk_create_transactions_uses_one_insert(
    monkeypatch: MonkeyPatch,
) -> None:
    """多个自动事件应由一次 bulk INSERT 保存。"""

    first = await _create_kit("批量流水 A", 10)
    second = await _create_kit("批量流水 B", 10)
    connection = connections.get("default")
    original_execute_many: Callable[..., Awaitable[Any]] = connection.execute_many
    inserts: list[str] = []

    async def capture_many(query: str, values: list[list[Any]]) -> Any:
        if query.lstrip().upper().startswith("INSERT"):
            inserts.append(query)
        return await original_execute_many(query, values)

    monkeypatch.setattr(connection, "execute_many", capture_many)
    await InventoryRepository().bulk_create_transactions(
        transactions=[
            _transaction_data(
                first,
                key=f"inventory:order:1:deduct:product:{first.product_id}",
            ),
            _transaction_data(
                second,
                key=f"inventory:order:1:deduct:product:{second.product_id}",
            ),
        ]
    )

    stored = await InventoryTransaction.all().order_by("product_id")
    assert len(inserts) == 1
    assert [item.product_id for item in stored] == [
        first.product_id,
        second.product_id,
    ]


async def test_bulk_create_transactions_empty_list_executes_no_sql(
    monkeypatch: MonkeyPatch,
) -> None:
    """空流水集合不得执行批量 SQL。"""

    connection = connections.get("default")
    original_execute_many: Callable[..., Awaitable[Any]] = connection.execute_many
    calls = 0

    async def capture_many(query: str, values: list[list[Any]]) -> Any:
        nonlocal calls
        calls += 1
        return await original_execute_many(query, values)

    monkeypatch.setattr(connection, "execute_many", capture_many)
    await InventoryRepository().bulk_create_transactions(transactions=[])

    assert calls == 0


async def test_bulk_create_transactions_uses_outer_transaction_rollback() -> None:
    """批量自动流水必须加入 Order/取消用例拥有的外层事务。"""

    first = await _create_kit("批量回滚 A", 10)
    second = await _create_kit("批量回滚 B", 10)
    keys = [
        f"inventory:order:2:deduct:product:{first.product_id}",
        f"inventory:order:2:deduct:product:{second.product_id}",
    ]

    with pytest.raises(RuntimeError, match="rollback bulk inventory"):
        async with in_transaction() as connection:
            await InventoryRepository().bulk_create_transactions(
                transactions=[
                    _transaction_data(first, key=keys[0]),
                    _transaction_data(second, key=keys[1]),
                ],
                using_db=connection,
            )
            assert (
                await InventoryTransaction.filter(idempotency_key__in=keys)
                .using_db(connection)
                .count()
                == 2
            )
            raise RuntimeError("rollback bulk inventory")

    assert not await InventoryTransaction.filter(idempotency_key__in=keys).exists()


async def test_idempotency_lookup_sees_uncommitted_transaction() -> None:
    """幂等读取必须复用调用方连接并看到同事务尚未提交的流水。"""

    kit = await _create_kit("幂等事务读取", 10)
    repository = InventoryRepository()
    key = "inventory:admin:uncommitted:adjust:product:1"

    with pytest.raises(RuntimeError, match="rollback idempotency"):
        async with in_transaction() as connection:
            await repository.create_transaction(
                data=_transaction_data(kit, key=key),
                using_db=connection,
            )
            loaded = await repository.get_transaction_by_idempotency_key(
                key,
                using_db=connection,
            )
            assert loaded is not None
            assert loaded.idempotency_key == key
            raise RuntimeError("rollback idempotency")

    assert not await InventoryTransaction.filter(idempotency_key=key).exists()


async def test_duplicate_idempotency_key_propagates_integrity_error() -> None:
    """Repository 不吞掉唯一冲突，由 Service 在退出失败事务后归因。"""

    kit = await _create_kit("幂等冲突", 10)
    repository = InventoryRepository()
    data = _transaction_data(
        kit,
        key="inventory:admin:duplicate:adjust:product:1",
    )
    await repository.create_transaction(data=data)

    with pytest.raises(IntegrityError):
        await repository.create_transaction(data=data)
