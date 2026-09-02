"""用户端 Order API —— 创建、我的订单查询与取消。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.api.deps import get_current_user, get_order_service, reject_request_body
from app.api.mappers.order import (
    map_order_detail,
    map_order_page,
    map_order_status_response,
)
from app.api.responses import error_responses, success_responses
from app.common.pagination import Page
from app.common.response import success
from app.models.user import User
from app.schemas.order import OrderCreate, OrderListQuery
from app.schemas.order_response import (
    OrderDetailOut,
    OrderListItemOut,
    OrderStatusOut,
)
from app.services.order_service import OrderItemInput, OrderService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/orders",
    tags=["orders"],
    responses=error_responses(400, 401, 404, 409, 422),
)
OrderId = Annotated[int, Path(gt=0)]
CurrentUser = Annotated[User, Depends(get_current_user)]
OrderServiceDependency = Annotated[OrderService, Depends(get_order_service)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(OrderDetailOut, status.HTTP_201_CREATED),
)
async def create_order(
    data: OrderCreate,
    request: Request,
    current_user: CurrentUser,
    service: OrderServiceDependency,
) -> dict:
    """创建当前用户的 Experience、Kit 或混合订单。"""

    order = await service.create_order(
        user_id=current_user.id,
        items=[
            OrderItemInput(
                product_id=item.product_id,
                experience_option_id=item.experience_option_id,
                quantity=item.quantity,
            )
            for item in data.items
        ],
        remark=data.remark,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_order_detail(order).model_dump(mode="json"),
        message="Order created",
    )


@router.get(
    "",
    response_model=None,
    responses=success_responses(Page[OrderListItemOut]),
)
async def list_orders(
    query: Annotated[OrderListQuery, Query()],
    current_user: CurrentUser,
    service: OrderServiceDependency,
) -> dict:
    """分页查询当前用户自己的订单。"""

    page = await service.list_user_orders(
        user_id=current_user.id,
        page=query.page,
        page_size=query.page_size,
        status=query.status,
    )
    return success(data=map_order_page(page).model_dump(mode="json"))


@router.get(
    "/{order_id}",
    response_model=None,
    responses=success_responses(OrderDetailOut),
)
async def get_order_detail(
    order_id: OrderId,
    current_user: CurrentUser,
    service: OrderServiceDependency,
) -> dict:
    """查询当前用户可见的订单详情。"""

    order = await service.get_user_order_detail(
        order_id,
        user_id=current_user.id,
    )
    return success(data=map_order_detail(order).model_dump(mode="json"))


@router.patch(
    "/{order_id}/cancel",
    response_model=None,
    responses=success_responses(OrderStatusOut),
)
async def cancel_order(
    order_id: OrderId,
    request: Request,
    current_user: CurrentUser,
    service: OrderServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
) -> dict:
    """取消当前用户自己的 Pending 订单。"""

    order = await service.cancel_order(
        order_id,
        user_id=current_user.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_order_status_response(order).model_dump(mode="json"),
        message="Order cancelled",
    )
