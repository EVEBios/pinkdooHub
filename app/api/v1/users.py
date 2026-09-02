"""用户 API —— 个人信息管理。"""

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_account_lifecycle_service, get_current_user
from app.api.responses import error_responses, success_responses
from app.common.response import success
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import AccountDeletionRequest, PasswordChange, UserOut, UserUpdate
from app.services.account_lifecycle_service import AccountLifecycleService
from app.services.user_service import UserService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses=error_responses(400, 401, 403, 422, 503),
)


@router.get(
    "/me",
    response_model=None,
    responses=success_responses(UserOut),
)
async def get_me(current_user: User = Depends(get_current_user)) -> dict:
    """获取当前登录用户信息。"""
    return success(data=UserOut.model_validate(current_user).model_dump())


@router.patch(
    "/me",
    response_model=None,
    responses=success_responses(UserOut),
)
async def update_profile(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(),
) -> dict:
    """更新个人资料——只更新传了值的字段。"""
    service = UserService(user_repo)
    updated = await service.update_profile(current_user, data)
    return success(data=UserOut.model_validate(updated).model_dump())


@router.put(
    "/me/password",
    response_model=None,
    responses=success_responses(type(None)),
)
async def change_password(
    data: PasswordChange,
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(),
) -> dict:
    """修改密码。"""
    service = UserService(user_repo)
    await service.change_password(current_user, data)
    return success(message="Password changed")


@router.delete(
    "/me",
    response_model=None,
    responses=success_responses(type(None)),
)
async def delete_my_account(
    data: AccountDeletionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: AccountLifecycleService = Depends(get_account_lifecycle_service),
) -> dict:
    """二次验证后逻辑注销并匿名化当前普通用户。"""

    await service.delete_account(
        user=current_user,
        data=data,
        ip_address=get_client_ip(request),
    )
    return success(message="Account deleted")
