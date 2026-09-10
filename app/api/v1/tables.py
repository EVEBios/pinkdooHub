"""公开桌台码与普通用户开台/计时 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status

from app.api.deps import get_current_customer, get_table_session_service
from app.api.mappers.table_session import (
    map_eligible_order_page,
    map_public_table_code,
    map_table_session,
)
from app.api.responses import error_responses, success_responses
from app.common.pagination import Page
from app.common.response import success
from app.core.rate_limit import (
    TABLE_CREATE_IP_POLICY,
    TABLE_CREATE_USER_POLICY,
    TABLE_RESOLVE_IP_POLICY,
    TABLE_USER_READ_POLICY,
    TableRateLimiter,
)
from app.models.user import User
from app.schemas.table_session import (
    EligibleOrderListQuery,
    TableIdempotencyKey,
    TableQrToken,
    TableSessionCreate,
)
from app.schemas.table_session_response import (
    EligibleOrderListItemOut,
    PublicTableCodeOut,
    TableSessionOut,
)
from app.services.table_session_service import TableSessionService
from app.utils.request import get_client_ip

router = APIRouter(
    tags=["table-sessions"],
    responses=error_responses(400, 401, 403, 404, 409, 422, 429, 503),
)
CurrentCustomer = Annotated[User, Depends(get_current_customer)]
TableService = Annotated[TableSessionService, Depends(get_table_session_service)]
IdempotencyKeyHeader = Annotated[
    TableIdempotencyKey,
    Header(alias="Idempotency-Key"),
]


@router.get(
    "/table-codes/{qr_token}",
    response_model=None,
    responses=success_responses(PublicTableCodeOut),
)
async def resolve_table_code(
    qr_token: Annotated[TableQrToken, Path()],
    request: Request,
    service: TableService,
) -> dict:
    client_ip = get_client_ip(request)
    await TableRateLimiter().check(TABLE_RESOLVE_IP_POLICY, client_ip)
    result = await service.resolve_table_code(qr_token)
    return success(
        data=map_public_table_code(
            result.table,
            is_available=result.is_available,
        ).model_dump(mode="json")
    )

@router.get(
    "/table-sessions/eligible-orders",
    response_model=None,
    responses=success_responses(Page[EligibleOrderListItemOut]),
)
async def list_eligible_orders(
    query: Annotated[EligibleOrderListQuery, Query()],
    current_user: CurrentCustomer,
    service: TableService,
) -> dict:
    await TableRateLimiter().check(TABLE_USER_READ_POLICY, f"eligible:{current_user.id}")
    page = await service.list_eligible_orders(
        user_id=current_user.id,
        page=query.page,
        page_size=query.page_size,
    )
    return success(data=map_eligible_order_page(page).model_dump(mode="json"))


@router.post(
    "/table-sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        TableSessionOut,
        status.HTTP_200_OK,
        status.HTTP_201_CREATED,
    ),
)
async def create_table_session(
    data: TableSessionCreate,
    idempotency_key: IdempotencyKeyHeader,
    request: Request,
    response: Response,
    current_user: CurrentCustomer,
    service: TableService,
) -> dict:
    client_ip = get_client_ip(request)
    limiter = TableRateLimiter()
    await limiter.check(TABLE_CREATE_USER_POLICY, str(current_user.id))
    await limiter.check(TABLE_CREATE_IP_POLICY, client_ip)
    result = await service.create_session(
        user=current_user,
        qr_token=data.qr_token,
        order_id=data.order_id,
        idempotency_key=idempotency_key,
        ip_address=client_ip,
    )
    if result.is_replay:
        response.status_code = status.HTTP_200_OK
    return success(
        data=map_table_session(result.session).model_dump(mode="json"),
        message="Table session created",
    )


@router.get(
    "/table-sessions/current",
    response_model=None,
    responses=success_responses(TableSessionOut | None),
)
async def get_current_table_session(
    current_user: CurrentCustomer,
    service: TableService,
) -> dict:
    await TableRateLimiter().check(TABLE_USER_READ_POLICY, f"current:{current_user.id}")
    session = await service.get_current_session(user_id=current_user.id)
    return success(
        data=(
            map_table_session(session).model_dump(mode="json")
            if session is not None
            else None
        )
    )


@router.get(
    "/orders/{order_id}/table-session",
    response_model=None,
    responses=success_responses(TableSessionOut | None),
)
async def get_order_table_session(
    order_id: Annotated[int, Path(gt=0)],
    current_user: CurrentCustomer,
    service: TableService,
) -> dict:
    await TableRateLimiter().check(
        TABLE_USER_READ_POLICY,
        f"order:{current_user.id}",
    )
    session = await service.get_latest_order_session(
        order_id=order_id,
        user_id=current_user.id,
    )
    return success(
        data=(
            map_table_session(session).model_dump(mode="json")
            if session is not None
            else None
        )
    )
