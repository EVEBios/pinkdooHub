"""Product 模块枚举。

数据库和 API 均使用字符串值。项目当前运行于 Python 3.10，
因此使用 ``str, Enum`` 兼容写法，而不是 Python 3.11 才提供的
标准库 ``StrEnum``。
"""

from enum import Enum


class ProductType(str, Enum):
    """商品类型。"""

    EXPERIENCE = "experience"
    KIT = "kit"


class ProductStatus(str, Enum):
    """商品生命周期状态。"""

    DRAFT = "draft"
    ONLINE = "online"
    OFFLINE = "offline"


class DayType(str, Enum):
    """体验 Option 的日期类型。"""

    WEEKDAY = "weekday"
    HOLIDAY = "holiday"
