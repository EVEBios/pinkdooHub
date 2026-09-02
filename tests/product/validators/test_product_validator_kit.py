"""ProductValidator Kit 上架规则契约测试。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.constants.product import PRODUCT_PRICE_MAX
from app.common.enums.product import ProductType
from app.common.exceptions import ProductNotReadyForOnline
from app.validators.product_validator import ProductValidator


def _complete_kit_product(
    *,
    price: Decimal = Decimal("99.00"),
    stock: int = 20,
) -> SimpleNamespace:
    """构造满足全部 Kit 上架条件的内存聚合。"""

    return SimpleNamespace(
        name="新手拼豆套装",
        description="包含拼豆、模板和基础工具",
        product_type=ProductType.KIT,
        images=[SimpleNamespace(id=1, is_cover=True)],
        kit=SimpleNamespace(
            price=price,
            stock=stock,
        ),
    )


def _validate_issues(product: SimpleNamespace) -> list[str]:
    """执行同步 Validator 并返回命名异常中的 issues。"""

    with pytest.raises(ProductNotReadyForOnline) as exc_info:
        ProductValidator.validate_before_online(product)

    assert exc_info.value.data is not None
    return exc_info.value.data["issues"]


def test_complete_kit_product_returns_none() -> None:
    result = ProductValidator.validate_before_online(_complete_kit_product())

    assert result is None


def test_missing_kit_configuration_returns_only_configuration_issue() -> None:
    product = _complete_kit_product()
    product.kit = None

    assert _validate_issues(product) == ["kit configuration is required"]


@pytest.mark.parametrize(
    "price",
    [
        Decimal("0.00"),
        Decimal("-1.00"),
        PRODUCT_PRICE_MAX + Decimal("0.01"),
    ],
)
def test_kit_price_outside_contract_range_is_rejected(
    price: Decimal,
) -> None:
    product = _complete_kit_product(price=price)

    assert _validate_issues(product) == [
        "kit price must be greater than 0 and no more than 99999",
    ]


def test_negative_kit_stock_is_rejected() -> None:
    product = _complete_kit_product(stock=-1)

    assert _validate_issues(product) == ["kit stock must be non-negative"]


def test_zero_kit_stock_is_allowed() -> None:
    result = ProductValidator.validate_before_online(
        _complete_kit_product(stock=0),
    )

    assert result is None


def test_maximum_kit_price_is_allowed() -> None:
    result = ProductValidator.validate_before_online(
        _complete_kit_product(price=PRODUCT_PRICE_MAX),
    )

    assert result is None


def test_kit_without_cover_returns_only_common_cover_issue() -> None:
    """Kit 不额外要求独立的 Product 公共图片数量 issue。"""

    product = _complete_kit_product()
    product.images = []

    assert _validate_issues(product) == ["product cover image is required"]


def test_kit_price_and_stock_issues_are_aggregated_in_order() -> None:
    product = _complete_kit_product(
        price=Decimal("0.00"),
        stock=-1,
    )

    assert _validate_issues(product) == [
        "kit price must be greater than 0 and no more than 99999",
        "kit stock must be non-negative",
    ]


def test_common_and_kit_issues_are_returned_in_contract_order() -> None:
    product = _complete_kit_product(
        price=PRODUCT_PRICE_MAX + Decimal("0.01"),
        stock=-1,
    )
    product.name = " "
    product.description = None
    product.images = []

    assert _validate_issues(product) == [
        "product name is required",
        "product description is required",
        "product cover image is required",
        "kit price must be greater than 0 and no more than 99999",
        "kit stock must be non-negative",
    ]
