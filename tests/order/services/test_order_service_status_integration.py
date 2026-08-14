"""Order 状态变迁、审计和回滚的真实 SQLite 集成测试。"""

import json
from decimal import Decimal

import pytest
from tortoise.backends.base.client import BaseDBAsyncClient

from app.common.enums.order import OrderStatus
from app.common.enums.product import ProductStatus, ProductType
from app.common.exceptions import (
    InventoryTransactionConflict,
    OrderNotFound,
    OrderStatusConflict,
)
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import (
    InventoryRepository,
    InventoryTransactionCreateData,
)
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderService


async def _create_user(number: int) -> User:
    return await User.create(
        username=f"order-status-user-{number}",
        password="hashed-password",
        nickname=f"状态用户 {number}",
        phone=f"1380013{number:04d}",
    )


async def _create_order(
    user: User,
    suffix: int,
    *,
    status: OrderStatus,
) -> Order:
    return await Order.create(
        order_no=f"OD{'0' * 24}{suffix:02d}",
        user=user,
        total_amount=Decimal("99.00"),
        status=status,
    )


def _service(
    *,
    order_repository: OrderRepository | None = None,
    inventory_repository: InventoryRepository | None = None,
    audit_service: AuditLogService | None = None,
) -> OrderService:
    return OrderService(
        order_repository or OrderRepository(),
        ProductRepository(),
        inventory_repository or InventoryRepository(),
        audit_service or AuditLogService(AuditLogRepository()),
    )


async def _create_pending_kit_order(
    user: User,
    suffix: int,
    *,
    stocks_and_quantities: list[tuple[int, int]],
) -> tuple[Order, list[ProductKit]]:
    order = await _create_order(user, suffix, status=OrderStatus.PENDING)
    kits: list[ProductKit] = []
    for index, (stock, quantity) in enumerate(stocks_and_quantities, start=1):
        product = await Product.create(
            name=f"取消恢复 Kit {suffix}-{index}",
            product_type=ProductType.KIT,
            status=ProductStatus.ONLINE,
        )
        kit = await ProductKit.create(
            product=product,
            price=Decimal("20.00"),
            stock=stock,
        )
        await OrderItem.create(
            order=order,
            product=product,
            experience_option_id=None,
            option_duration_minutes=None,
            option_participants=None,
            option_day_type=None,
            product_name=product.name,
            product_price=kit.price,
            quantity=quantity,
            subtotal=kit.price * quantity,
        )
        await InventoryTransaction.create(
            product=product,
            transaction_type="order_deduction",
            change_quantity=-quantity,
            before_quantity=stock + quantity,
            after_quantity=stock,
            source_type="order",
            source_id=order.id,
            operator=user,
            reason="Order stock deduction",
            idempotency_key=(
                f"inventory:order:{order.id}:deduct:product:{product.id}"
            ),
        )
        kits.append(kit)
    return order, kits


@pytest.mark.parametrize(
    (
        "method_name",
        "identity_name",
        "initial_status",
        "target_status",
        "audit_action",
        "before_value",
        "after_value",
    ),
    [
        (
            "cancel_order",
            "user_id",
            OrderStatus.PENDING,
            OrderStatus.CANCELLED,
            "CANCEL_ORDER",
            "pending",
            "cancelled",
        ),
        (
            "mark_order_paid",
            "operator_id",
            OrderStatus.PENDING,
            OrderStatus.PAID,
            "MARK_ORDER_PAID",
            "pending",
            "paid",
        ),
        (
            "complete_order",
            "operator_id",
            OrderStatus.PAID,
            OrderStatus.COMPLETED,
            "COMPLETE_ORDER",
            "paid",
            "completed",
        ),
    ],
)
async def test_status_transition_persists_one_status_and_one_audit(
    method_name: str,
    identity_name: str,
    initial_status: OrderStatus,
    target_status: OrderStatus,
    audit_action: str,
    before_value: str,
    after_value: str,
) -> None:
    """三条合法状态路径均原子持久化精确状态和非敏感审计摘要。"""

    owner = await _create_user(1)
    operator = owner if identity_name == "user_id" else await _create_user(2)
    order = await _create_order(owner, 1, status=initial_status)

    result = await getattr(_service(), method_name)(
        order.id,
        **{identity_name: operator.id, "ip_address": "203.0.113.9"},
    )

    assert result.id == order.id
    assert result.status == target_status
    stored = await Order.get(id=order.id)
    assert stored.status == target_status
    audits = await AuditLog.filter(target_type="order", target_id=order.id)
    assert len(audits) == 1
    assert audits[0].operator_id == operator.id
    assert audits[0].action == audit_action
    assert audits[0].ip_address == "203.0.113.9"
    assert json.loads(audits[0].description or "") == {
        "before_status": before_value,
        "after_status": after_value,
    }


async def test_user_cancel_hides_another_users_order() -> None:
    """用户取消通过锁查询中的 user_id 条件隐藏他人订单。"""

    owner = await _create_user(1)
    stranger = await _create_user(2)
    order = await _create_order(owner, 1, status=OrderStatus.PENDING)

    with pytest.raises(OrderNotFound):
        await _service().cancel_order(
            order.id,
            user_id=stranger.id,
            ip_address="127.0.0.1",
        )

    assert (await Order.get(id=order.id)).status == OrderStatus.PENDING
    assert await AuditLog.filter(target_type="order", target_id=order.id).count() == 0


async def test_repeated_transition_has_serial_equivalent_single_success() -> None:
    """相同取消请求串行执行时仅首个成功，后者看到新状态且不重复审计。"""

    owner = await _create_user(1)
    order = await _create_order(owner, 1, status=OrderStatus.PENDING)
    service = _service()

    await service.cancel_order(
        order.id,
        user_id=owner.id,
        ip_address="127.0.0.1",
    )
    with pytest.raises(OrderStatusConflict) as caught:
        await service.cancel_order(
            order.id,
            user_id=owner.id,
            ip_address="127.0.0.1",
        )

    assert caught.value.data == {
        "operation": "cancel",
        "current_status": "cancelled",
        "required_status": "pending",
    }
    assert (await Order.get(id=order.id)).status == OrderStatus.CANCELLED
    assert await AuditLog.filter(
        target_type="order",
        target_id=order.id,
        action="CANCEL_ORDER",
    ).count() == 1


async def test_cancel_mixed_kit_order_restores_balances_and_ledgers_once() -> None:
    """取消在一个事务中恢复全部 Kit，并为每个 Product 写一条稳定来源流水。"""

    owner = await _create_user(1)
    order, kits = await _create_pending_kit_order(
        owner,
        1,
        stocks_and_quantities=[(3, 2), (8, 4)],
    )
    service = _service()

    result = await service.cancel_order(
        order.id,
        user_id=owner.id,
        ip_address="198.51.100.8",
    )

    assert result.status == OrderStatus.CANCELLED
    assert [
        (await ProductKit.get(id=kit.id)).stock for kit in kits
    ] == [5, 12]
    restores = await InventoryTransaction.filter(
        source_type="order",
        source_id=order.id,
        transaction_type="order_cancellation_restore",
    ).order_by("product_id")
    assert [transaction.change_quantity for transaction in restores] == [2, 4]
    assert [transaction.before_quantity for transaction in restores] == [3, 8]
    assert [transaction.after_quantity for transaction in restores] == [5, 12]
    assert all(transaction.operator_id == owner.id for transaction in restores)
    assert all(
        transaction.reason == "Order cancellation stock restore"
        for transaction in restores
    )
    assert [transaction.idempotency_key for transaction in restores] == [
        f"inventory:order:{order.id}:restore:product:{kit.product_id}"
        for kit in kits
    ]

    with pytest.raises(OrderStatusConflict):
        await service.cancel_order(
            order.id,
            user_id=owner.id,
            ip_address="198.51.100.8",
        )
    assert [
        (await ProductKit.get(id=kit.id)).stock for kit in kits
    ] == [5, 12]
    assert await InventoryTransaction.filter(
        source_id=order.id,
        transaction_type="order_cancellation_restore",
    ).count() == 2
    assert await AuditLog.filter(
        target_type="order",
        target_id=order.id,
        action="CANCEL_ORDER",
    ).count() == 1


async def test_pending_order_with_existing_restore_identity_fails_atomically() -> None:
    """Pending 状态与已提交恢复身份矛盾时不得静默跳过或再次增加库存。"""

    owner = await _create_user(1)
    order, kits = await _create_pending_kit_order(
        owner,
        1,
        stocks_and_quantities=[(3, 2)],
    )
    kit = kits[0]
    await InventoryTransaction.create(
        product_id=kit.product_id,
        transaction_type="order_cancellation_restore",
        change_quantity=2,
        before_quantity=3,
        after_quantity=5,
        source_type="order",
        source_id=order.id,
        operator=owner,
        reason="Order cancellation stock restore",
        idempotency_key=(
            f"inventory:order:{order.id}:restore:product:{kit.product_id}"
        ),
    )

    with pytest.raises(InventoryTransactionConflict):
        await _service().cancel_order(
            order.id,
            user_id=owner.id,
            ip_address="127.0.0.1",
        )

    assert (await Order.get(id=order.id)).status == OrderStatus.PENDING
    assert (await ProductKit.get(id=kit.id)).stock == 3
    assert await AuditLog.filter(target_type="order", target_id=order.id).count() == 0


class _FailAfterStatusAudit(AuditLogService):
    async def log(
        self,
        operator_id: int,
        action: str,
        target_type: str,
        target_id: int,
        ip_address: str,
        description: str | None = None,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        await super().log(
            operator_id,
            action,
            target_type,
            target_id,
            ip_address,
            description,
            using_db=using_db,
        )
        raise RuntimeError("fail after status audit")


class _MissingStatusReloadRepository(OrderRepository):
    async def get_order_by_id(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Order | None:
        return None


class _FailAfterRestoreTransactionsRepository(InventoryRepository):
    async def bulk_create_transactions(
        self,
        *,
        transactions: list[InventoryTransactionCreateData],
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        await super().bulk_create_transactions(
            transactions=transactions,
            using_db=using_db,
        )
        raise RuntimeError("fail after restore transactions")


@pytest.mark.parametrize("failure_stage", ["inventory", "audit", "reload"])
async def test_status_transaction_failure_rolls_back_update_and_audit(
    failure_stage: str,
) -> None:
    """状态更新后的审计或响应重载失败必须恢复原状态且不留审计。"""

    owner = await _create_user(1)
    order, kits = await _create_pending_kit_order(
        owner,
        1,
        stocks_and_quantities=[(3, 2), (8, 4)],
    )
    repository: OrderRepository | None = None
    inventory_repository: InventoryRepository | None = None
    audit_service: AuditLogService | None = None
    expected_message = "Updated order not found"
    if failure_stage == "inventory":
        inventory_repository = _FailAfterRestoreTransactionsRepository()
        expected_message = "fail after restore transactions"
    elif failure_stage == "audit":
        audit_service = _FailAfterStatusAudit(AuditLogRepository())
        expected_message = "fail after status audit"
    else:
        repository = _MissingStatusReloadRepository()

    with pytest.raises(RuntimeError, match=expected_message):
        await _service(
            order_repository=repository,
            inventory_repository=inventory_repository,
            audit_service=audit_service,
        ).cancel_order(
            order.id,
            user_id=owner.id,
            ip_address="127.0.0.1",
        )

    assert (await Order.get(id=order.id)).status == OrderStatus.PENDING
    assert await AuditLog.filter(target_type="order", target_id=order.id).count() == 0
    assert [
        (await ProductKit.get(id=kit.id)).stock for kit in kits
    ] == [3, 8]
    assert await InventoryTransaction.filter(
        source_id=order.id,
        transaction_type="order_cancellation_restore",
    ).count() == 0
