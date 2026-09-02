"""管理端 Order API —— 查询、状态变迁与审计历史。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.api.deps import get_current_admin, get_order_service, reject_request_body
from app.api.mappers.audit import map_audit_log_page
from app.api.mappers.order import (
    map_admin_order_detail,
    map_admin_order_page,
    map_order_status_response,
)
from app.api.responses import error_responses, success_responses
from app.common.pagination import Page
from app.common.response import success
from app.models.user import User
from app.schemas.audit import AuditLogListQuery, AuditLogOut
from app.schemas.order import AdminOrderListQuery
from app.schemas.order_response import (
    AdminOrderDetailOut,
    AdminOrderListItemOut,
    OrderStatusOut,
)
from app.services.order_service import OrderService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/admin/orders",
    tags=["admin-orders"],
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
OrderId = Annotated[int, Path(gt=0)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
OrderServiceDependency = Annotated[OrderService, Depends(get_order_service)]


@router.get(
    "",
    response_model=None,
    responses=success_responses(Page[AdminOrderListItemOut]),
)
async def list_admin_orders(
    query: Annotated[AdminOrderListQuery, Query()],
    current_admin: CurrentAdmin,
    service: OrderServiceDependency,
) -> dict:
    """分页筛选全部订单。"""

    page = await service.list_admin_orders(
        page=query.page,
        page_size=query.page_size,
        status=query.status,
        order_no=query.order_no,
        product_name=query.product_name,
        user_id=query.user_id,
        created_from=query.created_from,
        created_to=query.created_to,
    )
    return success(data=map_admin_order_page(page).model_dump(mode="json"))


@router.get(
    "/{order_id}/audit-logs",
    response_model=None,
    responses=success_responses(Page[AuditLogOut]),
)
async def list_order_audit_logs(
    order_id: OrderId,
    query: Annotated[AuditLogListQuery, Query()],
    current_admin: CurrentAdmin,
    service: OrderServiceDependency,
) -> dict:
    """分页查询指定 Order 的操作历史。"""

    page = await service.list_order_audit_logs(
        order_id,
        page=query.page,
        page_size=query.page_size,
    )
    return success(data=map_audit_log_page(page).model_dump(mode="json"))


@router.get(
    "/{order_id}",
    response_model=None,
    responses=success_responses(AdminOrderDetailOut),
)
async def get_admin_order_detail(
    order_id: OrderId,
    current_admin: CurrentAdmin,
    service: OrderServiceDependency,
) -> dict:
    """查询任意 Order 的管理端详情。"""

    order = await service.get_admin_order_detail(order_id)
    return success(data=map_admin_order_detail(order).model_dump(mode="json"))


@router.patch(
    "/{order_id}/paid",
    response_model=None,
    responses=success_responses(OrderStatusOut),
)
async def mark_order_paid(
    order_id: OrderId,
    request: Request,
    current_admin: CurrentAdmin,
    service: OrderServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
) -> dict:
    """由 ADMIN+ 人工确认 Pending Order 已支付。"""

    order = await service.mark_order_paid(
        order_id,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_order_status_response(order).model_dump(mode="json"),
        message="Order marked as paid",
    )


@router.patch(
    "/{order_id}/complete",
    response_model=None,
    responses=success_responses(OrderStatusOut),
)
async def complete_order(
    order_id: OrderId,
    request: Request,
    current_admin: CurrentAdmin,
    service: OrderServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
) -> dict:
    """由 ADMIN+ 完成 Paid Order。"""

    order = await service.complete_order(
        order_id,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_order_status_response(order).model_dump(mode="json"),
        message="Order completed",
    )
