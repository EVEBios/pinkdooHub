"""门店库存的明确业务冲突。"""
from app.core.exceptions import ConflictException, NotFoundException, UnprocessableEntityException


class StoreBeadStockConflict(ConflictException):
    def __init__(self, conflicts: list[dict[str, int | None]]) -> None:
        super().__init__(code=40973, message="部分颜色库存已变化，请核对最新数量后重新确认", data={"conflicts": conflicts})


class StoreBeadBatchConflict(ConflictException):
    def __init__(self) -> None:
        super().__init__(code=40974, message="此批次标识已用于另一项调整，请核对原结果")


class StoreBeadStockNotFound(NotFoundException):
    def __init__(self) -> None:
        super().__init__(message="颜色或库存调整记录不存在")


class StoreBeadStockUnchanged(UnprocessableEntityException):
    def __init__(self) -> None:
        super().__init__(code=42273, message="提交的颜色中包含未改变的库存，请重新核对")
