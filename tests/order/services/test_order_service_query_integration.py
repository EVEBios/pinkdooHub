"""OrderService 只读用例的真实 SQLite 集成测试。"""

from decimal import Decimal

import pytest

from app.common.constants.order import ORDER_AUDIT_TARGET_TYPE
from app.common.enums.order import OrderStatus
from app.common.enums.product import ProductType
from app.common.exceptions import OrderNotFound
from app.models.audit_log import AuditLog
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderService


def _service() -> OrderService:
    return OrderService(
        OrderRepository(),
        ProductRepository(),
        InventoryRepository(),
        AuditLogService(AuditLogRepository()),
    )


async def _create_user(number: int) -> User:
    return await User.create(
        username=f"order-service-{number}",
        password="hashed-password",
        nickname=f"查询用户 {number}",
        phone=f"1390013{number:04d}",
    )


async def _create_order(
    user: User,
    number: int,
    *,
    status: OrderStatus = OrderStatus.PENDING,
    item_count: int = 1,
) -> Order:
    order = await Order.create(
        order_no=f"OD01ARZ3NDEKTSV4RRFFQ69G6F{number:02d}",
        user=user,
        total_amount=Decimal(item_count * 100),
        status=status,
    )
    for item_number in range(item_count):
        product = await Product.create(
            name=f"查询订单 {number} 商品 {item_number}",
            product_type=ProductType.EXPERIENCE,
        )
        await OrderItem.create(
            order=order,
            product=product,
            product_name=product.name,
            product_price=Decimal("100.00"),
            quantity=1,
            subtotal=Decimal("100.00"),
        )
    return order


async def test_real_user_queries_only_expose_owned_orders() -> None:
    """列表和详情都应在数据库查询层限定当前用户。"""

    owner = await _create_user(1)
    other = await _create_user(2)
    pending = await _create_order(owner, 1, item_count=2)
    paid = await _create_order(owner, 2, status=OrderStatus.PAID)
    foreign = await _create_order(other, 3, status=OrderStatus.PAID)
    service = _service()

    page = await service.list_user_orders(
        user_id=owner.id,
        page=1,
        page_size=20,
        status="paid",
    )
    detail = await service.get_user_order_detail(pending.id, user_id=owner.id)

    assert [order.id for order in page.items] == [paid.id]
    assert foreign.id not in [order.id for order in page.items]
    assert page.items[0].item_count == 1
    assert detail.id == pending.id
    assert [item.order_id for item in detail.items] == [pending.id, pending.id]


async def test_real_user_missing_and_foreign_details_are_indistinguishable() -> None:
    """两种不可见资源必须暴露相同命名异常、错误码和消息。"""

    owner = await _create_user(1)
    other = await _create_user(2)
    foreign = await _create_order(other, 1)
    service = _service()

    caught = []
    for order_id in (foreign.id, foreign.id + 999):
        with pytest.raises(OrderNotFound) as exc_info:
            await service.get_user_order_detail(order_id, user_id=owner.id)
        caught.append(exc_info.value)

    assert [(exc.code, exc.message, exc.data) for exc in caught] == [
        (40411, "Order not found", None),
        (40411, "Order not found", None),
    ]


async def test_real_admin_queries_return_user_and_items() -> None:
    """管理列表与详情应提供 Mapper 所需的预加载关系。"""

    user = await _create_user(1)
    order = await _create_order(
        user,
        1,
        status=OrderStatus.COMPLETED,
        item_count=2,
    )
    service = _service()

    page = await service.list_admin_orders(
        page=1,
        page_size=20,
        status="completed",
        order_no=order.order_no,
        product_name="订单 1 商品",
        user_id=user.id,
    )
    detail = await service.get_admin_order_detail(order.id)

    assert [item.id for item in page.items] == [order.id]
    assert page.items[0].user.nickname == user.nickname
    assert page.items[0].item_count == 2
    assert detail.user.nickname == user.nickname
    assert len(detail.items) == 2


async def test_real_order_audit_query_filters_target_and_stable_pages() -> None:
    """订单历史只返回自身 target，并沿用共享审计分页契约。"""

    user = await _create_user(1)
    order = await _create_order(user, 1)
    other = await _create_order(user, 2)
    for action in ("CREATE_ORDER", "MARK_ORDER_PAID"):
        await AuditLog.create(
            operator_id=user.id,
            action=action,
            target_type=ORDER_AUDIT_TARGET_TYPE,
            target_id=order.id,
            ip_address="127.0.0.1",
        )
    await AuditLog.create(
        operator_id=user.id,
        action="CREATE_ORDER",
        target_type=ORDER_AUDIT_TARGET_TYPE,
        target_id=other.id,
        ip_address="127.0.0.1",
    )
    await AuditLog.create(
        operator_id=user.id,
        action="UNRELATED",
        target_type="product",
        target_id=order.id,
        ip_address="127.0.0.1",
    )

    result = await _service().list_order_audit_logs(
        order.id,
        page=1,
        page_size=1,
    )

    assert [audit.action for audit in result.items] == ["MARK_ORDER_PAID"]
    assert result.total == 2
    assert result.pages == 2


async def test_missing_order_rejects_even_if_orphan_audit_exists() -> None:
    """孤立审计记录不能替代 Order 存在性，也不能返回伪历史。"""

    missing_id = 99999
    await AuditLog.create(
        operator_id=1,
        action="CREATE_ORDER",
        target_type=ORDER_AUDIT_TARGET_TYPE,
        target_id=missing_id,
        ip_address="127.0.0.1",
    )

    with pytest.raises(OrderNotFound):
        await _service().list_order_audit_logs(
            missing_id,
            page=1,
            page_size=20,
        )
