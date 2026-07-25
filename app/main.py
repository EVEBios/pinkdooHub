"""pinkdooHub —— 拼豆店管理系统。

启动方式：
    uvicorn app.main:app --reload

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
核心知识点：FastAPI Lifespan（生命周期）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FastAPI 应用的生命周期分三个阶段：

   Startup（启动）  →  Running（运行中）  →  Shutdown（关闭）
        │                    │                      │
   初始化一切            yield 之后            释放一切
   - 读配置             应用处理请求            - 关 DB 连接池
   - 设日志             - 关 Redis
   - 连数据库                                   - 停后台任务
   - 连 Redis
   - 注册路由

  "以后所有基础设施（DB、Redis、后台任务）的初始化
   和清理，全部写在这个 lifespan 里。"

FastAPI 通过 @asynccontextmanager 实现：

    @asynccontextmanager
    async def lifespan(app):
        # ── Startup  ──  所有初始化逻辑写在这里
        yield               # ← 分界线：应用在此刻开始接收请求
        # ── Shutdown ──  所有清理逻辑写在这里

  yield 之前 = 启动阶段（一条条顺序执行）
  yield 期间 = 应用在运行（处理 HTTP 请求）
  yield 之后 = 关闭阶段（一条条顺序执行，释放资源）
"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.auth import router as auth_router
from app.api.v1.router import router as v1_router
from app.api.v1.users import router as users_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.database import init_db
from app.middleware.exception import register_exception_handlers
from app.schemas.common import RootResponse

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════
# Lifespan —— 生命周期管理
# ═══════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """管理应用从启动到关闭的完整生命周期。

    Startup 阶段（yield 之前）
    ───────────────────────────
    按依赖顺序初始化所有基础设施。每一步都可能失败——
    如果某一步抛异常，FastAPI 会中止启动并报错。

    Shutdown 阶段（yield 之后）
    ────────────────────────────
    按启动的逆序释放资源。每个资源都要优雅关闭——
    比如 DB 连接池要先 wait_closed() 而不是直接断开。
    """

    # ╔══════════════════════════════════════════════════════╗
    # ║                  STARTUP                            ║
    # ╚══════════════════════════════════════════════════════╝
    t0 = time.perf_counter()

    # ── Step 1: Init Logger ────────────────────────────
    # 必须第一个执行——后续所有 logger.info() 都依赖它。
    # 日志格式、级别在这里统一配置。
    setup_logging()
    logger.info("=" * 52)
    logger.info("pinkdooHub Starting...")
    logger.info("=" * 52)
    logger.info("[1/4] Logger initialized")

    # ── Step 2: Load Config ────────────────────────────
    # config 在 import 时（app.core.config 模块加载）已自动执行：
    #   load_dotenv() → 把 .env 加载到 os.environ
    #   Settings()    → 从 os.environ 读取并设置默认值
    # 所以这里只需读出并验证配置正确。
    logger.info("[2/4] Config loaded  env=%s  debug=%s", settings.app_env, settings.app_debug)

    # ── Step 3: Init Infrastructure ────────────────────
    # DB 通过 register_tortoise() 注册，自动管理连接生命周期
    # Phase 3+ 将在此初始化：
    #   await init_redis()       # Redis 连接池
    #   await init_scheduler()   # 后台定时任务 (APScheduler / Celery)
    logger.info("[3/4] Infrastructure initialized")

    # ── Step 4: All Systems Ready ──────────────────────
    # 路由已在 app.include_router() 时注册。
    # 所有基础设施就绪后，应用可以安全接收请求。
    logger.info("[4/4] All systems ready")

    # ── Startup Complete ───────────────────────────────
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("pinkdooHub ready  startup=%.0fms", elapsed_ms)
    logger.info("=" * 52)
    logger.info("Ready. Visit:  http://127.0.0.1:8000/docs")
    logger.info("=" * 52)

    # ═══════════════════════════════════════════════════
    #   yield —— 分界线。
    #   代码在此暂停，应用开始接收并处理 HTTP 请求。
    #   当收到关闭信号时（Ctrl+C / SIGTERM），代码从下一行继续。
    # ═══════════════════════════════════════════════════
    yield

    # ╔══════════════════════════════════════════════════════╗
    # ║                 SHUTDOWN                            ║
    # ╚══════════════════════════════════════════════════════╝
    logger.info("=" * 52)
    logger.info("pinkdooHub Shutting down...")
    logger.info("=" * 52)

    # ── Step 1: Stop Accepting Requests ────────────────
    # FastAPI 自动停止接收新请求，等待进行中的请求完成。
    logger.info("[1/3] Stopped accepting new requests")

    # ── Step 2: Cleanup Resources ──────────────────────
    # DB 连接由 register_tortoise() 自动关闭
    # Phase 3+ 将在此释放：
    #   await close_redis()     # 关闭 Redis 连接
    #   await stop_scheduler()  # 停止后台任务
    logger.info("[2/3] Resources released")

    # ── Step 3: Final Flush ─────────────────────────────
    logger.info("[3/3] Shutting down logger")
    logger.info("=" * 52)
    logger.info("pinkdooHub stopped. Goodbye.")
    logger.info("=" * 52)

    # logging.shutdown() 必须放在最后——关闭所有 Handler，
    # 确保缓冲区刷入磁盘。此后不应再有任何 logger 调用。
    logging.shutdown()


# ═══════════════════════════════════════════════
# FastAPI 应用实例
# ═══════════════════════════════════════════════

app = FastAPI(
    title=settings.app_name,
    description="拼豆店管理系统 API",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,  # ← 核心：把生命周期函数注入 FastAPI
)

# ── 数据库 ──────────────────────────────────────
init_db(app)

# ── 路由注册 ────────────────────────────────────
app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(v1_router, prefix="/api/v1")

# ── 全局异常处理 ────────────────────────────────
register_exception_handlers(app)


# ── 根路由 ────────────────────────────────────────


@app.get("/", response_model=RootResponse)
async def root() -> RootResponse:
    """根路由 —— 返回应用基本信息。"""
    return RootResponse(
        app=settings.app_name,
        version=settings.app_version,
        docs="/docs",
        health="/api/v1/health",
    )
