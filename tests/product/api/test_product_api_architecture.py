"""Product FastAPI 路由分层与注册边界测试。"""

import ast
from collections import Counter
from pathlib import Path

from app.api.v1.admin_products import router as admin_products_router
from app.api.v1.products import router as products_router
from app.main import app


ROUTE_PATHS = (
    Path("app/api/v1/products.py"),
    Path("app/api/v1/admin_products.py"),
)
UPLOAD_ORCHESTRATION_PATH = Path("app/api/uploads.py")


def test_product_routes_do_not_import_repositories_or_models() -> None:
    """路由通过 Service 依赖工作，不直接访问 Product 持久化层。"""

    forbidden_prefixes = ("app.repositories", "app.models.product")
    for path in ROUTE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.append(node.module)

        assert not any(
            imported.startswith(prefix)
            for imported in imports
            for prefix in forbidden_prefixes
        )


def test_product_routes_do_not_catch_business_exceptions() -> None:
    """业务异常直接交给全局中间件，不在路由手写错误响应。"""

    for path in ROUTE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(isinstance(node, ast.Try) for node in ast.walk(tree))


def test_upload_orchestration_does_not_access_persistence_or_business_layers() -> None:
    tree = ast.parse(UPLOAD_ORCHESTRATION_PATH.read_text(encoding="utf-8"))
    imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]

    assert not any(
        imported.startswith(("app.models", "app.repositories", "app.services"))
        for imported in imports
    )


def test_expected_product_routes_are_registered_once() -> None:
    """固定本阶段 Product 端点集合，避免遗漏和重复挂载。"""

    expected = {
        ("GET", "/api/v1/products"),
        ("GET", "/api/v1/products/experience/{product_id}"),
        ("GET", "/api/v1/products/kit/{product_id}"),
        ("GET", "/api/v1/admin/products"),
        ("GET", "/api/v1/admin/products/{product_id}/audit-logs"),
        ("GET", "/api/v1/admin/products/experience/{product_id}"),
        ("GET", "/api/v1/admin/products/kit/{product_id}"),
        ("POST", "/api/v1/admin/products/experience"),
        ("POST", "/api/v1/admin/products/kit"),
        ("PATCH", "/api/v1/admin/products/{product_id}"),
        ("DELETE", "/api/v1/admin/products/{product_id}"),
        ("PATCH", "/api/v1/admin/products/{product_id}/online"),
        ("PATCH", "/api/v1/admin/products/{product_id}/offline"),
        (
            "POST",
            "/api/v1/admin/products/experience/{product_id}/options",
        ),
        ("PATCH", "/api/v1/admin/options/{option_id}"),
        ("DELETE", "/api/v1/admin/options/{option_id}"),
        ("PATCH", "/api/v1/admin/product-images/{image_id}"),
        ("DELETE", "/api/v1/admin/product-images/{image_id}"),
        ("POST", "/api/v1/admin/products/{product_id}/images"),
        ("POST", "/api/v1/admin/options/{option_id}/images"),
        ("PATCH", "/api/v1/admin/products/kit/{product_id}/price"),
        ("PATCH", "/api/v1/admin/products/kit/{product_id}/stock"),
    }
    registered = [
        (method, f"/api/v1{route.path}")
        for router in (products_router, admin_products_router)
        for route in router.routes
        for method in getattr(route, "methods", set())
        if (method, f"/api/v1{route.path}") in expected
    ]

    assert set(registered) == expected
    assert len(registered) == len(expected)

    included_product_routers = [
        route.original_router
        for route in app.routes
        if hasattr(route, "original_router")
        and route.original_router in (products_router, admin_products_router)
    ]
    assert included_product_routers.count(products_router) == 1
    assert included_product_routers.count(admin_products_router) == 1


def test_openapi_has_exact_product_operations_and_admin_security() -> None:
    """收口 Product OpenAPI 路径、operationId 唯一性和权限声明。"""

    schema = app.openapi()
    product_operations: list[tuple[str, str, dict]] = []
    for path, path_item in schema["paths"].items():
        if not (
            path.startswith("/api/v1/products")
            or path.startswith("/api/v1/admin/products")
            or path.startswith("/api/v1/admin/options")
            or path.startswith("/api/v1/admin/product-images")
        ):
            continue
        for method, operation in path_item.items():
            if method in {"get", "post", "patch", "delete"}:
                product_operations.append((method, path, operation))

    assert len(product_operations) == 22
    operation_ids = [item[2]["operationId"] for item in product_operations]
    assert len(operation_ids) == len(set(operation_ids))

    for _, path, operation in product_operations:
        if path.startswith("/api/v1/admin/"):
            assert operation["security"] == [{"HTTPBearer": []}]
            assert {"400", "401", "403", "404", "409", "422"} <= set(
                operation["responses"]
            )
        else:
            assert "security" not in operation
            assert {"404", "422"} <= set(operation["responses"])

        success_statuses = {"200", "201"} & set(operation["responses"])
        assert success_statuses
        for status_code in success_statuses:
            response_schema = operation["responses"][status_code]["content"][
                "application/json"
            ]["schema"]
            assert response_schema.get("$ref", "").startswith(
                "#/components/schemas/SuccessResponse_"
            )

        error_schema = operation["responses"]["422"]["content"][
            "application/json"
        ]["schema"]
        assert error_schema == {"$ref": "#/components/schemas/ErrorResponse"}


def test_all_openapi_operation_ids_are_unique() -> None:
    """任何模块的重复路由都不得污染生成的 OpenAPI。"""

    schema = app.openapi()
    operation_ids = [
        operation["operationId"]
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    counts = Counter(operation_ids)

    assert [operation_id for operation_id, count in counts.items() if count > 1] == []
