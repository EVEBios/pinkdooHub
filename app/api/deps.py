"""API 依赖注入。"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token
from app.models.user import User
from app.repositories.user_repo import UserRepository

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_repo: UserRepository = Depends(),
) -> User:
    """从 Authorization Header 解析 JWT，返回当前登录用户。"""
    payload = decode_token(credentials.credentials, "access")
    user = await user_repo.get_by_id(int(payload["sub"]))
    if not user:
        from app.core.exceptions import NotFoundException
        raise NotFoundException(message="User not found")
    return user
