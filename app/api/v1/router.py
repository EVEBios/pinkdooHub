"""v1 API 路由。

Phase 1: 演示统一响应格式 + 异常处理流程。
后续阶段将按模块拆分路由文件（auth、users、products、orders...）。

端点一览：

  GET /api/v1/health      兼容存活检查 → {"code":0, "data":{...}}
  GET /api/v1/health/live 进程存活检查 → {"code":0, "data":{...}}
  GET /api/v1/health/ready 依赖就绪检查 → 200 或 503
  GET /api/v1/ping        成功 + 无数据  → {"code":0, "data":null}
  GET /api/v1/error-demo  业务异常      → {"code":1001, "message":"..."}

三种模式覆盖了所有 API 的返回情况。
"""

from fastapi import APIRouter

from app.api.responses import success_responses
from app.common.response import success
from app.core.config import settings
from app.core.exceptions import (
    AuthenticationException,
    BusinessException,
    NotFoundException,
    PermissionException,
    ServiceUnavailableException,
)
from app.core.health import check_readiness
from app.schemas.health import (
    LegacyHealthOut,
    LivenessOut,
    ReadinessErrorResponse,
    ReadinessOut,
)

router = APIRouter()


# ── 模式 1：成功 + 数据 ──────────────────────────


@router.get(
    "/health",
    response_model=None,
    responses=success_responses(LegacyHealthOut),
)
async def health() -> dict:
    """兼容既有存活检查；不访问数据库或 Redis。"""

    data = LegacyHealthOut(
        app=settings.app_name,
        env=settings.app_env,
        status="ok",
    )
    return success(data=data.model_dump())


@router.get(
    "/health/live",
    response_model=None,
    responses=success_responses(LivenessOut),
)
async def liveness() -> dict:
    """证明应用进程能够响应，不访问任何外部依赖。"""

    data = LivenessOut(app=settings.app_name, status="alive")
    return success(data=data.model_dump())


@router.get(
    "/health/ready",
    response_model=None,
    responses={
        **success_responses(ReadinessOut),
        503: {"model": ReadinessErrorResponse},
    },
)
async def readiness() -> dict:
    """检查数据库与 Redis；任一失败时摘除业务流量。"""

    result = await check_readiness()
    data = ReadinessOut(
        status="ready" if result.is_ready else "not_ready",
        checks={
            "database": "up" if result.database else "down",
            "redis": "up" if result.redis else "down",
        },
    )
    payload = data.model_dump()
    if not result.is_ready:
        raise ServiceUnavailableException(data=payload)
    return success(data=payload)


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


# ── 模式 4：认证失败 → 401 ────────────────────


@router.get("/auth-required")
async def auth_required():
    """演示 401 —— 未登录或 Token 失效。"""
    raise AuthenticationException(message="Authentication required")


# ── 模式 5：权限不足 → 403 ────────────────────


@router.get("/admin-only")
async def admin_only():
    """演示 403 —— 已登录但权限不足。"""
    raise PermissionException(message="Admin access required")


# ── 模式 6：资源不存在 → 404 ────────────────────


@router.get("/not-found")
async def not_found():
    """演示 404 —— 请求的资源不存在。"""
    raise NotFoundException(message="Resource not found")
