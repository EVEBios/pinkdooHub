"""OrderService 分层与依赖方向契约测试。"""

import ast
import inspect
from pathlib import Path

from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
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


def test_order_service_constructor_owns_required_repository_boundaries() -> None:
    signature = inspect.signature(OrderService)

    assert list(signature.parameters) == [
        "order_repository",
        "product_repository",
        "inventory_repository",
        "audit_log_service",
        "user_repository",
        "order_number_generator",
    ]
    assert signature.parameters["order_repository"].annotation is OrderRepository
    assert signature.parameters["product_repository"].annotation is ProductRepository
    assert (
        signature.parameters["inventory_repository"].annotation
        is InventoryRepository
    )
    assert signature.parameters["audit_log_service"].annotation is AuditLogService
    assert signature.parameters["user_repository"].annotation is UserRepository


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
    assert "app.services.inventory_service" not in imported_modules


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


def test_cancel_inventory_sequence_keeps_order_lock_and_bulk_boundaries() -> None:
    """取消先锁 Order，再恢复库存，支付/完成通用路径不承担库存副作用。"""

    cancel_source = inspect.getsource(OrderService._cancel_order_once)
    restore_source = inspect.getsource(
        OrderService._restore_kit_stock_after_cancellation
    )
    transition_source = inspect.getsource(OrderService._transition_order)

    assert cancel_source.index("get_order_for_update") < cancel_source.index(
        "get_order_items"
    )
    assert cancel_source.index("get_order_items") < cancel_source.index(
        "_restore_kit_stock_after_cancellation"
    )
    assert cancel_source.index(
        "_restore_kit_stock_after_cancellation"
    ) < cancel_source.index("update_status")
    assert "get_kits_for_update" in restore_source
    assert "get_transactions_by_idempotency_keys" in restore_source
    assert "bulk_update_stocks" in restore_source
    assert "bulk_create_transactions" in restore_source
    assert "inventory_repository" not in transition_source
