"""OrderService 用户端与管理端只读查询契约测试。"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.common.enums.order import OrderStatus
from app.common.exceptions import OrderNotFound
from app.common.pagination import Page
from app.models.order import Order
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderService


def _service(repository: OrderRepository) -> OrderService:
    return OrderService(
        repository,
        AsyncMock(spec=ProductRepository),
        AsyncMock(spec=AuditLogService),
    )


async def test_user_list_forwards_identity_paging_and_status() -> None:
    """Service 不改变经过 Schema 校验的用户列表参数。"""

    repository = AsyncMock(spec=OrderRepository)
    expected = Page[Order](items=[], total=0, page=2, page_size=10, pages=0)
    repository.list_user_orders.return_value = expected

    result = await _service(repository).list_user_orders(
        user_id=7,
        page=2,
        page_size=10,
        status="paid",
    )

    assert result is expected
    repository.list_user_orders.assert_awaited_once_with(
        user_id=7,
        page=2,
        page_size=10,
        status=OrderStatus.PAID,
    )


async def test_user_detail_limits_visibility_in_repository_query() -> None:
    """用户身份必须进入 Repository SQL 条件，而不是详情返回后再比较。"""

    order = Order(
        id=11,
        order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id=7,
        total_amount="299.00",
    )
    repository = AsyncMock(spec=OrderRepository)
    repository.get_order_detail.return_value = order

    result = await _service(repository).get_user_order_detail(11, user_id=7)

    assert result is order
    repository.get_order_detail.assert_awaited_once_with(11, user_id=7)


@pytest.mark.parametrize("hidden_order", [None])
async def test_user_detail_hides_missing_and_foreign_orders(
    hidden_order: None,
) -> None:
    """Repository 对两种情况均返回 None，Service 对外只暴露同一异常。"""

    repository = AsyncMock(spec=OrderRepository)
    repository.get_order_detail.return_value = hidden_order

    with pytest.raises(OrderNotFound):
        await _service(repository).get_user_order_detail(11, user_id=7)

    repository.get_order_detail.assert_awaited_once_with(11, user_id=7)


async def test_admin_list_forwards_all_frozen_filters() -> None:
    """管理端组合筛选应无损转发给数据访问层。"""

    repository = AsyncMock(spec=OrderRepository)
    expected = Page[Order](items=[], total=0, page=3, page_size=5, pages=0)
    repository.list_admin_orders.return_value = expected
    created_from = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    created_to = datetime(2026, 8, 14, 8, 0, tzinfo=timezone.utc)

    result = await _service(repository).list_admin_orders(
        page=3,
        page_size=5,
        status="completed",
        order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id=7,
        created_from=created_from,
        created_to=created_to,
    )

    assert result is expected
    repository.list_admin_orders.assert_awaited_once_with(
        page=3,
        page_size=5,
        status=OrderStatus.COMPLETED,
        order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id=7,
        created_from=created_from,
        created_to=created_to,
    )


async def test_admin_detail_returns_any_existing_order() -> None:
    """管理查询不附加用户范围，但仍统一处理不存在订单。"""

    order = Order(
        id=11,
        order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id=7,
        total_amount="299.00",
    )
    repository = AsyncMock(spec=OrderRepository)
    repository.get_order_detail.return_value = order

    result = await _service(repository).get_admin_order_detail(11)

    assert result is order
    repository.get_order_detail.assert_awaited_once_with(11)


async def test_admin_detail_raises_named_not_found() -> None:
    repository = AsyncMock(spec=OrderRepository)
    repository.get_order_detail.return_value = None

    with pytest.raises(OrderNotFound):
        await _service(repository).get_admin_order_detail(404)

    repository.get_order_detail.assert_awaited_once_with(404)
