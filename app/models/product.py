"""Product Model —— 商品聚合根。"""

from tortoise import fields
from tortoise.indexes import Index
from tortoise.validators import MaxLengthValidator, MinLengthValidator

from app.common.constants.product import (
    PRODUCT_DESCRIPTION_MAX_LENGTH,
    PRODUCT_ENUM_MAX_LENGTH,
    PRODUCT_NAME_MAX_LENGTH,
    PRODUCT_NAME_MIN_LENGTH,
)
from app.common.enums.product import ProductStatus, ProductType
from app.models.base import BaseModel


class Product(BaseModel):
    """体验商品与套装商品的公共聚合根。"""

    name = fields.CharField(
        max_length=PRODUCT_NAME_MAX_LENGTH,
        validators=[MinLengthValidator(PRODUCT_NAME_MIN_LENGTH)],
    )
    product_type = fields.CharEnumField(
        ProductType,
        max_length=PRODUCT_ENUM_MAX_LENGTH,
    )
    description = fields.TextField(
        null=True,
        validators=[MaxLengthValidator(PRODUCT_DESCRIPTION_MAX_LENGTH)],
    )
    status = fields.CharEnumField(
        ProductStatus,
        max_length=PRODUCT_ENUM_MAX_LENGTH,
        default=ProductStatus.DRAFT,
        db_default=ProductStatus.DRAFT.value,
    )
    is_deleted = fields.BooleanField(default=False, db_default=False)

    class Meta:
        table = "products"
        indexes = [
            Index(
                fields=("status", "is_deleted"),
                name="idx_products_status_deleted",
            ),
        ]
