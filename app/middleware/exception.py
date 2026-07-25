"""全局异常处理中间件。

将 Python 异常映射为 HTTP 状态码 + 统一 JSON 响应。

映射关系：

    BusinessException        → 400
    AuthenticationException  → 401
    PermissionException      → 403
    NotFoundException        → 404
    Exception（兜底）         → 500

所有错误均转换为 {"code": N, "message": "...", "data": null} 格式。
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.common.response import error
from app.core.exceptions import (
    AppException,
    AuthenticationException,
    BusinessException,
    NotFoundException,
    PermissionException,
)

logger = logging.getLogger(__name__)

# 异常类型 → HTTP 状态码
_HANDLER_MAP: dict[type[AppException], int] = {
    BusinessException: 400,
    AuthenticationException: 401,
    PermissionException: 403,
    NotFoundException: 404,
}


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册全局异常处理器。"""

    @app.exception_handler(Exception)
    async def root_handler(request: Request, exc: Exception) -> JSONResponse:
        """统一入口：根据异常类型分发到对应的状态码。

        已知的 AppException 子类 → 对应 HTTP 状态码
        未知的 Exception → 500
        """
        if isinstance(exc, AppException):
            return _handle_app_exception(request, exc)
        return _handle_unknown_exception(request, exc)


def _handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
    """处理已知的业务异常。"""
    status_code = _HANDLER_MAP.get(type(exc), 400)
    logger.warning(
        "HTTP %d: code=%d message=%s path=%s",
        status_code,
        exc.code,
        exc.message,
        request.url.path,
    )
    return JSONResponse(
        status_code=status_code,
        content=error(code=exc.code, message=exc.message, data=exc.data),
    )


def _handle_unknown_exception(request: Request, exc: Exception) -> JSONResponse:
    """兜底：未预期的异常 → 500。"""
    logger.error(
        "HTTP 500: path=%s error=%s",
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content=error(code=500, message="Internal server error"),
    )
