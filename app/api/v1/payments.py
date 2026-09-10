"""用户订单支付与资金事实查询 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request, Response, status

from app.api.deps import (
    get_current_customer,
    get_payment_service,
    reject_request_body,
)
from app.api.mappers.payment import map_order_financial, map_wallet_payment
from app.api.responses import error_responses, success_responses
from app.common.response import success
from app.models.user import User
from app.schemas.wallet import WalletIdempotencyKey
from app.schemas.table_session import TableSessionNumber
from app.schemas.wallet_response import OrderFinancialOut, WalletPaymentOut
from app.services.payment_service import PaymentService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/orders",
    tags=["payments"],
    responses=error_responses(400, 401, 403, 404, 409, 422, 503),
)
OrderId = Annotated[int, Path(gt=0)]
CurrentUser = Annotated[User, Depends(get_current_customer)]
PaymentServiceDependency = Annotated[PaymentService, Depends(get_payment_service)]
IdempotencyKeyHeader = Annotated[
    WalletIdempotencyKey,
    Header(alias="Idempotency-Key"),
]


@router.get(
    "/{order_id}/financials",
    response_model=None,
    responses=success_responses(OrderFinancialOut),
)
async def get_order_financials(
    order_id: OrderId,
    current_user: CurrentUser,
    service: PaymentServiceDependency,
) -> dict:
    result = await service.get_user_order_financials(
        order_id,
        user_id=current_user.id,
    )
    return success(
        data=map_order_financial(
            result.order,
            payment=result.payment,
            refund=result.refund,
            inventory_restored=result.inventory_restored,
        ).model_dump(mode="json")
    )


@router.post(
    "/{order_id}/payments/wallet",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        WalletPaymentOut,
        status.HTTP_200_OK,
        status.HTTP_201_CREATED,
    ),
)
async def pay_order_with_wallet(
    order_id: OrderId,
    idempotency_key: IdempotencyKeyHeader,
    request: Request,
    response: Response,
    current_user: CurrentUser,
    service: PaymentServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
    table_session_no: Annotated[
        TableSessionNumber | None,
        Header(alias="Table-Session-No"),
    ] = None,
) -> dict:
    result = await service.pay_order_with_wallet(
        order_id,
        user=current_user,
        idempotency_key=idempotency_key,
        ip_address=get_client_ip(request),
        table_session_no=table_session_no,
    )
    if result.is_replay:
        response.status_code = status.HTTP_200_OK
    return success(
        data=map_wallet_payment(
            result.order,
            payment=result.payment,
            post_payment_balance=result.post_payment_balance,
        ).model_dump(mode="json"),
        message="Order paid with wallet",
    )


@router.post(
    "/{order_id}/payments/wechat",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(type(None), status.HTTP_201_CREATED),
)
async def create_wechat_order_payment(
    order_id: OrderId,
    idempotency_key: IdempotencyKeyHeader,
    current_user: CurrentUser,
    service: PaymentServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
) -> dict:
    await service.create_wechat_order_payment(
        order_id,
        user=current_user,
        idempotency_key=idempotency_key,
    )
    return success(message="WeChat payment created")
