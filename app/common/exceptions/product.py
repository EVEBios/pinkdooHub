"""Product 模块业务异常。"""

from app.core.exceptions import UnprocessableEntityException


class ProductException(UnprocessableEntityException):
    """Product 模块不可处理实体异常基类。"""


class ProductNotReadyForOnline(ProductException):
    """Product 聚合不满足上架完整性条件。"""

    def __init__(self, issues: list[str]) -> None:
        if not issues or any(
            not isinstance(issue, str) or not issue
            for issue in issues
        ):
            raise ValueError("issues must contain non-empty strings")

        super().__init__(
            code=42201,
            message="Product is not ready to go online",
            data={"issues": list(issues)},
        )
