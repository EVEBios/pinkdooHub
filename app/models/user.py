"""User Model —— 用户数据表。

字段规格见 docs/02_database/database_design.md §3.1。
"""

from tortoise import fields

from app.models.base import BaseModel


class User(BaseModel):
    """平台用户。

    password 字段通过 security.hash_password() 加密存储，
    任何接口不得返回此字段。
    """

    username = fields.CharField(max_length=32, unique=True)
    password = fields.CharField(max_length=128)
    nickname = fields.CharField(max_length=32)
    phone = fields.CharField(max_length=11, null=True)
    avatar = fields.CharField(max_length=256, null=True)
    role = fields.SmallIntField(default=1)     # UserRole.USER
    status = fields.SmallIntField(default=1)   # UserStatus.NORMAL
    last_login_at = fields.DatetimeField(null=True)

    class Meta:
        table = "users"
