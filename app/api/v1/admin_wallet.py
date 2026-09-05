"""ADMIN+ 用户钱包查询与余额调整 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status

from app.api.deps import get_current_admin, get_order_service, get_wallet_service
from app.api.mappers.payment import map_assisted_wallet_order
from app.api.mappers.wallet import (
    map_admin_user_wallet,
    map_wallet_adjustment,
    map_wallet_transaction_page,
)
from app.api.responses import error_responses, success_responses
from app.common.pagination import Page
from app.common.response import success
from app.models.user import User
from app.schemas.order import OrderCreate
from app.schemas.wallet import (
    WalletAdjustmentCreate,
    WalletIdempotencyKey,
    WalletTransactionQuery,
)
from app.schemas.wallet_response import (
    AssistedWalletOrderOut,
    AdminUserWalletOut,
    WalletAdjustmentOut,
    WalletTransactionOut,
)
from app.services.order_service import OrderItemInput, OrderService
from app.services.wallet_service import WalletService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/admin/users",
    tags=["admin-wallet"],
    responses=error_responses(400, 401, 403, 404, 409, 422, 503),
)
UserId = Annotated[int, Path(gt=0)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
WalletServiceDependency = Annotated[WalletService, Depends(get_wallet_service)]
OrderServiceDependency = Annotated[OrderService, Depends(get_order_service)]
IdempotencyKeyHeader = Annotated[
    WalletIdempotencyKey,
    Header(alias="Idempotency-Key"),
]


@router.get(
    "/{user_id}/wallet",
    response_model=None,
    responses=success_responses(AdminUserWalletOut),
)
async def get_admin_user_wallet(
    user_id: UserId,
    current_admin: CurrentAdmin,
    service: WalletServiceDependency,
) -> dict:
    target, account = await service.get_admin_user_wallet(
        operator=current_admin,
        user_id=user_id,
    )
    return success(
        data=map_admin_user_wallet(target, account).model_dump(mode="json")
    )


@router.get(
    "/{user_id}/wallet-transactions",
    response_model=None,
    responses=success_responses(Page[WalletTransactionOut]),
)
async def list_admin_user_wallet_transactions(
    user_id: UserId,
    query: Annotated[WalletTransactionQuery, Query()],
    current_admin: CurrentAdmin,
    service: WalletServiceDependency,
) -> dict:
    page = await service.list_admin_user_transactions(
        operator=current_admin,
        user_id=user_id,
        page=query.page,
        page_size=query.page_size,
    )
    return success(data=map_wallet_transaction_page(page).model_dump(mode="json"))


@router.post(
    "/{user_id}/wallet-adjustments",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        WalletAdjustmentOut,
        status.HTTP_200_OK,
        status.HTTP_201_CREATED,
    ),
)
async def adjust_admin_user_wallet(
    user_id: UserId,
    data: WalletAdjustmentCreate,
    idempotency_key: IdempotencyKeyHeader,
    request: Request,
    response: Response,
    current_admin: CurrentAdmin,
    service: WalletServiceDependency,
) -> dict:
    result = await service.adjust_balance(
        operator=current_admin,
        user_id=user_id,
        change=data.change,
        reason=data.reason,
        idempotency_key=idempotency_key,
        ip_address=get_client_ip(request),
    )
    if result.is_replay:
        response.status_code = status.HTTP_200_OK
    payload = map_wallet_adjustment(
        result.account,
        result.transaction,
        result_balance=result.result_balance,
    )
    return success(data=payload.model_dump(mode="json"))


@router.post(
    "/{user_id}/wallet-orders",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        AssistedWalletOrderOut,
        status.HTTP_200_OK,
        status.HTTP_201_CREATED,
    ),
)
async def create_assisted_wallet_order(
    user_id: UserId,
    data: OrderCreate,
    idempotency_key: IdempotencyKeyHeader,
    request: Request,
    response: Response,
    current_admin: CurrentAdmin,
    service: OrderServiceDependency,
) -> dict:
    """为普通客户创建真实商品订单，并在同一事务中扣减钱包。"""

    result = await service.create_assisted_wallet_order(
        operator=current_admin,
        user_id=user_id,
        items=[
            OrderItemInput(
                product_id=item.product_id,
                experience_option_id=item.experience_option_id,
                quantity=item.quantity,
            )
            for item in data.items
        ],
        remark=data.remark,
        idempotency_key=idempotency_key,
        ip_address=get_client_ip(request),
    )
    if result.is_replay:
        response.status_code = status.HTTP_200_OK
    payload = map_assisted_wallet_order(
        result.order,
        payment=result.payment,
        post_payment_balance=result.post_payment_balance,
    )
    return success(data=payload.model_dump(mode="json"))
