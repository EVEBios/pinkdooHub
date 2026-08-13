"""Redis 客户端与 Token 存储。

Phase 3: 用于 refresh token 的保存、验证和撤销。
"""

import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """获取 Redis 客户端实例。"""
    if _redis is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _redis


async def init_redis() -> None:
    """初始化 Redis 连接。"""
    global _redis
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    await _redis.ping()
    logger.info("Redis connected: url=%s", settings.redis_url)


async def close_redis() -> None:
    """关闭 Redis 连接。"""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
        logger.info("Redis disconnected")


# ── Refresh Token 操作 ──────────────────────────


async def save_refresh_token(jti: str, user_id: int) -> None:
    """保存 refresh token 到 Redis。"""
    r = get_redis()
    await r.set(f"rt:{jti}", str(user_id), ex=settings.jwt_refresh_token_expire)


async def verify_refresh_token(jti: str) -> int | None:
    """验证 refresh token 是否有效，返回 user_id 或 None。"""
    r = get_redis()
    value = await r.get(f"rt:{jti}")
    return int(value) if value else None


async def delete_refresh_token(jti: str) -> None:
    """撤销 refresh token（logout 时调用）。"""
    r = get_redis()
    await r.delete(f"rt:{jti}")
