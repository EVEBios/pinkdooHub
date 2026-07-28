"""Auth Schema —— 认证流程请求/响应数据结构。"""

from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.user import UserOut


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenOut(BaseModel):
    """登录响应——双 Token + 用户信息。"""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = settings.jwt_access_token_expire
    user: UserOut


class RefreshRequest(BaseModel):
    """刷新 Token 请求。"""

    refresh_token: str = Field(..., min_length=1)


class RefreshOut(BaseModel):
    """刷新响应——只返回新的 access token。"""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = settings.jwt_access_token_expire
