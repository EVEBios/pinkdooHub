"""ProductValidator 上架公共规则契约测试。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.enums.product import ProductType
from app.common.exceptions import ProductNotReadyForOnline
from app.validators.product_validator import ProductValidator


def _complete_kit_product() -> SimpleNamespace:
    """构造已加载且满足 Kit 上架条件的内存聚合。"""

    return SimpleNamespace(
        name="新手拼豆套装",
        description="适合第一次体验拼豆的完整材料包",
        product_type=ProductType.KIT,
        images=[SimpleNamespace(is_cover=True)],
        kit=SimpleNamespace(
            price=Decimal("99.00"),
            stock=0,
        ),
    )


def _validate_issues(product: SimpleNamespace) -> list[str]:
    """执行同步 Validator 并返回命名异常中的 issues。"""

    with pytest.raises(ProductNotReadyForOnline) as exc_info:
        ProductValidator.validate_before_online(product)

    assert exc_info.value.data is not None
    return exc_info.value.data["issues"]


def test_complete_product_returns_none() -> None:
    """完整聚合通过校验时只返回 None，不返回 bool。"""

    result = ProductValidator.validate_before_online(_complete_kit_product())

    assert result is None


def test_unknown_product_type_fails_closed() -> None:
    product = _complete_kit_product()
    product.product_type = "future-type"

    with pytest.raises(
        ValueError,
        match="Unsupported product type: 'future-type'",
    ):
        ProductValidator.validate_before_online(product)


@pytest.mark.parametrize("name", [None, ""])
def test_missing_product_name_is_rejected(name: str | None) -> None:
    product = _complete_kit_product()
    product.name = name

    assert _validate_issues(product) == ["product name is required"]


def test_whitespace_only_product_name_is_rejected() -> None:
    product = _complete_kit_product()
    product.name = " \t\n "

    assert _validate_issues(product) == ["product name is required"]


@pytest.mark.parametrize("description", [None, ""])
def test_missing_product_description_is_rejected(description: str | None) -> None:
    product = _complete_kit_product()
    product.description = description

    assert _validate_issues(product) == ["product description is required"]


def test_whitespace_only_product_description_is_rejected() -> None:
    product = _complete_kit_product()
    product.description = " \t\n "

    assert _validate_issues(product) == ["product description is required"]


def test_missing_public_cover_is_rejected() -> None:
    product = _complete_kit_product()
    product.images = [SimpleNamespace(is_cover=False)]

    assert _validate_issues(product) == ["product cover image is required"]


def test_all_common_issues_are_returned_together_in_contract_order() -> None:
    product = _complete_kit_product()
    product.name = " "
    product.description = None
    product.images = []

    assert _validate_issues(product) == [
        "product name is required",
        "product description is required",
        "product cover image is required",
    ]


def test_common_issue_order_is_stable_for_the_same_input() -> None:
    product = _complete_kit_product()
    product.name = None
    product.description = ""
    product.images = []
    expected = [
        "product name is required",
        "product description is required",
        "product cover image is required",
    ]

    assert _validate_issues(product) == expected
    assert _validate_issues(product) == expected
