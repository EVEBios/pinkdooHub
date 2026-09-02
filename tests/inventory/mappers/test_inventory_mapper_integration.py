"""Inventory Mapper 与真实 Repository 数据的零 SQL、零修改集成测试。"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from tortoise import connections

from app.api.mappers.inventory import map_inventory_transaction_page
from app.common.enums.inventory import InventorySourceType, InventoryTransactionType
from app.common.enums.product import ProductType
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.repositories.inventory_repo import (
    InventoryRepository,
    InventoryTransactionCreateData,
)


async def test_repository_page_maps_without_sql_or_orm_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = await User.create(
        username="inventory-mapper-admin",
        password="hashed-password",
        nickname="映射管理员",
        phone="13800310001",
    )
    product = await Product.create(
        name="Mapper Kit",
        product_type=ProductType.KIT,
    )
    await ProductKit.create(
        product=product,
        price=Decimal("88.00"),
        stock=12,
    )
    transaction = await InventoryRepository().create_transaction(
        data=InventoryTransactionCreateData(
            product_id=product.id,
            transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
            change_quantity=2,
            before_quantity=10,
            after_quantity=12,
            source_type=InventorySourceType.ADMIN,
            source_id=None,
            operator_id=operator.id,
            reason="真实 Mapper 调整",
            idempotency_key="inventory:mapper:admin:1",
        )
    )
    created_at = datetime(2026, 8, 14, 8, tzinfo=timezone.utc)
    transaction.created_at = created_at
    await transaction.save(update_fields=["created_at"])
    page = await InventoryRepository().list_transactions(
        page=1,
        page_size=20,
        product_id=product.id,
    )
    loaded = page.items[0]
    before = {
        "transaction": dict(vars(loaded)),
        "operator": dict(vars(loaded.operator)),
    }

    connection = connections.get("default")

    def fail_on_query(*args: object, **kwargs: object) -> None:
        raise AssertionError("Inventory Mapper must not execute SQL")

    monkeypatch.setattr(connection, "execute_query", fail_on_query)

    data = map_inventory_transaction_page(page).model_dump(mode="json")

    assert data == {
        "items": [
            {
                "id": loaded.id,
                "product_id": product.id,
                "transaction_type": "admin_adjustment",
                "change_quantity": 2,
                "before_quantity": 10,
                "after_quantity": 12,
                "reason": "真实 Mapper 调整",
                "source_type": "admin",
                "source_id": None,
                "source_order_no": None,
                "operator_id": operator.id,
                "operator_nickname": "映射管理员",
                "created_at": "2026-08-14T08:00:00Z",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
        "pages": 1,
    }
    assert dict(vars(loaded)) == before["transaction"]
    assert dict(vars(loaded.operator)) == before["operator"]
