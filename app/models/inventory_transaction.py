"""InventoryTransaction Model —— 不可变库存变化流水。"""

from tortoise import fields
from tortoise.indexes import Index
from tortoise.validators import (
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
)

from app.common.constants.inventory import (
    INVENTORY_CHANGE_MAX,
    INVENTORY_CHANGE_MIN,
    INVENTORY_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
    INVENTORY_REASON_MAX_LENGTH,
    INVENTORY_SOURCE_TYPE_MAX_LENGTH,
    INVENTORY_STOCK_MAX,
    INVENTORY_STOCK_MIN,
    INVENTORY_TRANSACTION_TYPE_MAX_LENGTH,
)
from app.common.enums.inventory import InventorySourceType, InventoryTransactionType
from app.db.indexes import UniqueIndex
from app.models.base import BaseModel
from app.models.validators import NonZeroIntegerValidator


class InventoryTransaction(BaseModel):
    """记录每一次已提交库存变化；当前余额仍以 ProductKit.stock 为准。"""

    product = fields.ForeignKeyField(
        "models.Product",
        related_name="inventory_transactions",
        on_delete=fields.RESTRICT,
    )
    transaction_type = fields.CharEnumField(
        InventoryTransactionType,
        max_length=INVENTORY_TRANSACTION_TYPE_MAX_LENGTH,
    )
    change_quantity = fields.IntField(
        validators=[
            MinValueValidator(INVENTORY_CHANGE_MIN),
            MaxValueValidator(INVENTORY_CHANGE_MAX),
            NonZeroIntegerValidator(),
        ],
    )
    before_quantity = fields.IntField(
        validators=[
            MinValueValidator(INVENTORY_STOCK_MIN),
            MaxValueValidator(INVENTORY_STOCK_MAX),
        ],
    )
    after_quantity = fields.IntField(
        validators=[
            MinValueValidator(INVENTORY_STOCK_MIN),
            MaxValueValidator(INVENTORY_STOCK_MAX),
        ],
    )
    source_type = fields.CharEnumField(
        InventorySourceType,
        max_length=INVENTORY_SOURCE_TYPE_MAX_LENGTH,
    )
    source_id = fields.BigIntField(
        null=True,
        validators=[MinValueValidator(1)],
    )
    operator = fields.ForeignKeyField(
        "models.User",
        related_name="operated_inventory_transactions",
        on_delete=fields.RESTRICT,
        null=True,
    )
    reason = fields.CharField(
        max_length=INVENTORY_REASON_MAX_LENGTH,
        validators=[MinLengthValidator(1)],
    )
    idempotency_key = fields.CharField(
        max_length=INVENTORY_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
        validators=[MinLengthValidator(1)],
    )

    class Meta:
        table = "inventory_transactions"
        indexes = [
            UniqueIndex(
                fields=("idempotency_key",),
                name="uidx_inventory_idempotency_key",
            ),
            Index(
                fields=("product_id", "created_at", "id"),
                name="idx_inventory_product_created_id",
            ),
            Index(
                fields=("source_type", "source_id", "created_at", "id"),
                name="idx_inventory_source_created_id",
            ),
            Index(
                fields=("transaction_type", "created_at", "id"),
                name="idx_inventory_type_created_id",
            ),
            Index(
                fields=("created_at", "id"),
                name="idx_inventory_created_id",
            ),
        ]
