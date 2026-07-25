"""认证 API —— 注册、登录、Token 刷新。

Phase 2: 仅实现 POST /auth/register。
Phase 3: 将加入 login、refresh、JWT 认证。
"""

from fastapi import APIRouter, Depends

from app.common.response import success
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserCreate, UserOut
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    data: UserCreate,
    user_repo: UserRepository = Depends(),
) -> UserOut:
    """用户注册。

    校验参数 → 查重 → 哈希密码 → 入库。
    成功返回用户信息（不含 password）。
    """
    service = UserService(user_repo)
    user = await service.register(data)
    return user
