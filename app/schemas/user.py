"""User Schema —— 用户模块请求/响应数据结构。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

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
from app.common.pagination import PageParams


class AdminUserListQuery(PageParams):
    """管理端用户列表的严格分页与枚举筛选。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: Literal["normal", "disabled"] | None = None
    role: Literal["user", "admin", "super_admin"] | None = None


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
    phone: str = Field(..., pattern=PHONE_PATTERN)


class PasswordChange(BaseModel):
    """修改密码请求。"""

    old_password: str = Field(..., min_length=1)
    new_password: str = Field(
        ..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )


class UserUpdate(BaseModel):
    """修改个人信息请求——所有字段可选，传什么改什么。"""

    nickname: str | None = Field(
        None, min_length=NICKNAME_MIN_LENGTH, max_length=NICKNAME_MAX_LENGTH
    )
    phone: str | None = Field(None, pattern=PHONE_PATTERN)
    avatar: str | None = Field(None, min_length=1)


class _EnumSerializerMixin:
    """Mixin：将 IntEnum 字段序列化为小写字符串。

    UserOut 和 UserListItem 共享此逻辑。
    """

    @field_serializer("role")
    def serialize_role(
        self,
        value: UserRole,
    ) -> Literal["user", "admin", "super_admin"]:
        return {
            UserRole.USER: "user",
            UserRole.ADMIN: "admin",
            UserRole.SUPER_ADMIN: "super_admin",
        }[value]

    @field_serializer("status")
    def serialize_status(
        self,
        value: UserStatus,
    ) -> Literal["normal", "disabled"]:
        return {
            UserStatus.NORMAL: "normal",
            UserStatus.DISABLED: "disabled",
        }[value]


class UserOut(_EnumSerializerMixin, BaseModel):
    """用户详情响应——不含 password。"""

    id: int
    username: str
    nickname: str
    phone: str
    avatar: str | None
    role: UserRole
    status: UserStatus
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True,
        "json_schema_mode_override": "serialization",
    }


class UserListItem(_EnumSerializerMixin, BaseModel):
    """用户列表项——后台列表用，比 UserOut 更轻量。

    排除 phone、avatar、updated_at，减少列表接口的响应体积。
    """

    id: int
    username: str
    nickname: str
    role: UserRole
    status: UserStatus
    last_login_at: datetime | None
    created_at: datetime

    model_config = {
        "from_attributes": True,
        "json_schema_mode_override": "serialization",
    }
