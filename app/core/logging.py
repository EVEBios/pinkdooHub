"""日志系统初始化。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
核心知识点：为什么不用 print()
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print() 和 logger 的区别：

    print("订单失败")                    logger.error("订单创建失败", extra={
                                            "order_id": 123,
    → 只有一段文字                        "user_id": 456,
    → 没有时间戳                           "reason": "stock insufficient",
    → 没有级别                             })
    → 没有模块名
    → 不能被过滤                       → 结构化，可检索，可告警

企业级日志要求：
  - 每条日志带时间戳、级别、模块名
  - 按级别过滤（生产只记录 INFO 以上，开发记录 DEBUG）
  - 可被日志采集系统（ELK、Loki）解析
  - Docker/K8s 从 stdout 采集，无需写文件

日志级别（严重程度递增）：

    DEBUG      开发调试信息，生产环境不输出
    INFO       关键业务流程节点（启动完成、订单创建、用户注册）
    WARNING    非预期但可恢复的情况（限流触发、Token 即将过期）
    ERROR      需要人工处理的错误（订单创建失败、支付超时）
    CRITICAL   系统级故障，需要立即响应（数据库宕机、Redis 不可用）

使用方式——项目任意模块：

    import logging
    logger = logging.getLogger(__name__)

    logger.debug("query prepared: sql=%s params=%s", sql, params)
    logger.info("order created: order_id=%d user_id=%d", order.id, user_id)
    logger.warning("rate limit triggered: ip=%s endpoint=%s", ip, path)
    logger.error("payment failed: order_id=%d reason=%s", order_id, error)

setup_logging() 在 lifespan 中调用一次，全局生效。
"""

import logging

from app.core.config import settings


def setup_logging() -> None:
    """初始化全局日志系统。

    调用一次，全局生效。后续任何模块直接使用 logging.getLogger(__name__)。
    日志级别根据 APP_ENV 自动切换：
      - development → DEBUG（输出所有日志，方便调试）
      - production  → INFO（过滤 DEBUG，减少噪音）
    """
    level = logging.DEBUG if settings.app_debug else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # 降低第三方库的日志噪音——只关注应用自身的日志
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("dotenv").setLevel(logging.WARNING)
    # code2Session 按微信协议将 AppSecret 放在 query 中；禁止 httpx
    # 记录完整 URL，避免凭据进入应用日志。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
