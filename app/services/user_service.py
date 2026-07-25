"""User Service —— 用户业务逻辑编排。

职责：
    - 注册（查重 → 哈希密码 → 创建用户）
    - 不直接操作 Model，通过 Repository
    - 不调用其他 Service，跨领域通过 Repository
"""

import logging

from app.core.exceptions import BusinessException
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserCreate

logger = logging.getLogger(__name__)


class UserService:
    """用户业务逻辑。"""

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def register(self, data: UserCreate) -> User:
        """注册新用户。

        流程：查重 → 哈希密码 → 入库
        """
        # 1. 查重
        existing = await self.user_repo.get_by_username(data.username)
        if existing:
            raise BusinessException(code=1001, message="Username already exists")

        # 2. 哈希密码
        hashed = hash_password(data.password)

        # 3. 入库（不含 password 的响应由 Schema 过滤）
        user = await self.user_repo.create(
            username=data.username,
            password=hashed,
            nickname=data.nickname,
            phone=data.phone,
        )
        logger.info("User registered: user_id=%d username=%s", user.id, user.username)
        return user
