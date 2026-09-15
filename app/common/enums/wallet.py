"""Wallet、Payment 与 Refund 模块的稳定字符串枚举。"""

from enum import Enum


class WalletStatus(str, Enum):
    """钱包生命周期；用户禁用状态仍以 User.status 为唯一事实。"""

    ACTIVE = "active"
    CLOSED = "closed"


class WalletTransactionType(str, Enum):
    """已提交钱包余额变化的业务类型。"""

    RECHARGE = "recharge"
    ORDER_PAYMENT = "order_payment"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    REFUND = "refund"


class WalletTransactionSourceType(str, Enum):
    """钱包流水的来源聚合类型。"""

    RECHARGE_ORDER = "recharge_order"
    ORDER = "order"
    ADMIN = "admin"
    REFUND = "refund"


class PaymentPurpose(str, Enum):
    """Payment 所服务的业务目的。"""

    ORDER = "order"
    RECHARGE = "recharge"


class PaymentMethod(str, Enum):
    """Payment 的资金渠道。"""

    WALLET = "wallet"
    WECHAT = "wechat"
    MANUAL = "manual"


class PaymentStatus(str, Enum):
    """Payment 独立状态机。"""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CLOSED = "closed"


class RechargeOrderStatus(str, Enum):
    """充值单状态；真实 Provider 成功路径尚未开放。"""

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CLOSED = "closed"


class RefundStatus(str, Enum):
    """退款独立状态机，不反向修改 Order 主状态。"""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
