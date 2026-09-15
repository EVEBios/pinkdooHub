"""InventoryService 查询与真实 SQLite Repository 的集成测试。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.common.enums.inventory import InventorySourceType, InventoryTransactionType
from app.common.enums.product import ProductType
from app.models.inventory_transaction import InventoryTransaction
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import (
    InventoryRepository,
    InventoryTransactionCreateData,
)
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.inventory_service import InventoryService


def _service() -> InventoryService:
    return InventoryService(
        inventory_repository=InventoryRepository(),
        product_repository=ProductRepository(),
        audit_log_service=AuditLogService(AuditLogRepository()),
    )


async def _create_admin_transaction(
    *,
    product: Product,
    operator: User,
    created_at: datetime,
) -> InventoryTransaction:
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
            reason="Service 查询集成调整",
            idempotency_key=f"inventory:service:query:{product.id}",
        )
    )
    await InventoryTransaction.filter(id=transaction.id).update(
        created_at=created_at
    )
    return transaction


async def test_product_query_returns_only_validated_kit_transactions() -> None:
    operator = await User.create(
        username="inventory-query-service-admin",
        password="hashed-password",
        nickname="查询管理员",
        phone="13800320001",
    )
    kit_product = await Product.create(
        name="查询目标 Kit",
        product_type=ProductType.KIT,
    )
    await ProductKit.create(
        product=kit_product,
        price=Decimal("99.00"),
        stock=12,
    )
    other_product = await Product.create(
        name="查询排除 Kit",
        product_type=ProductType.KIT,
    )
    await ProductKit.create(
        product=other_product,
        price=Decimal("88.00"),
        stock=12,
    )
    start = datetime(2026, 8, 14, 9, tzinfo=timezone.utc)
    expected = await _create_admin_transaction(
        product=kit_product,
        operator=operator,
        created_at=start,
    )
    await _create_admin_transaction(
        product=other_product,
        operator=operator,
        created_at=start,
    )

    result = await _service().list_product_transactions(
        kit_product.id,
        page=1,
        page_size=20,
        transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
        created_from=start,
        created_to=start + timedelta(minutes=1),
    )

    assert [item.id for item in result.items] == [expected.id]
    assert result.items[0].operator.nickname == "查询管理员"
    assert result.items[0].source_order_no is None
    assert result.total == 1


async def test_global_query_with_unknown_product_filter_returns_empty_page() -> None:
    result = await _service().list_transactions(
        page=4,
        page_size=20,
        product_id=999_999,
    )

    assert result.items == []
    assert result.total == 0
    assert result.page == 4
    assert result.page_size == 20
    assert result.pages == 0
