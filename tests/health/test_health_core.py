"""依赖感知 Readiness 的基础设施契约。"""

import logging

from app.core import health as health_module


async def test_readiness_checks_real_test_database_and_redis() -> None:
    """共享 fixture 提供的 SQLite 与 fakeredis 都可用时应 Ready。"""

    result = await health_module.check_readiness()

    assert result.database is True
    assert result.redis is True
    assert result.is_ready is True


async def test_readiness_reports_each_dependency_independently(monkeypatch) -> None:
    """单项失败不得跳过另一项检查。"""

    database_checked = False

    async def database_ok() -> None:
        nonlocal database_checked
        database_checked = True

    async def redis_failed() -> None:
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(health_module, "_ping_database", database_ok)
    monkeypatch.setattr(health_module, "_ping_redis", redis_failed)

    result = await health_module.check_readiness()

    assert database_checked is True
    assert result.database is True
    assert result.redis is False
    assert result.is_ready is False


async def test_readiness_times_out_slow_dependency(monkeypatch) -> None:
    """卡住的依赖必须在探针超时内收敛为 Down。"""

    async def database_never_returns() -> None:
        await health_module.asyncio.Event().wait()

    async def redis_ok() -> None:
        return None

    monkeypatch.setattr(health_module, "_ping_database", database_never_returns)
    monkeypatch.setattr(health_module, "_ping_redis", redis_ok)

    result = await health_module.check_readiness(timeout_seconds=0.001)

    assert result.database is False
    assert result.redis is True
    assert result.is_ready is False


async def test_readiness_log_does_not_include_dependency_error_text(
    monkeypatch,
    caplog,
) -> None:
    """驱动异常可能含连接串，日志只能保留依赖名与异常类型。"""

    sensitive_value = "redis://operator:do-not-log@cache.internal:6380/2"

    async def database_ok() -> None:
        return None

    async def redis_failed() -> None:
        raise RuntimeError(sensitive_value)

    monkeypatch.setattr(health_module, "_ping_database", database_ok)
    monkeypatch.setattr(health_module, "_ping_redis", redis_failed)

    with caplog.at_level(logging.WARNING, logger="app.core.health"):
        result = await health_module.check_readiness()

    assert result.redis is False
    assert sensitive_value not in caplog.text
    assert "dependency=redis error_type=RuntimeError" in caplog.text
