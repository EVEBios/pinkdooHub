"""User Schema —— 用户模块请求/响应数据结构。"""

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer

from app.common.constants.validation import (
    NICKNAME_MAX_LENGTH,
    NICKNAME_MIN_LENGTH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PHONE_PATTERN,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
)
from app.common.enums.user import UserRole, UserStatus


class UserCreate(BaseModel):
    """注册请求。"""

    username: str = Field(
        ..., min_length=USERNAME_MIN_LENGTH, max_length=USERNAME_MAX_LENGTH
    )
    password: str = Field(
        ..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )
    nickname: str = Field(
        ..., min_length=NICKNAME_MIN_LENGTH, max_length=NICKNAME_MAX_LENGTH
    )
    phone: str | None = Field(None, pattern=PHONE_PATTERN)


class UserLogin(BaseModel):
    """登录请求。"""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserUpdate(BaseModel):
    """修改个人信息请求。"""

    nickname: str | None = Field(
        None, min_length=NICKNAME_MIN_LENGTH, max_length=NICKNAME_MAX_LENGTH
    )
    phone: str | None = Field(None, pattern=PHONE_PATTERN)


class _EnumSerializerMixin:
    """Mixin：将 IntEnum 字段序列化为小写字符串。

    UserOut 和 UserListItem 共享此逻辑。
    """

    @field_serializer("role", "status")
    def serialize_enum(self, v: object) -> str:
        return v.name.lower()  # type: ignore[union-attr]


class UserOut(_EnumSerializerMixin, BaseModel):
    """用户详情响应——不含 password。"""

    id: int
    username: str
    nickname: str
    phone: str | None
    avatar: str | None
    role: UserRole
    status: UserStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListItem(_EnumSerializerMixin, BaseModel):
    """用户列表项——后台列表用，比 UserOut 更轻量。

    排除 phone、avatar、updated_at，减少列表接口的响应体积。
    """

    id: int
    username: str
    nickname: str
    role: UserRole
    status: UserStatus
    created_at: datetime

    model_config = {"from_attributes": True}
