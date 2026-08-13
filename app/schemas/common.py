"""公共 Schema —— 跨模块共享的响应信封与根路由模型。"""

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

DataT = TypeVar("DataT")


class SuccessResponse(BaseModel, Generic[DataT]):
    """统一成功信封的 OpenAPI 模型；运行时仍由 success() 构造。"""

    model_config = ConfigDict(extra="forbid")

    code: Literal[0] = 0
    message: str = "success"
    data: DataT


class ErrorResponse(BaseModel):
    """统一错误信封；具体 code 与 data 形状由模块契约定义。"""

    model_config = ConfigDict(extra="forbid")

    code: int
    message: str
    data: dict[str, Any] | None = None


class RootResponse(BaseModel):
    """GET / 根路由响应。"""

    app: str
    version: str
    docs: str
    health: str
