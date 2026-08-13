"""Tortoise ORM 数据库连接管理。

通过 register_tortoise() 与 FastAPI 生命周期集成，
自动处理连接池的建立和释放，为每个请求维护数据库上下文。

根据 DB_ENGINE 自动切换 SQLite（开发）和 MySQL（生产）。
"""

import logging
from typing import Any

from fastapi import FastAPI
from tortoise.contrib.fastapi import register_tortoise

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_db_config() -> dict[str, Any]:
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

    return {
        "connections": {
            "default": {
                "engine": "tortoise.backends.mysql",
                "credentials": {
                    "host": settings.db_host,
                    "port": settings.db_port,
                    "user": settings.db_user,
                    "password": settings.db_password,
                    "database": settings.db_name,
                },
            }
        },
        "apps": {
            "models": {
                "models": ["app.models", "aerich.models"],
                "default_connection": "default",
            },
        },
    }


def _should_generate_schemas() -> bool:
    """仅允许本地开发环境在启动时自动补齐表结构。"""

    return settings.app_env == "development"


# Aerich CLI 要求通过 import path 读取一个配置字典；命令进程启动时会按
# 当前环境变量重新构造该对象，因此可离线生成 MySQL 方言迁移。
TORTOISE_ORM: dict[str, Any] = _get_db_config()


def init_db(app: FastAPI) -> None:
    """向 FastAPI 应用注册 Tortoise ORM。

    startup 时建立连接，shutdown 时关闭连接。仅 development 自动建表；
    testing 由测试 fixture 管理临时 Schema，production 必须使用受控迁移。
    """
    config = _get_db_config()
    register_tortoise(
        app,
        config=config,
        generate_schemas=_should_generate_schemas(),
        add_exception_handlers=True,
    )
    logger.info("Database registered: engine=%s", settings.db_engine)
