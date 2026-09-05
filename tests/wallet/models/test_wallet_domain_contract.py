"""Wallet、Payment、Refund 的常量、Enum 与命名异常契约测试。"""

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

import pytest
from pydantic import ValidationError

from app.common.constants.wallet import (
    FINANCIAL_NUMBER_LENGTH,
    FINANCIAL_RETRYABLE_MYSQL_ERROR_CODES,
    FINANCIAL_TRANSACTION_MAX_ATTEMPTS,
    MONEY_AMOUNT_DECIMAL_PLACES,
    MONEY_AMOUNT_MAX_DIGITS,
    PAYMENT_NO_PATTERN,
    RECHARGE_AMOUNT_MAX,
    RECHARGE_AMOUNT_MIN,
    RECHARGE_NO_PATTERN,
    REFUND_NO_PATTERN,
    WALLET_BALANCE_MAX,
    WALLET_BALANCE_MIN,
    WALLET_CHANGE_MAX,
    WALLET_CHANGE_MIN,
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
from app.common.exceptions.wallet import (
    InsufficientWalletBalance,
    PaymentNotFound,
    PaymentSettlementConflict,
    PaymentStatusConflict,
    RechargeAmountOutOfRange,
    RechargeOrderNotFound,
    RefundNotFound,
    RefundStatusConflict,
    RefundWindowExpired,
    WalletBalanceExceeded,
    WalletNotFound,
    WalletTransactionConflict,
)
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    UnprocessableEntityException,
)
from app.schemas.wallet_response import PaymentOut, RefundOut, WalletPaymentOut


@pytest.mark.parametrize(
    ("enum_type", "values"),
    [
        (WalletStatus, ["active", "closed"]),
        (
            WalletTransactionType,
            ["recharge", "order_payment", "admin_adjustment", "refund"],
        ),
        (
            WalletTransactionSourceType,
            ["recharge_order", "order", "admin", "refund"],
        ),
        (PaymentPurpose, ["order", "recharge"]),
        (PaymentMethod, ["wallet", "wechat", "manual"]),
        (PaymentStatus, ["pending", "succeeded", "failed", "closed"]),
        (RechargeOrderStatus, ["pending", "paid", "failed", "closed"]),
        (RefundStatus, ["pending", "succeeded", "failed"]),
    ],
)
def test_wallet_string_enums_match_frozen_values(
    enum_type: type[Enum],
    values: list[str],
) -> None:
    assert issubclass(enum_type, str)
    assert [item.value for item in enum_type] == values


def test_wallet_money_constants_match_frozen_boundaries() -> None:
    assert MONEY_AMOUNT_MAX_DIGITS == 10
    assert MONEY_AMOUNT_DECIMAL_PLACES == 2
    assert WALLET_BALANCE_MIN == Decimal("0.00")
    assert WALLET_BALANCE_MAX == Decimal("1000.00")
    assert WALLET_CHANGE_MIN == Decimal("-1000.00")
    assert WALLET_CHANGE_MAX == Decimal("1000.00")
    assert RECHARGE_AMOUNT_MIN == Decimal("1.00")
    assert RECHARGE_AMOUNT_MAX == Decimal("1000.00")
    assert FINANCIAL_NUMBER_LENGTH == 28
    assert PAYMENT_NO_PATTERN.startswith("^PY")
    assert RECHARGE_NO_PATTERN.startswith("^RC")
    assert REFUND_NO_PATTERN.startswith("^RF")
    assert FINANCIAL_TRANSACTION_MAX_ATTEMPTS == 3
    assert FINANCIAL_RETRYABLE_MYSQL_ERROR_CODES == frozenset({1205, 1213})


@pytest.mark.parametrize(
    ("factory", "base", "code", "message"),
    [
        (WalletNotFound, NotFoundException, 40441, "Wallet not found"),
        (
            RechargeOrderNotFound,
            NotFoundException,
            40442,
            "Recharge order not found",
        ),
        (PaymentNotFound, NotFoundException, 40443, "Payment not found"),
        (RefundNotFound, NotFoundException, 40444, "Refund not found"),
        (
            WalletTransactionConflict,
            ConflictException,
            40943,
            "Wallet idempotency key conflicts with another request",
        ),
        (
            PaymentStatusConflict,
            ConflictException,
            40944,
            "Payment status conflict",
        ),
        (
            PaymentSettlementConflict,
            ConflictException,
            40945,
            "Payment settlement conflict",
        ),
        (
            RefundStatusConflict,
            ConflictException,
            40946,
            "Refund status conflict",
        ),
        (
            RefundWindowExpired,
            ConflictException,
            40948,
            "The completed order refund window has expired",
        ),
    ],
)
def test_simple_named_exception_contracts(
    factory: Callable[[], Exception],
    base: type[Exception],
    code: int,
    message: str,
) -> None:
    error = factory()
    assert isinstance(error, base)
    assert error.code == code
    assert error.message == message
    assert error.data is None


def test_wallet_amount_exception_payloads_do_not_expose_current_balance() -> None:
    exceeded = WalletBalanceExceeded(
        user_id=7,
        before_balance=Decimal("999.99"),
        change_amount=Decimal("0.02"),
    )
    insufficient = InsufficientWalletBalance(
        user_id=7,
        requested_amount=Decimal("30.00"),
    )
    recharge = RechargeAmountOutOfRange(amount=Decimal("0.99"))

    assert exceeded.code == 40941
    assert exceeded.data == {
        "user_id": 7,
        "before_balance": "999.99",
        "change_amount": "0.02",
        "minimum": "0.00",
        "maximum": "1000.00",
    }
    assert insufficient.code == 40942
    assert insufficient.data == {
        "user_id": 7,
        "requested_amount": "30.00",
    }
    assert "available_balance" not in insufficient.data
    assert isinstance(recharge, UnprocessableEntityException)
    assert recharge.code == 42241
    assert recharge.data == {"minimum": "1.00", "maximum": "1000.00"}


@pytest.mark.parametrize(
    "factory",
    [
        lambda: WalletBalanceExceeded(
            user_id=0,
            before_balance=Decimal("1000.00"),
            change_amount=Decimal("0.01"),
        ),
        lambda: WalletBalanceExceeded(
            user_id=1,
            before_balance=Decimal("10.00"),
            change_amount=Decimal("0.00"),
        ),
        lambda: WalletBalanceExceeded(
            user_id=1,
            before_balance=Decimal("10.00"),
            change_amount=Decimal("1.00"),
        ),
        lambda: InsufficientWalletBalance(
            user_id=1,
            requested_amount=Decimal("0.00"),
        ),
        lambda: RechargeAmountOutOfRange(amount=Decimal("1.00")),
        lambda: RechargeAmountOutOfRange(amount=Decimal("NaN")),
    ],
)
def test_wallet_exceptions_reject_incoherent_payloads(
    factory: Callable[[], Exception],
) -> None:
    with pytest.raises(ValueError):
        factory()


def _payment_payload() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "id": 1,
        "payment_no": "PY" + "A" * 26,
        "order_id": 7,
        "recharge_order_id": None,
        "purpose": PaymentPurpose.ORDER,
        "method": PaymentMethod.WALLET,
        "amount": Decimal("10.00"),
        "status": PaymentStatus.SUCCEEDED,
        "created_at": now,
        "updated_at": now,
        "succeeded_at": now,
    }


@pytest.mark.parametrize(
    "updates",
    [
        {"amount": Decimal("0.00")},
        {"order_id": None},
        {"recharge_order_id": 8},
        {"succeeded_at": None},
    ],
)
def test_payment_response_rejects_invalid_financial_identity(updates: dict) -> None:
    with pytest.raises(ValidationError):
        PaymentOut.model_validate({**_payment_payload(), **updates})


def test_refund_and_wallet_payment_responses_require_successful_linked_facts() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        RefundOut.model_validate(
            {
                "id": 2,
                "refund_no": "RF" + "B" * 26,
                "order_id": 7,
                "method": PaymentMethod.WALLET,
                "amount": Decimal("10.00"),
                "status": RefundStatus.SUCCEEDED,
                "reason": "全额退款",
                "operator_id": 3,
                "inventory_restored": False,
                "created_at": now,
                "updated_at": now,
                "succeeded_at": None,
            }
        )

    with pytest.raises(ValidationError):
        WalletPaymentOut.model_validate(
            {
                "order_id": 7,
                "order_no": "OD" + "C" * 26,
                "order_status": {"value": "pending", "label": "待支付"},
                "payment": _payment_payload(),
                "post_payment_balance": Decimal("90.00"),
            }
        )
