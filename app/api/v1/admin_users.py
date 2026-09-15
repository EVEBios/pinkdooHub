"""管理端用户 API —— 严格分页筛选与幂等禁用。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.api.deps import (
    get_admin_user_service,
    get_current_admin,
    reject_request_body,
)
from app.api.mappers.user import map_admin_user_page
from app.api.responses import error_responses, success_responses
from app.common.enums.user import UserRole, UserStatus
from app.common.pagination import Page, PageParams
from app.common.response import success
from app.models.user import User
from app.schemas.user import AdminUserListQuery, UserListItem
from app.services.admin_user_service import AdminUserService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/admin/users",
    tags=["admin-users"],
    responses=error_responses(400, 401, 403, 422),
)
UserId = Annotated[int, Path(gt=0)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
AdminUserServiceDependency = Annotated[
    AdminUserService,
    Depends(get_admin_user_service),
]

_STATUS_BY_VALUE = {
    "normal": UserStatus.NORMAL,
    "disabled": UserStatus.DISABLED,
    "deleted": UserStatus.DELETED,
}
_ROLE_BY_VALUE = {
    "user": UserRole.USER,
    "admin": UserRole.ADMIN,
    "super_admin": UserRole.SUPER_ADMIN,
}


@router.get(
    "",
    response_model=None,
    responses=success_responses(Page[UserListItem]),
)
async def list_users(
    query: Annotated[AdminUserListQuery, Query()],
    current_admin: CurrentAdmin,
    service: AdminUserServiceDependency,
) -> dict:
    """按状态、角色稳定倒序分页查询用户安全摘要。"""

    page = await service.list_users(
        PageParams(page=query.page, page_size=query.page_size),
        status=_STATUS_BY_VALUE[query.status] if query.status else None,
        role=_ROLE_BY_VALUE[query.role] if query.role else None,
    )
    return success(data=map_admin_user_page(page).model_dump(mode="json"))


@router.put(
    "/{user_id}/disable",
    response_model=None,
    responses=success_responses(type(None)),
)
async def disable_user(
    user_id: UserId,
    request: Request,
    current_admin: CurrentAdmin,
    service: AdminUserServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
) -> dict:
    """幂等禁用指定用户，状态写入与审计日志同事务提交。"""

    await service.disable_user(
        current_admin,
        user_id,
        ip_address=get_client_ip(request),
    )
    return success(message="User disabled")
