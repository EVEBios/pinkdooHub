"""Wallet、Payment 与 Refund 模块命名业务异常。"""

from decimal import Decimal

from app.common.constants.wallet import (
    RECHARGE_AMOUNT_MAX,
    RECHARGE_AMOUNT_MIN,
    WALLET_BALANCE_MAX,
    WALLET_BALANCE_MIN,
    WALLET_CHANGE_MAX,
    WALLET_CHANGE_MIN,
)
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    UnprocessableEntityException,
)


def _validate_positive_id(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _validate_decimal(value: Decimal, *, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


class WalletNotFound(NotFoundException):
    """钱包不存在或对当前用户不可见。"""

    def __init__(self) -> None:
        super().__init__(code=40441, message="Wallet not found")


class RechargeOrderNotFound(NotFoundException):
    """充值单不存在或对当前用户不可见。"""

    def __init__(self) -> None:
        super().__init__(code=40442, message="Recharge order not found")


class PaymentNotFound(NotFoundException):
    """支付记录不存在或不可见。"""

    def __init__(self) -> None:
        super().__init__(code=40443, message="Payment not found")


class RefundNotFound(NotFoundException):
    """退款记录不存在。"""

    def __init__(self) -> None:
        super().__init__(code=40444, message="Refund not found")


class WalletBalanceExceeded(ConflictException):
    """余额变化后的值超出冻结范围。"""

    def __init__(
        self,
        *,
        user_id: int,
        before_balance: Decimal,
        change_amount: Decimal,
    ) -> None:
        _validate_positive_id(user_id, field_name="user_id")
        _validate_decimal(before_balance, field_name="before_balance")
        _validate_decimal(change_amount, field_name="change_amount")
        if not WALLET_BALANCE_MIN <= before_balance <= WALLET_BALANCE_MAX:
            raise ValueError("before_balance must be within the wallet range")
        if not WALLET_CHANGE_MIN <= change_amount <= WALLET_CHANGE_MAX:
            raise ValueError("change_amount must be within the wallet change range")
        if change_amount == Decimal("0.00"):
            raise ValueError("change_amount must not be zero")
        after_balance = before_balance + change_amount
        if WALLET_BALANCE_MIN <= after_balance <= WALLET_BALANCE_MAX:
            raise ValueError("adjusted balance must exceed the wallet range")
        super().__init__(
            code=40941,
            message="Wallet balance exceeds the allowed range",
            data={
                "user_id": user_id,
                "before_balance": f"{before_balance:.2f}",
                "change_amount": f"{change_amount:.2f}",
                "minimum": f"{WALLET_BALANCE_MIN:.2f}",
                "maximum": f"{WALLET_BALANCE_MAX:.2f}",
            },
        )


class InsufficientWalletBalance(ConflictException):
    """钱包余额不足以支付请求金额。"""

    def __init__(self, *, user_id: int, requested_amount: Decimal) -> None:
        _validate_positive_id(user_id, field_name="user_id")
        _validate_decimal(requested_amount, field_name="requested_amount")
        if requested_amount <= Decimal("0.00"):
            raise ValueError("requested_amount must be positive")
        super().__init__(
            code=40942,
            message="Insufficient wallet balance",
            data={
                "user_id": user_id,
                "requested_amount": f"{requested_amount:.2f}",
            },
        )


class WalletTransactionConflict(ConflictException):
    """钱包幂等键已经绑定到另一业务意图。"""

    def __init__(self) -> None:
        super().__init__(
            code=40943,
            message="Wallet idempotency key conflicts with another request",
        )


class PaymentStatusConflict(ConflictException):
    """Payment 当前状态不允许目标操作。"""

    def __init__(self) -> None:
        super().__init__(code=40944, message="Payment status conflict")


class PaymentSettlementConflict(ConflictException):
    """订单或 Payment 已绑定成功结算。"""

    def __init__(self) -> None:
        super().__init__(code=40945, message="Payment settlement conflict")


class RefundStatusConflict(ConflictException):
    """退款当前状态不允许目标操作。"""

    def __init__(self) -> None:
        super().__init__(code=40946, message="Refund status conflict")


class WalletRefundCapacityExceeded(ConflictException):
    """正向入账会侵占尚未结清的钱包原路退款空间。"""

    def __init__(
        self,
        *,
        requested_balance: Decimal,
        refundable_exposure: Decimal,
    ) -> None:
        _validate_decimal(requested_balance, field_name="requested_balance")
        _validate_decimal(refundable_exposure, field_name="refundable_exposure")
        super().__init__(
            code=40947,
            message="Wallet credit would consume reserved refund capacity",
            data={
                "requested_balance": f"{requested_balance:.2f}",
                "refundable_exposure": f"{refundable_exposure:.2f}",
                "maximum": f"{WALLET_BALANCE_MAX:.2f}",
            },
        )


class RefundWindowExpired(ConflictException):
    """已完成订单超过默认退款期限。"""

    def __init__(self) -> None:
        super().__init__(
            code=40948,
            message="The completed order refund window has expired",
        )


class RechargeAmountOutOfRange(UnprocessableEntityException):
    """单笔充值金额不在冻结区间内。"""

    def __init__(self, *, amount: Decimal) -> None:
        _validate_decimal(amount, field_name="amount")
        if RECHARGE_AMOUNT_MIN <= amount <= RECHARGE_AMOUNT_MAX:
            raise ValueError("amount must be outside the recharge range")
        super().__init__(
            code=42241,
            message="Recharge amount is outside the allowed range",
            data={
                "minimum": f"{RECHARGE_AMOUNT_MIN:.2f}",
                "maximum": f"{RECHARGE_AMOUNT_MAX:.2f}",
            },
        )
