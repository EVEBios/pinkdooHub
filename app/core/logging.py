"""日志系统初始化。

应用启动时调用 setup_logging()，全局生效。
之后任何模块只需：

    import logging
    logger = logging.getLogger(__name__)
    logger.info("...")

即可自动使用统一格式，无需额外配置。
"""

import logging


def setup_logging() -> None:
    """初始化全局日志系统。

    调用一次，全局生效。后续可在各模块中直接使用 logging.getLogger(__name__)。

    格式说明：
        时间  级别  模块名  消息
        09:41:02  INFO    app.main  pinkdooHub ready  startup=42ms
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # 降低第三方库的日志噪音
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("dotenv").setLevel(logging.WARNING)
