"""OrderRepository 详情、列表、筛选与性能契约测试。"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pytest import MonkeyPatch
from tortoise import connections
from tortoise.exceptions import NoValuesFetched
from tortoise.transactions import in_transaction

from app.common.enums.order import OrderStatus
from app.common.enums.product import ProductType
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.repositories.order_repo import OrderRepository


async def _create_user(number: int) -> User:
    return await User.create(
        username=f"order-query-{number}",
        password="hashed-password",
        nickname=f"用户 {number}",
        phone=f"1380013{number:04d}",
    )


async def _create_order(
    user: User,
    number: int,
    *,
    status: OrderStatus = OrderStatus.PENDING,
    created_at: datetime | None = None,
    item_count: int = 1,
) -> Order:
    order = await Order.create(
        order_no=f"OD01ARZ3NDEKTSV4RRFFQ69G5F{number:02d}",
        user=user,
        total_amount=Decimal(item_count * 100),
        status=status.value,
    )
    if created_at is not None:
        await Order.filter(id=order.id).update(created_at=created_at)
        order.created_at = created_at

    for item_number in range(item_count):
        product = await Product.create(
            name=f"订单 {number} 商品 {item_number}",
            product_type=ProductType.EXPERIENCE,
        )
        await OrderItem.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=Decimal("100.00"),
            quantity=1,
            subtotal=Decimal("100.00"),
        )
    return order


async def test_get_order_detail_prefetches_user_and_stable_items() -> None:
    """详情应完整预加载安全用户展示源和按 ID 排序的 Items。"""

    user = await _create_user(1)
    order = await _create_order(user, 1, item_count=3)

    detail = await OrderRepository().get_order_detail(order.id)

    assert detail is not None
    assert detail.user.id == user.id
    assert detail.user.nickname == "用户 1"
    assert [item.id for item in detail.items] == sorted(item.id for item in detail.items)
    assert len(detail.items) == 3


async def test_get_order_detail_can_limit_user_visibility_in_sql() -> None:
    """用户详情查询可通过 user_id 条件统一隐藏不存在和他人订单。"""

    owner = await _create_user(1)
    stranger = await _create_user(2)
    order = await _create_order(owner, 1)
    repository = OrderRepository()

    assert await repository.get_order_detail(order.id, user_id=owner.id) is not None
    assert await repository.get_order_detail(order.id, user_id=stranger.id) is None
    assert await repository.get_order_detail(order.id + 999, user_id=owner.id) is None


async def test_get_order_detail_by_number_and_missing() -> None:
    """唯一订单号查询应返回同一预加载聚合，并处理不存在编号。"""

    user = await _create_user(1)
    order = await _create_order(user, 1, item_count=2)
    repository = OrderRepository()

    detail = await repository.get_order_detail_by_no(order.order_no)

    assert detail is not None
    assert detail.id == order.id
    assert detail.user.id == user.id
    assert len(detail.items) == 2
    assert (
        await repository.get_order_detail_by_no(
            "OD01ARZ3NDEKTSV4RRFFQ69G5F99"
        )
        is None
    )


async def test_get_order_by_id_is_lightweight_and_accepts_transaction() -> None:
    """审计存在性查询不加载关系，并可复用调用方数据库连接。"""

    user = await _create_user(1)
    order = await _create_order(user, 1, item_count=2)
    repository = OrderRepository()

    async with in_transaction() as connection:
        loaded = await repository.get_order_by_id(
            order.id,
            using_db=connection,
        )
        missing = await repository.get_order_by_id(
            order.id + 999,
            using_db=connection,
        )

    assert loaded is not None
    assert loaded.id == order.id
    assert missing is None
    with pytest.raises(NoValuesFetched):
        list(loaded.items)


async def test_get_order_items_returns_only_stable_cancellation_snapshot() -> None:
    """取消用查询在调用方事务中按 ID 返回最小不可变字段集合。"""

    user = await _create_user(1)
    order = await _create_order(user, 1, item_count=2)

    async with in_transaction() as connection:
        items = await OrderRepository().get_order_items(
            order.id,
            using_db=connection,
        )

    assert [item.product_id for item in items] == sorted(
        item.product_id for item in items
    )
    assert [item.quantity for item in items] == [1, 1]
    assert all(item.experience_option_id is None for item in items)
    assert all(type(item).__name__ == "OrderCancellationItemData" for item in items)


async def test_detail_query_count_is_constant(
    monkeypatch: MonkeyPatch,
) -> None:
    """Item 数量增加时详情仍只执行常量级 SELECT，不产生 N+1。"""

    user = await _create_user(1)
    order = await _create_order(user, 1, item_count=5)
    connection = connections.get("default")
    original_execute_query: Callable[..., Awaitable[Any]] = connection.execute_query
    select_queries: list[str] = []

    async def capture_query(query: str, values: list[Any] | None = None) -> Any:
        if query.lstrip().upper().startswith("SELECT"):
            select_queries.append(query)
        return await original_execute_query(query, values)

    monkeypatch.setattr(connection, "execute_query", capture_query)

    detail = await OrderRepository().get_order_detail(order.id)
    assert detail is not None
    assert len(detail.items) == 5
    assert 1 <= len(select_queries) <= 2


async def test_get_order_for_update_limits_user_and_uses_transaction() -> None:
    """状态用例可在事务中锁定用户可见订单，不加载他人资源。"""

    owner = await _create_user(1)
    stranger = await _create_user(2)
    order = await _create_order(owner, 1)
    repository = OrderRepository()

    async with in_transaction() as connection:
        visible = await repository.get_order_for_update(
            order.id,
            user_id=owner.id,
            using_db=connection,
        )
        hidden = await repository.get_order_for_update(
            order.id,
            user_id=stranger.id,
            using_db=connection,
        )

    assert visible is not None
    assert visible.id == order.id
    assert hidden is None


async def test_user_list_filters_status_as_integer_and_returns_item_counts(
    monkeypatch: MonkeyPatch,
) -> None:
    """状态筛选必须以原生 int 查询，并按明细行计数。"""

    user = await _create_user(1)
    other = await _create_user(2)
    pending = await _create_order(user, 1, item_count=2)
    paid = await _create_order(user, 2, status=OrderStatus.PAID, item_count=3)
    await _create_order(other, 3, status=OrderStatus.PAID, item_count=4)
    repository = OrderRepository()
    connection = connections.get("default")
    original_execute_query: Callable[..., Awaitable[Any]] = connection.execute_query
    filter_values: list[Any] = []

    async def capture_query(
        query: str,
        values: list[Any] | None = None,
    ) -> Any:
        if query.lstrip().upper().startswith("SELECT") and "STATUS" in query.upper():
            filter_values.extend(values or [])
        return await original_execute_query(query, values)

    monkeypatch.setattr(connection, "execute_query", capture_query)

    result = await repository.list_user_orders(
        user_id=user.id,
        status=OrderStatus.PAID,
        page=1,
        page_size=20,
    )

    assert [order.id for order in result.items] == [paid.id]
    assert result.items[0].item_count == 3
    assert result.total == 1
    assert pending.id not in [order.id for order in result.items]
    assert all(not isinstance(value, OrderStatus) for value in filter_values)
    assert any(
        type(value) is int and value == OrderStatus.PAID.value
        for value in filter_values
    )
    with pytest.raises(NoValuesFetched):
        list(result.items[0].items)


async def test_user_list_has_stable_latest_first_pagination() -> None:
    """相同创建时间下仍以 ID 倒序稳定分页并返回完整元数据。"""

    user = await _create_user(1)
    same_time = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    orders = [
        await _create_order(user, number, created_at=same_time)
        for number in range(1, 6)
    ]

    result = await OrderRepository().list_user_orders(
        user_id=user.id,
        page=2,
        page_size=2,
    )

    assert [order.id for order in result.items] == [orders[2].id, orders[1].id]
    assert result.total == 5
    assert result.page == 2
    assert result.page_size == 2
    assert result.pages == 3


async def test_admin_list_applies_all_filters_and_preloads_user() -> None:
    """管理端组合筛选使用包含下界、排除上界的 UTC 时间范围。"""

    user = await _create_user(1)
    other = await _create_user(2)
    start = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    expected = await _create_order(
        user,
        1,
        status=OrderStatus.PAID,
        created_at=start + timedelta(hours=1),
        item_count=2,
    )
    await _create_order(
        user,
        2,
        status=OrderStatus.PENDING,
        created_at=start + timedelta(hours=1),
    )
    await _create_order(
        user,
        3,
        status=OrderStatus.PAID,
        created_at=start + timedelta(hours=2),
    )
    await _create_order(
        other,
        4,
        status=OrderStatus.PAID,
        created_at=start + timedelta(hours=1),
    )

    result = await OrderRepository().list_admin_orders(
        page=1,
        page_size=20,
        status=OrderStatus.PAID,
        order_no=expected.order_no,
        product_name="订单 1 商品",
        user_id=user.id,
        created_from=start + timedelta(hours=1),
        created_to=start + timedelta(hours=2),
    )

    assert [order.id for order in result.items] == [expected.id]
    assert result.items[0].user.id == user.id
    assert result.items[0].user.nickname == "用户 1"
    assert result.items[0].item_count == 2


async def test_admin_product_name_filter_uses_snapshot_without_duplicate_pages(
) -> None:
    """多 Item 命中只计一单，且当前 Product 改名不改变历史检索。"""

    user = await _create_user(1)
    same_time = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    older = await _create_order(
        user,
        1,
        created_at=same_time,
        item_count=3,
    )
    newer = await _create_order(
        user,
        2,
        created_at=same_time,
        item_count=2,
    )
    current_name_only = await _create_order(user, 3, item_count=1)

    older_items = await OrderItem.filter(order_id=older.id).order_by("id")
    newer_items = await OrderItem.filter(order_id=newer.id).order_by("id")
    current_only_item = await OrderItem.get(order_id=current_name_only.id)
    await OrderItem.filter(id__in=[older_items[0].id, older_items[1].id]).update(
        product_name="历史星空拼豆",
    )
    await OrderItem.filter(id=newer_items[0].id).update(
        product_name="星空材料包历史快照",
    )
    await Product.filter(id=older_items[0].product_id).update(name="当前已改名")
    await Product.filter(id=current_only_item.product_id).update(
        name="当前星空商品",
    )

    first = await OrderRepository().list_admin_orders(
        page=1,
        page_size=1,
        product_name="星空",
    )
    second = await OrderRepository().list_admin_orders(
        page=2,
        page_size=1,
        product_name="星空",
    )

    assert [order.id for order in first.items] == [newer.id]
    assert [order.id for order in second.items] == [older.id]
    assert first.total == second.total == 2
    assert first.pages == second.pages == 2
    assert first.items[0].item_count == 2
    assert second.items[0].item_count == 3
    assert current_name_only.id not in {
        *(order.id for order in first.items),
        *(order.id for order in second.items),
    }


async def test_admin_created_range_boundaries() -> None:
    """created_from 包含边界，created_to 排除边界。"""

    user = await _create_user(1)
    start = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    at_start = await _create_order(user, 1, created_at=start)
    await _create_order(user, 2, created_at=start + timedelta(hours=1))

    result = await OrderRepository().list_admin_orders(
        page=1,
        page_size=20,
        created_from=start,
        created_to=start + timedelta(hours=1),
    )

    assert [order.id for order in result.items] == [at_start.id]


async def test_empty_page_metadata_and_summary_query_count(
    monkeypatch: MonkeyPatch,
) -> None:
    """空结果保持 Page 契约；摘要查询不随订单或明细数量增长。"""

    user = await _create_user(1)
    for number in range(1, 4):
        await _create_order(user, number, item_count=number)
    connection = connections.get("default")
    original_execute_query: Callable[..., Awaitable[Any]] = connection.execute_query
    select_queries: list[str] = []

    async def capture_query(query: str, values: list[Any] | None = None) -> Any:
        if query.lstrip().upper().startswith("SELECT"):
            select_queries.append(query)
        return await original_execute_query(query, values)

    monkeypatch.setattr(connection, "execute_query", capture_query)

    page = await OrderRepository().list_user_orders(
        user_id=user.id,
        page=1,
        page_size=20,
    )
    empty = await OrderRepository().list_user_orders(
        user_id=user.id,
        status=OrderStatus.COMPLETED,
        page=2,
        page_size=20,
    )

    assert [order.item_count for order in page.items] == [3, 2, 1]
    assert empty.items == []
    assert empty.total == 0
    assert empty.pages == 0
    assert len(select_queries) <= 4
