"""Order 查询、权限、状态机与无请求体协议的真实 HTTP 矩阵。"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.enums.user import UserRole
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.experience_option import ExperienceOption
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_user(index: int, *, role: UserRole = UserRole.USER) -> tuple[User, str]:
    user = await User.create(
        username=f"order-matrix-{index}",
        password="hashed-password",
        nickname=f"矩阵用户{index}",
        phone=f"139{index:08d}",
        role=role,
    )
    return user, create_access_token(user.id, str(uuid.uuid4()))


async def _create_catalog() -> tuple[Product, ExperienceOption]:
    product = await Product.create(
        name="查询矩阵体验",
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=90,
        participants=2,
        day_type=DayType.WEEKDAY,
        price=Decimal("10.00"),
    )
    return product, option


async def _seed_order(
    *,
    user: User,
    product: Product,
    option: ExperienceOption,
    index: int,
    status: OrderStatus,
    created_at: datetime | None = None,
) -> Order:
    order = await Order.create(
        order_no=f"OD{index:026d}",
        user=user,
        total_amount=Decimal("10.00"),
        status=status,
    )
    await OrderItem.create(
        order=order,
        product=product,
        experience_option=option,
        option_duration_minutes=option.duration,
        option_participants=option.participants,
        option_day_type=option.day_type,
        product_name=product.name,
        product_price=option.price,
        quantity=1,
        subtotal=Decimal("10.00"),
    )
    if created_at is not None:
        await Order.filter(id=order.id).update(
            created_at=created_at,
            updated_at=created_at,
        )
        await order.refresh_from_db()
    return order


async def test_user_and_admin_lists_apply_visibility_filters_and_pagination(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    owner = await User.get(id=auth_user["user"]["id"])
    other, _ = await _create_user(1)
    _, admin_token = await _create_user(2, role=UserRole.ADMIN)
    product, option = await _create_catalog()
    anchor = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    owner_pending = await _seed_order(
        user=owner,
        product=product,
        option=option,
        index=1,
        status=OrderStatus.PENDING,
        created_at=anchor - timedelta(hours=3),
    )
    owner_paid = await _seed_order(
        user=owner,
        product=product,
        option=option,
        index=2,
        status=OrderStatus.PAID,
        created_at=anchor - timedelta(hours=2),
    )
    other_paid = await _seed_order(
        user=other,
        product=product,
        option=option,
        index=3,
        status=OrderStatus.PAID,
        created_at=anchor - timedelta(hours=1),
    )
    owner_cancelled = await _seed_order(
        user=owner,
        product=product,
        option=option,
        index=4,
        status=OrderStatus.CANCELLED,
        created_at=anchor,
    )

    user_page = await client.get(
        "/api/v1/orders",
        params={"status": "paid", "page": 1, "page_size": 1},
        headers=_headers(auth_user["token"]),
    )
    assert user_page.status_code == 200
    assert user_page.json()["data"] == {
        "items": [
            {
                "id": owner_paid.id,
                "order_no": owner_paid.order_no,
                "status": {"value": "paid", "label": "已支付"},
                "total_amount": "10.00",
                "item_count": 1,
                "created_at": owner_paid.created_at.isoformat().replace("+00:00", "Z"),
                "updated_at": owner_paid.updated_at.isoformat().replace("+00:00", "Z"),
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 1,
        "pages": 1,
    }

    admin_page = await client.get(
        "/api/v1/admin/orders",
        params={"page": 1, "page_size": 2},
        headers=_headers(admin_token),
    )
    assert admin_page.status_code == 200
    page_data = admin_page.json()["data"]
    assert page_data["total"] == 4
    assert page_data["pages"] == 2
    assert [item["id"] for item in page_data["items"]] == [
        owner_cancelled.id,
        other_paid.id,
    ]

    combined = await client.get(
        "/api/v1/admin/orders",
        params={
            "status": "paid",
            "order_no": owner_paid.order_no,
            "user_id": owner.id,
            "created_from": (anchor - timedelta(hours=2, minutes=30)).isoformat(),
            "created_to": (anchor - timedelta(hours=1, minutes=30)).isoformat(),
        },
        headers=_headers(admin_token),
    )
    assert combined.status_code == 200, combined.text
    combined_data = combined.json()["data"]
    assert combined_data["total"] == 1
    assert combined_data["items"][0]["id"] == owner_paid.id
    assert combined_data["items"][0]["user_id"] == owner.id
    assert combined_data["items"][0]["user_nickname"] == "Alice"
    assert owner_pending.id not in {
        item["id"] for item in admin_page.json()["data"]["items"]
    }


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 101},
        {"status": "unknown"},
        {"order_no": "invalid"},
        {"user_id": "true"},
        {"created_from": "2026-08-13T08:00:00+08:00"},
        {
            "created_from": "2026-08-13T08:00:00Z",
            "created_to": "2026-08-13T08:00:00Z",
        },
        {
            "created_from": "2026-08-13T09:00:00Z",
            "created_to": "2026-08-13T08:00:00Z",
        },
        {"unexpected": "field"},
    ],
)
async def test_admin_list_rejects_invalid_filter_boundaries(
    client: AsyncClient,
    params: dict[str, object],
) -> None:
    _, admin_token = await _create_user(10, role=UserRole.ADMIN)

    response = await client.get(
        "/api/v1/admin/orders",
        params=params,
        headers=_headers(admin_token),
    )

    assert response.status_code == 422
    assert response.json()["code"] == 422
    assert response.json()["message"] == "Validation failed"


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/api/v1/orders", {"items": []}),
        ("GET", "/api/v1/orders", None),
        ("GET", "/api/v1/orders/1", None),
        ("PATCH", "/api/v1/orders/1/cancel", None),
        ("GET", "/api/v1/admin/orders", None),
        ("GET", "/api/v1/admin/orders/1", None),
        ("GET", "/api/v1/admin/orders/1/audit-logs", None),
        ("PATCH", "/api/v1/admin/orders/1/paid", None),
        ("PATCH", "/api/v1/admin/orders/1/complete", None),
    ],
)
async def test_all_order_routes_require_authentication(
    client: AsyncClient,
    method: str,
    path: str,
    json_body: dict | None,
) -> None:
    response = await client.request(method, path, json=json_body)

    assert response.status_code == 401
    assert response.json() == {
        "code": 401,
        "message": "Authentication required",
        "data": None,
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/admin/orders"),
        ("GET", "/api/v1/admin/orders/1"),
        ("GET", "/api/v1/admin/orders/1/audit-logs"),
        ("PATCH", "/api/v1/admin/orders/1/paid"),
        ("PATCH", "/api/v1/admin/orders/1/complete"),
    ],
)
async def test_all_admin_order_routes_reject_normal_users(
    client: AsyncClient,
    auth_user: dict,
    method: str,
    path: str,
) -> None:
    response = await client.request(
        method,
        path,
        headers=_headers(auth_user["token"]),
    )

    assert response.status_code == 403
    assert response.json()["code"] == 403


async def test_invalid_token_uses_existing_authentication_error_contract(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/v1/orders",
        headers=_headers("not-a-jwt"),
    )

    assert response.status_code == 400
    assert response.json()["code"] == 1006


@pytest.mark.parametrize(
    ("method", "path_kind"),
    [
        ("GET", "user_detail"),
        ("PATCH", "cancel"),
        ("GET", "admin_detail"),
        ("GET", "audit"),
        ("PATCH", "paid"),
        ("PATCH", "complete"),
    ],
)
async def test_missing_order_is_uniformly_hidden_as_404(
    client: AsyncClient,
    auth_user: dict,
    method: str,
    path_kind: str,
) -> None:
    missing_id = 99999
    if path_kind == "user_detail":
        path = f"/api/v1/orders/{missing_id}"
        token = auth_user["token"]
    elif path_kind == "cancel":
        path = f"/api/v1/orders/{missing_id}/cancel"
        token = auth_user["token"]
    else:
        _, token = await _create_user(15, role=UserRole.ADMIN)
        suffix = {
            "admin_detail": "",
            "audit": "/audit-logs",
            "paid": "/paid",
            "complete": "/complete",
        }[path_kind]
        path = f"/api/v1/admin/orders/{missing_id}{suffix}"

    response = await client.request(method, path, headers=_headers(token))

    assert response.status_code == 404
    assert response.json() == {
        "code": 40411,
        "message": "Order not found",
        "data": None,
    }


@pytest.mark.parametrize(
    ("operation", "current_status", "required_status"),
    [
        ("cancel", OrderStatus.PAID, OrderStatus.PENDING),
        ("cancel", OrderStatus.CANCELLED, OrderStatus.PENDING),
        ("cancel", OrderStatus.COMPLETED, OrderStatus.PENDING),
        ("mark_paid", OrderStatus.PAID, OrderStatus.PENDING),
        ("mark_paid", OrderStatus.CANCELLED, OrderStatus.PENDING),
        ("mark_paid", OrderStatus.COMPLETED, OrderStatus.PENDING),
        ("complete", OrderStatus.PENDING, OrderStatus.PAID),
        ("complete", OrderStatus.CANCELLED, OrderStatus.PAID),
        ("complete", OrderStatus.COMPLETED, OrderStatus.PAID),
    ],
)
async def test_every_illegal_status_precondition_returns_stable_conflict(
    client: AsyncClient,
    auth_user: dict,
    operation: str,
    current_status: OrderStatus,
    required_status: OrderStatus,
) -> None:
    owner = await User.get(id=auth_user["user"]["id"])
    product, option = await _create_catalog()
    order = await _seed_order(
        user=owner,
        product=product,
        option=option,
        index=100 + current_status.value,
        status=current_status,
    )
    if operation == "cancel":
        path = f"/api/v1/orders/{order.id}/cancel"
        token = auth_user["token"]
    else:
        _, token = await _create_user(20, role=UserRole.ADMIN)
        suffix = "paid" if operation == "mark_paid" else "complete"
        path = f"/api/v1/admin/orders/{order.id}/{suffix}"

    response = await client.patch(path, headers=_headers(token))

    assert response.status_code == 409
    assert response.json() == {
        "code": 40921,
        "message": "Order status does not allow this operation",
        "data": {
            "operation": operation,
            "current_status": {
                OrderStatus.PENDING: "pending",
                OrderStatus.PAID: "paid",
                OrderStatus.CANCELLED: "cancelled",
                OrderStatus.COMPLETED: "completed",
            }[current_status],
            "required_status": {
                OrderStatus.PENDING: "pending",
                OrderStatus.PAID: "paid",
            }[required_status],
        },
    }
    await order.refresh_from_db()
    assert order.status == current_status
    assert await AuditLog.filter(target_type="order", target_id=order.id).count() == 0


@pytest.mark.parametrize(
    ("path_kind", "status"),
    [
        ("cancel", OrderStatus.PENDING),
        ("paid", OrderStatus.PENDING),
        ("complete", OrderStatus.PAID),
    ],
)
@pytest.mark.parametrize(
    "request_body",
    [
        b"{}",
        b"null",
        b'{"status":"cancelled"}',
    ],
)
async def test_status_patch_rejects_any_request_body_without_mutation(
    client: AsyncClient,
    auth_user: dict,
    path_kind: str,
    status: OrderStatus,
    request_body: bytes,
) -> None:
    owner = await User.get(id=auth_user["user"]["id"])
    product, option = await _create_catalog()
    order = await _seed_order(
        user=owner,
        product=product,
        option=option,
        index=200,
        status=status,
    )
    if path_kind == "cancel":
        path = f"/api/v1/orders/{order.id}/cancel"
        token = auth_user["token"]
    else:
        _, token = await _create_user(30, role=UserRole.ADMIN)
        path = f"/api/v1/admin/orders/{order.id}/{path_kind}"

    response = await client.patch(
        path,
        content=request_body,
        headers={**_headers(token), "Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == 422
    await order.refresh_from_db()
    assert order.status == status
    assert await AuditLog.filter(target_type="order", target_id=order.id).count() == 0


async def test_audit_pagination_preserves_reverse_chronological_order(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    owner = await User.get(id=auth_user["user"]["id"])
    _, admin_token = await _create_user(40, role=UserRole.ADMIN)
    product, option = await _create_catalog()
    order = await _seed_order(
        user=owner,
        product=product,
        option=option,
        index=300,
        status=OrderStatus.PENDING,
    )
    await AuditLog.create(
        operator_id=owner.id,
        action="CREATE_ORDER",
        target_type="order",
        target_id=order.id,
        description='{"status":"pending"}',
        ip_address="192.0.2.10",
    )
    await AuditLog.create(
        operator_id=owner.id,
        action="CANCEL_ORDER",
        target_type="order",
        target_id=order.id,
        description='{"before_status":"pending","after_status":"cancelled"}',
        ip_address="192.0.2.11",
    )

    first_page = await client.get(
        f"/api/v1/admin/orders/{order.id}/audit-logs",
        params={"page": 1, "page_size": 1},
        headers=_headers(admin_token),
    )
    second_page = await client.get(
        f"/api/v1/admin/orders/{order.id}/audit-logs",
        params={"page": 2, "page_size": 1},
        headers=_headers(admin_token),
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json()["data"]["total"] == 2
    assert first_page.json()["data"]["pages"] == 2
    assert first_page.json()["data"]["items"][0]["action"] == "CANCEL_ORDER"
    assert second_page.json()["data"]["items"][0]["action"] == "CREATE_ORDER"
