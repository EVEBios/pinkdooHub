"""用户会员钱包 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.api.deps import get_current_customer, get_payment_service, get_wallet_service
from app.api.mappers.wallet import map_member, map_wallet_transaction_page
from app.api.responses import error_responses, success_responses
from app.common.pagination import Page
from app.common.response import success
from app.models.user import User
from app.schemas.wallet import (
    RechargeCreate,
    WalletIdempotencyKey,
    WalletTransactionQuery,
)
from app.schemas.wallet_response import MemberOut, WalletTransactionOut
from app.services.payment_service import PaymentService
from app.services.wallet_service import WalletService

router = APIRouter(
    prefix="/wallet",
    tags=["wallet"],
    responses=error_responses(400, 401, 403, 404, 409, 422, 503),
)
CurrentUser = Annotated[User, Depends(get_current_customer)]
WalletServiceDependency = Annotated[WalletService, Depends(get_wallet_service)]
PaymentServiceDependency = Annotated[PaymentService, Depends(get_payment_service)]
IdempotencyKeyHeader = Annotated[
    WalletIdempotencyKey,
    Header(alias="Idempotency-Key"),
]


@router.get(
    "",
    response_model=None,
    responses=success_responses(MemberOut),
)
async def get_member_wallet(
    current_user: CurrentUser,
    service: WalletServiceDependency,
) -> dict:
    """返回当前普通用户资料、权威余额、上限与能力开关。"""

    account = await service.get_member_wallet(current_user)
    return success(data=map_member(current_user, account).model_dump(mode="json"))


@router.get(
    "/transactions",
    response_model=None,
    responses=success_responses(Page[WalletTransactionOut]),
)
async def list_wallet_transactions(
    query: Annotated[WalletTransactionQuery, Query()],
    current_user: CurrentUser,
    service: WalletServiceDependency,
) -> dict:
    """分页查询当前普通用户自己的不可变钱包流水。"""

    page = await service.list_user_transactions(
        user=current_user,
        page=query.page,
        page_size=query.page_size,
    )
    return success(data=map_wallet_transaction_page(page).model_dump(mode="json"))


@router.post(
    "/recharges",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(type(None), status.HTTP_201_CREATED),
)
async def create_wallet_recharge(
    data: RechargeCreate,
    idempotency_key: IdempotencyKeyHeader,
    current_user: CurrentUser,
    service: PaymentServiceDependency,
) -> dict:
    """创建真实充值意图；Provider 未就绪时稳定返回 503 且零写入。"""

    await service.create_recharge_intent(
        user=current_user,
        amount=data.amount,
        idempotency_key=idempotency_key,
    )
    return success(message="Recharge intent created")
