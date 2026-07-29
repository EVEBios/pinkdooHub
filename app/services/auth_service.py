"""Auth Service —— 认证业务逻辑编排。

职责：
    - 注册（查重 → 哈希 → 入库）
    - 登录（验证 → JWT 双签发 → Redis 存储 refresh）
    - 刷新（验证 refresh → 签发新 access）
    - 登出（撤销 refresh token）

跨 User 和 Auth 两个领域，通过 UserRepository 获取用户数据。
"""

import logging
import uuid
from datetime import datetime, timezone

from app.common.enums.user import UserStatus
from app.common.exceptions.user import (
    IncorrectPassword,
    PhoneAlreadyExists,
    TokenExpired,
    UserDisabled,
    UsernameAlreadyExists,
    UserNotFound,
)
from app.core.redis import (
    delete_refresh_token,
    save_refresh_token,
    verify_refresh_token,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreate
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


class AuthService:
    """认证业务逻辑。"""

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    # ── 注册 ────────────────────────────────────

    async def register(self, data: UserCreate, ip_address: str = "") -> User:
        """注册新用户。"""
        existing = await self.user_repo.get_by_username(data.username)
        if existing:
            raise UsernameAlreadyExists()

        if data.phone:
            existing = await self.user_repo.get_by_phone(data.phone)
            if existing:
                raise PhoneAlreadyExists()

        hashed = hash_password(data.password)
        user = await self.user_repo.create(
            username=data.username,
            password=hashed,
            nickname=data.nickname,
            phone=data.phone,
        )
        await AuditLogService(AuditLogRepository()).log(
            operator_id=user.id,
            action="REGISTER",
            target_type="user",
            target_id=user.id,
            ip_address=ip_address,
        )
        logger.info("User registered: user_id=%d username=%s", user.id, user.username)
        return user

    # ── 登录 ────────────────────────────────────

    async def login(self, data: LoginRequest, ip_address: str = "") -> dict:
        """登录：验证凭证 → 签发双 Token → 存储 refresh。

        Returns:
            {"user": User, "access_token": str, "refresh_token": str}
        """
        user = await self.user_repo.get_by_username(data.username)
        if not user:
            raise UserNotFound()

        if user.status == UserStatus.DISABLED:
            raise UserDisabled()

        if not verify_password(data.password, user.password):
            raise IncorrectPassword()

        # 更新最后登录时间
        user.last_login_at = datetime.now(timezone.utc)
        await user.save(update_fields=["last_login_at"])

        # 签发双 Token（同一次登录共用 jti）
        jti = uuid.uuid4().hex
        access_token = create_access_token(user.id, jti)
        refresh_token = create_refresh_token(user.id, jti)
        await save_refresh_token(jti, user.id)
        await AuditLogService(AuditLogRepository()).log(
            operator_id=user.id,
            action="LOGIN",
            target_type="user",
            target_id=user.id,
            ip_address=ip_address,
        )

        logger.info("User logged in: user_id=%d username=%s", user.id, user.username)
        return {
            "user": user,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    # ── 刷新 ────────────────────────────────────

    async def refresh(self, refresh_token: str) -> dict:
        """用 refresh token 换取新的 access token。

        Phase 3: 不轮换 refresh token（Phase 4 加入）。
        """
        payload = decode_token(refresh_token, "refresh")
        jti = payload["jti"]
        user_id = int(payload["sub"])

        user_id_from_redis = await verify_refresh_token(jti)
        if not user_id_from_redis or user_id_from_redis != user_id:
            raise TokenExpired()

        access_token = create_access_token(user_id, jti)
        return {"access_token": access_token}

    # ── 登出 ────────────────────────────────────

    async def logout(self, access_token: str) -> None:
        """登出：从 access token 中提取 jti，删除对应的 refresh token。"""
        payload = decode_token(access_token, "access")
        jti = payload["jti"]
        await delete_refresh_token(jti)
        logger.info("User logged out: user_id=%s jti=%s", payload["sub"], jti)
