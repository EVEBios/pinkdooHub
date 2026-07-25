"""认证 API —— 注册、登录。

Phase 2: POST /auth/register, POST /auth/login。
Phase 3: 将加入 JWT 签发、refresh、认证中间件。
"""

from fastapi import APIRouter, Depends

from app.common.response import success
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserCreate, UserLogin, UserOut
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    data: UserCreate,
    user_repo: UserRepository = Depends(),
) -> UserOut:
    """用户注册。"""
    service = UserService(user_repo)
    user = await service.register(data)
    return user


@router.post("/login", response_model=UserOut)
async def login(
    data: UserLogin,
    user_repo: UserRepository = Depends(),
) -> UserOut:
    """用户登录。

    验证用户名、状态、密码，成功返回用户信息。
    Phase 3 将在此签发 JWT Token。
    """
    service = UserService(user_repo)
    user = await service.login(data)
    return user
