"""Inventory 模块写请求与流水查询 Schema。"""

from datetime import datetime, timedelta
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.common.constants.inventory import (
    INVENTORY_CHANGE_MAX,
    INVENTORY_CHANGE_MIN,
    INVENTORY_IDEMPOTENCY_KEY_MAX_LENGTH,
    INVENTORY_IDEMPOTENCY_KEY_MIN_LENGTH,
    INVENTORY_IDEMPOTENCY_KEY_PATTERN,
    INVENTORY_REASON_MAX_LENGTH,
    INVENTORY_REASON_MIN_LENGTH,
)
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.pagination import PageParams


def _normalize_idempotency_key(value: object) -> str:
    """幂等键只接受字符串，并在校验前去除首尾空白。"""

    if not isinstance(value, str):
        raise ValueError("Idempotency key must be a string")
    return value.strip()


def _parse_positive_query_id(value: object) -> int:
    """Query ID 接受 HTTP 十进制字符串，拒绝 bool 与宽松格式。"""

    if isinstance(value, bool):
        raise ValueError("Query ID must be a positive integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isascii() and normalized.isdecimal():
            return int(normalized)
    raise ValueError("Query ID must be a positive integer")


def _require_utc_datetime(value: AwareDatetime) -> datetime:
    """Inventory 时间筛选必须显式使用 UTC。"""

    if value.utcoffset() != timedelta(0):
        raise ValueError("Datetime must use UTC timezone")
    return value


InventoryIdempotencyKey = Annotated[
    str,
    BeforeValidator(_normalize_idempotency_key),
    Field(
        strict=True,
        min_length=INVENTORY_IDEMPOTENCY_KEY_MIN_LENGTH,
        max_length=INVENTORY_IDEMPOTENCY_KEY_MAX_LENGTH,
        pattern=INVENTORY_IDEMPOTENCY_KEY_PATTERN,
    ),
]
InventoryChange = Annotated[
    int,
    Field(
        strict=True,
        ge=INVENTORY_CHANGE_MIN,
        le=INVENTORY_CHANGE_MAX,
    ),
]
InventoryReason = Annotated[
    str,
    Field(
        strict=True,
        min_length=INVENTORY_REASON_MIN_LENGTH,
        max_length=INVENTORY_REASON_MAX_LENGTH,
    ),
]
PositiveInventoryQueryId = Annotated[
    int,
    BeforeValidator(_parse_positive_query_id),
    Field(gt=0),
]


class _InventoryRequest(BaseModel):
    """Inventory 不可信输入的严格公共配置。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InventoryAdjustmentCreate(_InventoryRequest):
    """管理员以变化量和原因调整 Kit 当前库存。"""

    change: InventoryChange
    reason: InventoryReason

    @field_validator("change", mode="after")
    @classmethod
    def reject_zero_change(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Inventory change must not be zero")
        return value


class _InventoryTransactionQueryBase(PageParams):
    """全局与指定 Product 流水共享筛选条件。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    transaction_type: InventoryTransactionType | None = Field(
        default=None,
        alias="type",
    )
    source_type: InventorySourceType | None = None
    source_id: PositiveInventoryQueryId | None = None
    created_from: AwareDatetime | None = None
    created_to: AwareDatetime | None = None

    @field_validator("created_from", "created_to", mode="after")
    @classmethod
    def require_utc_datetime(
        cls,
        value: AwareDatetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        return _require_utc_datetime(value)

    @model_validator(mode="after")
    def validate_filters(self) -> "_InventoryTransactionQueryBase":
        if (
            self.source_id is not None
            and self.source_type is not InventorySourceType.ORDER
        ):
            raise ValueError("source_id requires source_type=order")
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_to <= self.created_from
        ):
            raise ValueError("created_to must be later than created_from")
        return self


class InventoryProductTransactionQuery(_InventoryTransactionQueryBase):
    """指定 Kit Product 的库存流水分页筛选。"""


class InventoryTransactionQuery(_InventoryTransactionQueryBase):
    """全局库存流水分页筛选。"""

    product_id: PositiveInventoryQueryId | None = None
