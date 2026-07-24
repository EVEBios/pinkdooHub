"""全局异常处理中间件。

捕获 BusinessException 和未预期的异常，统一封装为 JSON 响应。
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.common.response import error
from app.core.exceptions import BusinessException

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册全局异常处理器。"""

    @app.exception_handler(BusinessException)
    async def business_exception_handler(
        request: Request, exc: BusinessException
    ) -> JSONResponse:
        """业务异常 → 400 + 统一错误信封。"""
        logger.warning(
            "Business error: code=%d message=%s path=%s",
            exc.code,
            exc.message,
            request.url.path,
        )
        return JSONResponse(
            status_code=400,
            content=error(code=exc.code, message=exc.message, data=exc.data),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """兜底：未预期的异常 → 500。"""
        logger.error(
            "Unhandled error: path=%s error=%s",
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content=error(code=500, message="Internal server error"),
        )
