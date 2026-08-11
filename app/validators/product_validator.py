"""Product 聚合状态变迁校验器。"""

from app.common.constants.product import (
    MIN_STOCK,
    PRODUCT_PRICE_MAX,
    PRODUCT_PRICE_MIN_EXCLUSIVE,
)
from app.common.enums.product import ProductType
from app.common.exceptions import ProductNotReadyForOnline
from app.models.product import Product


class ProductValidator:
    """同步校验已由 Service 预加载的 Product 聚合。"""

    @classmethod
    def validate_before_online(cls, product: Product) -> None:
        """收集上架完整性问题；存在问题时一次性抛出命名异常。"""

        issues = cls._collect_common_issues(product)
        if product.product_type == ProductType.EXPERIENCE:
            issues.extend(cls._collect_experience_issues(product))
        elif product.product_type == ProductType.KIT:
            issues.extend(cls._collect_kit_issues(product))
        else:
            raise ValueError(
                f"Unsupported product type: {product.product_type!r}"
            )

        if issues:
            raise ProductNotReadyForOnline(issues=issues)

    @classmethod
    def _collect_common_issues(cls, product: Product) -> list[str]:
        """按稳定顺序收集所有 ProductType 共用的上架问题。"""

        issues: list[str] = []

        if product.name is None or not product.name.strip():
            issues.append("product name is required")
        if product.description is None or not product.description.strip():
            issues.append("product description is required")
        if not any(image.is_cover for image in product.images):
            issues.append("product cover image is required")

        return issues

    @classmethod
    def _collect_experience_issues(cls, product: Product) -> list[str]:
        """按预加载关系顺序收集 Experience 专属上架问题。"""

        issues: list[str] = []

        if not any(True for _ in product.images):
            issues.append("at least one product image is required")

        options = list(product.experience_options)
        if not options:
            issues.append("at least one experience option is required")

        for option in options:
            if option.price <= PRODUCT_PRICE_MIN_EXCLUSIVE:
                issues.append(
                    f"option {option.id} price must be greater than 0"
                )
            if not any(True for _ in option.images):
                issues.append(f"option {option.id} has no image")

        return issues

    @classmethod
    def _collect_kit_issues(cls, product: Product) -> list[str]:
        """按稳定顺序收集 Kit 专属上架问题。"""

        kit = product.kit
        if kit is None:
            return ["kit configuration is required"]

        issues: list[str] = []
        if (
            kit.price <= PRODUCT_PRICE_MIN_EXCLUSIVE
            or kit.price > PRODUCT_PRICE_MAX
        ):
            issues.append(
                "kit price must be greater than 0 and no more than 99999"
            )
        if kit.stock < MIN_STOCK:
            issues.append("kit stock must be non-negative")

        return issues
