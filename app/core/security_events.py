"""可由日志采集系统稳定聚合的脱敏安全事件。"""

import logging

logger = logging.getLogger("app.security")


def emit_security_event(
    event: str,
    outcome: str,
    *,
    level: int = logging.INFO,
    user_id: int | None = None,
    scope: str | None = None,
) -> None:
    """只记录固定事件维度；禁止传入 Token、平台标识、code 或凭据。"""

    logger.log(
        level,
        "security_event=%s outcome=%s user_id=%s scope=%s",
        event,
        outcome,
        user_id if user_id is not None else "none",
        scope or "none",
    )
