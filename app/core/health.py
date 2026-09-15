"""应用基础设施健康检查。

Liveness 由 HTTP 层直接响应；本模块只负责会触碰外部依赖的 readiness
检查，避免把数据库或 Redis 查询散落在 Router 中。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from tortoise import connections

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

READINESS_CHECK_TIMEOUT_SECONDS: Final[float] = 1.0


@dataclass(frozen=True)
class ReadinessResult:
    """依赖检查的不可变结果。"""

    database: bool
    redis: bool

    @property
    def is_ready(self) -> bool:
        """所有关键依赖都可用时才允许实例接收业务流量。"""

        return self.database and self.redis


async def _ping_database() -> None:
    """通过当前 Tortoise 默认连接执行最小只读查询。"""

    connection = connections.get("default")
    await connection.execute_query("SELECT 1")


async def _ping_redis() -> None:
    """检查当前 Redis 客户端是否仍可响应。"""

    await get_redis().ping()


async def _run_check(
    dependency: str,
    operation: Callable[[], Awaitable[None]],
    timeout_seconds: float,
) -> bool:
    """在固定超时内执行单项检查，并只记录安全的失败摘要。"""

    try:
        await asyncio.wait_for(operation(), timeout=timeout_seconds)
    except Exception as exc:
        logger.warning(
            "Readiness check failed: dependency=%s error_type=%s",
            dependency,
            type(exc).__name__,
        )
        return False
    return True


async def check_readiness(
    timeout_seconds: float = READINESS_CHECK_TIMEOUT_SECONDS,
) -> ReadinessResult:
    """并行检查数据库和 Redis，不因单项失败跳过另一项检查。"""

    database_ready, redis_ready = await asyncio.gather(
        _run_check("database", _ping_database, timeout_seconds),
        _run_check("redis", _ping_redis, timeout_seconds),
    )
    return ReadinessResult(database=database_ready, redis=redis_ready)
