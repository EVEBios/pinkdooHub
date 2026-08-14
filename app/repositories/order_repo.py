"""Order Repository —— 封装订单聚合的数据访问。"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.functions import Count
from tortoise.query_utils import Prefetch
from tortoise.queryset import QuerySet

from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType
from app.common.pagination import Page
from app.models.order import Order, OrderItem


@dataclass(frozen=True, slots=True)
class OrderItemCreateData:
    """Repository 批量写入 OrderItem 所需的已验证快照。"""

    product_id: int
    experience_option_id: int | None
    option_duration_minutes: int | None
    option_participants: int | None
    option_day_type: DayType | None
    product_name: str
    product_price: Decimal
    quantity: int
    subtotal: Decimal


@dataclass(frozen=True, slots=True)
class OrderCancellationItemData:
    """取消恢复只需要的不可变 OrderItem 库存快照字段。"""

    product_id: int
    experience_option_id: int | None
    quantity: int


def _apply_order_filters(
    query: QuerySet[Order],
    *,
    status: OrderStatus | None = None,
    order_no: str | None = None,
    user_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> QuerySet[Order]:
    """向 Order QuerySet 应用纯数据库筛选，不包含业务判断。"""

    if status is not None:
        query = query.filter(status=status.value)
    if order_no is not None:
        query = query.filter(order_no=order_no)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    if created_from is not None:
        query = query.filter(created_at__gte=created_from)
    if created_to is not None:
        query = query.filter(created_at__lt=created_to)
    return query


class OrderRepository:
    """Order 数据访问层，不包含归属、状态机或可售性判断。"""

    async def get_order_by_id(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Order | None:
        """按主键读取 Order，不加载详情关系。"""

        query = Order.filter(id=order_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def order_number_exists(self, order_no: str) -> bool:
        """判断订单号是否已经持久化，用于事务回滚后的冲突归因。"""

        return await Order.filter(order_no=order_no).exists()

    async def create_order(
        self,
        *,
        order_no: str,
        user_id: int,
        total_amount: Decimal,
        remark: str | None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Order:
        """创建 Pending Order，并加入调用方提供的事务连接。"""

        return await Order.create(
            order_no=order_no,
            user_id=user_id,
            total_amount=total_amount,
            remark=remark,
            using_db=using_db,
        )

    async def bulk_create_items(
        self,
        *,
        order: Order,
        items: list[OrderItemCreateData],
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        """用一次批量写入保存已验证的 OrderItem 快照。"""

        if not items:
            return
        models = [
            OrderItem(
                order_id=order.id,
                product_id=item.product_id,
                experience_option_id=item.experience_option_id,
                option_duration_minutes=item.option_duration_minutes,
                option_participants=item.option_participants,
                option_day_type=item.option_day_type,
                product_name=item.product_name,
                product_price=item.product_price,
                quantity=item.quantity,
                subtotal=item.subtotal,
            )
            for item in items
        ]
        await OrderItem.bulk_create(models, using_db=using_db)

    async def get_order_detail(
        self,
        order_id: int,
        *,
        user_id: int | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Order | None:
        """按 ID 加载 User 与稳定排序的 Items，可限定用户可见范围。"""

        item_query = OrderItem.all().order_by("id")
        query = (
            Order.filter(id=order_id)
            .select_related("user")
            .prefetch_related(Prefetch("items", item_query))
        )
        if user_id is not None:
            query = query.filter(user_id=user_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_order_items(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> list[OrderCancellationItemData]:
        """按稳定 ID 顺序只加载取消恢复需要的订单快照字段。"""

        rows = await (
            OrderItem.filter(order_id=order_id)
            .using_db(using_db)
            .order_by("id")
            .values("product_id", "experience_option_id", "quantity")
        )
        return [OrderCancellationItemData(**row) for row in rows]

    async def get_order_detail_by_no(
        self,
        order_no: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Order | None:
        """按唯一订单号加载完整订单聚合。"""

        item_query = OrderItem.all().order_by("id")
        query = (
            Order.filter(order_no=order_no)
            .select_related("user")
            .prefetch_related(Prefetch("items", item_query))
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_order_for_update(
        self,
        order_id: int,
        *,
        user_id: int | None = None,
        using_db: BaseDBAsyncClient,
    ) -> Order | None:
        """在调用方事务中锁定订单，可在 SQL 层限定用户可见范围。"""

        query = Order.filter(id=order_id).using_db(using_db)
        if user_id is not None:
            query = query.filter(user_id=user_id)
        return await query.select_for_update().first()

    async def update_status(
        self,
        order: Order,
        *,
        status: OrderStatus,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Order:
        """持久化调用方已经判定合法的状态值。"""

        order.status = status.value
        await order.save(
            using_db=using_db,
            update_fields=["status", "updated_at"],
        )
        return order

    async def list_user_orders(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
        status: OrderStatus | None = None,
    ) -> Page[Order]:
        """分页查询指定用户的订单摘要。"""

        query = _apply_order_filters(
            Order.all(),
            user_id=user_id,
            status=status,
        )
        return await self._paginate_summaries(
            query,
            page=page,
            page_size=page_size,
            include_user=False,
        )

    async def list_admin_orders(
        self,
        *,
        page: int,
        page_size: int,
        status: OrderStatus | None = None,
        order_no: str | None = None,
        user_id: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> Page[Order]:
        """分页查询管理端订单摘要和冻结的组合筛选。"""

        query = _apply_order_filters(
            Order.all(),
            status=status,
            order_no=order_no,
            user_id=user_id,
            created_from=created_from,
            created_to=created_to,
        )
        return await self._paginate_summaries(
            query,
            page=page,
            page_size=page_size,
            include_user=True,
        )

    async def _paginate_summaries(
        self,
        query: QuerySet[Order],
        *,
        page: int,
        page_size: int,
        include_user: bool,
    ) -> Page[Order]:
        """执行摘要计数、数据库分页和 Item 行数聚合。"""

        total = await query.count()
        offset = (page - 1) * page_size
        item_query = query.annotate(item_count=Count("items"))
        if include_user:
            item_query = item_query.select_related("user")
        items = await (
            item_query.order_by("-created_at", "-id")
            .offset(offset)
            .limit(page_size)
        )
        pages = (total + page_size - 1) // page_size
        return Page[Order](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )
