"""Auth Schema —— 认证流程请求/响应数据结构。

登录/注册/刷新 Token 属于"认证流程"，不是用户资源。
REST 视角：/auth/* 处理凭证，/users/* 处理资源。
"""

from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.user import UserOut


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenOut(BaseModel):
    """登录/注册响应——JWT Token + 用户信息。"""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = settings.jwt_access_token_expire
    user: UserOut


class RefreshTokenRequest(BaseModel):
    """刷新 Token 请求（Phase 3 接入）。"""

    refresh_token: str = Field(..., min_length=1)
