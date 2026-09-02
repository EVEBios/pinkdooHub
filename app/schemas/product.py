"""Product Schema —— 商品模块请求/响应数据结构。"""

import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from app.common.constants.product import (
    MIN_DURATION_MINUTES,
    MIN_IMAGE_SORT,
    MIN_PARTICIPANTS,
    PRODUCT_DESCRIPTION_MAX_LENGTH,
    PRODUCT_NAME_MAX_LENGTH,
    PRODUCT_NAME_MIN_LENGTH,
    PRODUCT_PRICE_DECIMAL_PLACES,
    PRODUCT_PRICE_MAX,
    PRODUCT_PRICE_MIN_EXCLUSIVE,
    PRODUCT_PRICE_PATTERN,
    PRODUCT_SEARCH_KEYWORD_MAX_LENGTH,
)
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.pagination import PageParams

_product_price_regex = re.compile(PRODUCT_PRICE_PATTERN)


def _parse_product_price(value: object) -> Decimal:
    """将普通十进制字符串转换为 Decimal，拒绝隐式数值转换。"""

    if not isinstance(value, str):
        raise ValueError("Price must be provided as a string")

    normalized = value.strip()
    if not _product_price_regex.fullmatch(normalized):
        raise ValueError(
            "Price must be a plain decimal string with at most "
            f"{PRODUCT_PRICE_DECIMAL_PLACES} decimal places"
        )

    return Decimal(normalized)


def _normalize_empty_description(value: str | None) -> str | None:
    """将空字符串统一为 None；首尾空白已由模型配置清理。"""

    return None if value == "" else value


def _parse_cover_flag(value: object) -> Literal[True]:
    """仅接受真正的 boolean true，拒绝与 True 相等的整数 1。"""

    if value is not True:
        raise ValueError("is_cover only accepts boolean true")
    return True


def _parse_query_boolean(value: object) -> bool:
    """Query boolean 只接受 true/false，拒绝 1/0、yes/no 等宽松形式。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError("Boolean query value must be true or false")


ProductName = Annotated[
    str,
    Field(
        strict=True,
        min_length=PRODUCT_NAME_MIN_LENGTH,
        max_length=PRODUCT_NAME_MAX_LENGTH,
    ),
]

ProductDescription = Annotated[
    str,
    Field(strict=True, max_length=PRODUCT_DESCRIPTION_MAX_LENGTH),
]

ProductPriceInput = Annotated[
    Decimal,
    BeforeValidator(_parse_product_price),
    Field(
        gt=PRODUCT_PRICE_MIN_EXCLUSIVE,
        le=PRODUCT_PRICE_MAX,
        decimal_places=PRODUCT_PRICE_DECIMAL_PLACES,
    ),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": PRODUCT_PRICE_PATTERN,
            "description": (
                "金额字符串，0 < price <= 99999，"
                f"最多 {PRODUCT_PRICE_DECIMAL_PLACES} 位小数"
            ),
            "examples": ["599.00"],
        },
        mode="validation",
    ),
]

DurationMinutesInput = Annotated[
    int,
    Field(strict=True, ge=MIN_DURATION_MINUTES),
]
ParticipantsInput = Annotated[
    int,
    Field(strict=True, ge=MIN_PARTICIPANTS),
]
ImageSortInput = Annotated[int, Field(strict=True, ge=MIN_IMAGE_SORT)]
CoverFlagInput = Annotated[Literal[True], BeforeValidator(_parse_cover_flag)]
ProductSearchKeyword = Annotated[
    str,
    Field(strict=True, max_length=PRODUCT_SEARCH_KEYWORD_MAX_LENGTH),
]
QueryBoolean = Annotated[bool, BeforeValidator(_parse_query_boolean)]


class _ProductRequest(BaseModel):
    """Product 写请求公共配置。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _NonEmptyPatchRequest(_ProductRequest):
    """至少提交一个字段的 Product PATCH 请求。"""

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "_NonEmptyPatchRequest":
        """PATCH 请求必须至少提交一个允许修改的字段。"""

        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class _ProductCreateBase(_ProductRequest):
    """体验商品和套装商品共享的创建字段。"""

    name: ProductName
    description: ProductDescription | None = None

    @field_validator("description", mode="after")
    @classmethod
    def normalize_empty_description(cls, value: str | None) -> str | None:
        """将空字符串和纯空白描述统一为 None。"""

        return _normalize_empty_description(value)


class ExperienceProductCreate(_ProductCreateBase):
    """创建体验商品草稿请求。"""


class KitProductCreate(_ProductCreateBase):
    """创建套装商品草稿请求。"""

    price: ProductPriceInput


class ProductUpdate(_NonEmptyPatchRequest):
    """修改商品基本信息请求——只更新客户端明确提交的字段。"""

    name: ProductName | None = None
    description: ProductDescription | None = None

    @field_validator("name", mode="after")
    @classmethod
    def reject_null_name(cls, value: str | None) -> str:
        """name 可以缺失，但客户端显式提交时不能为 null。"""

        if value is None:
            raise ValueError("Name cannot be null")
        return value

    @field_validator("description", mode="after")
    @classmethod
    def normalize_empty_description(cls, value: str | None) -> str | None:
        """显式的 null、空字符串和纯空白都表示清空描述。"""

        return _normalize_empty_description(value)

class ExperienceOptionCreate(_ProductRequest):
    """新增体验 Option 请求。"""

    duration_minutes: DurationMinutesInput
    participants: ParticipantsInput
    day_type: DayType
    price: ProductPriceInput


class ExperienceOptionUpdate(_NonEmptyPatchRequest):
    """修改体验 Option 请求——只更新客户端明确提交的字段。"""

    duration_minutes: DurationMinutesInput | None = None
    participants: ParticipantsInput | None = None
    day_type: DayType | None = None
    price: ProductPriceInput | None = None

    @field_validator(
        "duration_minutes",
        "participants",
        "day_type",
        "price",
        mode="after",
    )
    @classmethod
    def reject_null_fields(cls, value: object) -> object:
        """Option 字段可以缺失，但客户端显式提交时不能为 null。"""

        if value is None:
            raise ValueError("Option fields cannot be null")
        return value


class ProductImageUpdate(_NonEmptyPatchRequest):
    """修改商品图片排序或设置 Product 封面请求。"""

    sort: ImageSortInput | None = None
    is_cover: CoverFlagInput | None = None

    @field_validator("sort", "is_cover", mode="after")
    @classmethod
    def reject_null_fields(cls, value: object) -> object:
        """图片字段可以缺失，但客户端显式提交时不能为 null。"""

        if value is None:
            raise ValueError("Image fields cannot be null")
        return value


class KitPriceUpdate(_ProductRequest):
    """修改套装商品价格请求。"""

    price: ProductPriceInput


class ProductListQuery(PageParams):
    """用户端商品列表查询参数。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_type: ProductType | None = None
    keyword: ProductSearchKeyword | None = None

    @field_validator("keyword", mode="after")
    @classmethod
    def normalize_empty_keyword(cls, value: str | None) -> str | None:
        """空搜索词等同于不启用关键字筛选。"""

        return None if value == "" else value


class AdminProductListQuery(ProductListQuery):
    """管理端商品列表查询参数。"""

    status: ProductStatus | None = None
    include_deleted: QueryBoolean = False
