"""InventoryService 分层、事务和敏感数据边界测试。"""

import ast
import inspect
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.inventory_service import (
    InventoryAdjustmentResult,
    InventoryService,
)


def test_inventory_service_constructor_exposes_only_required_collaborators() -> None:
    parameters = list(inspect.signature(InventoryService).parameters)

    assert parameters == [
        "inventory_repository",
        "product_repository",
        "audit_log_service",
    ]
    assert inspect.signature(InventoryService).parameters[
        "inventory_repository"
    ].annotation is InventoryRepository
    assert inspect.signature(InventoryService).parameters[
        "product_repository"
    ].annotation is ProductRepository
    assert inspect.signature(InventoryService).parameters[
        "audit_log_service"
    ].annotation is AuditLogService


def test_inventory_service_owns_transaction_without_layer_bypass() -> None:
    source = inspect.getsource(inspect.getmodule(InventoryService))
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert "in_transaction" in source
    assert "get_kit_for_update" in source
    assert "get_products_by_ids" in source
    assert "update_stock" in source
    assert "create_transaction" in source
    assert "audit_log_service.log" in source
    assert "get_transaction_detail" in source
    assert "fastapi" not in imports
    assert "app.schemas.inventory" not in imports
    assert "app.core.redis" not in imports
    assert "ProductService" not in source
    assert ".filter(" not in source
    assert ".create(" not in source
    assert ".save(" not in source


def test_adjustment_result_is_frozen_and_signals_idempotent_replay() -> None:
    result = InventoryAdjustmentResult(
        product_id=5,
        stock=10,
        transaction=SimpleNamespace(id=1),  # type: ignore[arg-type]
        is_replay=True,
    )

    assert result.is_replay is True
    with pytest.raises(FrozenInstanceError):
        result.stock = 11  # type: ignore[misc]


def test_logs_never_include_reason_or_idempotency_key() -> None:
    source = inspect.getsource(InventoryService.adjust_stock)

    assert "idempotency_key=%" not in source
    assert "internal_key=%" not in source
    assert "reason=%" not in source
