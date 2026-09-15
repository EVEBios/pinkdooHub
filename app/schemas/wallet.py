"""Wallet、充值和退款写请求与分页查询 Schema。"""

import re
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    WithJsonSchema,
    field_validator,
)

from app.common.constants.wallet import (
    RECHARGE_AMOUNT_MAX,
    RECHARGE_AMOUNT_MIN,
    WALLET_CHANGE_MAX,
    WALLET_CHANGE_MIN,
    WALLET_IDEMPOTENCY_KEY_MAX_LENGTH,
    WALLET_IDEMPOTENCY_KEY_MIN_LENGTH,
    WALLET_IDEMPOTENCY_KEY_PATTERN,
    WALLET_REASON_MAX_LENGTH,
    WALLET_REASON_MIN_LENGTH,
)
from app.common.pagination import PageParams

_MONEY_INPUT_PATTERN = re.compile(r"^-?(?:0|[1-9]\d{0,7})\.\d{2}$")


def _parse_money_input(value: object) -> Decimal:
    """资金写入只接受固定两位小数 JSON 字符串。"""

    if not isinstance(value, str) or _MONEY_INPUT_PATTERN.fullmatch(value) is None:
        raise ValueError("Money must be a fixed two-decimal string")
    amount = Decimal(value)
    if not amount.is_finite():
        raise ValueError("Money must be finite")
    return amount


def _normalize_idempotency_key(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Idempotency key must be a string")
    return value.strip()


MoneyInput = Annotated[
    Decimal,
    BeforeValidator(_parse_money_input),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"^-?(?:0|[1-9]\d{0,7})\.\d{2}$",
            "examples": ["100.00"],
        },
        mode="validation",
    ),
]
WalletIdempotencyKey = Annotated[
    str,
    BeforeValidator(_normalize_idempotency_key),
    Field(
        strict=True,
        min_length=WALLET_IDEMPOTENCY_KEY_MIN_LENGTH,
        max_length=WALLET_IDEMPOTENCY_KEY_MAX_LENGTH,
        pattern=WALLET_IDEMPOTENCY_KEY_PATTERN,
    ),
]
WalletReason = Annotated[
    str,
    Field(
        strict=True,
        min_length=WALLET_REASON_MIN_LENGTH,
        max_length=WALLET_REASON_MAX_LENGTH,
    ),
]


class _WalletRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WalletAdjustmentCreate(_WalletRequest):
    """ADMIN+ 以变化额调整普通用户钱包。"""

    change: MoneyInput
    reason: WalletReason

    @field_validator("change", mode="after")
    @classmethod
    def validate_change(cls, value: Decimal) -> Decimal:
        if value == Decimal("0.00"):
            raise ValueError("Wallet change must not be zero")
        if not WALLET_CHANGE_MIN <= value <= WALLET_CHANGE_MAX:
            raise ValueError("Wallet change is outside the allowed range")
        return value


class RechargeCreate(_WalletRequest):
    """创建单笔充值意图；当前真实 Provider 默认关闭。"""

    amount: MoneyInput

    @field_validator("amount", mode="after")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        if not RECHARGE_AMOUNT_MIN <= value <= RECHARGE_AMOUNT_MAX:
            raise ValueError("Recharge amount is outside the allowed range")
        return value


class RefundCreate(_WalletRequest):
    """ADMIN+ 对已结算订单执行一次全额退款。"""

    reason: WalletReason


class WalletTransactionQuery(PageParams):
    """用户或管理端的钱包流水稳定分页。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
