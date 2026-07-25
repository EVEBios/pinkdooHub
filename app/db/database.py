"""Tortoise ORM 数据库连接管理。

根据 DB_ENGINE 自动切换 SQLite（开发）和 MySQL（生产）。
init_db() 和 close_db() 分别用于应用启动和关闭。
"""

import logging

from tortoise import Tortoise

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_db_config() -> dict:
    """根据配置生成 Tortoise ORM 连接参数。

    SQLite: 免安装，文件即数据库，适合开发和测试
    MySQL:  生产环境，需要先安装并创建数据库
    """
    if settings.db_engine == "sqlite":
        return {
            "connections": {
                "default": f"sqlite://{settings.db_sqlite_path}",
            },
            "apps": {
                "models": {
                    "models": ["app.models", "aerich.models"],
                    "default_connection": "default",
                },
            },
        }

    # MySQL
    db_url = (
        f"mysql://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )
    return {
        "connections": {"default": db_url},
        "apps": {
            "models": {
                "models": ["app.models", "aerich.models"],
                "default_connection": "default",
            },
        },
    }


async def init_db() -> None:
    """初始化数据库连接。

    启动时调用，建立连接池并自动建表（开发环境）。
    生产环境应使用 Aerich 迁移代替 generate_schemas()。
    """
    config = _get_db_config()
    await Tortoise.init(config=config)
    await Tortoise.generate_schemas()
    logger.info("Database connected: engine=%s", settings.db_engine)


async def close_db() -> None:
    """关闭数据库连接。

    关闭时调用，等待所有进行中的查询完成后释放连接。
    """
    await Tortoise.close_connections()
    logger.info("Database disconnected")
