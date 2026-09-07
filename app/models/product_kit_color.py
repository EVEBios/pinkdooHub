"""ProductKitColor Model —— 商品级颜色启用状态与库存余额。"""

from tortoise import fields
from tortoise.indexes import Index
from tortoise.validators import MaxValueValidator, MinValueValidator

from app.common.constants.product import (
    MIN_STOCK,
    PRODUCT_KIT_COLOR_STOCK_UNITS_MAX,
)
from app.models.base import BaseModel


class ProductKitColor(BaseModel):
    """一个自选颜色 Kit 对一个全局颜色槽的商品级配置。"""

    product = fields.ForeignKeyField(
        "models.Product",
        related_name="kit_colors",
        on_delete=fields.RESTRICT,
    )
    bead_color = fields.ForeignKeyField(
        "models.BeadColor",
        related_name="product_kit_colors",
        on_delete=fields.RESTRICT,
    )
    is_enabled = fields.BooleanField(default=False, db_default=False)
    stock_units = fields.IntField(
        default=MIN_STOCK,
        db_default=MIN_STOCK,
        validators=[
            MinValueValidator(MIN_STOCK),
            MaxValueValidator(PRODUCT_KIT_COLOR_STOCK_UNITS_MAX),
        ],
    )

    class Meta:
        table = "product_kit_colors"
        unique_together = (("product", "bead_color"),)
        indexes = [
            Index(
                fields=("product", "is_enabled"),
                name="idx_product_kit_colors_product_enabled",
            ),
            Index(
                fields=("bead_color", "is_enabled"),
                name="idx_product_kit_colors_color_enabled",
            ),
        ]
