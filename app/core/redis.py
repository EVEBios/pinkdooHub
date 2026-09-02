"""Redis 客户端、Refresh Token family 与安全计数器。"""

from __future__ import annotations

import logging
from enum import Enum
from urllib.parse import urlsplit

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None
_REFRESH_PREFIX = "rt:"
_USED_REFRESH_PREFIX = "rt-used:"
_FAMILY_PREFIX = "rt-family:"
_USER_FAMILIES_PREFIX = "rt-user:"
_REVOKED = "revoked"


class RefreshRotationResult(str, Enum):
    """Refresh 轮换的原子结果。"""

    ROTATED = "rotated"
    REUSED = "reused"
    INVALID = "invalid"


class RefreshTokenState(str, Enum):
    ACTIVE = "active"
    USED = "used"
    MISSING = "missing"


_ROTATE_REFRESH_SCRIPT = """
local active = redis.call('GET', KEYS[1])
local expected = ARGV[1]
local legacy = ARGV[2]
local ttl = tonumber(ARGV[4])

if active then
  if active ~= expected and active ~= legacy then
    return 0
  end
  if redis.call('GET', KEYS[3]) == ARGV[5] then
    redis.call('DEL', KEYS[1])
    return 0
  end
  redis.call('DEL', KEYS[1])
  redis.call('SET', KEYS[2], expected, 'EX', ttl)
  redis.call('SET', KEYS[4], expected, 'EX', ttl)
  redis.call('SET', KEYS[3], ARGV[3], 'EX', ttl)
  return 1
end

if redis.call('EXISTS', KEYS[2]) == 1 then
  local current = redis.call('GET', KEYS[3])
  if current and current ~= ARGV[5] then
    redis.call('DEL', ARGV[6] .. current)
  end
  redis.call('SET', KEYS[3], ARGV[5], 'EX', ttl)
  return 2
end

return 0
"""

_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return count
"""


def _log_redis_connected(redis_url: str) -> None:
    """仅记录可观测连接目标，不输出 Redis 凭据或查询参数。"""

    parsed = urlsplit(redis_url)
    try:
        port = parsed.port
    except ValueError:
        port = None
    database = parsed.path.removeprefix("/")
    safe_database = database if database.isdigit() else "unknown"
    logger.info(
        "Redis connected: scheme=%s host=%s port=%s db=%s",
        parsed.scheme or "unknown",
        parsed.hostname or "unknown",
        port,
        safe_database or "0",
    )


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
    _log_redis_connected(settings.redis_url)


async def close_redis() -> None:
    """关闭 Redis 连接。"""

    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        logger.info("Redis disconnected")


def _session_value(user_id: int, session_id: str) -> str:
    return f"{user_id}:{session_id}"


def _parse_user_id(value: str | None) -> int | None:
    if not value:
        return None
    user_id, _, _session_id = value.partition(":")
    try:
        return int(user_id)
    except ValueError:
        return None


async def save_refresh_session(jti: str, session_id: str, user_id: int) -> None:
    """保存新 Refresh Token 及其 family 索引。"""

    redis = get_redis()
    ttl = settings.jwt_refresh_token_expire
    async with redis.pipeline(transaction=True) as pipeline:
        pipeline.set(
            f"{_REFRESH_PREFIX}{jti}",
            _session_value(user_id, session_id),
            ex=ttl,
        )
        pipeline.set(f"{_FAMILY_PREFIX}{session_id}", jti, ex=ttl)
        pipeline.sadd(f"{_USER_FAMILIES_PREFIX}{user_id}", session_id)
        pipeline.expire(f"{_USER_FAMILIES_PREFIX}{user_id}", ttl)
        await pipeline.execute()


async def rotate_refresh_session(
    *,
    old_jti: str,
    new_jti: str,
    session_id: str,
    user_id: int,
) -> RefreshRotationResult:
    """原子消费旧 Refresh Token 并签发新 Token。

    已消费 Token 再次出现时，立即撤销当前 family 的 Refresh
    能力，不输出 jti、Token 或用户标识到日志。
    """

    redis = get_redis()
    expected = _session_value(user_id, session_id)
    result = await redis.eval(
        _ROTATE_REFRESH_SCRIPT,
        4,
        f"{_REFRESH_PREFIX}{old_jti}",
        f"{_USED_REFRESH_PREFIX}{old_jti}",
        f"{_FAMILY_PREFIX}{session_id}",
        f"{_REFRESH_PREFIX}{new_jti}",
        expected,
        str(user_id),
        new_jti,
        settings.jwt_refresh_token_expire,
        _REVOKED,
        _REFRESH_PREFIX,
    )
    if result == 1:
        return RefreshRotationResult.ROTATED
    if result == 2:
        return RefreshRotationResult.REUSED
    return RefreshRotationResult.INVALID


async def get_refresh_token_state(jti: str) -> RefreshTokenState:
    """区分可用、已消费与从未存在的 Refresh Token。"""

    redis = get_redis()
    active, used = await redis.mget(
        f"{_REFRESH_PREFIX}{jti}",
        f"{_USED_REFRESH_PREFIX}{jti}",
    )
    if active is not None:
        return RefreshTokenState.ACTIVE
    if used is not None:
        return RefreshTokenState.USED
    return RefreshTokenState.MISSING


async def revoke_refresh_family(session_id: str) -> None:
    """撤销一个登录 family 的 Refresh 能力。"""

    redis = get_redis()
    family_key = f"{_FAMILY_PREFIX}{session_id}"
    current_jti = await redis.get(family_key)
    async with redis.pipeline(transaction=True) as pipeline:
        if current_jti and current_jti != _REVOKED:
            pipeline.delete(f"{_REFRESH_PREFIX}{current_jti}")
        pipeline.set(
            family_key,
            _REVOKED,
            ex=settings.jwt_refresh_token_expire,
        )
        await pipeline.execute()


async def revoke_user_refresh_sessions(user_id: int) -> None:
    """撤销用户所有已索引的 Refresh family。"""

    redis = get_redis()
    user_key = f"{_USER_FAMILIES_PREFIX}{user_id}"
    session_ids = await redis.smembers(user_key)
    for session_id in session_ids:
        await revoke_refresh_family(session_id)
    await redis.delete(user_key)


async def increment_rate_limit(key: str, window_seconds: int) -> int:
    """在固定窗口中原子增加安全计数器。"""

    return int(
        await get_redis().eval(
            _RATE_LIMIT_SCRIPT,
            1,
            key,
            window_seconds,
        )
    )


# 以下兼容函数保留给旧测试、恢复工具和滚动升级期。
async def save_refresh_token(jti: str, user_id: int) -> None:
    await save_refresh_session(jti, jti, user_id)


async def verify_refresh_token(jti: str) -> int | None:
    return _parse_user_id(await get_redis().get(f"{_REFRESH_PREFIX}{jti}"))


async def delete_refresh_token(jti: str) -> None:
    redis = get_redis()
    value = await redis.get(f"{_REFRESH_PREFIX}{jti}")
    if value and ":" in value:
        _user_id, _separator, session_id = value.partition(":")
        await revoke_refresh_family(session_id)
        return
    await redis.delete(f"{_REFRESH_PREFIX}{jti}")
