"""Inventory 路由参数适配、权限、状态码和响应隔离测试。"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import AsyncClient

from app.api.deps import get_current_admin, get_inventory_service
from app.common.enums.inventory import InventorySourceType, InventoryTransactionType
from app.common.pagination import Page
from app.main import app
from app.services.inventory_service import InventoryAdjustmentResult, InventoryService


NOW = datetime(2026, 8, 14, 10, 30, tzinfo=timezone.utc)


def _transaction() -> SimpleNamespace:
    return SimpleNamespace(
        id=101,
        product_id=5,
        transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
        change_quantity=2,
        before_quantity=10,
        after_quantity=12,
        reason="采购入库",
        source_type=InventorySourceType.ADMIN,
        source_id=None,
        source_order_no=None,
        operator_id=7,
        operator=SimpleNamespace(
            id=7,
            nickname="店长",
            username="must-not-leak",
            phone="13800138000",
            password="must-not-leak",
        ),
        idempotency_key="inventory:must-not-leak",
        created_at=NOW,
        updated_at=NOW,
    )


def _service() -> Mock:
    service = Mock(spec=InventoryService)
    service.adjust_stock = AsyncMock()
    service.list_product_transactions = AsyncMock()
    service.list_transactions = AsyncMock()
    return service


@pytest.fixture
def routed_service() -> Mock:
    service = _service()
    app.dependency_overrides[get_inventory_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


@pytest.fixture
def admin_routed_service(routed_service: Mock) -> Mock:
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=7)
    yield routed_service
    app.dependency_overrides.clear()


@pytest.mark.parametrize(("is_replay", "expected_status"), [(False, 201), (True, 200)])
async def test_adjustment_maps_request_and_selects_replay_status(
    client: AsyncClient,
    admin_routed_service: Mock,
    is_replay: bool,
    expected_status: int,
) -> None:
    transaction = _transaction()
    admin_routed_service.adjust_stock.return_value = InventoryAdjustmentResult(
        product_id=5,
        stock=12,
        transaction=transaction,
        is_replay=is_replay,
    )

    response = await client.post(
        "/api/v1/admin/products/kit/5/inventory-adjustments",
        headers={"Idempotency-Key": "  request-001  "},
        json={"change": 2, "reason": "  采购入库  "},
    )

    assert response.status_code == expected_status
    assert response.json()["data"] == {
        "product_id": 5,
        "stock": 12,
        "transaction": {
            "id": 101,
            "product_id": 5,
            "transaction_type": "admin_adjustment",
            "change_quantity": 2,
            "before_quantity": 10,
            "after_quantity": 12,
            "reason": "采购入库",
            "source_type": "admin",
            "source_id": None,
            "source_order_no": None,
            "operator_id": 7,
            "operator_nickname": "店长",
            "created_at": "2026-08-14T10:30:00Z",
        },
    }
    admin_routed_service.adjust_stock.assert_awaited_once_with(
        5,
        change=2,
        reason="采购入库",
        operator_id=7,
        ip_address="127.0.0.1",
        idempotency_key="request-001",
    )
    assert "must-not-leak" not in response.text


async def test_product_query_forwards_all_filters_and_serializes_page(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    transaction = _transaction()
    admin_routed_service.list_product_transactions.return_value = Page(
        items=[transaction], total=21, page=2, page_size=20, pages=2
    )

    response = await client.get(
        "/api/v1/admin/products/kit/5/inventory-transactions",
        params={
            "page": "2",
            "page_size": "20",
            "type": "admin_adjustment",
            "source_type": "admin",
            "created_from": "2026-08-14T00:00:00Z",
            "created_to": "2026-08-15T00:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["id"] == 101
    assert response.json()["data"] | {"items": []} == {
        "items": [],
        "total": 21,
        "page": 2,
        "page_size": 20,
        "pages": 2,
    }
    call = admin_routed_service.list_product_transactions.await_args
    assert call.args == (5,)
    assert call.kwargs["transaction_type"] is InventoryTransactionType.ADMIN_ADJUSTMENT
    assert call.kwargs["source_type"] is InventorySourceType.ADMIN
    assert call.kwargs["created_from"].utcoffset().total_seconds() == 0
    assert call.kwargs["created_to"].utcoffset().total_seconds() == 0


async def test_global_query_forwards_product_and_order_source_filters(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    admin_routed_service.list_transactions.return_value = Page(
        items=[], total=0, page=1, page_size=5, pages=0
    )

    response = await client.get(
        "/api/v1/admin/inventory-transactions",
        params={
            "page_size": "5",
            "product_id": "5",
            "source_type": "order",
            "source_id": "31",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 5,
        "pages": 0,
    }
    admin_routed_service.list_transactions.assert_awaited_once_with(
        page=1,
        page_size=5,
        product_id=5,
        transaction_type=None,
        source_type=InventorySourceType.ORDER,
        source_id=31,
        created_from=None,
        created_to=None,
    )


@pytest.mark.parametrize(
    ("headers", "payload"),
    [
        ({}, {"change": 1, "reason": "补货"}),
        ({"Idempotency-Key": "   "}, {"change": 1, "reason": "补货"}),
        ({"Idempotency-Key": "key-1"}, {"change": 0, "reason": "补货"}),
        (
            {"Idempotency-Key": "key-1"},
            {"change": 1, "reason": "补货", "stock": 12},
        ),
    ],
)
async def test_invalid_adjustment_never_calls_service(
    client: AsyncClient,
    admin_routed_service: Mock,
    headers: dict[str, str],
    payload: dict[str, object],
) -> None:
    response = await client.post(
        "/api/v1/admin/products/kit/5/inventory-adjustments",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == 422
    admin_routed_service.adjust_stock.assert_not_awaited()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/products/kit/5/inventory-transactions?unknown=x",
        "/api/v1/admin/inventory-transactions?source_id=31",
        "/api/v1/admin/inventory-transactions?created_from=2026-08-14T08:00:00%2B08:00",
    ],
)
async def test_invalid_query_never_calls_service(
    client: AsyncClient,
    admin_routed_service: Mock,
    path: str,
) -> None:
    response = await client.get(path)

    assert response.status_code == 422
    admin_routed_service.list_product_transactions.assert_not_awaited()
    admin_routed_service.list_transactions.assert_not_awaited()


async def test_inventory_routes_require_admin_permission(
    client: AsyncClient,
    auth_user: dict,
    routed_service: Mock,
) -> None:
    response = await client.get(
        "/api/v1/admin/inventory-transactions",
        headers={"Authorization": f"Bearer {auth_user['token']}"},
    )

    assert response.status_code == 403
    routed_service.list_transactions.assert_not_awaited()
