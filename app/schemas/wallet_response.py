"""Wallet、Payment 与 Refund API 的严格响应白名单。"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    model_validator,
)

from app.common.constants.order import ORDER_NO_PATTERN
from app.common.constants.wallet import (
    MONEY_AMOUNT_DECIMAL_PLACES,
    MONEY_AMOUNT_MAX,
    PAYMENT_NO_PATTERN,
    RECHARGE_NO_PATTERN,
    REFUND_NO_PATTERN,
    WALLET_BALANCE_MAX,
    WALLET_BALANCE_MIN,
    WALLET_REASON_MAX_LENGTH,
)
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    RechargeOrderStatus,
    RefundStatus,
    WalletStatus,
    WalletTransactionSourceType,
    WalletTransactionType,
)
from app.schemas.order_response import AdminOrderDetailOut, OrderStatusValueOut
from app.schemas.user import UserListItem, UserOut


def _require_decimal(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Response money must be a finite Decimal")
    return value


def _serialize_money(value: Decimal) -> str:
    return f"{value:.{MONEY_AMOUNT_DECIMAL_PLACES}f}"


def _require_utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError("Response datetime must use UTC timezone")
    return value


MoneyOut = Annotated[
    Decimal,
    BeforeValidator(_require_decimal),
    Field(ge=-MONEY_AMOUNT_MAX, le=MONEY_AMOUNT_MAX, decimal_places=2),
    PlainSerializer(_serialize_money, return_type=str, when_used="always"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["100.00"]},
        mode="serialization",
    ),
]
WalletBalanceOut = Annotated[
    Decimal,
    BeforeValidator(_require_decimal),
    Field(ge=WALLET_BALANCE_MIN, le=WALLET_BALANCE_MAX, decimal_places=2),
    PlainSerializer(_serialize_money, return_type=str, when_used="always"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^\d+\.\d{2}$", "examples": ["80.00"]},
        mode="serialization",
    ),
]
FinancialUtcDatetimeOut = Annotated[datetime, BeforeValidator(_require_utc)]


class _FinancialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class WalletCapabilitiesOut(_FinancialOut):
    topup_enabled: bool
    wallet_payment_enabled: bool
    refund_enabled: bool


class WalletSummaryOut(_FinancialOut):
    wallet_id: int = Field(strict=True, gt=0)
    user_id: int = Field(strict=True, gt=0)
    balance: WalletBalanceOut
    balance_limit: WalletBalanceOut
    status: WalletStatus
    capabilities: WalletCapabilitiesOut
    created_at: FinancialUtcDatetimeOut
    updated_at: FinancialUtcDatetimeOut


class MemberOut(_FinancialOut):
    user: UserOut
    wallet: WalletSummaryOut


class AdminUserWalletOut(_FinancialOut):
    user: UserListItem
    wallet: WalletSummaryOut


class WalletTransactionOut(_FinancialOut):
    id: int = Field(strict=True, gt=0)
    transaction_type: WalletTransactionType
    direction: Literal["income", "expense"]
    change_amount: MoneyOut
    before_balance: WalletBalanceOut
    after_balance: WalletBalanceOut
    source_type: WalletTransactionSourceType
    source_id: int | None = Field(default=None, strict=True, gt=0)
    source_order_no: str | None = None
    operator_id: int | None = Field(default=None, strict=True, gt=0)
    operator_nickname: str | None = Field(default=None, min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=WALLET_REASON_MAX_LENGTH)
    created_at: FinancialUtcDatetimeOut

    @model_validator(mode="after")
    def validate_balances(self) -> "WalletTransactionOut":
        if self.change_amount == Decimal("0.00"):
            raise ValueError("Wallet transaction change must not be zero")
        if self.after_balance != self.before_balance + self.change_amount:
            raise ValueError("Wallet transaction balances are inconsistent")
        expected = "income" if self.change_amount > Decimal("0.00") else "expense"
        if self.direction != expected:
            raise ValueError("Wallet transaction direction is inconsistent")
        return self


class WalletAdjustmentOut(_FinancialOut):
    wallet: WalletSummaryOut
    transaction: WalletTransactionOut


class RechargeOrderOut(_FinancialOut):
    id: int = Field(strict=True, gt=0)
    recharge_no: str = Field(pattern=RECHARGE_NO_PATTERN)
    amount: MoneyOut
    status: RechargeOrderStatus
    created_at: FinancialUtcDatetimeOut
    updated_at: FinancialUtcDatetimeOut

    @model_validator(mode="after")
    def validate_amount(self) -> "RechargeOrderOut":
        if self.amount <= Decimal("0.00"):
            raise ValueError("Recharge amount must be positive")
        return self


class PaymentOut(_FinancialOut):
    id: int = Field(strict=True, gt=0)
    payment_no: str = Field(pattern=PAYMENT_NO_PATTERN)
    order_id: int | None = Field(default=None, strict=True, gt=0)
    recharge_order_id: int | None = Field(default=None, strict=True, gt=0)
    purpose: PaymentPurpose
    method: PaymentMethod
    amount: MoneyOut
    status: PaymentStatus
    created_at: FinancialUtcDatetimeOut
    updated_at: FinancialUtcDatetimeOut
    succeeded_at: FinancialUtcDatetimeOut | None = None

    @model_validator(mode="after")
    def validate_payment_identity(self) -> "PaymentOut":
        if self.amount <= Decimal("0.00"):
            raise ValueError("Payment amount must be positive")
        if self.purpose is PaymentPurpose.ORDER:
            if self.order_id is None or self.recharge_order_id is not None:
                raise ValueError("Order payment requires only order_id")
        elif self.order_id is not None or self.recharge_order_id is None:
            raise ValueError("Recharge payment requires only recharge_order_id")
        if self.status is PaymentStatus.SUCCEEDED and self.succeeded_at is None:
            raise ValueError("Succeeded payment requires succeeded_at")
        return self


class RefundOut(_FinancialOut):
    id: int = Field(strict=True, gt=0)
    refund_no: str = Field(pattern=REFUND_NO_PATTERN)
    order_id: int = Field(strict=True, gt=0)
    method: PaymentMethod
    amount: MoneyOut
    status: RefundStatus
    reason: str = Field(min_length=1, max_length=WALLET_REASON_MAX_LENGTH)
    operator_id: int = Field(strict=True, gt=0)
    inventory_restored: bool
    created_at: FinancialUtcDatetimeOut
    updated_at: FinancialUtcDatetimeOut
    succeeded_at: FinancialUtcDatetimeOut | None = None

    @model_validator(mode="after")
    def validate_refund_state(self) -> "RefundOut":
        if self.amount <= Decimal("0.00"):
            raise ValueError("Refund amount must be positive")
        if self.status is RefundStatus.SUCCEEDED and self.succeeded_at is None:
            raise ValueError("Succeeded refund requires succeeded_at")
        return self


class OrderFinancialOut(_FinancialOut):
    order_id: int = Field(strict=True, gt=0)
    order_status: OrderStatusValueOut
    payment: PaymentOut | None = None
    refund: RefundOut | None = None

    @model_validator(mode="after")
    def validate_financial_links(self) -> "OrderFinancialOut":
        if self.payment is None:
            if self.refund is not None:
                raise ValueError("Refund requires a payment")
            return self
        if (
            self.payment.order_id != self.order_id
            or self.payment.purpose is not PaymentPurpose.ORDER
            or self.payment.status is not PaymentStatus.SUCCEEDED
            or self.order_status.value not in ("paid", "completed")
        ):
            raise ValueError("Order financial payment is inconsistent")
        if self.refund is not None and (
            self.refund.order_id != self.order_id
            or self.refund.method is not self.payment.method
            or self.refund.amount != self.payment.amount
        ):
            raise ValueError("Order financial refund is inconsistent")
        return self


class WalletPaymentOut(_FinancialOut):
    order_id: int = Field(strict=True, gt=0)
    order_no: str = Field(strict=True, pattern=ORDER_NO_PATTERN)
    order_status: OrderStatusValueOut
    payment: PaymentOut
    post_payment_balance: WalletBalanceOut

    @model_validator(mode="after")
    def validate_wallet_payment_result(self) -> "WalletPaymentOut":
        if (
            self.order_status.value not in ("paid", "completed")
            or self.payment.order_id != self.order_id
            or self.payment.purpose is not PaymentPurpose.ORDER
            or self.payment.method is not PaymentMethod.WALLET
            or self.payment.status is not PaymentStatus.SUCCEEDED
        ):
            raise ValueError("Wallet payment result is inconsistent")
        return self


class AssistedWalletOrderOut(_FinancialOut):
    order: AdminOrderDetailOut
    payment: PaymentOut
    post_payment_balance: WalletBalanceOut

    @model_validator(mode="after")
    def validate_assisted_wallet_order(self) -> "AssistedWalletOrderOut":
        if (
            self.order.status.value != "paid"
            or self.payment.order_id != self.order.id
            or self.payment.amount != self.order.total_amount
            or self.payment.purpose is not PaymentPurpose.ORDER
            or self.payment.method is not PaymentMethod.WALLET
            or self.payment.status is not PaymentStatus.SUCCEEDED
        ):
            raise ValueError("Assisted wallet order result is inconsistent")
        return self
