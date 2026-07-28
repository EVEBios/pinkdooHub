"""User Service —— 用户资料管理。

职责：
    - 修改密码（验证旧密码 → 哈希新密码 → 更新）
    - 不直接操作 Model，通过 Repository
    - 不调用其他 Service

注册和登录已迁移至 AuthService（认证属于 Auth 领域）。
"""

import logging

from app.common.exceptions.user import OldPasswordIncorrect
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import PasswordChange

logger = logging.getLogger(__name__)


class UserService:
    """用户资料业务逻辑。"""

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def change_password(self, user: User, data: PasswordChange) -> None:
        """修改密码。"""
        if not verify_password(data.old_password, user.password):
            raise OldPasswordIncorrect()

        hashed = hash_password(data.new_password)
        await self.user_repo.update(user, password=hashed)
        logger.info("Password changed: user_id=%d", user.id)
