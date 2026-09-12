"""AuditLog Model 索引契约测试。"""

from tortoise import connections


async def test_audit_log_query_indexes_exist_in_sqlite() -> None:
    """实体追踪和操作人追踪索引必须按查询顺序真实落库。"""

    connection = connections.get("default")
    expected_indexes = {
        "idx_audit_target_created": ["target_type", "target_id", "created_at"],
        "idx_audit_operator_created": ["operator_id", "created_at"],
    }

    indexes = await connection.execute_query_dict("PRAGMA index_list('audit_logs')")
    assert {index["name"] for index in indexes} == set(expected_indexes)

    for index_name, expected_columns in expected_indexes.items():
        columns = await connection.execute_query_dict(
            f"PRAGMA index_info('{index_name}')"
        )
        assert [column["name"] for column in columns] == expected_columns
