"""ProductService 分层和依赖方向契约测试。"""

import ast
import inspect
from pathlib import Path

from app.services.product_service import ProductService


def test_online_product_is_async_orchestration() -> None:
    assert inspect.iscoroutinefunction(ProductService.online_product)


def test_update_and_delete_are_async_orchestrations() -> None:
    assert inspect.iscoroutinefunction(ProductService.update_product)
    assert inspect.iscoroutinefunction(ProductService.delete_product)


def test_create_experience_option_is_async_orchestration() -> None:
    assert inspect.iscoroutinefunction(ProductService.create_experience_option)


def test_update_experience_option_is_async_orchestration() -> None:
    assert inspect.iscoroutinefunction(ProductService.update_experience_option)


def test_delete_experience_option_is_async_orchestration() -> None:
    assert inspect.iscoroutinefunction(ProductService.delete_experience_option)


def test_kit_mutations_are_async_orchestration() -> None:
    assert inspect.iscoroutinefunction(ProductService.update_kit_price)
    assert inspect.iscoroutinefunction(ProductService.update_kit_stock)


def test_product_service_has_no_transport_schema_or_redis_dependency() -> None:
    source_path = Path(inspect.getsourcefile(ProductService) or "")
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


def test_product_service_does_not_persist_models_directly() -> None:
    source = inspect.getsource(ProductService)
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
            "update_from_dict",
        }
    )
