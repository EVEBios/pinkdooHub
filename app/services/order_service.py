"""Order Service —— 订单查询与后续写用例的业务编排层。"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.common.constants.order import (
    ORDER_AUDIT_ACTION_CANCEL,
    ORDER_AUDIT_ACTION_COMPLETE,
    ORDER_AUDIT_ACTION_CREATE,
    ORDER_AUDIT_ACTION_MARK_PAID,
    ORDER_AUDIT_TARGET_TYPE,
    ORDER_NO_GENERATION_MAX_ATTEMPTS,
    ORDER_OPERATION_CANCEL,
    ORDER_OPERATION_COMPLETE,
    ORDER_OPERATION_MARK_PAID,
    ORDER_STATUS_BY_VALUE,
    ORDER_STATUS_VALUES,
)
from app.common.enums.order import OrderStatus, OrderStatusValue
from app.common.enums.product import ProductStatus, ProductType
from app.common.exceptions import (
    KitOrderingRequiresInventory,
    OrderNotFound,
    OrderOptionUnavailable,
    OrderProductUnavailable,
    OrderStatusConflict,
)
from app.common.order_number import generate_order_number
from app.common.pagination import Page
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.repositories.order_repo import (
    OrderItemCreateData,
    OrderRepository,
)
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OrderItemInput:
    """创建订单的领域输入，不包含任何客户端可伪造快照。"""

    product_id: int
    experience_option_id: int
    quantity: int


class OrderService:
    """Order 创建、状态变迁与查询用例的业务编排层。"""

    def __init__(
        self,
        order_repository: OrderRepository,
        product_repository: ProductRepository,
        audit_log_service: AuditLogService,
        order_number_generator: Callable[[], str] = generate_order_number,
    ) -> None:
        self.order_repository = order_repository
        self.product_repository = product_repository
        self.audit_log_service = audit_log_service
        self.order_number_generator = order_number_generator

    async def create_order(
        self,
        *,
        user_id: int,
        items: list[OrderItemInput],
        remark: str | None,
        ip_address: str,
    ) -> Order:
        """校验 Experience Items，并原子创建订单、快照与审计。"""

        snapshots, total_amount = await self._build_order_snapshots(items)
        audit_description = json.dumps(
            {
                "item_count": len(snapshots),
                "total_amount": f"{total_amount:.2f}",
            },
            separators=(",", ":"),
        )

        for attempt in range(ORDER_NO_GENERATION_MAX_ATTEMPTS):
            order_no = self.order_number_generator()
            try:
                async with in_transaction() as connection:
                    order = await self.order_repository.create_order(
                        order_no=order_no,
                        user_id=user_id,
                        total_amount=total_amount,
                        remark=remark,
                        using_db=connection,
                    )
                    await self.order_repository.bulk_create_items(
                        order=order,
                        items=snapshots,
                        using_db=connection,
                    )
                    await self.audit_log_service.log(
                        operator_id=user_id,
                        action=ORDER_AUDIT_ACTION_CREATE,
                        target_type=ORDER_AUDIT_TARGET_TYPE,
                        target_id=order.id,
                        ip_address=ip_address,
                        description=audit_description,
                        using_db=connection,
                    )
                    loaded = await self.order_repository.get_order_detail(
                        order.id,
                        user_id=user_id,
                        using_db=connection,
                    )
                    if loaded is None:
                        raise RuntimeError("Persisted order not found")
            except IntegrityError:
                is_order_number_collision = (
                    await self.order_repository.order_number_exists(order_no)
                )
                if (
                    is_order_number_collision
                    and attempt + 1 < ORDER_NO_GENERATION_MAX_ATTEMPTS
                ):
                    continue
                raise

            logger.info(
                "Order created: user_id=%d order_id=%d item_count=%d",
                user_id,
                loaded.id,
                len(snapshots),
            )
            return loaded

        raise RuntimeError("Order number retry loop exhausted")

    async def cancel_order(
        self,
        order_id: int,
        *,
        user_id: int,
        ip_address: str,
    ) -> Order:
        """由订单所属用户执行 ``pending → cancelled``。"""

        return await self._transition_order(
            order_id,
            operator_id=user_id,
            visible_user_id=user_id,
            operation=ORDER_OPERATION_CANCEL,
            required_status=OrderStatus.PENDING,
            target_status=OrderStatus.CANCELLED,
            audit_action=ORDER_AUDIT_ACTION_CANCEL,
            ip_address=ip_address,
        )

    async def mark_order_paid(
        self,
        order_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> Order:
        """由 ADMIN+ 执行 ``pending → paid``；角色权限由 API 依赖保证。"""

        return await self._transition_order(
            order_id,
            operator_id=operator_id,
            visible_user_id=None,
            operation=ORDER_OPERATION_MARK_PAID,
            required_status=OrderStatus.PENDING,
            target_status=OrderStatus.PAID,
            audit_action=ORDER_AUDIT_ACTION_MARK_PAID,
            ip_address=ip_address,
        )

    async def complete_order(
        self,
        order_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> Order:
        """由 ADMIN+ 执行 ``paid → completed``；角色权限由 API 依赖保证。"""

        return await self._transition_order(
            order_id,
            operator_id=operator_id,
            visible_user_id=None,
            operation=ORDER_OPERATION_COMPLETE,
            required_status=OrderStatus.PAID,
            target_status=OrderStatus.COMPLETED,
            audit_action=ORDER_AUDIT_ACTION_COMPLETE,
            ip_address=ip_address,
        )

    async def _transition_order(
        self,
        order_id: int,
        *,
        operator_id: int,
        visible_user_id: int | None,
        operation: str,
        required_status: OrderStatus,
        target_status: OrderStatus,
        audit_action: str,
        ip_address: str,
    ) -> Order:
        """在行锁保护下执行一条由公开用例固定的状态变迁。"""

        audit_description = json.dumps(
            {
                "before_status": ORDER_STATUS_VALUES[required_status],
                "after_status": ORDER_STATUS_VALUES[target_status],
            },
            separators=(",", ":"),
        )
        async with in_transaction() as connection:
            order = await self.order_repository.get_order_for_update(
                order_id,
                user_id=visible_user_id,
                using_db=connection,
            )
            if order is None:
                raise OrderNotFound()

            current_status = OrderStatus(order.status)
            if current_status != required_status:
                raise OrderStatusConflict(
                    operation=operation,
                    current_status=current_status,
                    required_status=required_status,
                )

            await self.order_repository.update_status(
                order,
                status=target_status,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action=audit_action,
                target_type=ORDER_AUDIT_TARGET_TYPE,
                target_id=order.id,
                ip_address=ip_address,
                description=audit_description,
                using_db=connection,
            )
            loaded = await self.order_repository.get_order_by_id(
                order.id,
                using_db=connection,
            )
            if loaded is None:
                raise RuntimeError("Updated order not found")

        logger.info(
            "Order status changed: operator_id=%d order_id=%d operation=%s",
            operator_id,
            loaded.id,
            operation,
        )
        return loaded

    async def _build_order_snapshots(
        self,
        items: list[OrderItemInput],
    ) -> tuple[list[OrderItemCreateData], Decimal]:
        """批量读取权威聚合，并按请求顺序构造 Experience 快照。"""

        products = await self.product_repository.get_products_by_ids(
            {item.product_id for item in items}
        )
        options = await self.product_repository.get_options_by_ids(
            {item.experience_option_id for item in items}
        )
        products_by_id = {product.id: product for product in products}
        options_by_id = {option.id: option for option in options}

        snapshots: list[OrderItemCreateData] = []
        total_amount = Decimal("0.00")
        for item in items:
            product = (
                products_by_id[item.product_id]
                if item.product_id in products_by_id
                else None
            )
            if product is not None and product.product_type is ProductType.KIT:
                raise KitOrderingRequiresInventory(product_id=item.product_id)
            if (
                product is None
                or product.is_deleted
                or product.status is not ProductStatus.ONLINE
                or product.product_type is not ProductType.EXPERIENCE
            ):
                raise OrderProductUnavailable(product_id=item.product_id)

            option = (
                options_by_id[item.experience_option_id]
                if item.experience_option_id in options_by_id
                else None
            )
            if (
                option is None
                or option.is_deleted
                or option.product_id != product.id
            ):
                raise OrderOptionUnavailable(
                    product_id=item.product_id,
                    experience_option_id=item.experience_option_id,
                )

            subtotal = option.price * item.quantity
            snapshots.append(
                OrderItemCreateData(
                    product_id=product.id,
                    experience_option_id=option.id,
                    option_duration_minutes=option.duration,
                    option_participants=option.participants,
                    option_day_type=option.day_type,
                    product_name=product.name,
                    product_price=option.price,
                    quantity=item.quantity,
                    subtotal=subtotal,
                )
            )
            total_amount += subtotal

        return snapshots, total_amount

    async def list_user_orders(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
        status: OrderStatusValue | None = None,
    ) -> Page[Order]:
        """查询当前用户可见的订单摘要。"""

        return await self.order_repository.list_user_orders(
            user_id=user_id,
            page=page,
            page_size=page_size,
            status=ORDER_STATUS_BY_VALUE[status] if status is not None else None,
        )

    async def get_user_order_detail(
        self,
        order_id: int,
        *,
        user_id: int,
    ) -> Order:
        """查询用户订单；不存在与他人订单统一隐藏为 OrderNotFound。"""

        order = await self.order_repository.get_order_detail(
            order_id,
            user_id=user_id,
        )
        if order is None:
            raise OrderNotFound()
        return order

    async def list_admin_orders(
        self,
        *,
        page: int,
        page_size: int,
        status: OrderStatusValue | None = None,
        order_no: str | None = None,
        user_id: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> Page[Order]:
        """查询管理端订单摘要并原样转发已校验筛选条件。"""

        return await self.order_repository.list_admin_orders(
            page=page,
            page_size=page_size,
            status=ORDER_STATUS_BY_VALUE[status] if status is not None else None,
            order_no=order_no,
            user_id=user_id,
            created_from=created_from,
            created_to=created_to,
        )

    async def get_admin_order_detail(self, order_id: int) -> Order:
        """查询任意管理端订单详情。"""

        order = await self.order_repository.get_order_detail(order_id)
        if order is None:
            raise OrderNotFound()
        return order

    async def list_order_audit_logs(
        self,
        order_id: int,
        *,
        page: int,
        page_size: int,
    ) -> Page[AuditLog]:
        """确认 Order 存在后委托共享审计服务分页查询。"""

        order = await self.order_repository.get_order_by_id(order_id)
        if order is None:
            raise OrderNotFound()
        return await self.audit_log_service.list_logs(
            target_type=ORDER_AUDIT_TARGET_TYPE,
            target_id=order_id,
            page=page,
            page_size=page_size,
        )
