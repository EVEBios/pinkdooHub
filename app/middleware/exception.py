"""全局异常处理中间件。"""

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


def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 应用注册全局异常处理器。

    直接为已知异常类型注册独立 handler，避免 Starlette 的
    ExceptionMiddleware 在 dispatch 时重新抛出异常。
    """

    @app.exception_handler(BusinessException)
    async def handle_business(request: Request, exc: BusinessException) -> JSONResponse:
        logger.warning("HTTP 400: code=%d message=%s path=%s", exc.code, exc.message, request.url.path)
        return JSONResponse(status_code=400, content=error(exc.code, exc.message, exc.data))

    @app.exception_handler(AuthenticationException)
    async def handle_auth(request: Request, exc: AuthenticationException) -> JSONResponse:
        logger.warning("HTTP 401: code=%d message=%s path=%s", exc.code, exc.message, request.url.path)
        return JSONResponse(status_code=401, content=error(exc.code, exc.message, exc.data))

    @app.exception_handler(PermissionException)
    async def handle_permission(request: Request, exc: PermissionException) -> JSONResponse:
        logger.warning("HTTP 403: code=%d message=%s path=%s", exc.code, exc.message, request.url.path)
        return JSONResponse(status_code=403, content=error(exc.code, exc.message, exc.data))

    @app.exception_handler(NotFoundException)
    async def handle_not_found(request: Request, exc: NotFoundException) -> JSONResponse:
        logger.warning("HTTP 404: code=%d message=%s path=%s", exc.code, exc.message, request.url.path)
        return JSONResponse(status_code=404, content=error(exc.code, exc.message, exc.data))

    @app.exception_handler(AppException)
    async def handle_app(request: Request, exc: AppException) -> JSONResponse:
        logger.warning("HTTP 400: code=%d message=%s path=%s", exc.code, exc.message, request.url.path)
        return JSONResponse(status_code=400, content=error(exc.code, exc.message, exc.data))

    @app.exception_handler(Exception)
    async def handle_unknown(request: Request, exc: Exception) -> JSONResponse:
        logger.error("HTTP 500: path=%s error=%s", request.url.path, exc, exc_info=True)
        return JSONResponse(status_code=500, content=error(500, "Internal server error"))
