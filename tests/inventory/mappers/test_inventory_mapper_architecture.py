"""Inventory Mapper 分层、同步纯函数和字段边界测试。"""

import ast
import inspect

from app.api.mappers import inventory
from app.api.mappers.inventory import (
    map_inventory_adjustment,
    map_inventory_transaction,
    map_inventory_transaction_list_item,
    map_inventory_transaction_page,
)


def test_inventory_mapper_is_synchronous_and_has_no_data_access_dependency() -> None:
    source = inspect.getsource(inventory)
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert all(
        not inspect.iscoroutinefunction(function)
        for function in (
            map_inventory_transaction,
            map_inventory_transaction_list_item,
            map_inventory_transaction_page,
            map_inventory_adjustment,
        )
    )
    assert not any("repositories" in module for module in imported_modules)
    assert not any("services" in module for module in imported_modules)
    assert ".filter(" not in source
    assert ".get(" not in source
    assert ".save(" not in source
    assert "await " not in source


def test_inventory_mapper_does_not_reference_private_fields() -> None:
    source = inspect.getsource(inventory)

    for field in (
        "idempotency_key",
        "updated_at",
        "username",
        "phone",
        "password",
        "token",
    ):
        assert field not in source
