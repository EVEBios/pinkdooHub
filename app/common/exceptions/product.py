"""Product 模块业务异常。"""

from app.core.exceptions import (
    ConflictException,
    NotFoundException,
    UnprocessableEntityException,
)


class ProductNotFound(NotFoundException):
    """指定 Product 不存在。"""

    def __init__(self) -> None:
        super().__init__(code=40401, message="Product not found")


class ProductIsDeleted(ConflictException):
    """Product 已逻辑删除，不能继续执行状态操作。"""

    def __init__(self) -> None:
        super().__init__(code=40903, message="Product is deleted")


class ProductAlreadyOnline(ConflictException):
    """Product 已经处于 Online 状态。"""

    def __init__(self) -> None:
        super().__init__(code=40901, message="Product is already online")


class ProductAlreadyOffline(ConflictException):
    """Product 已经处于非销售状态，不能执行下架。"""

    def __init__(self) -> None:
        super().__init__(code=40902, message="Product is already offline")


class ProductMustBeOfflineBeforeDelete(ConflictException):
    """Online Product 必须先下架才能逻辑删除。"""

    def __init__(self) -> None:
        super().__init__(
            code=40904,
            message="Product must be offline before deletion",
        )


class OnlineProductCannotBeModified(ConflictException):
    """Online Product 不允许直接修改业务数据。"""

    def __init__(self) -> None:
        super().__init__(
            code=40905,
            message="Online product cannot be modified",
        )


class ProductNotReadyForOnline(UnprocessableEntityException):
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
