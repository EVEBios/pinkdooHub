"""自选颜色 Kit 的订单快照、库存扣减与取消恢复集成测试。"""

from decimal import Decimal

import pytest

from app.common.enums.inventory import InventoryTransactionType
from app.common.enums.product import KitKind, ProductStatus, ProductType
from app.common.exceptions import OrderAmountExceeded, OrderKitColorUnavailable
from app.models.audit_log import AuditLog
from app.models.bead_color import BeadColor
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.product_kit_color import ProductKitColor
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderItemInput, OrderService


def _service() -> OrderService:
    return OrderService(
        OrderRepository(),
        ProductRepository(),
        InventoryRepository(),
        AuditLogService(AuditLogRepository()),
        user_repository=UserRepository(),
        order_number_generator=lambda: "OD00000000000000000000000001",
    )


async def _user() -> User:
    return await User.create(
        username="color-order-user",
        password="hashed-password",
        nickname="自选颜色顾客",
    )


async def _color_kit(
    *,
    price: str = "6.50",
    stock_units: int = 5,
    active: bool = True,
    code: str | None = "C001",
    name: str | None = "珊瑚红",
    swatch_hex: str | None = "#FF7F50",
) -> tuple[Product, ProductKitColor]:
    product = await Product.create(
        name="10g 自选拼豆",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    await ProductKit.create(
        product=product,
        price=Decimal(price),
        stock=None,
        kit_kind=KitKind.COLOR_SELECTABLE,
        sale_unit_grams=10,
    )
    bead_color = await BeadColor.create(
        slot_no=1,
        color_code=code,
        name=name,
        swatch_hex=swatch_hex,
        sort=1,
        is_active=active,
    )
    kit_color = await ProductKitColor.create(
        product=product,
        bead_color=bead_color,
        is_enabled=True,
        stock_units=stock_units,
    )
    return product, kit_color


async def test_color_and_fixed_kit_create_then_cancel_restore_both_balances() -> None:
    user = await _user()
    fixed_product = await Product.create(
        name="固定套装",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    fixed_kit = await ProductKit.create(
        product=fixed_product,
        price=Decimal("20.00"),
        stock=3,
        kit_kind=KitKind.FIXED,
    )
    color_product, kit_color = await _color_kit()

    created = await _service().create_order(
        user_id=user.id,
        items=[
            OrderItemInput(fixed_product.id, None, 1),
            OrderItemInput(color_product.id, None, 2, kit_color.id),
        ],
        remark=None,
        ip_address="127.0.0.1",
    )

    await fixed_kit.refresh_from_db()
    await kit_color.refresh_from_db()
    assert created.total_amount == Decimal("33.00")
    assert fixed_kit.stock == 2
    assert kit_color.stock_units == 3
    assert len(created.items) == 2
    color_item = created.items[1]
    assert color_item.kit_color_id == kit_color.id
    assert color_item.kit_color_slot_no == 1
    assert color_item.kit_color_code == "C001"
    assert color_item.kit_color_name == "珊瑚红"
    assert color_item.sale_unit_grams == 10

    deductions = await InventoryTransaction.filter(
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
    ).order_by("id")
    assert [
        (row.product_id, row.kit_color_id, row.change_quantity)
        for row in deductions
    ] == [
        (fixed_product.id, None, -1),
        (color_product.id, kit_color.id, -2),
    ]

    await _service().cancel_order(
        created.id,
        user_id=user.id,
        ip_address="127.0.0.1",
    )

    await fixed_kit.refresh_from_db()
    await kit_color.refresh_from_db()
    assert fixed_kit.stock == 3
    assert kit_color.stock_units == 5
    restores = await InventoryTransaction.filter(
        transaction_type=InventoryTransactionType.ORDER_CANCELLATION_RESTORE,
    ).order_by("id")
    assert [
        (row.product_id, row.kit_color_id, row.change_quantity)
        for row in restores
    ] == [
        (fixed_product.id, None, 1),
        (color_product.id, kit_color.id, 2),
    ]


async def test_unconfigured_color_is_rejected_before_any_order_write() -> None:
    user = await _user()
    product, kit_color = await _color_kit(
        active=False,
        code=None,
        name=None,
        swatch_hex=None,
    )

    with pytest.raises(OrderKitColorUnavailable):
        await _service().create_order(
            user_id=user.id,
            items=[OrderItemInput(product.id, None, 1, kit_color.id)],
            remark=None,
            ip_address="127.0.0.1",
        )

    assert await Order.all().count() == 0
    assert await OrderItem.all().count() == 0
    assert await InventoryTransaction.all().count() == 0
    assert await AuditLog.all().count() == 0
    await kit_color.refresh_from_db()
    assert kit_color.stock_units == 5


async def test_color_without_hex_is_rejected_before_any_order_write() -> None:
    user = await _user()
    product, kit_color = await _color_kit(swatch_hex=None)

    with pytest.raises(OrderKitColorUnavailable):
        await _service().create_order(
            user_id=user.id,
            items=[OrderItemInput(product.id, None, 1, kit_color.id)],
            remark=None,
            ip_address="127.0.0.1",
        )

    assert await Order.all().count() == 0
    assert await InventoryTransaction.all().count() == 0
    await kit_color.refresh_from_db()
    assert kit_color.stock_units == 5


async def test_explicit_total_guard_rejects_color_order_before_write() -> None:
    user = await _user()
    product, kit_color = await _color_kit(
        price="99999.00",
        stock_units=999_999,
    )

    with pytest.raises(OrderAmountExceeded):
        await _service().create_order(
            user_id=user.id,
            items=[
                OrderItemInput(product.id, None, 99, kit_color.id)
                for _ in range(11)
            ],
            remark=None,
            ip_address="127.0.0.1",
        )

    assert await Order.all().count() == 0
    assert await InventoryTransaction.all().count() == 0
