"""ADMIN+ 订单资金查询与全额退款 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request, Response, status

from app.api.deps import get_current_admin, get_payment_service, get_refund_service
from app.api.mappers.payment import map_order_financial, map_refund
from app.api.responses import error_responses, success_responses
from app.common.response import success
from app.models.user import User
from app.schemas.wallet import RefundCreate, WalletIdempotencyKey
from app.schemas.wallet_response import OrderFinancialOut, RefundOut
from app.services.payment_service import PaymentService
from app.services.refund_service import RefundService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/admin/orders",
    tags=["admin-refunds"],
    responses=error_responses(400, 401, 403, 404, 409, 422, 503),
)
OrderId = Annotated[int, Path(gt=0)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
PaymentServiceDependency = Annotated[PaymentService, Depends(get_payment_service)]
RefundServiceDependency = Annotated[RefundService, Depends(get_refund_service)]
IdempotencyKeyHeader = Annotated[
    WalletIdempotencyKey,
    Header(alias="Idempotency-Key"),
]


@router.get(
    "/{order_id}/financials",
    response_model=None,
    responses=success_responses(OrderFinancialOut),
)
async def get_admin_order_financials(
    order_id: OrderId,
    current_admin: CurrentAdmin,
    service: PaymentServiceDependency,
) -> dict:
    result = await service.get_admin_order_financials(order_id)
    return success(
        data=map_order_financial(
            result.order,
            payment=result.payment,
            refund=result.refund,
            inventory_restored=result.inventory_restored,
        ).model_dump(mode="json")
    )


@router.post(
    "/{order_id}/refunds",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        RefundOut,
        status.HTTP_200_OK,
        status.HTTP_201_CREATED,
    ),
)
async def refund_admin_order(
    order_id: OrderId,
    data: RefundCreate,
    idempotency_key: IdempotencyKeyHeader,
    request: Request,
    response: Response,
    current_admin: CurrentAdmin,
    service: RefundServiceDependency,
) -> dict:
    result = await service.refund_order(
        order_id,
        operator=current_admin,
        reason=data.reason,
        idempotency_key=idempotency_key,
        ip_address=get_client_ip(request),
    )
    if result.is_replay:
        response.status_code = status.HTTP_200_OK
    return success(
        data=map_refund(
            result.refund,
            payment=result.payment,
            inventory_restored=result.inventory_restored,
        ).model_dump(mode="json"),
        message="Order refunded",
    )
