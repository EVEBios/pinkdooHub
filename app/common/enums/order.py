"""Order 模块枚举。

数据库使用整数值存储订单状态；API value 与展示 label 由
``app.common.constants.order`` 中的 Registry 显式映射。
"""

from enum import IntEnum
from typing import Literal, TypeAlias


OrderStatusValue: TypeAlias = Literal[
    "pending",
    "paid",
    "cancelled",
    "completed",
]


class OrderStatus(IntEnum):
    """订单生命周期状态。"""

    PENDING = 0
    PAID = 1
    CANCELLED = 2
    COMPLETED = 3
