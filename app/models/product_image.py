"""ProductImage Model —— Product 公共图与 ExperienceOption 专属图。"""

from tortoise import fields
from tortoise.indexes import Index
from tortoise.validators import MinLengthValidator, MinValueValidator

from app.common.constants.product import (
    MIN_IMAGE_SORT,
    PRODUCT_IMAGE_URL_MAX_LENGTH,
    PRODUCT_IMAGE_URL_MIN_LENGTH,
)
from app.models.base import BaseModel


class ProductImage(BaseModel):
    """商品图片；可选关联 ExperienceOption 以表达 Option 专属图片。"""

    product = fields.ForeignKeyField(
        "models.Product",
        related_name="images",
        on_delete=fields.RESTRICT,
    )
    experience_option = fields.ForeignKeyField(
        "models.ExperienceOption",
        related_name="images",
        on_delete=fields.SET_NULL,
        null=True,
    )
    image_url = fields.CharField(
        max_length=PRODUCT_IMAGE_URL_MAX_LENGTH,
        validators=[MinLengthValidator(PRODUCT_IMAGE_URL_MIN_LENGTH)],
    )
    is_cover = fields.BooleanField(default=False, db_default=False)
    sort = fields.IntField(
        default=MIN_IMAGE_SORT,
        db_default=MIN_IMAGE_SORT,
        validators=[MinValueValidator(MIN_IMAGE_SORT)],
    )
    is_deleted = fields.BooleanField(default=False, db_default=False)

    class Meta:
        table = "product_images"
        indexes = [
            Index(
                fields=("product_id", "sort"),
                name="idx_image_product_sort",
            ),
            Index(
                fields=("product_id", "is_cover"),
                name="idx_image_product_cover",
            ),
            Index(
                fields=("experience_option_id", "sort"),
                name="idx_image_option_sort",
            ),
        ]
