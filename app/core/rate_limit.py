"""认证边界的 Redis 原子限流。"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

from redis.exceptions import RedisError

from app.core.config import settings
from app.core.exceptions import ServiceUnavailableException, TooManyRequestsException
from app.common.exceptions.table_session import TableRateLimitExceeded
from app.core.redis import increment_rate_limit
from app.core.security_events import emit_security_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """固定窗口限流策略。"""

    scope: str
    limit: int
    window_seconds: int


class AuthRateLimiter:
    """对身份敏感端点执行 fail-closed 限流。"""

    async def check(self, policy: RateLimitPolicy, principal: str) -> None:
        digest = hmac.new(
            settings.jwt_secret_key.encode("utf-8"),
            principal.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        key = f"rate:auth:{policy.scope}:{digest}"
        try:
            count = await increment_rate_limit(key, policy.window_seconds)
        except (RedisError, RuntimeError):
            emit_security_event(
                "auth_rate_limit",
                "unavailable",
                level=logging.ERROR,
                scope=policy.scope,
            )
            logger.error("Authentication rate limiter unavailable", exc_info=True)
            raise ServiceUnavailableException(
                message="Authentication service temporarily unavailable"
            )
        if count > policy.limit:
            emit_security_event(
                "auth_rate_limit",
                "blocked",
                level=logging.WARNING,
                scope=policy.scope,
            )
            logger.warning("Authentication rate limit triggered: scope=%s", policy.scope)
            raise TooManyRequestsException()


class TableRateLimiter:
    """桌台公开解析和占台入口的 Redis fail-closed 限流。"""

    async def check(self, policy: RateLimitPolicy, principal: str) -> None:
        digest = hmac.new(
            settings.jwt_secret_key.encode("utf-8"),
            principal.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        key = f"rate:table:{policy.scope}:{digest}"
        try:
            count = await increment_rate_limit(key, policy.window_seconds)
        except (RedisError, RuntimeError):
            logger.error("Table rate limiter unavailable", exc_info=True)
            raise ServiceUnavailableException(
                message="Table service temporarily unavailable"
            )
        if count > policy.limit:
            logger.warning("Table rate limit triggered: scope=%s", policy.scope)
            raise TableRateLimitExceeded()


LOGIN_IP_POLICY = RateLimitPolicy(
    "login-ip",
    settings.auth_login_ip_limit,
    settings.auth_login_window_seconds,
)
LOGIN_SUBJECT_POLICY = RateLimitPolicy(
    "login-subject",
    settings.auth_login_subject_limit,
    settings.auth_login_window_seconds,
)
REGISTER_IP_POLICY = RateLimitPolicy(
    "register-ip",
    settings.auth_register_ip_limit,
    settings.auth_register_window_seconds,
)
REFRESH_POLICY = RateLimitPolicy(
    "refresh",
    settings.auth_refresh_limit,
    settings.auth_refresh_window_seconds,
)
WECHAT_LOGIN_POLICY = RateLimitPolicy(
    "wechat-login",
    settings.auth_wechat_login_limit,
    settings.auth_wechat_login_window_seconds,
)
WECHAT_BIND_POLICY = RateLimitPolicy(
    "wechat-bind",
    settings.auth_wechat_bind_limit,
    settings.auth_wechat_bind_window_seconds,
)

TABLE_RESOLVE_IP_POLICY = RateLimitPolicy(
    "resolve-ip",
    settings.table_resolve_ip_limit,
    settings.table_resolve_window_seconds,
)
TABLE_CREATE_USER_POLICY = RateLimitPolicy(
    "create-user",
    settings.table_create_user_limit,
    settings.table_create_window_seconds,
)
TABLE_CREATE_IP_POLICY = RateLimitPolicy(
    "create-ip",
    settings.table_create_ip_limit,
    settings.table_create_window_seconds,
)
TABLE_USER_READ_POLICY = RateLimitPolicy(
    "user-read",
    settings.table_user_read_limit,
    settings.table_user_read_window_seconds,
)
