"""Tortoise ORM 数据库连接管理。

通过 register_tortoise() 与 FastAPI 生命周期集成，
自动处理连接池的建立和释放，为每个请求维护数据库上下文。

根据 DB_ENGINE 自动切换 SQLite（开发）和 MySQL（生产）。
"""

import logging

from tortoise.contrib.fastapi import register_tortoise

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


def init_db(app) -> None:
    """向 FastAPI 应用注册 Tortoise ORM。

    自动在 startup 时建立连接并建表，在 shutdown 时关闭连接。
    替代手动 lifespan 管理。
    """
    config = _get_db_config()
    register_tortoise(
        app,
        config=config,
        generate_schemas=True,
        add_exception_handlers=True,
    )
    logger.info("Database registered: engine=%s", settings.db_engine)
