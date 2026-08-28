"""Order FastAPI 路由的分层、注册和 OpenAPI 契约测试。"""

import ast
from collections import Counter
from pathlib import Path

from app.api.deps import get_order_service
from app.api.v1.admin_orders import router as admin_orders_router
from app.api.v1.orders import router as orders_router
from app.main import app
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService


ROUTE_PATHS = (
    Path("app/api/v1/orders.py"),
    Path("app/api/v1/admin_orders.py"),
)


def test_order_routes_do_not_import_persistence_or_domain_models() -> None:
    """路由只能通过 Service 和 Mapper 工作，不跳层访问持久化。"""

    forbidden_prefixes = (
        "app.repositories",
        "app.models.order",
        "app.models.product",
        "app.models.experience_option",
    )
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


def test_order_routes_do_not_catch_business_exceptions() -> None:
    """业务异常必须交给全局中间件转换。"""

    for path in ROUTE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(isinstance(node, ast.Try) for node in ast.walk(tree))


def test_order_composition_root_wires_expected_dependencies() -> None:
    """组合根集中组装 Order、Product 与共享审计边界。"""

    order_repository = OrderRepository()
    product_repository = ProductRepository()
    inventory_repository = InventoryRepository()
    audit_repository = AuditLogRepository()

    service = get_order_service(
        order_repository,
        product_repository,
        inventory_repository,
        audit_repository,
    )

    assert service.order_repository is order_repository
    assert service.product_repository is product_repository
    assert service.inventory_repository is inventory_repository
    assert isinstance(service.audit_log_service, AuditLogService)
    assert service.audit_log_service.audit_repo is audit_repository


def test_expected_order_routes_are_registered_once() -> None:
    """固定九个 Order 端点，避免遗漏、重复或路径漂移。"""

    expected = {
        ("POST", "/api/v1/orders"),
        ("GET", "/api/v1/orders"),
        ("GET", "/api/v1/orders/{order_id}"),
        ("PATCH", "/api/v1/orders/{order_id}/cancel"),
        ("GET", "/api/v1/admin/orders"),
        ("GET", "/api/v1/admin/orders/{order_id}"),
        ("PATCH", "/api/v1/admin/orders/{order_id}/paid"),
        ("PATCH", "/api/v1/admin/orders/{order_id}/complete"),
        ("GET", "/api/v1/admin/orders/{order_id}/audit-logs"),
    }
    registered = [
        (method, f"/api/v1{route.path}")
        for router in (orders_router, admin_orders_router)
        for route in router.routes
        for method in getattr(route, "methods", set())
        if (method, f"/api/v1{route.path}") in expected
    ]

    assert set(registered) == expected
    assert len(registered) == len(expected)

    included_order_routers = [
        route.original_router
        for route in app.routes
        if hasattr(route, "original_router")
        and route.original_router in (orders_router, admin_orders_router)
    ]
    assert included_order_routers.count(orders_router) == 1
    assert included_order_routers.count(admin_orders_router) == 1


def test_order_openapi_has_security_success_errors_and_body_contracts() -> None:
    """九个端点必须精确声明 Bearer、安全信封和 PATCH 无 body。"""

    schema = app.openapi()
    operations: list[tuple[str, str, dict]] = []
    for path, path_item in schema["paths"].items():
        if not (
            path.startswith("/api/v1/orders")
            or path.startswith("/api/v1/admin/orders")
        ):
            continue
        for method, operation in path_item.items():
            if method in {"get", "post", "patch"}:
                operations.append((method, path, operation))

    assert len(operations) == 9
    assert len({item[2]["operationId"] for item in operations}) == 9
    for method, path, operation in operations:
        assert operation["security"] == [{"HTTPBearer": []}]
        expected_errors = {"400", "401", "404", "409", "422"}
        if path.startswith("/api/v1/admin/"):
            expected_errors.add("403")
        assert expected_errors <= set(operation["responses"])

        expected_success = "201" if method == "post" else "200"
        assert expected_success in operation["responses"]
        response_schema = operation["responses"][expected_success]["content"][
            "application/json"
        ]["schema"]
        assert response_schema.get("$ref", "").startswith(
            "#/components/schemas/SuccessResponse_"
        )
        assert operation["responses"]["422"]["content"]["application/json"][
            "schema"
        ] == {"$ref": "#/components/schemas/ErrorResponse"}

        if method == "patch":
            assert "requestBody" not in operation
        elif method == "post":
            assert "requestBody" in operation

    admin_list_parameters = schema["paths"]["/api/v1/admin/orders"]["get"][
        "parameters"
    ]
    product_name_parameter = next(
        parameter
        for parameter in admin_list_parameters
        if parameter["name"] == "product_name"
    )
    product_name_string_schema = product_name_parameter["schema"]["anyOf"][0]
    assert product_name_string_schema["minLength"] == 1
    assert product_name_string_schema["maxLength"] == 100


def test_all_openapi_operation_ids_remain_unique_with_order_routes() -> None:
    """新增 Order 路由不能与任何既有模块产生 operationId 冲突。"""

    schema = app.openapi()
    operation_ids = [
        operation["operationId"]
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    counts = Counter(operation_ids)

    assert [value for value, count in counts.items() if count > 1] == []
