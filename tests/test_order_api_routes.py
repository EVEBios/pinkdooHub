"""Order FastAPI 路由参数、身份和响应编排测试。"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import AsyncClient

from app.api.deps import get_current_admin, get_current_user, get_order_service
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType
from app.common.pagination import Page
from app.main import app
from app.services.order_service import OrderItemInput, OrderService


NOW = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)
ORDER_NO = "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC"


def _item() -> SimpleNamespace:
    return SimpleNamespace(
        id=1001,
        order_id=101,
        product_id=1,
        experience_option_id=11,
        product_name="路由订单快照",
        option_duration_minutes=60,
        option_participants=1,
        option_day_type=DayType.WEEKDAY,
        product_price=Decimal("99.00"),
        quantity=2,
        subtotal=Decimal("198.00"),
    )


def _order(
    *,
    status: OrderStatus = OrderStatus.PENDING,
    with_items: bool = True,
    with_count: bool = False,
) -> SimpleNamespace:
    values = {
        "id": 101,
        "order_no": ORDER_NO,
        "user_id": 7,
        "user": SimpleNamespace(id=7, nickname="Alice"),
        "total_amount": Decimal("198.00"),
        "status": status,
        "remark": "周五到店",
        "items": [_item()] if with_items else [],
        "created_at": NOW,
        "updated_at": NOW,
    }
    if with_count:
        values["item_count"] = 1
    return SimpleNamespace(**values)


def _service() -> Mock:
    service = Mock(spec=OrderService)
    for name in (
        "create_order",
        "list_user_orders",
        "get_user_order_detail",
        "cancel_order",
        "list_admin_orders",
        "get_admin_order_detail",
        "mark_order_paid",
        "complete_order",
        "list_order_audit_logs",
    ):
        setattr(service, name, AsyncMock())
    return service


@pytest.fixture
def routed_service() -> Mock:
    service = _service()
    app.dependency_overrides[get_order_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


@pytest.fixture
def user_routed_service(routed_service: Mock) -> Mock:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
    yield routed_service
    app.dependency_overrides.clear()


@pytest.fixture
def admin_routed_service(routed_service: Mock) -> Mock:
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=70)
    yield routed_service
    app.dependency_overrides.clear()


async def test_create_uses_authenticated_identity_domain_items_ip_and_201(
    client: AsyncClient,
    user_routed_service: Mock,
) -> None:
    user_routed_service.create_order.return_value = _order()

    response = await client.post(
        "/api/v1/orders",
        json={
            "items": [
                {"product_id": 1, "experience_option_id": 11, "quantity": 2}
            ],
            "remark": " 周五到店 ",
        },
        headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"},
    )

    assert response.status_code == 201
    assert response.json()["message"] == "Order created"
    assert response.json()["data"]["total_amount"] == "198.00"
    assert "user_id" not in response.json()["data"]
    user_routed_service.create_order.assert_awaited_once_with(
        user_id=7,
        items=[OrderItemInput(1, 11, 2)],
        remark="周五到店",
        ip_address="203.0.113.7",
    )


async def test_create_rejects_forged_identity_and_snapshot_fields(
    client: AsyncClient,
    user_routed_service: Mock,
) -> None:
    response = await client.post(
        "/api/v1/orders",
        json={
            "user_id": 999,
            "items": [
                {
                    "product_id": 1,
                    "experience_option_id": 11,
                    "quantity": 1,
                    "product_price": "0.01",
                }
            ],
        },
    )

    assert response.status_code == 422
    locations = [item["location"] for item in response.json()["data"]["errors"]]
    assert ["body", "user_id"] in locations
    assert ["body", "items", "0", "product_price"] in locations
    assert "0.01" not in response.text
    user_routed_service.create_order.assert_not_awaited()


async def test_user_list_forwards_query_and_identity(
    client: AsyncClient,
    user_routed_service: Mock,
) -> None:
    user_routed_service.list_user_orders.return_value = Page(
        items=[_order(with_items=False, with_count=True)],
        total=1,
        page=2,
        page_size=5,
        pages=1,
    )

    response = await client.get(
        "/api/v1/orders?page=2&page_size=5&status=pending"
    )

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["item_count"] == 1
    user_routed_service.list_user_orders.assert_awaited_once_with(
        user_id=7,
        page=2,
        page_size=5,
        status="pending",
    )


async def test_user_detail_and_cancel_are_owner_scoped(
    client: AsyncClient,
    user_routed_service: Mock,
) -> None:
    user_routed_service.get_user_order_detail.return_value = _order()
    user_routed_service.cancel_order.return_value = _order(
        status=OrderStatus.CANCELLED,
        with_items=False,
    )

    detail_response = await client.get("/api/v1/orders/101")
    cancel_response = await client.patch(
        "/api/v1/orders/101/cancel",
        headers={"X-Forwarded-For": "198.51.100.8"},
    )

    assert detail_response.status_code == 200
    assert "user_id" not in detail_response.json()["data"]
    assert cancel_response.status_code == 200
    assert cancel_response.json()["message"] == "Order cancelled"
    assert cancel_response.json()["data"]["status"]["value"] == "cancelled"
    user_routed_service.get_user_order_detail.assert_awaited_once_with(
        101,
        user_id=7,
    )
    user_routed_service.cancel_order.assert_awaited_once_with(
        101,
        user_id=7,
        ip_address="198.51.100.8",
    )


async def test_admin_list_forwards_all_validated_filters(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    admin_routed_service.list_admin_orders.return_value = Page(
        items=[_order(with_items=False, with_count=True)],
        total=1,
        page=1,
        page_size=10,
        pages=1,
    )

    response = await client.get(
        "/api/v1/admin/orders?page=1&page_size=10&status=paid"
        f"&order_no={ORDER_NO}&user_id=7"
        "&created_from=2026-08-13T00%3A00%3A00Z"
        "&created_to=2026-08-14T00%3A00%3A00Z"
    )

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["user_nickname"] == "Alice"
    kwargs = admin_routed_service.list_admin_orders.await_args.kwargs
    assert kwargs["page"] == 1
    assert kwargs["page_size"] == 10
    assert kwargs["status"] == "paid"
    assert kwargs["order_no"] == ORDER_NO
    assert kwargs["user_id"] == 7
    assert kwargs["created_from"] == datetime(
        2026, 8, 13, tzinfo=timezone.utc
    )
    assert kwargs["created_to"] == datetime(
        2026, 8, 14, tzinfo=timezone.utc
    )


async def test_admin_detail_serializes_only_safe_user_fields(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    admin_routed_service.get_admin_order_detail.return_value = _order()

    response = await client.get("/api/v1/admin/orders/101")

    assert response.status_code == 200
    assert response.json()["data"]["user_id"] == 7
    assert response.json()["data"]["user_nickname"] == "Alice"
    admin_routed_service.get_admin_order_detail.assert_awaited_once_with(101)


@pytest.mark.parametrize(
    ("path", "method_name", "target_status", "message"),
    [
        (
            "/api/v1/admin/orders/101/paid",
            "mark_order_paid",
            OrderStatus.PAID,
            "Order marked as paid",
        ),
        (
            "/api/v1/admin/orders/101/complete",
            "complete_order",
            OrderStatus.COMPLETED,
            "Order completed",
        ),
    ],
)
async def test_admin_status_routes_use_authenticated_operator_and_ip(
    client: AsyncClient,
    admin_routed_service: Mock,
    path: str,
    method_name: str,
    target_status: OrderStatus,
    message: str,
) -> None:
    getattr(admin_routed_service, method_name).return_value = _order(
        status=target_status,
        with_items=False,
    )

    response = await client.patch(
        path,
        headers={"X-Forwarded-For": "192.0.2.70"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == message
    getattr(admin_routed_service, method_name).assert_awaited_once_with(
        101,
        operator_id=70,
        ip_address="192.0.2.70",
    )


async def test_admin_audit_route_uses_shared_mapper_and_paging(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    admin_routed_service.list_order_audit_logs.return_value = Page(
        items=[
            SimpleNamespace(
                id=9,
                operator_id=70,
                action="MARK_ORDER_PAID",
                target_type="order",
                target_id=101,
                description='{"before_status":"pending","after_status":"paid"}',
                ip_address="192.0.2.70",
                created_at=NOW,
            )
        ],
        total=1,
        page=2,
        page_size=5,
        pages=1,
    )

    response = await client.get(
        "/api/v1/admin/orders/101/audit-logs?page=2&page_size=5"
    )

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["action"] == "MARK_ORDER_PAID"
    admin_routed_service.list_order_audit_logs.assert_awaited_once_with(
        101,
        page=2,
        page_size=5,
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/orders?page=0"),
        ("get", "/api/v1/orders?unknown=value"),
        ("get", "/api/v1/orders/0"),
        ("get", "/api/v1/admin/orders?created_from=2026-08-13T08%3A00%3A00%2B08%3A00"),
        ("get", "/api/v1/admin/orders/1/audit-logs?action=x"),
    ],
)
async def test_invalid_http_inputs_use_unified_422_without_service_call(
    client: AsyncClient,
    user_routed_service: Mock,
    method: str,
    path: str,
) -> None:
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=70)

    response = await getattr(client, method)(path)

    assert response.status_code == 422
    assert response.json()["code"] == 422
    assert response.json()["message"] == "Validation failed"
    assert all(
        not getattr(user_routed_service, method_name).await_count
        for method_name in (
            "list_user_orders",
            "get_user_order_detail",
            "list_admin_orders",
            "list_order_audit_logs",
        )
    )


async def test_admin_routes_reject_authenticated_normal_user(
    client: AsyncClient,
    auth_user: dict,
    routed_service: Mock,
) -> None:
    response = await client.get(
        "/api/v1/admin/orders",
        headers={"Authorization": f"Bearer {auth_user['token']}"},
    )

    assert response.status_code == 403
    routed_service.list_admin_orders.assert_not_awaited()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/orders",
        "/api/v1/admin/orders",
    ],
)
async def test_order_routes_use_unified_authentication_error(
    client: AsyncClient,
    routed_service: Mock,
    path: str,
) -> None:
    """HTTPBearer 缺失凭据由共享异常中间件输出统一 401 信封。"""

    response = await client.get(path)

    assert response.status_code == 401
    assert response.json() == {
        "code": 401,
        "message": "Authentication required",
        "data": None,
    }
    routed_service.list_user_orders.assert_not_awaited()
    routed_service.list_admin_orders.assert_not_awaited()
