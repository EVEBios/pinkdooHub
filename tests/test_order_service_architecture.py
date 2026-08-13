"""OrderService 分层与依赖方向契约测试。"""

import ast
import inspect
from pathlib import Path

from app.services.order_service import OrderService


def test_order_query_methods_are_async_orchestration() -> None:
    """创建、状态变迁和五个只读用例都必须是异步编排接口。"""

    for method_name in (
        "create_order",
        "cancel_order",
        "mark_order_paid",
        "complete_order",
        "list_user_orders",
        "get_user_order_detail",
        "list_admin_orders",
        "get_admin_order_detail",
        "list_order_audit_logs",
    ):
        assert inspect.iscoroutinefunction(getattr(OrderService, method_name))


def test_order_service_has_no_transport_schema_or_redis_dependency() -> None:
    """Service 不依赖传输层、Schema 或 Redis。"""

    source_path = Path(inspect.getsourcefile(OrderService) or "")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(
        imported == forbidden or imported.startswith(f"{forbidden}.")
        for imported in imported_modules
        for forbidden in (
            "fastapi",
            "app.api",
            "app.schemas",
            "app.core.redis",
        )
    )


def test_order_service_does_not_persist_or_query_models_directly() -> None:
    """所有数据库访问必须经 Repository 或共享 AuditLogService。"""

    source = inspect.getsource(OrderService)
    tree = ast.parse(source)
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    }

    assert called_attributes.isdisjoint(
        {
            "all",
            "create",
            "delete",
            "filter",
            "get",
            "save",
            "update",
            "update_from_dict",
        }
    )
