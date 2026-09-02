"""User Service —— 用户资料管理。

职责：
    - 修改密码（验证旧密码 → 哈希新密码 → 更新）
    - 不直接操作 Model，通过 Repository
    - 不调用其他 Service

注册和登录已迁移至 AuthService（认证属于 Auth 领域）。
"""

import logging

from app.common.exceptions.user import OldPasswordIncorrect, PhoneAlreadyExists
from app.core.exceptions import BusinessException
from app.core.security import hash_password, verify_password
from app.core.redis import revoke_user_refresh_sessions
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import PasswordChange, UserUpdate

logger = logging.getLogger(__name__)


class UserService:
    """用户资料业务逻辑。"""

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def change_password(self, user: User, data: PasswordChange) -> None:
        """修改密码。"""
        if user.password is None or not verify_password(data.old_password, user.password):
            raise OldPasswordIncorrect()

        hashed = hash_password(data.new_password)
        await self.user_repo.update(
            user,
            password=hashed,
            auth_version=user.auth_version + 1,
        )
        await revoke_user_refresh_sessions(user.id)
        logger.info("Password changed: user_id=%d", user.id)

    async def update_profile(self, user: User, data: UserUpdate) -> User:
        """更新个人资料——手机号/昵称/头像。

        只有传了值的字段才更新，未传保持原值。
        """
        updates = data.model_dump(exclude_none=True)
        if not updates:
            raise BusinessException(code=422, message="No fields to update")

        # 手机号查重（排除自己）
        if "phone" in updates:
            conflict = await self.user_repo.get_by_phone_exclude_id(
                updates["phone"], user.id
            )
            if conflict:
                raise PhoneAlreadyExists()

        updated = await self.user_repo.update(user, **updates)
        logger.info("Profile updated: user_id=%d fields=%s", user.id, list(updates.keys()))
        return updated
