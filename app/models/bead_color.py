"""BeadColor Model —— 全局固定 221 槽的拼豆颜色目录。"""

from tortoise import fields
from tortoise.indexes import Index
from tortoise.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)

from app.common.constants.product import (
    BEAD_COLOR_CODE_MAX_LENGTH,
    BEAD_COLOR_NAME_MAX_LENGTH,
    BEAD_COLOR_SLOT_COUNT,
    BEAD_COLOR_SLOT_MIN,
    BEAD_COLOR_SWATCH_HEX_LENGTH,
    BEAD_COLOR_SWATCH_HEX_PATTERN,
    MAX_BEAD_COLOR_SORT,
    MIN_BEAD_COLOR_SORT,
    PRODUCT_IMAGE_URL_MAX_LENGTH,
)
from app.models.base import BaseModel


class BeadColor(BaseModel):
    """全局颜色身份；占位槽允许暂时没有编码和名称。"""

    slot_no = fields.SmallIntField(
        unique=True,
        validators=[
            MinValueValidator(BEAD_COLOR_SLOT_MIN),
            MaxValueValidator(BEAD_COLOR_SLOT_COUNT),
        ],
    )
    color_code = fields.CharField(
        max_length=BEAD_COLOR_CODE_MAX_LENGTH,
        null=True,
        unique=True,
    )
    name = fields.CharField(max_length=BEAD_COLOR_NAME_MAX_LENGTH, null=True)
    swatch_hex = fields.CharField(
        max_length=BEAD_COLOR_SWATCH_HEX_LENGTH,
        null=True,
        validators=[RegexValidator(BEAD_COLOR_SWATCH_HEX_PATTERN, flags=0)],
    )
    swatch_image_url = fields.CharField(
        max_length=PRODUCT_IMAGE_URL_MAX_LENGTH,
        null=True,
    )
    sort = fields.SmallIntField(
        default=MIN_BEAD_COLOR_SORT,
        db_default=MIN_BEAD_COLOR_SORT,
        validators=[
            MinValueValidator(MIN_BEAD_COLOR_SORT),
            MaxValueValidator(MAX_BEAD_COLOR_SORT),
        ],
    )
    is_active = fields.BooleanField(default=False, db_default=False)

    class Meta:
        table = "bead_colors"
        indexes = [
            Index(
                fields=("is_active", "sort", "slot_no"),
                name="idx_bead_colors_active_sort_slot",
            ),
        ]
