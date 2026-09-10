"""ADMIN+ 固定桌台、会话查询与应急释放 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request

from app.api.deps import get_current_admin, get_table_session_service
from app.api.mappers.table_session import (
    map_admin_table_list,
    map_admin_table_session,
    map_admin_table_session_page,
    map_table_summary,
)
from app.api.responses import error_responses, success_responses
from app.common.pagination import Page
from app.common.response import success
from app.models.user import User
from app.schemas.table_session import (
    AdminTableSessionListQuery,
    AdminTableSessionRelease,
    AdminTableUpdate,
    TableIdempotencyKey,
    TableSessionNumber,
)
from app.schemas.table_session_response import (
    AdminTableListOut,
    AdminTableSessionListItemOut,
    AdminTableSessionOut,
    TableSummaryOut,
)
from app.services.table_session_service import TableSessionService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/admin",
    tags=["admin-table-sessions"],
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
TableService = Annotated[TableSessionService, Depends(get_table_session_service)]
IdempotencyKeyHeader = Annotated[
    TableIdempotencyKey,
    Header(alias="Idempotency-Key"),
]


@router.get(
    "/tables",
    response_model=None,
    responses=success_responses(AdminTableListOut),
)
async def list_admin_tables(
    current_admin: CurrentAdmin,
    service: TableService,
) -> dict:
    tables = await service.list_admin_tables()
    return success(data=map_admin_table_list(tables).model_dump(mode="json"))


@router.patch(
    "/tables/{table_id}",
    response_model=None,
    responses=success_responses(TableSummaryOut),
)
async def update_admin_table(
    table_id: Annotated[int, Path(gt=0)],
    data: AdminTableUpdate,
    request: Request,
    current_admin: CurrentAdmin,
    service: TableService,
) -> dict:
    table = await service.update_table(
        table_id=table_id,
        is_enabled=data.is_enabled,
        reason=data.reason,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_table_summary(table).model_dump(mode="json"))


@router.get(
    "/table-sessions",
    response_model=None,
    responses=success_responses(Page[AdminTableSessionListItemOut]),
)
async def list_admin_table_sessions(
    query: Annotated[AdminTableSessionListQuery, Query()],
    current_admin: CurrentAdmin,
    service: TableService,
) -> dict:
    page = await service.list_admin_sessions(
        page=query.page,
        page_size=query.page_size,
        table_id=query.table_id,
        user_id=query.user_id,
        order_id=query.order_id,
        status=query.status,
        close_reason=query.close_reason,
        claimed_from=query.claimed_from,
        claimed_to=query.claimed_to,
    )
    return success(data=map_admin_table_session_page(page).model_dump(mode="json"))


@router.get(
    "/table-sessions/{session_no}",
    response_model=None,
    responses=success_responses(AdminTableSessionOut),
)
async def get_admin_table_session(
    session_no: Annotated[TableSessionNumber, Path()],
    current_admin: CurrentAdmin,
    service: TableService,
) -> dict:
    session = await service.get_admin_session(session_no)
    return success(data=map_admin_table_session(session).model_dump(mode="json"))


@router.post(
    "/table-sessions/{session_no}/release",
    response_model=None,
    responses=success_responses(AdminTableSessionOut),
)
async def release_admin_table_session(
    session_no: Annotated[TableSessionNumber, Path()],
    data: AdminTableSessionRelease,
    idempotency_key: IdempotencyKeyHeader,
    request: Request,
    current_admin: CurrentAdmin,
    service: TableService,
) -> dict:
    result = await service.release_session(
        session_no=session_no,
        operator_id=current_admin.id,
        reason=data.reason,
        idempotency_key=idempotency_key,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_admin_table_session(result.session).model_dump(mode="json"),
        message="Table session released",
    )
