"""用户 API —— 个人信息管理。"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.common.response import success
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import PasswordChange, UserOut
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return success(data=UserOut.model_validate(current_user).model_dump())


@router.put("/me/password")
async def change_password(
    data: PasswordChange,
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(),
):
    """修改密码。"""
    service = UserService(user_repo)
    await service.change_password(current_user, data)
    return success(message="Password changed")
