"""Order 模块请求体与列表查询 Schema。"""

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

from app.common.constants.order import (
    ORDER_ITEM_QUANTITY_MAX,
    ORDER_ITEM_QUANTITY_MIN,
    ORDER_ITEMS_MAX_COUNT,
    ORDER_ITEMS_MIN_COUNT,
    ORDER_NO_PATTERN,
    ORDER_REMARK_MAX_LENGTH,
)
from app.common.enums.order import OrderStatusValue
from app.common.pagination import PageParams

PositiveOrderResourceId = Annotated[int, Field(strict=True, gt=0)]


def _parse_positive_query_id(value: object) -> int:
    """Query ID 接受十进制字符串，拒绝 bool 和宽松数值格式。"""

    if isinstance(value, bool):
        raise ValueError("Query ID must be a positive integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isascii() and normalized.isdecimal():
            return int(normalized)
    raise ValueError("Query ID must be a positive integer")


PositiveOrderQueryId = Annotated[
    int,
    BeforeValidator(_parse_positive_query_id),
    Field(gt=0),
]
OrderItemQuantity = Annotated[
    int,
    Field(
        strict=True,
        ge=ORDER_ITEM_QUANTITY_MIN,
        le=ORDER_ITEM_QUANTITY_MAX,
    ),
]
OrderRemark = Annotated[
    str,
    Field(strict=True, max_length=ORDER_REMARK_MAX_LENGTH),
]
OrderNumberQuery = Annotated[
    str,
    Field(strict=True, pattern=ORDER_NO_PATTERN),
]


def _require_utc_datetime(value: AwareDatetime) -> datetime:
    """查询时间必须显式携带 UTC 时区，拒绝其他 offset。"""

    if value.utcoffset() != timedelta(0):
        raise ValueError("Datetime must use UTC timezone")
    return value


class _OrderRequest(BaseModel):
    """Order 请求公共严格配置。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OrderItemCreate(_OrderRequest):
    """创建订单时的单个 Experience Item。"""

    product_id: PositiveOrderResourceId
    experience_option_id: PositiveOrderResourceId
    quantity: OrderItemQuantity


class OrderCreate(_OrderRequest):
    """创建 Experience 订单请求。"""

    items: list[OrderItemCreate] = Field(
        min_length=ORDER_ITEMS_MIN_COUNT,
        max_length=ORDER_ITEMS_MAX_COUNT,
    )
    remark: OrderRemark | None = None

    @field_validator("remark", mode="after")
    @classmethod
    def normalize_empty_remark(cls, value: str | None) -> str | None:
        """空字符串或纯空白备注统一为未填写。"""

        return None if value == "" else value

    @model_validator(mode="after")
    def reject_duplicate_items(self) -> "OrderCreate":
        """同一 Product/Option 组合不得重复，也不静默合并。"""

        keys = [
            (item.product_id, item.experience_option_id)
            for item in self.items
        ]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "Duplicate product and experience option combinations "
                "are not allowed"
            )
        return self


class OrderListQuery(PageParams):
    """用户端订单分页查询。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: OrderStatusValue | None = None


class AdminOrderListQuery(OrderListQuery):
    """管理端订单分页与组合筛选。"""

    order_no: OrderNumberQuery | None = None
    user_id: PositiveOrderQueryId | None = None
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
    def validate_created_range(self) -> "AdminOrderListQuery":
        """同时提供上下界时，上界必须严格晚于下界。"""

        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_to <= self.created_from
        ):
            raise ValueError("created_to must be later than created_from")
        return self
