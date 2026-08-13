"""Product 操作历史 Service 编排测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.common.exceptions import ProductNotFound
from app.common.pagination import Page
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService


def _service(product: object | None) -> tuple[ProductService, Mock, Mock]:
    repository = Mock()
    repository.get_product_by_id = AsyncMock(return_value=product)
    audit_service = Mock(spec=AuditLogService)
    audit_service.list_logs = AsyncMock()
    return ProductService(repository, audit_service), repository, audit_service


async def test_product_audit_query_includes_logically_deleted_product() -> None:
    product = SimpleNamespace(id=3, is_deleted=True)
    service, repository, audit_service = _service(product)
    expected = Page(items=[], total=0, page=2, page_size=5, pages=0)
    audit_service.list_logs.return_value = expected

    result = await service.list_product_audit_logs(3, page=2, page_size=5)

    assert result is expected
    repository.get_product_by_id.assert_awaited_once_with(
        3,
        include_deleted=True,
    )
    audit_service.list_logs.assert_awaited_once_with(
        target_type="product",
        target_id=3,
        page=2,
        page_size=5,
    )


async def test_product_audit_query_rejects_missing_product_before_audit_query() -> None:
    service, repository, audit_service = _service(None)

    with pytest.raises(ProductNotFound):
        await service.list_product_audit_logs(404, page=1, page_size=20)

    repository.get_product_by_id.assert_awaited_once_with(
        404,
        include_deleted=True,
    )
    audit_service.list_logs.assert_not_awaited()
