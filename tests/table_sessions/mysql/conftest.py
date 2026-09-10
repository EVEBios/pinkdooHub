"""M9 桌台会话隔离 MySQL 发布门槛配置。"""

import os

import pytest
import pytest_asyncio
from tortoise import Tortoise, connections
from tortoise.backends.base.executor import EXECUTOR_CACHE


MYSQL_DATABASE_PREFIX = "pinkdoohub_inventory_4311"
MIGRATION_EVIDENCE_TABLES = {"aerich", "bead_colors", "reservation_settings"}


def _mysql_test_config() -> dict[str, object]:
    if os.getenv("INVENTORY_MYSQL_TEST_ENABLED") != "1":
        pytest.skip("set INVENTORY_MYSQL_TEST_ENABLED=1 for the isolated MySQL gate")
    host = os.getenv("INVENTORY_MYSQL_TEST_HOST", "127.0.0.1")
    port = int(os.getenv("INVENTORY_MYSQL_TEST_PORT", "13306"))
    database = os.getenv("INVENTORY_MYSQL_TEST_DB", "")
    if host != "127.0.0.1" or port == 3306 or not 1024 <= port <= 65535:
        pytest.fail("M9 MySQL gate requires a non-default local loopback target")
    if not database.startswith(MYSQL_DATABASE_PREFIX):
        pytest.fail("M9 MySQL gate requires the dedicated disposable schema")
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
    connection = connections.get("default")
    table_names = sorted(
        {
            model._meta.db_table
            for model in Tortoise.apps["models"].values()
            if model._meta.db_table not in MIGRATION_EVIDENCE_TABLES
        }
    )
    await connection.execute_query("SET FOREIGN_KEY_CHECKS = 0")
    try:
        for table_name in table_names:
            await connection.execute_query(f"TRUNCATE TABLE `{table_name}`")
    finally:
        await connection.execute_query("SET FOREIGN_KEY_CHECKS = 1")
    await connection.execute_query(
        "UPDATE reservation_settings "
        "SET singleton_key = 1, weekly_closed_weekday = 'monday'"
    )


@pytest_asyncio.fixture(autouse=True)
async def setup_db() -> None:
    EXECUTOR_CACHE.clear()
    await Tortoise.init(config=_mysql_test_config())
    try:
        await _truncate_business_tables()
        yield
    finally:
        await Tortoise.close_connections()
        EXECUTOR_CACHE.clear()
