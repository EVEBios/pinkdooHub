"""Order Models —— 订单聚合根与不可变业务快照明细。"""

from tortoise import fields
from tortoise.indexes import Index
from tortoise.validators import (
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    RegexValidator,
)

from app.common.constants.order import (
    ORDER_AMOUNT_DECIMAL_PLACES,
    ORDER_AMOUNT_MAX,
    ORDER_AMOUNT_MIN,
    ORDER_ITEM_QUANTITY_MAX,
    ORDER_ITEM_QUANTITY_MIN,
    ORDER_NO_LENGTH,
    ORDER_NO_PATTERN,
    ORDER_REMARK_MAX_LENGTH,
)
from app.common.constants.product import (
    MIN_DURATION_MINUTES,
    MIN_PARTICIPANTS,
    PRODUCT_ENUM_MAX_LENGTH,
    PRODUCT_NAME_MAX_LENGTH,
    PRODUCT_NAME_MIN_LENGTH,
    PRODUCT_PRICE_DECIMAL_PLACES,
    PRODUCT_PRICE_MAX,
    PRODUCT_PRICE_MIN,
)
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType
from app.models.base import BaseModel
from app.models.fields import StrictDecimalField


class Order(BaseModel):
    """订单聚合根；金额与状态只允许由 Order Service 编排修改。"""

    order_no = fields.CharField(
        max_length=ORDER_NO_LENGTH,
        unique=True,
        validators=[RegexValidator(ORDER_NO_PATTERN, flags=0)],
    )
    user = fields.ForeignKeyField(
        "models.User",
        related_name="orders",
        on_delete=fields.RESTRICT,
    )
    total_amount = StrictDecimalField(
        max_digits=10,
        decimal_places=ORDER_AMOUNT_DECIMAL_PLACES,
        validators=[
            MinValueValidator(ORDER_AMOUNT_MIN),
            MaxValueValidator(ORDER_AMOUNT_MAX),
        ],
    )
    status = fields.SmallIntField(
        default=OrderStatus.PENDING,
        db_default=OrderStatus.PENDING.value,
        validators=[
            MinValueValidator(OrderStatus.PENDING.value),
            MaxValueValidator(OrderStatus.COMPLETED.value),
        ],
    )
    remark = fields.CharField(max_length=ORDER_REMARK_MAX_LENGTH, null=True)

    class Meta:
        table = "orders"
        indexes = [
            Index(
                fields=("user_id", "created_at", "id"),
                name="idx_orders_user_created_id",
            ),
            Index(
                fields=("user_id", "status", "created_at", "id"),
                name="idx_orders_user_status_created_id",
            ),
            Index(
                fields=("status", "created_at", "id"),
                name="idx_orders_status_created_id",
            ),
            Index(
                fields=("created_at", "id"),
                name="idx_orders_created_id",
            ),
        ]


class OrderItem(BaseModel):
    """订单创建时写入的商品与 Experience Option 历史快照。"""

    order = fields.ForeignKeyField(
        "models.Order",
        related_name="items",
        on_delete=fields.RESTRICT,
    )
    product = fields.ForeignKeyField(
        "models.Product",
        related_name="order_items",
        on_delete=fields.RESTRICT,
    )
    experience_option = fields.ForeignKeyField(
        "models.ExperienceOption",
        related_name="order_items",
        on_delete=fields.RESTRICT,
        null=True,
    )
    option_duration_minutes = fields.IntField(
        null=True,
        validators=[MinValueValidator(MIN_DURATION_MINUTES)],
    )
    option_participants = fields.IntField(
        null=True,
        validators=[MinValueValidator(MIN_PARTICIPANTS)],
    )
    option_day_type = fields.CharEnumField(
        DayType,
        max_length=PRODUCT_ENUM_MAX_LENGTH,
        null=True,
    )
    product_name = fields.CharField(
        max_length=PRODUCT_NAME_MAX_LENGTH,
        validators=[MinLengthValidator(PRODUCT_NAME_MIN_LENGTH)],
    )
    product_price = StrictDecimalField(
        max_digits=10,
        decimal_places=PRODUCT_PRICE_DECIMAL_PLACES,
        validators=[
            MinValueValidator(PRODUCT_PRICE_MIN),
            MaxValueValidator(PRODUCT_PRICE_MAX),
        ],
    )
    quantity = fields.IntField(
        validators=[
            MinValueValidator(ORDER_ITEM_QUANTITY_MIN),
            MaxValueValidator(ORDER_ITEM_QUANTITY_MAX),
        ],
    )
    subtotal = StrictDecimalField(
        max_digits=10,
        decimal_places=ORDER_AMOUNT_DECIMAL_PLACES,
        validators=[
            MinValueValidator(ORDER_AMOUNT_MIN),
            MaxValueValidator(ORDER_AMOUNT_MAX),
        ],
    )

    class Meta:
        table = "order_items"
        indexes = [
            Index(
                fields=("order_id", "id"),
                name="idx_order_items_order_id",
            ),
        ]
