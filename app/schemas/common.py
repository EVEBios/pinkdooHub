"""公共 Schema —— 跨模块共享的通用响应模型。

Phase 1: 仅 RootResponse。
Phase 2+ 将按模块拆分：user.py、product.py、order.py。
"""

from pydantic import BaseModel


class RootResponse(BaseModel):
    """GET / 根路由响应。"""

    app: str
    version: str
    docs: str
    health: str
