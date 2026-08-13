"""Order API Mapper 的分层和纯度契约。"""

import ast
from pathlib import Path


MAPPER_PATH = Path("app/api/mappers/order.py")
FORBIDDEN_IMPORT_PREFIXES = (
    "app.services",
    "app.repositories",
    "fastapi",
    "app.core.redis",
)
FORBIDDEN_CALL_NAMES = {
    "filter",
    "get",
    "all",
    "save",
    "create",
    "delete",
    "update",
}


def _tree() -> ast.Module:
    return ast.parse(MAPPER_PATH.read_text(encoding="utf-8"))


def test_order_mapper_has_no_async_or_await() -> None:
    tree = _tree()

    assert not any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(tree))
    assert not any(isinstance(node, ast.Await) for node in ast.walk(tree))


def test_order_mapper_does_not_depend_on_forbidden_layers() -> None:
    imports: list[str] = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(node.module)

    assert not any(
        imported.startswith(prefix)
        for imported in imports
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )


def test_order_mapper_contains_no_orm_query_or_mutation_calls() -> None:
    called_attributes = {
        node.func.attr
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert called_attributes.isdisjoint(FORBIDDEN_CALL_NAMES)
