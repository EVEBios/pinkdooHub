"""安全模块 —— 密码哈希。

Phase 2: 仅包含密码哈希和验证。
Phase 3: 将加入 JWT 签发和验证（create_access_token、decode_token 等）。
"""

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"])


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。

    哈希后的密文可直接存入数据库，不可逆。
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码是否与哈希值匹配。"""
    return pwd_context.verify(plain_password, hashed_password)
