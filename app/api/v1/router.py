"""v1 API 路由。

Phase 1: 演示统一响应格式 + 异常处理流程。
后续阶段将按模块拆分路由文件（auth、users、products、orders...）。

端点一览：

  GET /api/v1/health      成功 + 数据   → {"code":0, "data":{...}}
  GET /api/v1/ping        成功 + 无数据  → {"code":0, "data":null}
  GET /api/v1/error-demo  业务异常      → {"code":1001, "message":"..."}

三种模式覆盖了所有 API 的返回情况。
"""

from fastapi import APIRouter

from app.common.response import success
from app.core.config import settings
from app.core.exceptions import BusinessException

router = APIRouter()


# ── 模式 1：成功 + 数据 ──────────────────────────


@router.get("/health")
async def health() -> dict:
    """健康检查 —— success(data=...)"""
    return success(
        data={
            "app": settings.app_name,
            "env": settings.app_env,
            "status": "ok",
        }
    )


# ── 模式 2：成功 + 无数据 ────────────────────────


@router.get("/ping")
async def ping() -> dict:
    """连通性检查 —— success() 无参数，data 为 null"""
    return success(message="pong")


# ── 模式 3：业务异常（由中间件统一捕获）──────────


@router.get("/error-demo")
async def error_demo():
    """演示异常处理流程。

    注意：此函数始终抛出异常，无返回值，因此不标注返回类型。

    不在 API 层 try/except，而是直接抛出 BusinessException。
    middleware/exception.py 自动捕获并转换为：
    HTTP 400 + {"code": 1001, "message": "This is a demo error", "data": null}
    """
    raise BusinessException(code=1001, message="This is a demo error")
