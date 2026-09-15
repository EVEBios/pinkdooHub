"""SUPER_ADMIN Bootstrap 的分层与数据库锁适配契约。"""

import ast
import inspect
from types import SimpleNamespace

from app.repositories.bootstrap_lock_repo import BootstrapLockRepository
from app.services import super_admin_bootstrap_service as service_module


def test_bootstrap_service_respects_application_boundaries() -> None:
    source = inspect.getsource(service_module)
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert not any(name.startswith("fastapi") for name in imports)
    assert not any(name.startswith("app.api") for name in imports)
    assert not any(name.startswith("app.schemas") for name in imports)
    assert not any(name.startswith("app.models") for name in imports)


async def test_mysql_lock_uses_parameterized_fixed_name_and_same_connection() -> None:
    class FakeMySQLConnection:
        capabilities = SimpleNamespace(dialect="mysql")

        def __init__(self) -> None:
            self.calls: list[tuple[str, list[object]]] = []

        async def execute_query_dict(self, query, values):
            self.calls.append((query, values))
            if "GET_LOCK" in query:
                return [{"acquired": 1}]
            return [{"released": 1}]

    connection = FakeMySQLConnection()
    repository = BootstrapLockRepository()

    acquired = await repository.acquire_database_lock(
        using_db=connection,
        timeout_seconds=10,
    )
    await repository.release_database_lock(using_db=connection)

    assert acquired is True
    assert connection.calls == [
        (
            "SELECT GET_LOCK(%s, %s) AS acquired",
            ["pinkdoohub:super-admin-bootstrap", 10],
        ),
        (
            "SELECT RELEASE_LOCK(%s) AS released",
            ["pinkdoohub:super-admin-bootstrap"],
        ),
    ]
