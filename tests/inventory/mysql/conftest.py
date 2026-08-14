"""Phase 4.3.11 隔离 MySQL 测试连接与数据清理。"""

import os

import pytest
import pytest_asyncio
from tortoise import Tortoise, connections
from tortoise.backends.base.executor import EXECUTOR_CACHE


MYSQL_DATABASE_PREFIX = "pinkdoohub_inventory_4311"


def _mysql_test_config() -> dict[str, object]:
    """只接受显式启用的本机、非默认端口、专用测试 Schema。"""

    if os.getenv("INVENTORY_MYSQL_TEST_ENABLED") != "1":
        pytest.skip(
            "set INVENTORY_MYSQL_TEST_ENABLED=1 for the isolated MySQL gate"
        )

    host = os.getenv("INVENTORY_MYSQL_TEST_HOST", "127.0.0.1")
    port = int(os.getenv("INVENTORY_MYSQL_TEST_PORT", "13306"))
    database = os.getenv("INVENTORY_MYSQL_TEST_DB", "")
    if host != "127.0.0.1":
        pytest.fail("MySQL gate only permits the local loopback host")
    if port == 3306 or not 1024 <= port <= 65535:
        pytest.fail("MySQL gate refuses the default or invalid server port")
    if not database.startswith(MYSQL_DATABASE_PREFIX):
        pytest.fail("MySQL gate requires its dedicated disposable schema prefix")

    return {
        "connections": {
            "default": {
                "engine": "tortoise.backends.mysql",
                "credentials": {
                    "host": host,
                    "port": port,
                    "user": os.getenv("INVENTORY_MYSQL_TEST_USER", "root"),
                    "password": os.getenv("INVENTORY_MYSQL_TEST_PASSWORD", ""),
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
    """在已校验的专用 Schema 中清空业务数据，保留 Aerich 版本链。"""

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
    """覆盖全局 SQLite fixture，连接已迁移的隔离 MySQL Schema。"""

    # Tortoise 1.1.7 的全局 Executor cache key 不包含数据库后端；若同一
    # pytest 进程先运行 SQLite，它会缓存带 `?` 参数的 INSERT。跨方言切换
    # 前后都清空该内部缓存，避免测试顺序改变 MySQL/SQLite SQL 占位符。
    EXECUTOR_CACHE.clear()
    await Tortoise.init(config=_mysql_test_config())
    try:
        await _truncate_business_tables()
        yield
    finally:
        await Tortoise.close_connections()
        EXECUTOR_CACHE.clear()
