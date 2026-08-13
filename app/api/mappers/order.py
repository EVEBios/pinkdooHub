"""Order ORM 聚合到 API Out Schema 的同步纯映射。"""

from app.common.constants.order import ORDER_STATUS_LABELS, ORDER_STATUS_VALUES
from app.common.constants.product import DAY_TYPE_LABELS
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType
from app.common.pagination import Page
from app.models.order import Order, OrderItem
from app.schemas.order_response import (
    AdminOrderDetailOut,
    AdminOrderListItemOut,
    OrderDayTypeOut,
    OrderDetailOut,
    OrderItemOut,
    OrderListItemOut,
    OrderStatusOut,
    OrderStatusValueOut,
)


def map_order_status_value(value: OrderStatus | int) -> OrderStatusValueOut:
    """将数据库订单状态转换为稳定 API value/label。"""

    normalized = OrderStatus(value)
    return OrderStatusValueOut.model_validate(
        {
            "value": ORDER_STATUS_VALUES[normalized],
            "label": ORDER_STATUS_LABELS[normalized],
        }
    )


def map_order_day_type(value: DayType | str) -> OrderDayTypeOut:
    """将 OrderItem 日期类型快照转换为稳定 API value/label。"""

    normalized = DayType(value)
    return OrderDayTypeOut.model_validate(
        {"value": normalized, "label": DAY_TYPE_LABELS[normalized]}
    )


def map_order_item(item: OrderItem) -> OrderItemOut:
    """映射不可变 OrderItem 快照，不读取当前 Product/Option。"""

    return OrderItemOut.model_validate(
        {
            "id": item.id,
            "product_id": item.product_id,
            "experience_option_id": item.experience_option_id,
            "product_name": item.product_name,
            "option_duration_minutes": item.option_duration_minutes,
            "option_participants": item.option_participants,
            "option_day_type": map_order_day_type(item.option_day_type),
            "product_price": item.product_price,
            "quantity": item.quantity,
            "subtotal": item.subtotal,
        }
    )


def _order_identity_payload(order: Order) -> dict[str, object]:
    """构造 Order 响应共享身份字段白名单。"""

    return {
        "id": order.id,
        "order_no": order.order_no,
        "status": map_order_status_value(order.status),
    }


def _order_list_payload(order: Order) -> dict[str, object]:
    """构造用户与管理列表共享摘要字段。"""

    return {
        **_order_identity_payload(order),
        "total_amount": order.total_amount,
        "item_count": order.item_count,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def map_order_list_item(order: Order) -> OrderListItemOut:
    """映射用户端订单列表项，不读取或输出 User 关系。"""

    return OrderListItemOut.model_validate(_order_list_payload(order))


def map_admin_order_list_item(order: Order) -> AdminOrderListItemOut:
    """映射管理端列表项，只增加安全用户 ID 与昵称。"""

    return AdminOrderListItemOut.model_validate(
        {
            **_order_list_payload(order),
            "user_id": order.user_id,
            "user_nickname": order.user.nickname,
        }
    )


def map_order_page(page: Page[Order]) -> Page[OrderListItemOut]:
    """保留分页元数据并映射用户端订单列表。"""

    return Page[OrderListItemOut](
        items=[map_order_list_item(order) for order in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def map_admin_order_page(page: Page[Order]) -> Page[AdminOrderListItemOut]:
    """保留分页元数据并映射管理端订单列表。"""

    return Page[AdminOrderListItemOut](
        items=[map_admin_order_list_item(order) for order in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def _order_detail_payload(order: Order) -> dict[str, object]:
    """消费已预加载 Items 并构造详情共享字段。"""

    mapped_items: list[OrderItemOut] = []
    for item in order.items:
        if item.order_id != order.id:
            raise ValueError("Order item belongs to a different order")
        mapped_items.append(map_order_item(item))

    return {
        **_order_identity_payload(order),
        "total_amount": order.total_amount,
        "remark": order.remark,
        "items": mapped_items,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
    }


def map_order_detail(order: Order) -> OrderDetailOut:
    """映射用户端详情，不读取或输出 User 关系。"""

    return OrderDetailOut.model_validate(_order_detail_payload(order))


def map_admin_order_detail(order: Order) -> AdminOrderDetailOut:
    """映射管理端详情，只增加安全用户 ID 与昵称。"""

    return AdminOrderDetailOut.model_validate(
        {
            **_order_detail_payload(order),
            "user_id": order.user_id,
            "user_nickname": order.user.nickname,
        }
    )


def map_order_status_response(order: Order) -> OrderStatusOut:
    """映射取消、确认支付和完成订单的轻量响应。"""

    payload = _order_identity_payload(order)
    payload["updated_at"] = order.updated_at
    return OrderStatusOut.model_validate(payload)
