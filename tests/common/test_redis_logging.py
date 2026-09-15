"""Redis 连接日志脱敏契约。"""

import logging

from app.core.redis import _log_redis_connected


def test_redis_connection_log_contains_only_safe_target_fields(caplog) -> None:
    redis_url = (
        "rediss://release-user:do-not-log@cache.internal:6380/2"
        "?ssl_cert_reqs=required&token=also-secret"
    )

    with caplog.at_level(logging.INFO, logger="app.core.redis"):
        _log_redis_connected(redis_url)

    message = caplog.records[-1].getMessage()
    assert message == (
        "Redis connected: scheme=rediss host=cache.internal port=6380 db=2"
    )
    assert "release-user" not in message
    assert "do-not-log" not in message
    assert "also-secret" not in message
