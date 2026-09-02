"""真实 MySQL 上的 Inventory FastAPI 并发幂等与查询 smoke。"""

import asyncio
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.api.deps import get_current_admin
from app.common.enums.product import ProductStatus, ProductType
from app.main import app
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User


pytestmark = pytest.mark.mysql


@pytest.fixture
async def mysql_http_admin() -> User:
    admin = await User.create(
        username="mysql-http-admin",
        password="hashed-password",
        nickname="MySQL 店长",
        phone="13844600001",
    )
    app.dependency_overrides[get_current_admin] = lambda: admin
    yield admin
    app.dependency_overrides.clear()


async def test_concurrent_http_replay_and_queries_cross_mysql_boundary(
    client: AsyncClient,
    mysql_http_admin: User,
) -> None:
    product = await Product.create(
        name="MySQL HTTP Kit",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    kit = await ProductKit.create(
        product=product,
        price=Decimal("99.00"),
        stock=0,
    )
    path = (
        f"/api/v1/admin/products/kit/{product.id}/inventory-adjustments"
    )
    headers = {"Idempotency-Key": "mysql-http-concurrent-replay"}
    payload = {"change": 4, "reason": "真实 MySQL HTTP 入库"}

    first, second = await asyncio.gather(
        client.post(path, headers=headers, json=payload),
        client.post(path, headers=headers, json=payload),
    )

    assert {first.status_code, second.status_code} == {200, 201}
    assert first.json()["data"] == second.json()["data"]
    response_data = first.json()["data"]
    assert response_data["stock"] == 4
    assert response_data["transaction"]["operator_id"] == mysql_http_admin.id
    assert response_data["transaction"]["operator_nickname"] == "MySQL 店长"
    assert "idempotency_key" not in first.text

    await kit.refresh_from_db()
    assert kit.stock == 4
    assert await InventoryTransaction.filter(product_id=product.id).count() == 1
    assert await AuditLog.filter(action="ADJUST_INVENTORY").count() == 1

    product_page = await client.get(
        f"/api/v1/admin/products/kit/{product.id}/inventory-transactions",
        params={"type": "admin_adjustment"},
    )
    global_page = await client.get(
        "/api/v1/admin/inventory-transactions",
        params={"product_id": product.id, "source_type": "admin"},
    )

    assert product_page.status_code == 200
    assert global_page.status_code == 200
    assert product_page.json()["data"]["items"] == [
        response_data["transaction"]
    ]
    assert global_page.json()["data"]["items"] == [
        response_data["transaction"]
    ]
