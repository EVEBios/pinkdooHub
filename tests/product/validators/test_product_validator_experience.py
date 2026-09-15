"""ProductValidator Experience 上架规则契约测试。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.enums.product import ProductType
from app.common.exceptions import ProductNotReadyForOnline
from app.validators.product_validator import ProductValidator


def _option(
    option_id: int,
    *,
    price: Decimal = Decimal("99.00"),
    has_image: bool = True,
) -> SimpleNamespace:
    """构造已按 Repository 契约过滤的有效 ExperienceOption。"""

    images = [SimpleNamespace(id=option_id * 10)] if has_image else []
    return SimpleNamespace(
        id=option_id,
        price=price,
        images=images,
    )


def _complete_experience_product() -> SimpleNamespace:
    """构造满足全部 Experience 上架条件的内存聚合。"""

    return SimpleNamespace(
        name="周末拼豆体验",
        description="包含材料和现场指导",
        product_type=ProductType.EXPERIENCE,
        images=[SimpleNamespace(id=1, is_cover=True)],
        experience_options=[_option(11)],
    )


def _validate_issues(product: SimpleNamespace) -> list[str]:
    """执行同步 Validator 并返回命名异常中的 issues。"""

    with pytest.raises(ProductNotReadyForOnline) as exc_info:
        ProductValidator.validate_before_online(product)

    assert exc_info.value.data is not None
    return exc_info.value.data["issues"]


def test_complete_experience_product_returns_none() -> None:
    result = ProductValidator.validate_before_online(
        _complete_experience_product(),
    )

    assert result is None


def test_experience_without_public_images_returns_both_image_issues() -> None:
    product = _complete_experience_product()
    product.images = []

    assert _validate_issues(product) == [
        "product cover image is required",
        "at least one product image is required",
    ]


def test_experience_without_options_is_rejected() -> None:
    product = _complete_experience_product()
    product.experience_options = []

    assert _validate_issues(product) == [
        "at least one experience option is required",
    ]


@pytest.mark.parametrize("price", [Decimal("0.00"), Decimal("-1.00")])
def test_experience_option_non_positive_price_is_rejected(
    price: Decimal,
) -> None:
    product = _complete_experience_product()
    product.experience_options = [_option(11, price=price)]

    assert _validate_issues(product) == [
        "option 11 price must be greater than 0",
    ]


def test_experience_option_without_image_is_rejected() -> None:
    """Product 公共图片不能回退为 Option 专属图片。"""

    product = _complete_experience_product()
    product.experience_options = [_option(11, has_image=False)]

    assert _validate_issues(product) == ["option 11 has no image"]


def test_same_option_returns_price_issue_before_image_issue() -> None:
    product = _complete_experience_product()
    product.experience_options = [
        _option(11, price=Decimal("0.00"), has_image=False),
    ]

    assert _validate_issues(product) == [
        "option 11 price must be greater than 0",
        "option 11 has no image",
    ]


def test_multiple_option_issues_follow_preloaded_option_order() -> None:
    product = _complete_experience_product()
    product.experience_options = [
        _option(11, price=Decimal("0.00"), has_image=False),
        _option(22, price=Decimal("-1.00"), has_image=False),
    ]

    assert _validate_issues(product) == [
        "option 11 price must be greater than 0",
        "option 11 has no image",
        "option 22 price must be greater than 0",
        "option 22 has no image",
    ]


def test_all_experience_issues_are_returned_in_contract_order() -> None:
    product = _complete_experience_product()
    product.name = " "
    product.description = None
    product.images = []
    product.experience_options = []

    assert _validate_issues(product) == [
        "product name is required",
        "product description is required",
        "product cover image is required",
        "at least one product image is required",
        "at least one experience option is required",
    ]


def test_option_image_does_not_replace_product_public_image() -> None:
    """Option 专属图片不能回退为 Product 公共图片或封面。"""

    product = _complete_experience_product()
    product.images = []
    product.experience_options = [_option(11, has_image=True)]

    assert _validate_issues(product) == [
        "product cover image is required",
        "at least one product image is required",
    ]
