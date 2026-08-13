"""安全模块 —— 密码哈希 + JWT 签发与验证。"""

import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"])


# ═══════════════════════════════════════════════
# 密码哈希
# ═══════════════════════════════════════════════


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码是否与哈希值匹配。"""
    return pwd_context.verify(plain_password, hashed_password)


# ═══════════════════════════════════════════════
# JWT
# ═══════════════════════════════════════════════


def _create_token(user_id: int, token_type: str, jti: str, ttl: int) -> str:
    """签发 JWT Token。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "jti": jti,
        "exp": now + timedelta(seconds=ttl),
        "iat": now,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, jti: str) -> str:
    """签发 access token（2 小时）。"""
    return _create_token(user_id, "access", jti, settings.jwt_access_token_expire)


def create_refresh_token(user_id: int, jti: str) -> str:
    """签发 refresh token（7 天）。"""
    return _create_token(user_id, "refresh", jti, settings.jwt_refresh_token_expire)


def decode_token(token: str, expected_type: str) -> dict:
    """解析并验证 JWT Token。

    Args:
        token: JWT 字符串
        expected_type: 期望的 token 类型 ("access" / "refresh")

    Raises:
        TokenExpired: Token 无效/过期/类型不匹配
    """
    from app.common.exceptions.user import TokenExpired

    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        raise TokenExpired()

    if payload.get("type") != expected_type:
        raise TokenExpired()

    return payload
