"""认证 API —— 注册、登录。"""

from fastapi import APIRouter, Depends

from app.common.response import success
from app.core.security import create_access_token
from app.repositories.user_repo import UserRepository
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreate, UserOut
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(
    data: UserCreate,
    user_repo: UserRepository = Depends(),
):
    """用户注册。"""
    service = UserService(user_repo)
    user = await service.register(data)
    return success(data=UserOut.model_validate(user).model_dump())


@router.post("/login")
async def login(
    data: LoginRequest,
    user_repo: UserRepository = Depends(),
):
    """用户登录。

    验证用户名/密码 → 签发 JWT → 返回 Token + 用户信息。
    """
    service = UserService(user_repo)
    user = await service.login(data)
    access_token = create_access_token(user.id)
    return success(
        data={
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 7200,
            "user": UserOut.model_validate(user).model_dump(),
        }
    )
