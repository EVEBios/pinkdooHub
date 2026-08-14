"""Order 操作历史 Service 编排测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.constants.order import ORDER_AUDIT_TARGET_TYPE
from app.common.exceptions import OrderNotFound
from app.common.pagination import Page
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderService


def _service(order: object | None) -> tuple[OrderService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=OrderRepository)
    repository.get_order_by_id.return_value = order
    audit_service = AsyncMock(spec=AuditLogService)
    return (
        OrderService(
            repository,
            AsyncMock(spec=ProductRepository),
            AsyncMock(spec=InventoryRepository),
            audit_service,
        ),
        repository,
        audit_service,
    )


async def test_order_audit_query_delegates_after_existence_check() -> None:
    order = SimpleNamespace(id=11)
    service, repository, audit_service = _service(order)
    expected = Page(items=[], total=0, page=2, page_size=5, pages=0)
    audit_service.list_logs.return_value = expected

    result = await service.list_order_audit_logs(11, page=2, page_size=5)

    assert result is expected
    repository.get_order_by_id.assert_awaited_once_with(11)
    audit_service.list_logs.assert_awaited_once_with(
        target_type=ORDER_AUDIT_TARGET_TYPE,
        target_id=11,
        page=2,
        page_size=5,
    )


async def test_order_audit_query_rejects_missing_before_log_query() -> None:
    service, repository, audit_service = _service(None)

    with pytest.raises(OrderNotFound):
        await service.list_order_audit_logs(404, page=1, page_size=20)

    repository.get_order_by_id.assert_awaited_once_with(404)
    audit_service.list_logs.assert_not_awaited()
