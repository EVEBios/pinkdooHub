"""Inventory FastAPI 组合根、路由注册与 OpenAPI 边界测试。"""

import ast
import inspect
from pathlib import Path
from unittest.mock import Mock

from app.api.deps import get_inventory_service
from app.api.v1.admin_inventory import router as admin_inventory_router
from app.main import app
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.services.inventory_service import InventoryService


ROUTE_PATH = Path("app/api/v1/admin_inventory.py")


def test_inventory_composition_root_assembles_exact_dependencies() -> None:
    inventory_repository = Mock(spec=InventoryRepository)
    product_repository = Mock(spec=ProductRepository)
    audit_log_repository = Mock(spec=AuditLogRepository)

    service = get_inventory_service(
        inventory_repository,
        product_repository,
        audit_log_repository,
    )

    assert isinstance(service, InventoryService)
    assert service.inventory_repository is inventory_repository
    assert service.product_repository is product_repository
    assert service.audit_log_service.audit_repo is audit_log_repository


def test_inventory_routes_do_not_bypass_service_or_catch_business_errors() -> None:
    tree = ast.parse(ROUTE_PATH.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(module.startswith("app.repositories") for module in imports)
    assert not any(
        module.startswith("app.models") and module != "app.models.user"
        for module in imports
    )
    assert not any(isinstance(node, ast.Try) for node in ast.walk(tree))
    assert ".filter(" not in ROUTE_PATH.read_text(encoding="utf-8")


def test_inventory_routes_are_registered_once_and_legacy_route_is_absent() -> None:
    expected = {
        (
            "POST",
            "/api/v1/admin/products/kit/{product_id}/inventory-adjustments",
        ),
        (
            "GET",
            "/api/v1/admin/products/kit/{product_id}/inventory-transactions",
        ),
        ("GET", "/api/v1/admin/inventory-transactions"),
    }
    registered = {
        (method, f"/api/v1{route.path}")
        for route in admin_inventory_router.routes
        for method in getattr(route, "methods", set())
    }

    assert registered == expected
    assert not any(
        getattr(route, "path", None)
        == "/api/v1/admin/products/kit/{product_id}/stock"
        for route in app.routes
    )
    included_inventory_routers = [
        route.original_router
        for route in app.routes
        if hasattr(route, "original_router")
        and route.original_router is admin_inventory_router
    ]
    assert included_inventory_routers.count(admin_inventory_router) == 1


def test_inventory_openapi_declares_security_headers_and_success_envelopes() -> None:
    schema = app.openapi()
    paths = {
        path: item
        for path, item in schema["paths"].items()
        if "inventory-" in path or path.endswith("inventory-transactions")
    }

    assert set(paths) == {
        "/api/v1/admin/products/kit/{product_id}/inventory-adjustments",
        "/api/v1/admin/products/kit/{product_id}/inventory-transactions",
        "/api/v1/admin/inventory-transactions",
    }
    for path_item in paths.values():
        for operation in path_item.values():
            assert operation["security"] == [{"HTTPBearer": []}]
            assert {"400", "401", "403", "404", "409", "422"} <= set(
                operation["responses"]
            )

    adjustment = paths[
        "/api/v1/admin/products/kit/{product_id}/inventory-adjustments"
    ]["post"]
    assert {"200", "201"} <= set(adjustment["responses"])
    idempotency_header = next(
        parameter
        for parameter in adjustment["parameters"]
        if parameter["in"] == "header"
    )
    assert idempotency_header["name"] == "Idempotency-Key"
    assert idempotency_header["required"] is True

    for path_item in paths.values():
        for operation in path_item.values():
            for status_code in {"200", "201"} & set(operation["responses"]):
                response_schema = operation["responses"][status_code]["content"][
                    "application/json"
                ]["schema"]
                assert response_schema.get("$ref", "").startswith(
                    "#/components/schemas/SuccessResponse_"
                )


def test_inventory_route_functions_are_async() -> None:
    functions = [
        route.endpoint
        for route in admin_inventory_router.routes
        if hasattr(route, "endpoint")
    ]

    assert len(functions) == 3
    assert all(inspect.iscoroutinefunction(function) for function in functions)
