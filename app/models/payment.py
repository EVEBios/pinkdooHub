"""Payment、成功结算、充值单与独立退款记录。"""

from tortoise import fields
from tortoise.indexes import Index
from tortoise.validators import (
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    RegexValidator,
)

from app.common.constants.wallet import (
    FINANCIAL_NUMBER_LENGTH,
    MONEY_AMOUNT_DECIMAL_PLACES,
    MONEY_AMOUNT_MAX,
    MONEY_AMOUNT_MAX_DIGITS,
    MONEY_AMOUNT_MIN,
    PAYMENT_ENUM_MAX_LENGTH,
    PAYMENT_NO_PATTERN,
    PAYMENT_PROVIDER_REFERENCE_MAX_LENGTH,
    RECHARGE_AMOUNT_MAX,
    RECHARGE_AMOUNT_MIN,
    RECHARGE_NO_PATTERN,
    REFUND_NO_PATTERN,
    WALLET_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
    WALLET_REASON_MAX_LENGTH,
)
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    RechargeOrderStatus,
    RefundStatus,
)
from app.db.indexes import UniqueIndex
from app.models.base import BaseModel
from app.models.fields import AsciiBinaryCharField, StrictDecimalField


class RechargeOrder(BaseModel):
    """用户为自己钱包发起的单笔充值业务单。"""

    recharge_no = fields.CharField(
        max_length=FINANCIAL_NUMBER_LENGTH,
        unique=True,
        validators=[RegexValidator(RECHARGE_NO_PATTERN, flags=0)],
    )
    user = fields.ForeignKeyField(
        "models.User",
        related_name="recharge_orders",
        on_delete=fields.RESTRICT,
    )
    wallet_account = fields.ForeignKeyField(
        "models.WalletAccount",
        related_name="recharge_orders",
        on_delete=fields.RESTRICT,
    )
    amount = StrictDecimalField(
        max_digits=MONEY_AMOUNT_MAX_DIGITS,
        decimal_places=MONEY_AMOUNT_DECIMAL_PLACES,
        validators=[
            MinValueValidator(RECHARGE_AMOUNT_MIN),
            MaxValueValidator(RECHARGE_AMOUNT_MAX),
        ],
    )
    status = fields.CharEnumField(
        RechargeOrderStatus,
        max_length=PAYMENT_ENUM_MAX_LENGTH,
        default=RechargeOrderStatus.PENDING,
        db_default=RechargeOrderStatus.PENDING.value,
    )
    idempotency_key = AsciiBinaryCharField(
        max_length=WALLET_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
        validators=[MinLengthValidator(1)],
    )
    succeeded_at = fields.DatetimeField(null=True)

    class Meta:
        table = "recharge_orders"
        indexes = [
            UniqueIndex(
                fields=("idempotency_key",),
                name="uidx_recharge_order_idempotency",
            ),
            Index(
                fields=("user_id", "created_at", "id"),
                name="idx_recharge_order_user_created_id",
            ),
            Index(
                fields=("status", "created_at", "id"),
                name="idx_recharge_order_status_created_id",
            ),
        ]


class Payment(BaseModel):
    """订单或充值业务的一次支付记录。"""

    payment_no = fields.CharField(
        max_length=FINANCIAL_NUMBER_LENGTH,
        unique=True,
        validators=[RegexValidator(PAYMENT_NO_PATTERN, flags=0)],
    )
    user = fields.ForeignKeyField(
        "models.User",
        related_name="payments",
        on_delete=fields.RESTRICT,
    )
    purpose = fields.CharEnumField(
        PaymentPurpose,
        max_length=PAYMENT_ENUM_MAX_LENGTH,
    )
    method = fields.CharEnumField(
        PaymentMethod,
        max_length=PAYMENT_ENUM_MAX_LENGTH,
    )
    amount = StrictDecimalField(
        max_digits=MONEY_AMOUNT_MAX_DIGITS,
        decimal_places=MONEY_AMOUNT_DECIMAL_PLACES,
        validators=[
            MinValueValidator(MONEY_AMOUNT_MIN),
            MaxValueValidator(MONEY_AMOUNT_MAX),
        ],
    )
    status = fields.CharEnumField(
        PaymentStatus,
        max_length=PAYMENT_ENUM_MAX_LENGTH,
        default=PaymentStatus.PENDING,
        db_default=PaymentStatus.PENDING.value,
    )
    order = fields.ForeignKeyField(
        "models.Order",
        related_name="payments",
        on_delete=fields.RESTRICT,
        null=True,
    )
    recharge_order = fields.ForeignKeyField(
        "models.RechargeOrder",
        related_name="payments",
        on_delete=fields.RESTRICT,
        null=True,
    )
    idempotency_key = AsciiBinaryCharField(
        max_length=WALLET_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
        validators=[MinLengthValidator(1)],
    )
    provider_transaction_id = fields.CharField(
        max_length=PAYMENT_PROVIDER_REFERENCE_MAX_LENGTH,
        null=True,
        validators=[MinLengthValidator(1)],
    )
    succeeded_at = fields.DatetimeField(null=True)

    class Meta:
        table = "payments"
        indexes = [
            UniqueIndex(
                fields=("idempotency_key",),
                name="uidx_payment_idempotency",
            ),
            UniqueIndex(
                fields=("provider_transaction_id",),
                name="uidx_payment_provider_transaction",
            ),
            Index(
                fields=("user_id", "created_at", "id"),
                name="idx_payment_user_created_id",
            ),
            Index(
                fields=("order_id", "created_at", "id"),
                name="idx_payment_order_created_id",
            ),
            Index(
                fields=("recharge_order_id", "created_at", "id"),
                name="idx_payment_recharge_created_id",
            ),
            Index(
                fields=("status", "created_at", "id"),
                name="idx_payment_status_created_id",
            ),
        ]


class PaymentSettlement(BaseModel):
    """成功 Payment 与 Order 的唯一结算事实。"""

    payment = fields.OneToOneField(
        "models.Payment",
        related_name="settlement",
        on_delete=fields.RESTRICT,
    )
    order = fields.OneToOneField(
        "models.Order",
        related_name="payment_settlement",
        on_delete=fields.RESTRICT,
    )
    amount = StrictDecimalField(
        max_digits=MONEY_AMOUNT_MAX_DIGITS,
        decimal_places=MONEY_AMOUNT_DECIMAL_PLACES,
        validators=[
            MinValueValidator(MONEY_AMOUNT_MIN),
            MaxValueValidator(MONEY_AMOUNT_MAX),
        ],
    )

    class Meta:
        table = "payment_settlements"


class Refund(BaseModel):
    """一个成功结算最多对应一次全额退款。"""

    refund_no = fields.CharField(
        max_length=FINANCIAL_NUMBER_LENGTH,
        unique=True,
        validators=[RegexValidator(REFUND_NO_PATTERN, flags=0)],
    )
    settlement = fields.OneToOneField(
        "models.PaymentSettlement",
        related_name="refund",
        on_delete=fields.RESTRICT,
    )
    order = fields.OneToOneField(
        "models.Order",
        related_name="refund",
        on_delete=fields.RESTRICT,
    )
    operator = fields.ForeignKeyField(
        "models.User",
        related_name="operated_refunds",
        on_delete=fields.RESTRICT,
    )
    amount = StrictDecimalField(
        max_digits=MONEY_AMOUNT_MAX_DIGITS,
        decimal_places=MONEY_AMOUNT_DECIMAL_PLACES,
        validators=[
            MinValueValidator(MONEY_AMOUNT_MIN),
            MaxValueValidator(MONEY_AMOUNT_MAX),
        ],
    )
    status = fields.CharEnumField(
        RefundStatus,
        max_length=PAYMENT_ENUM_MAX_LENGTH,
        default=RefundStatus.PENDING,
        db_default=RefundStatus.PENDING.value,
    )
    inventory_restored = fields.BooleanField(
        default=False,
        db_default=False,
    )
    reason = fields.CharField(
        max_length=WALLET_REASON_MAX_LENGTH,
        validators=[MinLengthValidator(1)],
    )
    idempotency_key = AsciiBinaryCharField(
        max_length=WALLET_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
        validators=[MinLengthValidator(1)],
    )
    provider_refund_id = fields.CharField(
        max_length=PAYMENT_PROVIDER_REFERENCE_MAX_LENGTH,
        null=True,
        validators=[MinLengthValidator(1)],
    )
    succeeded_at = fields.DatetimeField(null=True)

    class Meta:
        table = "refunds"
        indexes = [
            UniqueIndex(
                fields=("idempotency_key",),
                name="uidx_refund_idempotency",
            ),
            UniqueIndex(
                fields=("provider_refund_id",),
                name="uidx_refund_provider_reference",
            ),
            Index(
                fields=("order_id", "created_at", "id"),
                name="idx_refund_order_created_id",
            ),
            Index(
                fields=("status", "created_at", "id"),
                name="idx_refund_status_created_id",
            ),
        ]
