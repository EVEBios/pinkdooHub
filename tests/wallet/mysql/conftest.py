"""Wallet v1 的隔离 MySQL 8 真实链路测试配置。"""

import os

import pytest
import pytest_asyncio
from tortoise import Tortoise, connections
from tortoise.backends.base.executor import EXECUTOR_CACHE


MYSQL_DATABASE_PREFIX = "pinkdoohub_wallet_"


def _mysql_test_config() -> dict[str, object]:
    """只允许显式启用的本机、非默认端口、专用测试 Schema。"""

    if os.getenv("WALLET_MYSQL_TEST_ENABLED") != "1":
        pytest.skip("set WALLET_MYSQL_TEST_ENABLED=1 for the wallet MySQL gate")

    host = os.getenv("WALLET_MYSQL_TEST_HOST", "127.0.0.1")
    port = int(os.getenv("WALLET_MYSQL_TEST_PORT", "13316"))
    database = os.getenv("WALLET_MYSQL_TEST_DB", "")
    if host != "127.0.0.1":
        pytest.fail("Wallet MySQL gate only permits the local loopback host")
    if port == 3306 or not 1024 <= port <= 65535:
        pytest.fail("Wallet MySQL gate refuses the default or invalid server port")
    if not database.startswith(MYSQL_DATABASE_PREFIX):
        pytest.fail("Wallet MySQL gate requires its dedicated disposable schema prefix")

    return {
        "connections": {
            "default": {
                "engine": "tortoise.backends.mysql",
                "credentials": {
                    "host": host,
                    "port": port,
                    "user": os.getenv("WALLET_MYSQL_TEST_USER", "root"),
                    "password": os.getenv("WALLET_MYSQL_TEST_PASSWORD", ""),
                    "database": database,
                    "minsize": 1,
                    "maxsize": 8,
                    "connect_timeout": 5,
                },
            }
        },
        "apps": {
            "models": {
                "models": ["app.models", "aerich.models"],
                "default_connection": "default",
            }
        },
    }


async def _truncate_business_tables() -> None:
    """清空已经过专用 Schema 校验的业务表，保留 Aerich 版本链。"""

    connection = connections.get("default")
    table_names = sorted(
        {
            model._meta.db_table
            for model in Tortoise.apps["models"].values()
            if model._meta.db_table != "aerich"
        }
    )
    await connection.execute_query("SET FOREIGN_KEY_CHECKS = 0")
    try:
        for table_name in table_names:
            await connection.execute_query(f"TRUNCATE TABLE `{table_name}`")
    finally:
        await connection.execute_query("SET FOREIGN_KEY_CHECKS = 1")


@pytest_asyncio.fixture(autouse=True)
async def setup_db() -> None:
    """覆盖共享 SQLite fixture，连接已完成 0→4 迁移的隔离 MySQL。"""

    EXECUTOR_CACHE.clear()
    await Tortoise.init(config=_mysql_test_config())
    try:
        await _truncate_business_tables()
        yield
    finally:
        await Tortoise.close_connections()
        EXECUTOR_CACHE.clear()
