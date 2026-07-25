"""安全模块 —— 密码哈希 + JWT 签发与验证。"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"])


# ═══════════════════════════════════════════════
# 密码哈希
# ═══════════════════════════════════════════════


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希，不可逆。"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码是否与哈希值匹配。"""
    return pwd_context.verify(plain_password, hashed_password)


# ═══════════════════════════════════════════════
# JWT
# ═══════════════════════════════════════════════


def create_access_token(user_id: int) -> str:
    """签发访问令牌。

    payload:
        sub  → 用户 ID（subject）
        exp  → 过期时间
        iat  → 签发时间
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(seconds=settings.jwt_access_token_expire)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """解析访问令牌，返回 payload。

    Raises:
        AuthenticationException: Token 无效或已过期
    """
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        from app.common.exceptions.user import TokenExpired
        raise TokenExpired()
