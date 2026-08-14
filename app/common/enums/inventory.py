"""Inventory 模块字符串枚举。"""

from enum import Enum


class InventoryTransactionType(str, Enum):
    """库存余额变化的稳定业务类型。"""

    OPENING_BALANCE = "opening_balance"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    ORDER_DEDUCTION = "order_deduction"
    ORDER_CANCELLATION_RESTORE = "order_cancellation_restore"


class InventorySourceType(str, Enum):
    """库存流水的业务来源类型。"""

    MIGRATION = "migration"
    ADMIN = "admin"
    ORDER = "order"
