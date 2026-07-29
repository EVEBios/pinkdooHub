"""API 依赖注入。

Depends 链式组合：

    HTTPBearer  →  get_current_user  →  get_current_admin  →  get_current_super_admin
    提取Token      验证JWT+查库         role >= ADMIN         role == SUPER_ADMIN

每一层只做一件事，外层层依赖内层，FastAPI 自动递归解析。
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.common.enums.user import UserRole
from app.core.exceptions import PermissionException
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


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """要求管理员及以上角色。"""
    if current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise PermissionException(message="Admin access required")
    return current_user


async def get_current_super_admin(
    current_user: User = Depends(get_current_admin),
) -> User:
    """要求超级管理员角色。"""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise PermissionException(message="Super admin access required")
    return current_user
