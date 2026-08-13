"""OrderRepository 写入、状态持久化与事务契约测试。"""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from pytest import MonkeyPatch
from tortoise import connections
from tortoise.transactions import in_transaction

from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductType
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.repositories.order_repo import OrderItemCreateData, OrderRepository


async def _create_user() -> User:
    return await User.create(
        username="order-repo-user",
        password="hashed-password",
        nickname="订单仓储用户",
        phone="13800138000",
    )


async def _create_products() -> tuple[Product, Product]:
    first = await Product.create(name="体验 A", product_type=ProductType.EXPERIENCE)
    second = await Product.create(name="体验 B", product_type=ProductType.EXPERIENCE)
    return first, second


def _item_data(product: Product, *, subtotal: str = "299.00") -> OrderItemCreateData:
    return OrderItemCreateData(
        product_id=product.id,
        experience_option_id=None,
        option_duration_minutes=60,
        option_participants=1,
        option_day_type=DayType.WEEKDAY,
        product_name=product.name,
        product_price=Decimal("299.00"),
        quantity=1,
        subtotal=Decimal(subtotal),
    )


async def test_create_order_uses_model_pending_default() -> None:
    """Repository 只接收创建数据，初始状态由 Model 契约提供。"""

    user = await _create_user()

    created = await OrderRepository().create_order(
        order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id=user.id,
        total_amount=Decimal("299.00"),
        remark="预约晚场",
    )

    assert created.id is not None
    assert created.user_id == user.id
    assert created.status == OrderStatus.PENDING
    assert created.total_amount == Decimal("299.00")
    assert created.remark == "预约晚场"


async def test_create_order_uses_supplied_transaction_connection() -> None:
    """Order 创建必须随调用方事务异常完整回滚。"""

    user = await _create_user()
    created_id: int | None = None

    with pytest.raises(RuntimeError, match="rollback order"):
        async with in_transaction() as connection:
            order = await OrderRepository().create_order(
                order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
                user_id=user.id,
                total_amount=Decimal("299.00"),
                remark=None,
                using_db=connection,
            )
            created_id = order.id
            raise RuntimeError("rollback order")

    assert created_id is not None
    assert not await Order.filter(id=created_id).exists()


async def test_bulk_create_items_uses_one_insert_and_preserves_snapshots(
    monkeypatch: MonkeyPatch,
) -> None:
    """多条明细应由一次 bulk INSERT 写入并保留完整快照。"""

    user = await _create_user()
    products = await _create_products()
    repository = OrderRepository()
    order = await repository.create_order(
        order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id=user.id,
        total_amount=Decimal("598.00"),
        remark=None,
    )
    connection = connections.get("default")
    original_execute_many: Callable[..., Awaitable[Any]] = connection.execute_many
    insert_queries: list[str] = []

    async def capture_many(query: str, values: list[list[Any]]) -> Any:
        if query.lstrip().upper().startswith("INSERT"):
            insert_queries.append(query)
        return await original_execute_many(query, values)

    monkeypatch.setattr(connection, "execute_many", capture_many)

    await repository.bulk_create_items(
        order=order,
        items=[_item_data(product) for product in products],
    )

    stored = await OrderItem.filter(order_id=order.id).order_by("id")
    assert len(insert_queries) == 1
    assert [item.product_id for item in stored] == [
        products[0].id,
        products[1].id,
    ]
    assert all(item.product_price == Decimal("299.00") for item in stored)
    assert all(item.option_day_type is DayType.WEEKDAY for item in stored)


async def test_bulk_create_items_noops_for_empty_input(
    monkeypatch: MonkeyPatch,
) -> None:
    """空集合不应产生无意义 SQL；非空要求由 Schema/Service 保证。"""

    user = await _create_user()
    order = await OrderRepository().create_order(
        order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id=user.id,
        total_amount=Decimal("299.00"),
        remark=None,
    )
    connection = connections.get("default")
    original_execute_many: Callable[..., Awaitable[Any]] = connection.execute_many
    calls = 0

    async def capture_many(query: str, values: list[list[Any]]) -> Any:
        nonlocal calls
        calls += 1
        return await original_execute_many(query, values)

    monkeypatch.setattr(connection, "execute_many", capture_many)

    await OrderRepository().bulk_create_items(order=order, items=[])

    assert calls == 0
    assert await OrderItem.filter(order_id=order.id).count() == 0


async def test_order_and_bulk_items_share_transaction_rollback() -> None:
    """主表和批量明细必须能加入同一事务并一起回滚。"""

    user = await _create_user()
    product, _ = await _create_products()
    repository = OrderRepository()
    order_id: int | None = None

    with pytest.raises(RuntimeError, match="rollback aggregate"):
        async with in_transaction() as connection:
            order = await repository.create_order(
                order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
                user_id=user.id,
                total_amount=Decimal("299.00"),
                remark=None,
                using_db=connection,
            )
            order_id = order.id
            await repository.bulk_create_items(
                order=order,
                items=[_item_data(product)],
                using_db=connection,
            )
            raise RuntimeError("rollback aggregate")

    assert order_id is not None
    assert not await Order.filter(id=order_id).exists()
    assert not await OrderItem.filter(order_id=order_id).exists()


async def test_transaction_detail_reload_sees_uncommitted_bulk_items() -> None:
    """创建事务的响应重载必须读取同连接中尚未提交的完整聚合。"""

    user = await _create_user()
    products = await _create_products()
    repository = OrderRepository()
    order_id: int | None = None

    with pytest.raises(RuntimeError, match="rollback after reload"):
        async with in_transaction() as connection:
            order = await repository.create_order(
                order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
                user_id=user.id,
                total_amount=Decimal("598.00"),
                remark=None,
                using_db=connection,
            )
            order_id = order.id
            await repository.bulk_create_items(
                order=order,
                items=[_item_data(product) for product in products],
                using_db=connection,
            )

            detail = await repository.get_order_detail(
                order.id,
                using_db=connection,
            )

            assert detail is not None
            assert detail.user.id == user.id
            assert [item.product_id for item in detail.items] == [
                products[0].id,
                products[1].id,
            ]
            raise RuntimeError("rollback after reload")

    assert order_id is not None
    assert not await Order.filter(id=order_id).exists()
    assert not await OrderItem.filter(order_id=order_id).exists()


async def test_update_status_uses_supplied_transaction_connection() -> None:
    """Repository 持久化状态但不判断状态机，并加入调用方事务。"""

    user = await _create_user()
    repository = OrderRepository()
    order = await repository.create_order(
        order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id=user.id,
        total_amount=Decimal("299.00"),
        remark=None,
    )

    with pytest.raises(RuntimeError, match="rollback status"):
        async with in_transaction() as connection:
            locked = await repository.get_order_for_update(
                order.id,
                using_db=connection,
            )
            assert locked is not None
            updated = await repository.update_status(
                locked,
                status=OrderStatus.PAID,
                using_db=connection,
            )
            assert updated.status == OrderStatus.PAID
            raise RuntimeError("rollback status")

    stored = await Order.get(id=order.id)
    assert stored.status == OrderStatus.PENDING
