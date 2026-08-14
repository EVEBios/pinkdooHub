"""Order 模块用户端与管理端响应白名单 Schema。"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    model_validator,
)

from app.common.constants.order import (
    ORDER_AMOUNT_DECIMAL_PLACES,
    ORDER_AMOUNT_MAX,
    ORDER_AMOUNT_MIN_EXCLUSIVE,
    ORDER_ITEM_QUANTITY_MAX,
    ORDER_ITEM_QUANTITY_MIN,
    ORDER_ITEMS_MAX_COUNT,
    ORDER_ITEMS_MIN_COUNT,
    ORDER_NO_PATTERN,
    ORDER_REMARK_MAX_LENGTH,
    ORDER_STATUS_LABELS,
    ORDER_STATUS_VALUES,
)
from app.common.constants.product import (
    MIN_DURATION_MINUTES,
    MIN_PARTICIPANTS,
    PRODUCT_NAME_MAX_LENGTH,
    PRODUCT_PRICE_MAX,
)
from app.common.constants.validation import (
    NICKNAME_MAX_LENGTH,
    NICKNAME_MIN_LENGTH,
)
from app.common.enums.order import OrderStatusValue
from app.common.enums.product import DayType

_ORDER_STATUS_LABELS_BY_VALUE = {
    ORDER_STATUS_VALUES[status]: ORDER_STATUS_LABELS[status]
    for status in ORDER_STATUS_VALUES
}
_DAY_TYPE_LABELS = {
    DayType.WEEKDAY: "工作日",
    DayType.HOLIDAY: "节假日",
}


def _require_order_amount_decimal(value: object) -> Decimal:
    """响应金额必须来自领域 Decimal，拒绝 string/float 隐式转换。"""

    if not isinstance(value, Decimal):
        raise ValueError("Response amount must be a Decimal")
    return value


def _serialize_order_amount(value: Decimal) -> str:
    """将合法 Order 金额固定序列化为两位小数字符串。"""

    return f"{value:.{ORDER_AMOUNT_DECIMAL_PLACES}f}"


def _require_utc_response_datetime(value: object) -> datetime:
    """响应时间必须已经是 UTC aware datetime。"""

    if not isinstance(value, datetime):
        raise ValueError("Response datetime must be a datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError("Response datetime must use UTC timezone")
    return value


OrderAmountOut = Annotated[
    Decimal,
    BeforeValidator(_require_order_amount_decimal),
    Field(
        gt=ORDER_AMOUNT_MIN_EXCLUSIVE,
        le=ORDER_AMOUNT_MAX,
        decimal_places=ORDER_AMOUNT_DECIMAL_PLACES,
    ),
    PlainSerializer(
        _serialize_order_amount,
        return_type=str,
        when_used="always",
    ),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": rf"^\d+\.\d{{{ORDER_AMOUNT_DECIMAL_PLACES}}}$",
            "description": "固定两位小数的订单金额字符串",
            "examples": ["497.00"],
        },
        mode="serialization",
    ),
]
OrderUnitPriceOut = Annotated[
    Decimal,
    BeforeValidator(_require_order_amount_decimal),
    Field(
        gt=ORDER_AMOUNT_MIN_EXCLUSIVE,
        le=PRODUCT_PRICE_MAX,
        decimal_places=ORDER_AMOUNT_DECIMAL_PLACES,
    ),
    PlainSerializer(
        _serialize_order_amount,
        return_type=str,
        when_used="always",
    ),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": rf"^\d+\.\d{{{ORDER_AMOUNT_DECIMAL_PLACES}}}$",
            "description": "固定两位小数的 Product/Option 单价快照字符串",
            "examples": ["99.00"],
        },
        mode="serialization",
    ),
]
OrderUtcDatetimeOut = Annotated[
    datetime,
    BeforeValidator(_require_utc_response_datetime),
]


class _OrderOut(BaseModel):
    """Order 响应公共字段白名单配置。"""

    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


class OrderStatusValueOut(_OrderOut):
    """订单状态的机器值与中文展示文案。"""

    value: OrderStatusValue
    label: str = Field(strict=True, min_length=1)

    @model_validator(mode="after")
    def validate_value_label_pair(self) -> "OrderStatusValueOut":
        if self.label != _ORDER_STATUS_LABELS_BY_VALUE[self.value]:
            raise ValueError("Order status label does not match value")
        return self


class OrderDayTypeOut(_OrderOut):
    """订单中的 Experience 日期类型快照展示。"""

    value: DayType
    label: str = Field(strict=True, min_length=1)

    @model_validator(mode="after")
    def validate_value_label_pair(self) -> "OrderDayTypeOut":
        if self.label != _DAY_TYPE_LABELS[self.value]:
            raise ValueError("Order day type label does not match value")
        return self


class OrderItemOut(_OrderOut):
    """OrderItem 历史快照字段白名单。"""

    id: int = Field(strict=True, gt=0)
    product_id: int = Field(strict=True, gt=0)
    experience_option_id: int | None = Field(default=None, strict=True, gt=0)
    product_name: str = Field(
        strict=True,
        min_length=1,
        max_length=PRODUCT_NAME_MAX_LENGTH,
    )
    option_duration_minutes: int | None = Field(
        default=None,
        strict=True,
        ge=MIN_DURATION_MINUTES,
    )
    option_participants: int | None = Field(
        default=None,
        strict=True,
        ge=MIN_PARTICIPANTS,
    )
    option_day_type: OrderDayTypeOut | None = None
    product_price: OrderUnitPriceOut
    quantity: int = Field(
        strict=True,
        ge=ORDER_ITEM_QUANTITY_MIN,
        le=ORDER_ITEM_QUANTITY_MAX,
    )
    subtotal: OrderAmountOut

    @model_validator(mode="after")
    def validate_subtotal(self) -> "OrderItemOut":
        option_metadata = (
            self.option_duration_minutes,
            self.option_participants,
            self.option_day_type,
        )
        if self.experience_option_id is None:
            if any(value is not None for value in option_metadata):
                raise ValueError("Kit item must not contain option snapshots")
        elif any(value is None for value in option_metadata):
            raise ValueError("Experience item requires complete option snapshots")
        if self.subtotal != self.product_price * self.quantity:
            raise ValueError("Order item subtotal does not match price and quantity")
        return self


class _OrderIdentityOut(_OrderOut):
    """Order 列表、详情和状态变迁共享字段。"""

    id: int = Field(strict=True, gt=0)
    order_no: str = Field(strict=True, pattern=ORDER_NO_PATTERN)
    status: OrderStatusValueOut


class _OrderListItemBaseOut(_OrderIdentityOut):
    """用户和管理列表共享摘要。"""

    total_amount: OrderAmountOut
    item_count: int = Field(
        strict=True,
        ge=ORDER_ITEMS_MIN_COUNT,
        le=ORDER_ITEMS_MAX_COUNT,
    )
    created_at: OrderUtcDatetimeOut
    updated_at: OrderUtcDatetimeOut


class OrderListItemOut(_OrderListItemBaseOut):
    """用户端订单列表项，不包含 user 或明细字段。"""


class AdminOrderListItemOut(_OrderListItemBaseOut):
    """管理端订单列表项，增加安全用户展示字段。"""

    user_id: int = Field(strict=True, gt=0)
    user_nickname: str = Field(
        strict=True,
        min_length=NICKNAME_MIN_LENGTH,
        max_length=NICKNAME_MAX_LENGTH,
    )


class _OrderDetailBaseOut(_OrderIdentityOut):
    """用户和管理详情共享的订单快照。"""

    total_amount: OrderAmountOut
    remark: str | None = Field(
        default=None,
        strict=True,
        min_length=1,
        max_length=ORDER_REMARK_MAX_LENGTH,
    )
    items: list[OrderItemOut] = Field(
        min_length=ORDER_ITEMS_MIN_COUNT,
        max_length=ORDER_ITEMS_MAX_COUNT,
    )
    created_at: OrderUtcDatetimeOut
    updated_at: OrderUtcDatetimeOut

    @model_validator(mode="after")
    def validate_total_amount(self) -> "_OrderDetailBaseOut":
        if self.total_amount != sum(
            (item.subtotal for item in self.items),
            start=Decimal("0.00"),
        ):
            raise ValueError("Order total amount does not match item subtotals")
        return self


class OrderDetailOut(_OrderDetailBaseOut):
    """用户端创建/详情响应，不暴露 user 字段。"""


class AdminOrderDetailOut(_OrderDetailBaseOut):
    """管理端详情，额外返回安全用户展示字段。"""

    user_id: int = Field(strict=True, gt=0)
    user_nickname: str = Field(
        strict=True,
        min_length=NICKNAME_MIN_LENGTH,
        max_length=NICKNAME_MAX_LENGTH,
    )


class OrderStatusOut(_OrderIdentityOut):
    """取消、确认支付和完成订单的轻量响应。"""

    updated_at: OrderUtcDatetimeOut
