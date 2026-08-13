"""Product 模块响应数据结构。"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    model_validator,
)

from app.common.constants.product import (
    MIN_DURATION_MINUTES,
    MIN_IMAGE_SORT,
    MIN_PARTICIPANTS,
    MIN_STOCK,
    PRODUCT_DESCRIPTION_MAX_LENGTH,
    PRODUCT_PRICE_DECIMAL_PLACES,
    PRODUCT_PRICE_MAX,
    PRODUCT_PRICE_MIN_EXCLUSIVE,
)
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.schemas.product import ProductDescription, ProductName

ValueT = TypeVar("ValueT")


def _require_product_price_decimal(value: object) -> Decimal:
    """响应金额必须已经是 Decimal，拒绝 string/float 的隐式转换。"""

    if not isinstance(value, Decimal):
        raise ValueError("Response price must be a Decimal")
    return value


def _serialize_product_price(value: Decimal) -> str:
    """将合法 Decimal 金额固定序列化为两位小数字符串。"""

    return f"{value:.{PRODUCT_PRICE_DECIMAL_PLACES}f}"


def _require_true_boolean(value: object) -> Literal[True]:
    """成功删除响应只接受真正的 boolean true。"""

    if value is not True:
        raise ValueError("Deleted flag must be boolean true")
    return True


ProductPriceOut = Annotated[
    Decimal,
    BeforeValidator(_require_product_price_decimal),
    Field(
        gt=PRODUCT_PRICE_MIN_EXCLUSIVE,
        le=PRODUCT_PRICE_MAX,
        decimal_places=PRODUCT_PRICE_DECIMAL_PLACES,
    ),
    PlainSerializer(
        _serialize_product_price,
        return_type=str,
        when_used="always",
    ),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": rf"^\d+\.\d{{{PRODUCT_PRICE_DECIMAL_PLACES}}}$",
            "description": "固定两位小数的金额字符串，0 < price <= 99999",
            "examples": ["599.00"],
        },
        mode="serialization",
    ),
]

PublishedProductDescription = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=PRODUCT_DESCRIPTION_MAX_LENGTH,
    ),
]

DurationMinutesOut = Annotated[
    int,
    Field(strict=True, ge=MIN_DURATION_MINUTES),
]
ParticipantsOut = Annotated[
    int,
    Field(strict=True, ge=MIN_PARTICIPANTS),
]
DeletedFlagOut = Annotated[
    Literal[True],
    BeforeValidator(_require_true_boolean),
]


class _ProductOut(BaseModel):
    """Product 响应模型公共配置。"""

    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


class LabeledValue(_ProductOut, Generic[ValueT]):
    """前端展示值对象：机器可读 value + 用户可读 label。"""

    value: ValueT
    label: str = Field(strict=True, min_length=1)


class _ImageOutBase(_ProductOut):
    """两类商品图片共享的响应字段。"""

    id: int = Field(strict=True, gt=0)
    image_url: str = Field(strict=True, min_length=1)


class ProductImageOut(_ImageOutBase):
    """Product 公共图片响应，包含封面标记。"""

    is_cover: bool = Field(strict=True)
    sort: int = Field(strict=True, ge=MIN_IMAGE_SORT)


class OptionImageOut(_ImageOutBase):
    """Experience Option 专属图片响应，不包含封面标记。"""

    sort: int = Field(strict=True, ge=MIN_IMAGE_SORT)


class ExperienceOptionBaseOut(_ProductOut):
    """Experience Option 基础响应，不包含图片。"""

    id: int = Field(strict=True, gt=0)
    duration: LabeledValue[DurationMinutesOut]
    participants: LabeledValue[ParticipantsOut]
    day_type: LabeledValue[DayType]
    price: ProductPriceOut


class ExperienceOptionOut(ExperienceOptionBaseOut):
    """Experience Option 完整响应。"""

    images: list[OptionImageOut]


class ExperienceDimensionsOut(_ProductOut):
    """由有效 Experience Option 动态汇总的选择维度。"""

    durations: list[LabeledValue[DurationMinutesOut]]
    participants: list[LabeledValue[ParticipantsOut]]
    day_types: list[LabeledValue[DayType]]


class _ProductIdentityOut(_ProductOut):
    """商品列表与详情共享的稳定标识字段。"""

    id: int = Field(strict=True, gt=0)
    name: ProductName
    product_type: LabeledValue[ProductType]


class _ProductCreateOut(_ProductIdentityOut):
    """创建商品草稿的公共响应字段。"""

    status: LabeledValue[Literal[ProductStatus.DRAFT]]


class ExperienceProductCreateOut(_ProductCreateOut):
    """创建体验商品草稿响应。"""

    product_type: LabeledValue[Literal[ProductType.EXPERIENCE]]


class KitProductCreateOut(_ProductCreateOut):
    """创建套装商品草稿响应。"""

    product_type: LabeledValue[Literal[ProductType.KIT]]


class ProductBasicInfoOut(_ProductOut):
    """修改商品名称或描述后的轻量响应。"""

    id: int = Field(strict=True, gt=0)
    name: ProductName
    description: ProductDescription | None
    updated_at: datetime = Field(strict=True)


class ProductOnlineOut(_ProductOut):
    """商品上架成功响应。"""

    id: int = Field(strict=True, gt=0)
    status: LabeledValue[Literal[ProductStatus.ONLINE]]


class ProductOfflineOut(_ProductOut):
    """商品下架成功响应。"""

    id: int = Field(strict=True, gt=0)
    status: LabeledValue[Literal[ProductStatus.OFFLINE]]


class DeletedResourceOut(_ProductOut):
    """Product、Option 和 Image 逻辑删除成功响应。"""

    id: int = Field(strict=True, gt=0)
    is_deleted: DeletedFlagOut


class KitPriceOut(_ProductOut):
    """修改套装商品价格响应。"""

    id: int = Field(strict=True, gt=0)
    price: ProductPriceOut


class KitStockOut(_ProductOut):
    """修改套装商品当前库存响应。"""

    id: int = Field(strict=True, gt=0)
    stock: int = Field(strict=True, ge=MIN_STOCK)


class ProductListItemOut(_ProductIdentityOut):
    """用户端商品列表项——仅用于完整且已上架的商品。"""

    cover_image: str = Field(strict=True, min_length=1)
    display_price: ProductPriceOut


class AdminProductListItemOut(_ProductIdentityOut):
    """管理端商品列表摘要，允许草稿商品尚未配置完整。"""

    status: LabeledValue[ProductStatus]
    cover_image: str | None = Field(default=None, strict=True, min_length=1)
    display_price: ProductPriceOut | None = None
    updated_at: datetime = Field(strict=True)
    is_deleted: bool = Field(strict=True)


class _OnlineExperienceOptionOut(ExperienceOptionBaseOut):
    """用户端已上架体验 Option，必须至少包含一张专属图片。"""

    images: list[OptionImageOut] = Field(min_length=1)


class _OnlineExperienceDimensionsOut(_ProductOut):
    """用户端已上架体验商品的非空可选维度。"""

    durations: list[LabeledValue[DurationMinutesOut]] = Field(min_length=1)
    participants: list[LabeledValue[ParticipantsOut]] = Field(min_length=1)
    day_types: list[LabeledValue[DayType]] = Field(min_length=1)


class _UserProductDetailOut(_ProductIdentityOut):
    """用户端详情公共字段，只允许输出已上架完整商品的数据。"""

    description: PublishedProductDescription
    images: list[ProductImageOut] = Field(min_length=1)


class ExperienceProductDetailOut(_UserProductDetailOut):
    """用户端体验商品详情。"""

    product_type: LabeledValue[Literal[ProductType.EXPERIENCE]]
    dimensions: _OnlineExperienceDimensionsOut
    options: list[_OnlineExperienceOptionOut] = Field(min_length=1)


class KitProductDetailOut(_UserProductDetailOut):
    """用户端套装商品详情。"""

    product_type: LabeledValue[Literal[ProductType.KIT]]
    price: ProductPriceOut
    stock: int = Field(strict=True, ge=MIN_STOCK)
    available: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_availability(self) -> "KitProductDetailOut":
        """available 必须与当前库存是否大于零保持一致。"""

        if self.available != (self.stock > MIN_STOCK):
            raise ValueError("Available must equal whether stock is greater than zero")
        return self


class _AdminProductDetailOut(_ProductIdentityOut):
    """管理端详情公共字段，允许查看未完成或已删除商品。"""

    description: ProductDescription | None
    status: LabeledValue[ProductStatus]
    images: list[ProductImageOut]
    created_at: datetime = Field(strict=True)
    updated_at: datetime = Field(strict=True)
    is_deleted: bool = Field(strict=True)


class AdminExperienceProductDetailOut(_AdminProductDetailOut):
    """管理端体验商品详情。"""

    product_type: LabeledValue[Literal[ProductType.EXPERIENCE]]
    dimensions: ExperienceDimensionsOut
    options: list[ExperienceOptionOut]


class AdminKitProductDetailOut(_AdminProductDetailOut):
    """管理端套装商品详情。"""

    product_type: LabeledValue[Literal[ProductType.KIT]]
    price: ProductPriceOut
    stock: int = Field(strict=True, ge=MIN_STOCK)
