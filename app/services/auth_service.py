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
    RegistrationDisabled,
    TokenExpired,
    UserDisabled,
    UserDeleted,
    UsernameAlreadyExists,
)
from app.core.auth_session import issue_token_pair
from app.core.redis import (
    RefreshRotationResult,
    RefreshTokenState,
    get_refresh_token_state,
    revoke_refresh_family,
    rotate_refresh_session,
)
from app.core.config import settings
from app.core.rate_limit import (
    AuthRateLimiter,
    LOGIN_IP_POLICY,
    LOGIN_SUBJECT_POLICY,
    REFRESH_POLICY,
    REGISTER_IP_POLICY,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    dummy_verify_password,
    hash_password,
    verify_password,
)
from app.core.security_events import emit_security_event
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import LoginRequest
from app.schemas.user import UserCreate
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


class AuthService:
    """认证业务逻辑。"""

    def __init__(
        self,
        user_repo: UserRepository,
        rate_limiter: AuthRateLimiter | None = None,
    ) -> None:
        self.user_repo = user_repo
        self.rate_limiter = rate_limiter or AuthRateLimiter()

    # ── 注册 ────────────────────────────────────

    async def register(self, data: UserCreate, ip_address: str = "") -> User:
        """注册新用户。"""
        await self.rate_limiter.check(REGISTER_IP_POLICY, ip_address or "unknown")
        if not settings.password_registration_enabled:
            raise RegistrationDisabled()
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
        await self.rate_limiter.check(LOGIN_IP_POLICY, ip_address or "unknown")
        await self.rate_limiter.check(
            LOGIN_SUBJECT_POLICY,
            f"{ip_address or 'unknown'}:{data.username.casefold()}",
        )
        user = await self.user_repo.get_by_username(data.username)
        if not user:
            dummy_verify_password()
            raise IncorrectPassword()

        if user.password is None:
            dummy_verify_password()
            raise IncorrectPassword()
        if not verify_password(data.password, user.password):
            raise IncorrectPassword()
        if user.status == UserStatus.DISABLED:
            raise UserDisabled()
        if user.status == UserStatus.DELETED:
            raise UserDeleted()

        # 更新最后登录时间
        user.last_login_at = datetime.now(timezone.utc)
        await user.save(update_fields=["last_login_at"])

        tokens = await issue_token_pair(
            user_id=user.id,
            auth_version=user.auth_version,
        )
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
            **tokens,
        }

    # ── 刷新 ────────────────────────────────────

    async def refresh(self, refresh_token: str, ip_address: str = "") -> dict:
        """用 refresh token 换取新的 access token。

        成功后旧 refresh token 立即失效，响应返回新双 Token。
        """
        # Refresh Token 每次成功都会轮换；若以 Token 本身作为 principal，
        # 正常调用永远落入新桶，无法约束同一来源的高频刷新。
        await self.rate_limiter.check(REFRESH_POLICY, ip_address or "unknown")
        payload = decode_token(refresh_token, "refresh")
        jti = payload["jti"]
        session_id = payload["sid"]
        user_id = int(payload["sub"])

        token_state = await get_refresh_token_state(jti)
        if token_state == RefreshTokenState.MISSING:
            raise TokenExpired()
        if token_state == RefreshTokenState.USED:
            await rotate_refresh_session(
                old_jti=jti,
                new_jti=uuid.uuid4().hex,
                session_id=session_id,
                user_id=user_id,
            )
            emit_security_event(
                "refresh_reuse",
                "family_revoked",
                level=logging.WARNING,
                user_id=user_id,
            )
            logger.warning("Refresh token reuse detected; family revoked")
            raise TokenExpired()

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            await revoke_refresh_family(session_id)
            raise TokenExpired()
        if user.status == UserStatus.DISABLED:
            await revoke_refresh_family(session_id)
            raise UserDisabled()
        if user.status == UserStatus.DELETED:
            await revoke_refresh_family(session_id)
            raise UserDeleted()
        if payload["ver"] != user.auth_version:
            await revoke_refresh_family(session_id)
            raise TokenExpired()

        new_jti = uuid.uuid4().hex
        rotation = await rotate_refresh_session(
            old_jti=jti,
            new_jti=new_jti,
            session_id=session_id,
            user_id=user_id,
        )
        if rotation == RefreshRotationResult.REUSED:
            emit_security_event(
                "refresh_reuse",
                "family_revoked",
                level=logging.WARNING,
                user_id=user_id,
            )
            logger.warning("Refresh token reuse detected; family revoked")
            raise TokenExpired()
        if rotation != RefreshRotationResult.ROTATED:
            raise TokenExpired()

        access_token = create_access_token(
            user_id,
            new_jti,
            session_id=session_id,
            auth_version=user.auth_version,
        )
        new_refresh_token = create_refresh_token(
            user_id,
            new_jti,
            session_id=session_id,
            auth_version=user.auth_version,
        )
        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
        }

    # ── 登出 ────────────────────────────────────

    async def logout(self, access_token: str) -> None:
        """登出：从 access token 中提取 jti，删除对应的 refresh token。"""
        payload = decode_token(access_token, "access")
        await revoke_refresh_family(payload["sid"])
        logger.info("User logged out: user_id=%s", payload["sub"])
