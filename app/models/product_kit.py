"""ProductKit Model —— 套装商品的一对一扩展数据。"""

from tortoise import fields
from tortoise.validators import MaxValueValidator, MinValueValidator

from app.common.constants.inventory import INVENTORY_STOCK_MAX
from app.common.constants.product import (
    MIN_STOCK,
    PRODUCT_PRICE_DECIMAL_PLACES,
    PRODUCT_PRICE_MAX,
    PRODUCT_PRICE_MIN,
)
from app.models.base import BaseModel
from app.models.fields import StrictDecimalField


class ProductKit(BaseModel):
    """套装商品的价格与当前库存。"""

    product = fields.OneToOneField(
        "models.Product",
        related_name="kit",
        on_delete=fields.RESTRICT,
    )
    price = StrictDecimalField(
        max_digits=10,
        decimal_places=PRODUCT_PRICE_DECIMAL_PLACES,
        validators=[
            MinValueValidator(PRODUCT_PRICE_MIN),
            MaxValueValidator(PRODUCT_PRICE_MAX),
        ],
    )
    stock = fields.IntField(
        default=MIN_STOCK,
        db_default=MIN_STOCK,
        validators=[
            MinValueValidator(MIN_STOCK),
            MaxValueValidator(INVENTORY_STOCK_MAX),
        ],
    )

    class Meta:
        table = "product_kits"
