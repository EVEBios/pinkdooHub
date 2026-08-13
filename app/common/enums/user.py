"""用户模块枚举。

DB 通过 Tortoise ``SmallIntField`` 存储为 SMALLINT，API 返回小写字符串。
映射关系见 docs/03_api/api_design_conventions.md §14。
"""

from enum import IntEnum


class UserRole(IntEnum):
    USER = 1
    ADMIN = 2
    SUPER_ADMIN = 3


class UserStatus(IntEnum):
    NORMAL = 1
    DISABLED = 2
