"""Inventory 模块响应字段白名单与聚合一致性校验。"""

from datetime import datetime, timedelta
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from app.common.constants.inventory import (
    INVENTORY_REASON_MAX_LENGTH,
    INVENTORY_REASON_MIN_LENGTH,
    INVENTORY_STOCK_MAX,
    INVENTORY_STOCK_MIN,
)
from app.common.constants.order import ORDER_NO_PATTERN
from app.common.constants.product import (
    BEAD_COLOR_CODE_MAX_LENGTH,
    BEAD_COLOR_NAME_MAX_LENGTH,
    BEAD_COLOR_SLOT_COUNT,
    BEAD_COLOR_SLOT_MIN,
    COLOR_SELECTABLE_SALE_UNIT_GRAMS,
)
from app.common.constants.validation import (
    NICKNAME_MAX_LENGTH,
    NICKNAME_MIN_LENGTH,
)
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)


def _require_utc_response_datetime(value: object) -> datetime:
    """响应时间必须已经是 UTC aware datetime。"""

    if not isinstance(value, datetime):
        raise ValueError("Response datetime must be a datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError("Response datetime must use UTC timezone")
    return value


InventoryUtcDatetimeOut = Annotated[
    datetime,
    BeforeValidator(_require_utc_response_datetime),
]
InventoryQuantityOut = Annotated[
    int,
    Field(strict=True, ge=INVENTORY_STOCK_MIN, le=INVENTORY_STOCK_MAX),
]
PositiveInventoryResourceIdOut = Annotated[int, Field(strict=True, gt=0)]
InventoryReasonOut = Annotated[
    str,
    Field(
        strict=True,
        min_length=INVENTORY_REASON_MIN_LENGTH,
        max_length=INVENTORY_REASON_MAX_LENGTH,
    ),
]


class _InventoryOut(BaseModel):
    """Inventory 响应的可信内部数据白名单配置。"""

    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


class InventoryBalanceOut(_InventoryOut):
    """Kit 当前权威库存余额。"""

    product_id: PositiveInventoryResourceIdOut
    stock: InventoryQuantityOut


class InventoryColorBalanceOut(_InventoryOut):
    """一个可选颜色以 10g 为单位的当前权威库存余额。"""

    product_id: PositiveInventoryResourceIdOut
    kit_color_id: PositiveInventoryResourceIdOut
    bead_color_id: PositiveInventoryResourceIdOut
    bead_color_slot_no: int = Field(
        strict=True,
        ge=BEAD_COLOR_SLOT_MIN,
        le=BEAD_COLOR_SLOT_COUNT,
    )
    color_code: str | None = Field(
        strict=True,
        min_length=1,
        max_length=BEAD_COLOR_CODE_MAX_LENGTH,
    )
    color_name: str | None = Field(
        strict=True,
        min_length=1,
        max_length=BEAD_COLOR_NAME_MAX_LENGTH,
    )
    sale_unit_grams: int = Field(
        strict=True,
        ge=COLOR_SELECTABLE_SALE_UNIT_GRAMS,
        le=COLOR_SELECTABLE_SALE_UNIT_GRAMS,
    )
    stock_units: InventoryQuantityOut


class InventoryTransactionOut(_InventoryOut):
    """单条不可变库存流水的公开字段。"""

    id: PositiveInventoryResourceIdOut
    product_id: PositiveInventoryResourceIdOut
    kit_color_id: PositiveInventoryResourceIdOut | None
    bead_color_id: PositiveInventoryResourceIdOut | None
    bead_color_slot_no: int | None = Field(
        strict=True,
        ge=BEAD_COLOR_SLOT_MIN,
        le=BEAD_COLOR_SLOT_COUNT,
    )
    color_code: str | None = Field(
        strict=True,
        min_length=1,
        max_length=BEAD_COLOR_CODE_MAX_LENGTH,
    )
    color_name: str | None = Field(
        strict=True,
        min_length=1,
        max_length=BEAD_COLOR_NAME_MAX_LENGTH,
    )
    sale_unit_grams: int | None = Field(
        strict=True,
        ge=COLOR_SELECTABLE_SALE_UNIT_GRAMS,
        le=COLOR_SELECTABLE_SALE_UNIT_GRAMS,
    )
    transaction_type: InventoryTransactionType
    change_quantity: int = Field(
        strict=True,
        ge=-INVENTORY_STOCK_MAX,
        le=INVENTORY_STOCK_MAX,
    )
    before_quantity: InventoryQuantityOut
    after_quantity: InventoryQuantityOut
    reason: InventoryReasonOut
    source_type: InventorySourceType
    source_id: PositiveInventoryResourceIdOut | None = None
    source_order_no: str | None = Field(
        default=None,
        strict=True,
        pattern=ORDER_NO_PATTERN,
    )
    operator_id: PositiveInventoryResourceIdOut | None = None
    operator_nickname: str | None = Field(
        default=None,
        strict=True,
        min_length=NICKNAME_MIN_LENGTH,
        max_length=NICKNAME_MAX_LENGTH,
    )
    created_at: InventoryUtcDatetimeOut

    @model_validator(mode="after")
    def validate_transaction_consistency(self) -> "InventoryTransactionOut":
        if self.change_quantity == 0:
            raise ValueError("Inventory transaction change must not be zero")
        if self.after_quantity != self.before_quantity + self.change_quantity:
            raise ValueError("Inventory transaction quantities are inconsistent")

        color_metadata = (
            self.bead_color_id,
            self.bead_color_slot_no,
            self.color_code,
            self.color_name,
            self.sale_unit_grams,
        )
        if self.kit_color_id is None:
            if any(value is not None for value in color_metadata):
                raise ValueError("Fixed inventory transaction has color metadata")
        elif any(
            value is None
            for value in (
                self.bead_color_id,
                self.bead_color_slot_no,
                self.sale_unit_grams,
            )
        ):
            raise ValueError("Color inventory transaction metadata is incomplete")

        if self.transaction_type is InventoryTransactionType.OPENING_BALANCE:
            if (
                self.source_type is not InventorySourceType.MIGRATION
                or self.before_quantity != INVENTORY_STOCK_MIN
                or self.change_quantity <= 0
                or self.source_id is not None
                or self.source_order_no is not None
                or self.operator_id is not None
                or self.operator_nickname is not None
            ):
                raise ValueError("Opening balance transaction metadata is invalid")
        elif self.transaction_type is InventoryTransactionType.ADMIN_ADJUSTMENT:
            if (
                self.source_type is not InventorySourceType.ADMIN
                or self.source_id is not None
                or self.source_order_no is not None
                or self.operator_id is None
                or self.operator_nickname is None
            ):
                raise ValueError("Admin adjustment transaction metadata is invalid")
        else:
            expected_positive = self.transaction_type in (
                InventoryTransactionType.ORDER_CANCELLATION_RESTORE,
                InventoryTransactionType.ORDER_REFUND_RESTORE,
            )
            if (
                self.source_type is not InventorySourceType.ORDER
                or self.source_id is None
                or self.source_order_no is None
                or (expected_positive and self.change_quantity <= 0)
                or (not expected_positive and self.change_quantity >= 0)
                or (self.operator_id is None) != (self.operator_nickname is None)
            ):
                raise ValueError("Order inventory transaction metadata is invalid")
        return self


class InventoryTransactionListItem(InventoryTransactionOut):
    """流水分页列表项；与详情共享同一安全字段集合。"""


class InventoryAdjustmentOut(InventoryBalanceOut):
    """管理员调整成功后的余额与本次流水。"""

    transaction: InventoryTransactionOut

    @model_validator(mode="after")
    def validate_adjustment_result(self) -> "InventoryAdjustmentOut":
        if (
            self.transaction.transaction_type
            is not InventoryTransactionType.ADMIN_ADJUSTMENT
            or self.transaction.product_id != self.product_id
            or self.transaction.after_quantity != self.stock
        ):
            raise ValueError("Inventory adjustment result is inconsistent")
        return self


class InventoryColorAdjustmentOut(InventoryColorBalanceOut):
    """管理员调整颜色余额后的当前值与不可变流水。"""

    transaction: InventoryTransactionOut

    @model_validator(mode="after")
    def validate_adjustment_result(self) -> "InventoryColorAdjustmentOut":
        if (
            self.transaction.transaction_type
            is not InventoryTransactionType.ADMIN_ADJUSTMENT
            or self.transaction.product_id != self.product_id
            or self.transaction.kit_color_id != self.kit_color_id
            or self.transaction.after_quantity != self.stock_units
        ):
            raise ValueError("Color inventory adjustment result is inconsistent")
        return self
