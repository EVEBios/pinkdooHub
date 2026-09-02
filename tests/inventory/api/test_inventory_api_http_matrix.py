"""Phase 4.3.11 Inventory 三端点完整 HTTP 权限、错误与边界矩阵。"""

from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.api.deps import get_current_admin
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.enums.product import ProductType
from app.main import app
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User


ADJUSTMENT_PATH = "/api/v1/admin/products/kit/1/inventory-adjustments"
PRODUCT_QUERY_PATH = (
    "/api/v1/admin/products/kit/1/inventory-transactions"
)
GLOBAL_QUERY_PATH = "/api/v1/admin/inventory-transactions"


@pytest.fixture
async def matrix_admin() -> User:
    admin = await User.create(
        username="inventory-matrix-admin",
        password="hashed-password",
        nickname="矩阵店长",
        phone="13800550001",
    )
    app.dependency_overrides[get_current_admin] = lambda: admin
    yield admin
    app.dependency_overrides.clear()


async def _create_kit(
    name: str,
    *,
    stock: int = 0,
    is_deleted: bool = False,
) -> ProductKit:
    product = await Product.create(
        name=name,
        product_type=ProductType.KIT,
        is_deleted=is_deleted,
    )
    return await ProductKit.create(
        product=product,
        price=Decimal("88.00"),
        stock=stock,
    )


async def _request_inventory_path(
    client: AsyncClient,
    path: str,
    *,
    authorization: str | None = None,
) -> object:
    headers: dict[str, str] = {}
    if authorization is not None:
        headers["Authorization"] = authorization
    if path == ADJUSTMENT_PATH:
        headers["Idempotency-Key"] = "matrix-auth-key"
        return await client.post(
            path,
            headers=headers,
            json={"change": 1, "reason": "权限矩阵"},
        )
    return await client.get(path, headers=headers)


@pytest.mark.parametrize(
    "path",
    [ADJUSTMENT_PATH, PRODUCT_QUERY_PATH, GLOBAL_QUERY_PATH],
)
async def test_every_inventory_endpoint_requires_bearer_authentication(
    client: AsyncClient,
    path: str,
) -> None:
    response = await _request_inventory_path(client, path)

    assert response.status_code == 401
    assert response.json() == {
        "code": 401,
        "message": "Authentication required",
        "data": None,
    }


@pytest.mark.parametrize(
    "path",
    [ADJUSTMENT_PATH, PRODUCT_QUERY_PATH, GLOBAL_QUERY_PATH],
)
async def test_every_inventory_endpoint_rejects_invalid_tokens(
    client: AsyncClient,
    path: str,
) -> None:
    response = await _request_inventory_path(
        client,
        path,
        authorization="Bearer invalid-token",
    )

    assert response.status_code == 400
    assert response.json()["code"] == 1006


@pytest.mark.parametrize(
    "path",
    [ADJUSTMENT_PATH, PRODUCT_QUERY_PATH, GLOBAL_QUERY_PATH],
)
async def test_every_inventory_endpoint_rejects_normal_users(
    client: AsyncClient,
    auth_user: dict,
    path: str,
) -> None:
    response = await _request_inventory_path(
        client,
        path,
        authorization=f"Bearer {auth_user['token']}",
    )

    assert response.status_code == 403
    assert response.json()["code"] == 403
    assert not await InventoryTransaction.all().exists()


@pytest.mark.parametrize(
    ("resource", "status_code", "error_code"),
    [
        ("missing", 404, 40401),
        ("deleted", 409, 40903),
        ("experience", 400, 40001),
        ("missing_kit", 404, 40404),
    ],
)
async def test_adjustment_and_product_query_share_resource_error_priority(
    client: AsyncClient,
    matrix_admin: User,
    resource: str,
    status_code: int,
    error_code: int,
) -> None:
    if resource == "missing":
        product_id = 999_999
    elif resource == "deleted":
        product_id = (await _create_kit("已删除 Kit", is_deleted=True)).product_id
    elif resource == "experience":
        product_id = (
            await Product.create(
                name="错误类型 Experience",
                product_type=ProductType.EXPERIENCE,
            )
        ).id
    else:
        product_id = (
            await Product.create(
                name="缺少扩展 Kit",
                product_type=ProductType.KIT,
            )
        ).id

    adjustment = await client.post(
        f"/api/v1/admin/products/kit/{product_id}/inventory-adjustments",
        headers={"Idempotency-Key": f"resource-{resource}"},
        json={"change": 1, "reason": "资源优先级"},
    )
    product_query = await client.get(
        f"/api/v1/admin/products/kit/{product_id}/inventory-transactions"
    )

    for response in (adjustment, product_query):
        assert response.status_code == status_code
        assert response.json()["code"] == error_code
    assert not await InventoryTransaction.all().exists()
    assert not await AuditLog.filter(action="ADJUST_INVENTORY").exists()


async def test_adjustment_http_balance_edges_replay_and_conflict(
    client: AsyncClient,
    matrix_admin: User,
) -> None:
    kit = await _create_kit("余额边界 Kit", stock=0)
    path = (
        f"/api/v1/admin/products/kit/{kit.product_id}/inventory-adjustments"
    )

    underflow = await client.post(
        path,
        headers={"Idempotency-Key": "matrix-underflow"},
        json={"change": -1, "reason": "越过下界"},
    )
    first = await client.post(
        path,
        headers={"Idempotency-Key": "matrix-full-stock"},
        json={"change": 999_999, "reason": "  填满库存  "},
    )
    replay = await client.post(
        path,
        headers={"Idempotency-Key": "  matrix-full-stock  "},
        json={"change": 999_999, "reason": "填满库存"},
    )
    conflict = await client.post(
        path,
        headers={"Idempotency-Key": "matrix-full-stock"},
        json={"change": 999_999, "reason": "不同原因"},
    )
    overflow = await client.post(
        path,
        headers={"Idempotency-Key": "matrix-overflow"},
        json={"change": 1, "reason": "越过上界"},
    )

    assert underflow.status_code == 409
    assert underflow.json() == {
        "code": 40932,
        "message": "Inventory balance exceeds the allowed range",
        "data": {
            "product_id": kit.product_id,
            "before_quantity": 0,
            "change_quantity": -1,
            "minimum": 0,
            "maximum": 999_999,
        },
    }
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["data"] == first.json()["data"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 40933
    assert overflow.status_code == 409
    assert overflow.json()["code"] == 40932
    assert overflow.json()["data"]["before_quantity"] == 999_999
    await kit.refresh_from_db()
    assert kit.stock == 999_999
    assert await InventoryTransaction.all().count() == 1
    assert await AuditLog.filter(action="ADJUST_INVENTORY").count() == 1


@pytest.mark.parametrize(
    ("headers", "payload"),
    [
        ({}, {"change": 1, "reason": "补货"}),
        ({"Idempotency-Key": "   "}, {"change": 1, "reason": "补货"}),
        ({"Idempotency-Key": "x" * 129}, {"change": 1, "reason": "补货"}),
        ({"Idempotency-Key": "key"}, {"change": True, "reason": "补货"}),
        ({"Idempotency-Key": "key"}, {"change": "1", "reason": "补货"}),
        ({"Idempotency-Key": "key"}, {"change": 1.0, "reason": "补货"}),
        ({"Idempotency-Key": "key"}, {"change": 0, "reason": "补货"}),
        ({"Idempotency-Key": "key"}, {"change": -1_000_000, "reason": "补货"}),
        ({"Idempotency-Key": "key"}, {"change": 1_000_000, "reason": "补货"}),
        ({"Idempotency-Key": "key"}, {"change": 1, "reason": "   "}),
        ({"Idempotency-Key": "key"}, {"change": 1, "reason": "x" * 257}),
        ({"Idempotency-Key": "key"}, {"change": 1}),
        (
            {"Idempotency-Key": "key"},
            {"change": 1, "reason": "补货", "stock": 10},
        ),
    ],
)
async def test_adjustment_http_rejects_every_untrusted_shape(
    client: AsyncClient,
    matrix_admin: User,
    headers: dict[str, str],
    payload: dict[str, object],
) -> None:
    kit = await _create_kit("严格调整 Kit")

    response = await client.post(
        f"/api/v1/admin/products/kit/{kit.product_id}/inventory-adjustments",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == 422
    assert not await InventoryTransaction.all().exists()
    assert not await AuditLog.filter(action="ADJUST_INVENTORY").exists()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/products/kit/0/inventory-transactions",
        "/api/v1/admin/products/kit/1/inventory-transactions?page=0",
        "/api/v1/admin/products/kit/1/inventory-transactions?page_size=101",
        "/api/v1/admin/products/kit/1/inventory-transactions?type=unknown",
        "/api/v1/admin/products/kit/1/inventory-transactions?source_id=1",
        (
            "/api/v1/admin/products/kit/1/inventory-transactions"
            "?source_type=admin&source_id=1"
        ),
        (
            "/api/v1/admin/products/kit/1/inventory-transactions"
            "?created_from=2026-08-14T08:00:00%2B08:00"
        ),
        (
            "/api/v1/admin/products/kit/1/inventory-transactions"
            "?created_from=2026-08-14T10:00:00Z"
            "&created_to=2026-08-14T10:00:00Z"
        ),
        "/api/v1/admin/products/kit/1/inventory-transactions?unknown=x",
        (
            "/api/v1/admin/products/kit/1/inventory-transactions"
            "?product_id=1"
        ),
        "/api/v1/admin/inventory-transactions?product_id=0",
        "/api/v1/admin/inventory-transactions?product_id=1.0",
        "/api/v1/admin/inventory-transactions?source_type=migration&source_id=1",
    ],
)
async def test_query_http_rejects_invalid_filters_before_database_use(
    client: AsyncClient,
    matrix_admin: User,
    path: str,
) -> None:
    response = await client.get(path)

    assert response.status_code == 422
    assert response.json()["code"] == 422


async def test_query_http_filters_pages_order_source_and_privacy(
    client: AsyncClient,
    matrix_admin: User,
) -> None:
    first_kit = await _create_kit("查询矩阵 Kit A")
    second_kit = await _create_kit("查询矩阵 Kit B")
    for key, product_id, change, reason in (
        ("matrix-query-a1", first_kit.product_id, 5, "A 入库"),
        ("matrix-query-a2", first_kit.product_id, -1, "A 盘亏"),
        ("matrix-query-b1", second_kit.product_id, 2, "B 入库"),
    ):
        response = await client.post(
            f"/api/v1/admin/products/kit/{product_id}/inventory-adjustments",
            headers={"Idempotency-Key": key},
            json={"change": change, "reason": reason},
        )
        assert response.status_code == 201

    order = await Order.create(
        order_no="OD00000000000000000000000001",
        user=matrix_admin,
        total_amount=Decimal("88.00"),
        remark="must-not-leak",
    )
    order_transaction = await InventoryTransaction.create(
        product_id=first_kit.product_id,
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        change_quantity=-1,
        before_quantity=4,
        after_quantity=3,
        source_type=InventorySourceType.ORDER,
        source_id=order.id,
        operator_id=matrix_admin.id,
        reason="Order stock deduction",
        idempotency_key="inventory:matrix:order-deduction",
    )

    product_page = await client.get(
        f"/api/v1/admin/products/kit/{first_kit.product_id}"
        "/inventory-transactions",
        params={"page_size": 2},
    )
    second_product_page = await client.get(
        f"/api/v1/admin/products/kit/{first_kit.product_id}"
        "/inventory-transactions",
        params={"page": 2, "page_size": 2},
    )
    order_page = await client.get(
        "/api/v1/admin/inventory-transactions",
        params={
            "product_id": first_kit.product_id,
            "type": "order_deduction",
            "source_type": "order",
            "source_id": order.id,
        },
    )
    unknown_product_page = await client.get(
        "/api/v1/admin/inventory-transactions",
        params={"product_id": 999_999},
    )
    lower = (order_transaction.created_at - timedelta(seconds=1)).isoformat()
    upper = (order_transaction.created_at + timedelta(seconds=1)).isoformat()
    time_page = await client.get(
        "/api/v1/admin/inventory-transactions",
        params={"created_from": lower, "created_to": upper},
    )

    assert product_page.status_code == 200
    assert second_product_page.status_code == 200
    assert product_page.json()["data"] | {"items": []} == {
        "items": [],
        "total": 3,
        "page": 1,
        "page_size": 2,
        "pages": 2,
    }
    first_ids = [item["id"] for item in product_page.json()["data"]["items"]]
    second_ids = [
        item["id"] for item in second_product_page.json()["data"]["items"]
    ]
    assert first_ids + second_ids == sorted(
        first_ids + second_ids,
        reverse=True,
    )
    assert order_page.status_code == 200
    assert order_page.json()["data"]["items"] == [
        {
            "id": order_transaction.id,
            "product_id": first_kit.product_id,
            "transaction_type": "order_deduction",
            "change_quantity": -1,
            "before_quantity": 4,
            "after_quantity": 3,
            "reason": "Order stock deduction",
            "source_type": "order",
            "source_id": order.id,
            "source_order_no": order.order_no,
            "operator_id": matrix_admin.id,
            "operator_nickname": matrix_admin.nickname,
            "created_at": order_transaction.created_at.isoformat().replace(
                "+00:00", "Z"
            ),
        }
    ]
    assert unknown_product_page.status_code == 200
    assert unknown_product_page.json()["data"]["items"] == []
    assert unknown_product_page.json()["data"]["total"] == 0
    assert time_page.status_code == 200
    assert any(
        item["id"] == order_transaction.id
        for item in time_page.json()["data"]["items"]
    )
    assert "idempotency_key" not in order_page.text
    assert "must-not-leak" not in order_page.text
    assert "inventory-matrix-admin" not in order_page.text
    assert matrix_admin.phone not in order_page.text
