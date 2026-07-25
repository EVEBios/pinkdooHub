"""User Service —— 用户业务逻辑编排。

职责：
    - 注册（查重 → 哈希密码 → 创建用户）
    - 不直接操作 Model，通过 Repository
    - 不调用其他 Service，跨领域通过 Repository
"""

import logging

from app.common.enums.user import UserStatus
from app.common.exceptions.user import (
    IncorrectPassword,
    PhoneAlreadyExists,
    UserDisabled,
    UsernameAlreadyExists,
    UserNotFound,
)
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserCreate, UserLogin

logger = logging.getLogger(__name__)


class UserService:
    """用户业务逻辑。"""

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def register(self, data: UserCreate) -> User:
        """注册新用户。

        流程：用户名查重 → 手机号查重 → 哈希密码 → 入库
        在业务层完成所有校验，不依赖数据库报错。
        """
        # 1. 用户名查重
        existing = await self.user_repo.get_by_username(data.username)
        if existing:
            raise UsernameAlreadyExists()

        # 2. 手机号查重
        if data.phone:
            existing = await self.user_repo.get_by_phone(data.phone)
            if existing:
                raise PhoneAlreadyExists()

        # 3. 哈希密码
        hashed = hash_password(data.password)

        # 4. 入库
        user = await self.user_repo.create(
            username=data.username,
            password=hashed,
            nickname=data.nickname,
            phone=data.phone,
        )
        logger.info("User registered: user_id=%d username=%s", user.id, user.username)
        return user

    async def login(self, data: UserLogin) -> User:
        """用户登录。

        流程：查用户 → 验状态 → 验密码 → 返回用户
        Phase 3 将在此处签发 JWT Token。
        """
        # 1. 查用户
        user = await self.user_repo.get_by_username(data.username)
        if not user:
            raise UserNotFound()

        # 2. 验状态
        if user.status == UserStatus.DISABLED:
            raise UserDisabled()

        # 3. 验密码
        if not verify_password(data.password, user.password):
            raise IncorrectPassword()

        logger.info("User logged in: user_id=%d username=%s", user.id, user.username)
        return user
