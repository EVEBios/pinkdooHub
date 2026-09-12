"""商品颜色 10g 单位库存的调整、幂等与类型边界集成测试。"""

from decimal import Decimal

import pytest

from app.common.enums.product import KitKind, ProductType
from app.common.exceptions import InventoryKitKindMismatch, ProductKitColorNotFound
from app.models.audit_log import AuditLog
from app.models.bead_color import BeadColor
from app.models.inventory_transaction import InventoryTransaction
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.product_kit_color import ProductKitColor
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.inventory_service import InventoryService


def _service() -> InventoryService:
    return InventoryService(
        InventoryRepository(),
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )


async def _operator() -> User:
    return await User.create(
        username="color-inventory-admin",
        password="hashed-password",
        nickname="颜色库存管理员",
    )


async def _color_kit(slot_no: int) -> tuple[Product, ProductKitColor]:
    product = await Product.create(
        name=f"颜色库存商品 {slot_no}",
        product_type=ProductType.KIT,
    )
    await ProductKit.create(
        product=product,
        price=Decimal("5.00"),
        stock=None,
        kit_kind=KitKind.COLOR_SELECTABLE,
        sale_unit_grams=10,
    )
    bead_color = await BeadColor.create(
        slot_no=slot_no,
        sort=slot_no,
        is_active=False,
    )
    kit_color = await ProductKitColor.create(
        product=product,
        bead_color=bead_color,
        is_enabled=False,
        stock_units=0,
    )
    return product, kit_color


async def test_color_adjustment_updates_authority_and_replays_idempotently() -> None:
    operator = await _operator()
    product, kit_color = await _color_kit(1)
    service = _service()

    first = await service.adjust_color_stock(
        product.id,
        kit_color.id,
        change=5,
        reason="预先入库",
        operator_id=operator.id,
        ip_address="127.0.0.1",
        idempotency_key="color-adjustment-1",
    )
    replay = await service.adjust_color_stock(
        product.id,
        kit_color.id,
        change=5,
        reason="预先入库",
        operator_id=operator.id,
        ip_address="127.0.0.1",
        idempotency_key="color-adjustment-1",
    )

    await kit_color.refresh_from_db()
    transaction = await InventoryTransaction.get(id=first.transaction.id)
    assert kit_color.stock_units == 5
    assert first.stock_units == 5
    assert first.is_replay is False
    assert replay.is_replay is True
    assert replay.transaction.id == first.transaction.id
    assert transaction.product_id == product.id
    assert transaction.kit_color_id == kit_color.id
    assert transaction.before_quantity == 0
    assert transaction.change_quantity == 5
    assert transaction.after_quantity == 5
    assert await InventoryTransaction.all().count() == 1
    assert await AuditLog.all().count() == 1
    page = await service.list_product_color_transactions(
        product.id,
        kit_color.id,
        page=1,
        page_size=20,
    )
    assert page.total == 1
    assert page.items[0].kit_color_id == kit_color.id
    assert page.items[0].kit_color.bead_color.slot_no == 1


async def test_fixed_and_color_inventory_endpoints_reject_wrong_kit_kind() -> None:
    operator = await _operator()
    color_product, kit_color = await _color_kit(1)
    fixed_product = await Product.create(
        name="固定库存商品",
        product_type=ProductType.KIT,
    )
    await ProductKit.create(
        product=fixed_product,
        price=Decimal("20.00"),
        stock=2,
        kit_kind=KitKind.FIXED,
    )
    service = _service()

    with pytest.raises(InventoryKitKindMismatch):
        await service.adjust_stock(
            color_product.id,
            change=1,
            reason="错误端点",
            operator_id=operator.id,
            ip_address="127.0.0.1",
            idempotency_key="wrong-fixed-endpoint",
        )
    with pytest.raises(InventoryKitKindMismatch):
        await service.adjust_color_stock(
            fixed_product.id,
            kit_color.id,
            change=1,
            reason="错误端点",
            operator_id=operator.id,
            ip_address="127.0.0.1",
            idempotency_key="wrong-color-endpoint",
        )

    assert await InventoryTransaction.all().count() == 0
    await kit_color.refresh_from_db()
    assert kit_color.stock_units == 0


async def test_color_adjustment_hides_cross_product_association() -> None:
    operator = await _operator()
    first_product, _ = await _color_kit(1)
    _, second_color = await _color_kit(2)

    with pytest.raises(ProductKitColorNotFound):
        await _service().adjust_color_stock(
            first_product.id,
            second_color.id,
            change=1,
            reason="错误归属",
            operator_id=operator.id,
            ip_address="127.0.0.1",
            idempotency_key="cross-product-color",
        )

    assert await InventoryTransaction.all().count() == 0
