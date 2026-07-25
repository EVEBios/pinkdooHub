"""API 依赖注入。

提供 FastAPI Depends() 可用的认证和数据库依赖。
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repo import UserRepository

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_repo: UserRepository = Depends(),
) -> User:
    """从 Authorization Header 解析 JWT，返回当前登录用户。

    用法：
        @router.get("/users/me")
        async def me(current_user: User = Depends(get_current_user)):
            return current_user

    Token 无效 → AuthenticationException → 401
    用户不存在 → NotFoundException → 404
    """
    payload = decode_access_token(credentials.credentials)
    user = await user_repo.get_by_id(int(payload["sub"]))
    if not user:
        from app.core.exceptions import NotFoundException
        raise NotFoundException(message="User not found")
    return user
