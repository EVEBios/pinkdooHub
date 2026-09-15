"""Wallet 余额账户与不可变资金流水。"""

from decimal import Decimal

from tortoise import fields
from tortoise.exceptions import ValidationError
from tortoise.indexes import Index
from tortoise.validators import MaxValueValidator, MinLengthValidator, MinValueValidator

from app.common.constants.wallet import (
    MONEY_AMOUNT_DECIMAL_PLACES,
    MONEY_AMOUNT_MAX_DIGITS,
    WALLET_BALANCE_MAX,
    WALLET_BALANCE_MIN,
    WALLET_CHANGE_MAX,
    WALLET_CHANGE_MIN,
    WALLET_ENUM_MAX_LENGTH,
    WALLET_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
    WALLET_REASON_MAX_LENGTH,
    WALLET_SOURCE_TYPE_MAX_LENGTH,
    WALLET_TRANSACTION_TYPE_MAX_LENGTH,
)
from app.common.enums.wallet import (
    WalletStatus,
    WalletTransactionSourceType,
    WalletTransactionType,
)
from app.db.indexes import UniqueIndex
from app.models.base import BaseModel
from app.models.fields import AsciiBinaryCharField, StrictDecimalField


class _NonZeroDecimalValidator:
    """拒绝零变化流水，避免持久化无资金语义的记录。"""

    def __call__(self, value: int | float | Decimal) -> None:
        if Decimal(str(value)) == Decimal("0"):
            raise ValidationError("Decimal value must not be zero")


class WalletAccount(BaseModel):
    """一个 User 唯一拥有的权威钱包余额。"""

    user = fields.OneToOneField(
        "models.User",
        related_name="wallet_account",
        on_delete=fields.RESTRICT,
    )
    balance = StrictDecimalField(
        max_digits=MONEY_AMOUNT_MAX_DIGITS,
        decimal_places=MONEY_AMOUNT_DECIMAL_PLACES,
        default=Decimal("0.00"),
        db_default=Decimal("0.00"),
        validators=[
            MinValueValidator(WALLET_BALANCE_MIN),
            MaxValueValidator(WALLET_BALANCE_MAX),
        ],
    )
    status = fields.CharEnumField(
        WalletStatus,
        max_length=WALLET_ENUM_MAX_LENGTH,
        default=WalletStatus.ACTIVE,
        db_default=WalletStatus.ACTIVE.value,
    )

    class Meta:
        table = "wallet_accounts"


class WalletTransaction(BaseModel):
    """记录每一次已提交余额变化；Repository 不提供修改或删除入口。"""

    wallet_account = fields.ForeignKeyField(
        "models.WalletAccount",
        related_name="transactions",
        on_delete=fields.RESTRICT,
    )
    transaction_type = fields.CharEnumField(
        WalletTransactionType,
        max_length=WALLET_TRANSACTION_TYPE_MAX_LENGTH,
    )
    change_amount = StrictDecimalField(
        max_digits=MONEY_AMOUNT_MAX_DIGITS,
        decimal_places=MONEY_AMOUNT_DECIMAL_PLACES,
        validators=[
            MinValueValidator(WALLET_CHANGE_MIN),
            _NonZeroDecimalValidator(),
            MaxValueValidator(WALLET_CHANGE_MAX),
        ],
    )
    before_balance = StrictDecimalField(
        max_digits=MONEY_AMOUNT_MAX_DIGITS,
        decimal_places=MONEY_AMOUNT_DECIMAL_PLACES,
        validators=[
            MinValueValidator(WALLET_BALANCE_MIN),
            MaxValueValidator(WALLET_BALANCE_MAX),
        ],
    )
    after_balance = StrictDecimalField(
        max_digits=MONEY_AMOUNT_MAX_DIGITS,
        decimal_places=MONEY_AMOUNT_DECIMAL_PLACES,
        validators=[
            MinValueValidator(WALLET_BALANCE_MIN),
            MaxValueValidator(WALLET_BALANCE_MAX),
        ],
    )
    source_type = fields.CharEnumField(
        WalletTransactionSourceType,
        max_length=WALLET_SOURCE_TYPE_MAX_LENGTH,
    )
    source_id = fields.BigIntField(null=True, validators=[MinValueValidator(1)])
    operator = fields.ForeignKeyField(
        "models.User",
        related_name="operated_wallet_transactions",
        on_delete=fields.RESTRICT,
        null=True,
    )
    reason = fields.CharField(
        max_length=WALLET_REASON_MAX_LENGTH,
        validators=[MinLengthValidator(1)],
    )
    idempotency_key = AsciiBinaryCharField(
        max_length=WALLET_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
        validators=[MinLengthValidator(1)],
    )

    class Meta:
        table = "wallet_transactions"
        indexes = [
            UniqueIndex(
                fields=("idempotency_key",),
                name="uidx_wallet_transaction_idempotency",
            ),
            Index(
                fields=("wallet_account_id", "created_at", "id"),
                name="idx_wallet_transaction_wallet_created_id",
            ),
            Index(
                fields=("source_type", "source_id", "created_at", "id"),
                name="idx_wallet_transaction_source_created_id",
            ),
            Index(
                fields=("transaction_type", "created_at", "id"),
                name="idx_wallet_transaction_type_created_id",
            ),
            Index(
                fields=("created_at", "id"),
                name="idx_wallet_transaction_created_id",
            ),
        ]
