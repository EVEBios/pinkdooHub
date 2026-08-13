"""User Model 数据库约束契约测试。"""

import pytest
from tortoise import connections
from tortoise.exceptions import IntegrityError

from app.models.user import User


async def test_phone_is_unique_at_database_boundary() -> None:
    """手机号查重必须有数据库兜底，避免并发写穿透 Service 预检查。"""

    await User.create(
        username="phone_owner",
        password="hashed-password",
        nickname="Owner",
        phone="13800001000",
    )

    with pytest.raises(IntegrityError):
        await User.create(
            username="phone_conflict",
            password="hashed-password",
            nickname="Conflict",
            phone="13800001000",
        )


async def test_phone_unique_constraint_exists_in_sqlite() -> None:
    """真实 SQLite Schema 应包含仅覆盖 phone 的唯一索引。"""

    connection = connections.get("default")
    indexes = await connection.execute_query_dict("PRAGMA index_list('users')")
    unique_indexes = [index for index in indexes if index["unique"] == 1]
    indexed_columns = []

    for index in unique_indexes:
        columns = await connection.execute_query_dict(
            f"PRAGMA index_info('{index['name']}')"
        )
        indexed_columns.append([column["name"] for column in columns])

    assert ["phone"] in indexed_columns


async def test_admin_list_index_exists_in_sqlite() -> None:
    """管理端按状态和角色筛选应使用文档约定的命名索引。"""

    connection = connections.get("default")
    columns = await connection.execute_query_dict(
        "PRAGMA index_info('idx_users_status_role')"
    )

    assert [column["name"] for column in columns] == ["status", "role"]
