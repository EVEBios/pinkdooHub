"""Auth Schema —— 认证模块响应数据结构。"""

from pydantic import BaseModel

from app.core.config import settings
from app.schemas.user import UserOut


class TokenOut(BaseModel):
    """登录响应——JWT Token + 用户信息。"""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = settings.jwt_access_token_expire
    user: UserOut
