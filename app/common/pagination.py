"""分页请求/响应模型。

所有列表接口统一使用 PageParams 接收分页参数，
返回 Page[T] 作为分页响应结构。
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.common.constants.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MIN_PAGE_SIZE,
)

T = TypeVar("T")


class PageParams(BaseModel):
    """分页请求参数。"""

    page: int = Field(1, ge=1)
    page_size: int = Field(DEFAULT_PAGE_SIZE, ge=MIN_PAGE_SIZE, le=MAX_PAGE_SIZE)


class Page(BaseModel, Generic[T]):
    """分页结果，可在 Repository 和 API 层分别承载 Model 与 Schema。"""

    # Repository 按项目规范返回 Page[Model]，API 层则使用 Page[OutSchema]；
    # 允许 ORM Model 作为泛型参数不会削弱 Out Schema 自身的字段校验。
    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int
