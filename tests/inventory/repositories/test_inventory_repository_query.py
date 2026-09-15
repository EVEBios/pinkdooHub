"""InventoryRepository 详情、筛选、分页与查询数量契约测试。"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pytest import MonkeyPatch
from tortoise import connections
from tortoise.transactions import in_transaction

from app.common.enums.inventory import InventorySourceType, InventoryTransactionType
from app.common.enums.order import OrderStatus
from app.common.enums.product import ProductType
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.repositories.inventory_repo import (
    InventoryRepository,
    InventoryTransactionCreateData,
)


async def _create_user(number: int) -> User:
    return await User.create(
        username=f"inventory-query-{number}",
        password="hashed-password",
        nickname=f"库存用户 {number}",
        phone=f"1380023{number:04d}",
    )


async def _create_kit(number: int) -> ProductKit:
    product = await Product.create(
        name=f"流水查询 Kit {number}",
        product_type=ProductType.KIT,
    )
    return await ProductKit.create(
        product=product,
        price=Decimal("99.00"),
        stock=20,
    )


async def _create_order(user: User, number: int) -> Order:
    return await Order.create(
        order_no=f"OD01ARZ3NDEKTSV4RRFFQ69G6A{number:02d}",
        user=user,
        total_amount=Decimal("99.00"),
        status=OrderStatus.PENDING,
    )


async def _create_transaction(
    kit: ProductKit,
    number: int,
    *,
    transaction_type: InventoryTransactionType,
    source_type: InventorySourceType,
    source_id: int | None = None,
    operator_id: int | None = None,
    created_at: datetime | None = None,
) -> InventoryTransaction:
    positive = transaction_type in {
        InventoryTransactionType.OPENING_BALANCE,
        InventoryTransactionType.ORDER_CANCELLATION_RESTORE,
    }
    before = 0 if transaction_type is InventoryTransactionType.OPENING_BALANCE else 10
    change = 2 if positive else -2
    created = await InventoryRepository().create_transaction(
        data=InventoryTransactionCreateData(
            product_id=kit.product_id,
            transaction_type=transaction_type,
            change_quantity=change,
            before_quantity=before,
            after_quantity=before + change,
            source_type=source_type,
            source_id=source_id,
            operator_id=operator_id,
            reason=f"流水查询原因 {number}",
            idempotency_key=f"inventory:query:{number}:product:{kit.product_id}",
        )
    )
    if created_at is not None:
        await InventoryTransaction.filter(id=created.id).update(created_at=created_at)
        created.created_at = created_at
    return created


async def test_get_transaction_detail_preloads_operator_and_order_number() -> None:
    """详情应一次准备操作人关系和批量来源订单号，Mapper 无需查库。"""

    user = await _create_user(1)
    kit = await _create_kit(1)
    order = await _create_order(user, 1)
    transaction = await _create_transaction(
        kit,
        1,
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        source_type=InventorySourceType.ORDER,
        source_id=order.id,
        operator_id=user.id,
    )

    detail = await InventoryRepository().get_transaction_detail(transaction.id)

    assert detail is not None
    assert detail.operator.id == user.id
    assert detail.operator.nickname == user.nickname
    assert detail.source_order_no == order.order_no


async def test_get_transactions_by_idempotency_keys_uses_one_transaction_query() -> None:
    """取消恢复可批量确认一组服务端幂等身份，空集合保持空结果。"""

    user = await _create_user(1)
    kit = await _create_kit(1)
    order = await _create_order(user, 1)
    first = await _create_transaction(
        kit,
        1,
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        source_type=InventorySourceType.ORDER,
        source_id=order.id,
        operator_id=user.id,
    )
    repository = InventoryRepository()

    async with in_transaction() as connection:
        found = await repository.get_transactions_by_idempotency_keys(
            {first.idempotency_key, "inventory:missing"},
            using_db=connection,
        )
        empty = await repository.get_transactions_by_idempotency_keys(
            set(),
            using_db=connection,
        )

    assert [transaction.id for transaction in found] == [first.id]
    assert empty == []


async def test_get_transaction_detail_handles_non_order_source_and_missing() -> None:
    """非订单来源显式补齐 None，不存在流水保持 None。"""

    kit = await _create_kit(1)
    transaction = await _create_transaction(
        kit,
        1,
        transaction_type=InventoryTransactionType.OPENING_BALANCE,
        source_type=InventorySourceType.MIGRATION,
    )
    repository = InventoryRepository()

    detail = await repository.get_transaction_detail(transaction.id)
    missing = await repository.get_transaction_detail(transaction.id + 999)

    assert detail is not None
    assert detail.operator is None
    assert detail.source_order_no is None
    assert missing is None


async def test_transaction_detail_reload_sees_uncommitted_write() -> None:
    """管理员调整响应重载必须读取同连接内尚未提交的流水。"""

    user = await _create_user(1)
    kit = await _create_kit(1)
    repository = InventoryRepository()
    created_id: int | None = None

    with pytest.raises(RuntimeError, match="rollback detail reload"):
        async with in_transaction() as connection:
            created = await repository.create_transaction(
                data=InventoryTransactionCreateData(
                    product_id=kit.product_id,
                    transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
                    change_quantity=2,
                    before_quantity=20,
                    after_quantity=22,
                    source_type=InventorySourceType.ADMIN,
                    source_id=None,
                    operator_id=user.id,
                    reason="未提交详情重载",
                    idempotency_key="inventory:admin:reload:adjust:product:1",
                ),
                using_db=connection,
            )
            created_id = created.id
            detail = await repository.get_transaction_detail(
                created.id,
                using_db=connection,
            )
            assert detail is not None
            assert detail.operator.nickname == user.nickname
            assert detail.source_order_no is None
            raise RuntimeError("rollback detail reload")

    assert created_id is not None
    assert not await InventoryTransaction.filter(id=created_id).exists()


async def test_list_transactions_applies_all_filters_and_preloads_metadata() -> None:
    """全局流水组合筛选应使用包含下界、排除上界的时间范围。"""

    user = await _create_user(1)
    other = await _create_user(2)
    first_kit = await _create_kit(1)
    second_kit = await _create_kit(2)
    order = await _create_order(user, 1)
    other_order = await _create_order(other, 2)
    start = datetime(2026, 8, 14, 2, 0, tzinfo=timezone.utc)
    expected = await _create_transaction(
        first_kit,
        1,
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        source_type=InventorySourceType.ORDER,
        source_id=order.id,
        operator_id=user.id,
        created_at=start + timedelta(minutes=1),
    )
    await _create_transaction(
        second_kit,
        2,
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        source_type=InventorySourceType.ORDER,
        source_id=other_order.id,
        operator_id=other.id,
        created_at=start + timedelta(minutes=1),
    )
    await _create_transaction(
        first_kit,
        3,
        transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
        source_type=InventorySourceType.ADMIN,
        operator_id=user.id,
        created_at=start + timedelta(minutes=1),
    )
    await _create_transaction(
        first_kit,
        4,
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        source_type=InventorySourceType.ORDER,
        source_id=order.id,
        operator_id=user.id,
        created_at=start + timedelta(minutes=2),
    )

    result = await InventoryRepository().list_transactions(
        page=1,
        page_size=20,
        product_id=first_kit.product_id,
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        source_type=InventorySourceType.ORDER,
        source_id=order.id,
        created_from=start + timedelta(minutes=1),
        created_to=start + timedelta(minutes=2),
    )

    assert [item.id for item in result.items] == [expected.id]
    assert result.items[0].operator.nickname == user.nickname
    assert result.items[0].source_order_no == order.order_no
    assert result.total == 1


async def test_list_transactions_has_stable_latest_first_pagination() -> None:
    """相同创建时间仍以 ID 倒序稳定分页，并返回完整 Page 元数据。"""

    user = await _create_user(1)
    kit = await _create_kit(1)
    same_time = datetime(2026, 8, 14, 3, 0, tzinfo=timezone.utc)
    transactions = [
        await _create_transaction(
            kit,
            number,
            transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
            source_type=InventorySourceType.ADMIN,
            operator_id=user.id,
            created_at=same_time,
        )
        for number in range(1, 6)
    ]

    result = await InventoryRepository().list_transactions(
        page=2,
        page_size=2,
        product_id=kit.product_id,
    )

    assert [item.id for item in result.items] == [
        transactions[2].id,
        transactions[1].id,
    ]
    assert result.total == 5
    assert result.page == 2
    assert result.page_size == 2
    assert result.pages == 3


async def test_list_transactions_created_range_boundaries() -> None:
    """created_from 包含边界，created_to 排除边界。"""

    kit = await _create_kit(1)
    start = datetime(2026, 8, 14, 4, 0, tzinfo=timezone.utc)
    at_start = await _create_transaction(
        kit,
        1,
        transaction_type=InventoryTransactionType.OPENING_BALANCE,
        source_type=InventorySourceType.MIGRATION,
        created_at=start,
    )
    await _create_transaction(
        kit,
        2,
        transaction_type=InventoryTransactionType.ORDER_CANCELLATION_RESTORE,
        source_type=InventorySourceType.ORDER,
        source_id=1,
        created_at=start + timedelta(hours=1),
    )

    result = await InventoryRepository().list_transactions(
        page=1,
        page_size=20,
        created_from=start,
        created_to=start + timedelta(hours=1),
    )

    assert [item.id for item in result.items] == [at_start.id]


async def test_empty_page_has_zero_pages() -> None:
    """无匹配流水时返回稳定的空 Page。"""

    result = await InventoryRepository().list_transactions(
        page=3,
        page_size=20,
        product_id=999,
    )

    assert result.items == []
    assert result.total == 0
    assert result.page == 3
    assert result.page_size == 20
    assert result.pages == 0


async def test_list_query_count_is_constant_with_multiple_order_sources(
    monkeypatch: MonkeyPatch,
) -> None:
    """流水数量增加时查询保持 count + page + 一次 Order 批量读取。"""

    user = await _create_user(1)
    kit = await _create_kit(1)
    for number in range(1, 6):
        order = await _create_order(user, number)
        await _create_transaction(
            kit,
            number,
            transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
            source_type=InventorySourceType.ORDER,
            source_id=order.id,
            operator_id=user.id,
        )

    connection = connections.get("default")
    original_execute_query: Callable[..., Awaitable[Any]] = connection.execute_query
    selects: list[str] = []

    async def capture_query(query: str, values: list[Any] | None = None) -> Any:
        if query.lstrip().upper().startswith("SELECT"):
            selects.append(query)
        return await original_execute_query(query, values)

    monkeypatch.setattr(connection, "execute_query", capture_query)
    result = await InventoryRepository().list_transactions(
        page=1,
        page_size=20,
        source_type=InventorySourceType.ORDER,
    )

    assert len(result.items) == 5
    assert all(item.source_order_no is not None for item in result.items)
    assert len(selects) == 3
