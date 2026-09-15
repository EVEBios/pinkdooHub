"""ADMIN User 路由分层与 OpenAPI 契约。"""

import ast
from pathlib import Path

from app.main import app


ROUTE_PATH = Path("app/api/v1/admin_users.py")


def test_admin_user_route_does_not_import_repository_or_catch_errors() -> None:
    tree = ast.parse(ROUTE_PATH.read_text(encoding="utf-8"))
    imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]

    assert not any(name.startswith("app.repositories") for name in imports)
    assert not any(isinstance(node, ast.Try) for node in ast.walk(tree))


def test_admin_user_openapi_has_typed_envelopes_and_admin_security() -> None:
    schema = app.openapi()
    list_operation = schema["paths"]["/api/v1/admin/users"]["get"]
    disable_operation = schema["paths"][
        "/api/v1/admin/users/{user_id}/disable"
    ]["put"]

    for operation in (list_operation, disable_operation):
        assert operation["security"] == [{"HTTPBearer": []}]
        assert {"400", "401", "403", "422"} <= set(operation["responses"])

    list_schema = list_operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    disable_schema = disable_operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert list_schema["$ref"].endswith("/SuccessResponse_Page_UserListItem__")
    assert disable_schema["$ref"].endswith("/SuccessResponse_NoneType_")

    query_names = {parameter["name"] for parameter in list_operation["parameters"]}
    assert query_names == {"page", "page_size", "status", "role"}
    user_properties = schema["components"]["schemas"]["UserListItem"]["properties"]
    assert set(user_properties) == {
        "id", "username", "nickname", "role", "status", "last_login_at", "created_at",
    }
