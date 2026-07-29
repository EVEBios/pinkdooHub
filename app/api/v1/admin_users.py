"""管理端用户 API —— 用户列表、禁用。

Phase 3.4: 分页筛选 + 角色层级保护 + 幂等禁用。
"""

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_current_admin
from app.common.pagination import PageParams
from app.common.response import success
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.services.admin_user_service import AdminUserService
from app.utils.request import get_client_ip

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    admin: User = Depends(get_current_admin),
    user_repo: UserRepository = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    role: str | None = Query(None),
):
    """分页获取用户列表，支持按 status/role 筛选。

    ?page=1&page_size=20&status=normal&role=user
    """
    service = AdminUserService(user_repo)
    params = PageParams(page=page, page_size=page_size)
    result = await service.list_users(params, status=status, role=role)
    return success(data=result.model_dump())


@router.put("/users/{user_id}/disable")
async def disable_user(
    user_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    user_repo: UserRepository = Depends(),
):
    """禁用指定用户。"""
    service = AdminUserService(user_repo)
    await service.disable_user(admin, user_id, ip_address=get_client_ip(request))
    return success(message="User disabled")
