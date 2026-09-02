"""Auth Schema —— 认证流程请求/响应数据结构。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.schemas.user import UserOut


class LoginRequest(BaseModel):
    """登录请求。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=64)


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
    """刷新响应——返回轮换后的新双 Token。"""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = settings.jwt_access_token_expire


class WeChatCodeRequest(BaseModel):
    """微信 wx.login 一次性 code。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=128, pattern=r"^\S+$")


class WeChatUnbindRequest(BaseModel):
    """解绑需使用现有密码做二次验证。"""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(..., min_length=1, max_length=64)


class ExternalIdentityOut(BaseModel):
    """对用户可见的绑定摘要，不暴露 OpenID/UnionID。"""

    provider: Literal["wechat_miniprogram"]
    bound_at: datetime


class ExternalIdentityListOut(BaseModel):
    items: list[ExternalIdentityOut]
