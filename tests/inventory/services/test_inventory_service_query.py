"""InventoryService 查询编排、筛选转发与资源错误契约。"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.enums.inventory import InventorySourceType, InventoryTransactionType
from app.common.enums.product import ProductType
from app.common.exceptions import (
    ProductIsDeleted,
    ProductKitNotFound,
    ProductNotFound,
    ProductTypeMismatch,
)
from app.common.pagination import Page
from app.services.inventory_service import InventoryService


def _service() -> tuple[InventoryService, AsyncMock, AsyncMock]:
    inventory_repository = AsyncMock()
    product_repository = AsyncMock()
    service = InventoryService(
        inventory_repository=inventory_repository,
        product_repository=product_repository,
        audit_log_service=AsyncMock(),
    )
    return service, inventory_repository, product_repository


def _product(
    *,
    product_type: ProductType = ProductType.KIT,
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        product_type=product_type,
        is_deleted=is_deleted,
    )


async def test_product_query_validates_kit_and_forwards_all_filters() -> None:
    service, inventory_repository, product_repository = _service()
    product = _product()
    kit = SimpleNamespace(product_id=7, stock=12)
    expected = Page(items=[], total=0, page=2, page_size=10, pages=0)
    created_from = datetime(2026, 8, 14, tzinfo=timezone.utc)
    created_to = datetime(2026, 8, 15, tzinfo=timezone.utc)
    product_repository.get_products_by_ids.return_value = [product]
    product_repository.get_kits_by_product_ids.return_value = [kit]
    inventory_repository.list_transactions.return_value = expected

    result = await service.list_product_transactions(
        7,
        page=2,
        page_size=10,
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        source_type=InventorySourceType.ORDER,
        source_id=31,
        created_from=created_from,
        created_to=created_to,
    )

    assert result is expected
    product_repository.get_products_by_ids.assert_awaited_once_with(
        {7},
        using_db=None,
    )
    product_repository.get_kits_by_product_ids.assert_awaited_once_with({7})
    inventory_repository.list_transactions.assert_awaited_once_with(
        page=2,
        page_size=10,
        product_id=7,
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        source_type=InventorySourceType.ORDER,
        source_id=31,
        created_from=created_from,
        created_to=created_to,
    )


@pytest.mark.parametrize(
    ("products", "kits", "expected_exception"),
    [
        ([], [], ProductNotFound),
        ([_product(is_deleted=True)], [], ProductIsDeleted),
        (
            [_product(product_type=ProductType.EXPERIENCE)],
            [],
            ProductTypeMismatch,
        ),
        ([_product()], [], ProductKitNotFound),
    ],
)
async def test_product_query_enforces_resource_error_priority(
    products: list[SimpleNamespace],
    kits: list[SimpleNamespace],
    expected_exception: type[Exception],
) -> None:
    service, inventory_repository, product_repository = _service()
    product_repository.get_products_by_ids.return_value = products
    product_repository.get_kits_by_product_ids.return_value = kits

    with pytest.raises(expected_exception):
        await service.list_product_transactions(7, page=1, page_size=20)

    inventory_repository.list_transactions.assert_not_awaited()
    if not products or expected_exception in {ProductIsDeleted, ProductTypeMismatch}:
        product_repository.get_kits_by_product_ids.assert_not_awaited()


async def test_global_query_does_not_validate_product_filter() -> None:
    service, inventory_repository, product_repository = _service()
    expected = Page(items=[], total=0, page=3, page_size=20, pages=0)
    inventory_repository.list_transactions.return_value = expected

    result = await service.list_transactions(
        page=3,
        page_size=20,
        product_id=999,
    )

    assert result is expected
    product_repository.get_products_by_ids.assert_not_awaited()
    product_repository.get_kits_by_product_ids.assert_not_awaited()
    inventory_repository.list_transactions.assert_awaited_once_with(
        page=3,
        page_size=20,
        product_id=999,
        transaction_type=None,
        source_type=None,
        source_id=None,
        created_from=None,
        created_to=None,
    )
