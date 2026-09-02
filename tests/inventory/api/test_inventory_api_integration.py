"""Inventory 管理 API 与真实 SQLite Service/Repository 的端到端测试。"""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.api.deps import get_current_admin
from app.common.enums.product import ProductType
from app.main import app
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User


@pytest.fixture
async def inventory_admin() -> User:
    admin = await User.create(
        username="inventory-http-admin",
        password="hashed-password",
        nickname="库存店长",
        phone="13800330001",
    )
    app.dependency_overrides[get_current_admin] = lambda: admin
    yield admin
    app.dependency_overrides.clear()


async def test_adjust_replay_and_query_flow_uses_real_boundaries(
    client: AsyncClient,
    inventory_admin: User,
) -> None:
    product = await Product.create(
        name="Inventory HTTP Kit",
        product_type=ProductType.KIT,
    )
    kit = await ProductKit.create(
        product=product,
        price=Decimal("99.00"),
        stock=0,
    )
    headers = {"Idempotency-Key": "inventory-http-adjust-1"}
    payload = {"change": 5, "reason": "HTTP 采购入库"}

    first = await client.post(
        f"/api/v1/admin/products/kit/{product.id}/inventory-adjustments",
        headers=headers,
        json=payload,
    )
    replay = await client.post(
        f"/api/v1/admin/products/kit/{product.id}/inventory-adjustments",
        headers=headers,
        json=payload,
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["data"] == first.json()["data"]
    data = first.json()["data"]
    assert data["product_id"] == product.id
    assert data["stock"] == 5
    assert data["transaction"]["operator_id"] == inventory_admin.id
    assert data["transaction"]["operator_nickname"] == "库存店长"
    assert not (
        {"idempotency_key", "updated_at", "username", "phone", "password"}
        & data["transaction"].keys()
    )

    await kit.refresh_from_db()
    assert kit.stock == 5
    assert await InventoryTransaction.filter(product_id=product.id).count() == 1
    assert await AuditLog.filter(
        target_id=product.id,
        action="ADJUST_INVENTORY",
    ).count() == 1

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
    assert product_page.json()["data"]["items"] == [data["transaction"]]
    assert global_page.json()["data"]["items"] == [data["transaction"]]


async def test_kit_creation_starts_at_zero_and_legacy_writes_are_rejected(
    client: AsyncClient,
    inventory_admin: User,
) -> None:
    created = await client.post(
        "/api/v1/admin/products/kit",
        json={"name": "Zero Opening Kit", "price": "88.00"},
    )

    assert created.status_code == 201
    product_id = created.json()["data"]["id"]
    kit = await ProductKit.get(product_id=product_id)
    assert kit.stock == 0
    assert not await InventoryTransaction.filter(product_id=product_id).exists()

    forged_create = await client.post(
        "/api/v1/admin/products/kit",
        json={"name": "Forged Opening Kit", "price": "88.00", "stock": 3},
    )
    legacy_patch = await client.patch(
        f"/api/v1/admin/products/kit/{product_id}/stock",
        json={"stock": 3},
    )

    assert forged_create.status_code == 422
    assert legacy_patch.status_code == 404
    await kit.refresh_from_db()
    assert kit.stock == 0
