"""ExperienceOption Model —— 体验商品的可售配置。"""

from tortoise import fields
from tortoise.validators import MaxValueValidator, MinValueValidator

from app.common.constants.product import (
    MIN_DURATION_MINUTES,
    MIN_PARTICIPANTS,
    PRODUCT_ENUM_MAX_LENGTH,
    PRODUCT_PRICE_DECIMAL_PLACES,
    PRODUCT_PRICE_MAX,
    PRODUCT_PRICE_MIN,
)
from app.common.enums.product import DayType
from app.db.indexes import UniqueIndex
from app.models.base import BaseModel
from app.models.fields import StrictDecimalField


class ExperienceOption(BaseModel):
    """体验商品的一组时长、人数、日期类型与价格配置。"""

    product = fields.ForeignKeyField(
        "models.Product",
        related_name="experience_options",
        on_delete=fields.RESTRICT,
    )
    duration = fields.IntField(
        validators=[MinValueValidator(MIN_DURATION_MINUTES)],
    )
    participants = fields.IntField(
        validators=[MinValueValidator(MIN_PARTICIPANTS)],
    )
    day_type = fields.CharEnumField(
        DayType,
        max_length=PRODUCT_ENUM_MAX_LENGTH,
    )
    price = StrictDecimalField(
        max_digits=10,
        decimal_places=PRODUCT_PRICE_DECIMAL_PLACES,
        validators=[
            MinValueValidator(PRODUCT_PRICE_MIN),
            MaxValueValidator(PRODUCT_PRICE_MAX),
        ],
    )
    is_deleted = fields.BooleanField(default=False, db_default=False)

    class Meta:
        table = "experience_options"
        indexes = [
            UniqueIndex(
                fields=("product_id", "duration", "participants", "day_type"),
                name="idx_option_unique",
            ),
        ]
