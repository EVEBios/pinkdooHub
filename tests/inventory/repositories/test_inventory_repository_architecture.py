"""InventoryRepository 分层、行锁与批量边界契约测试。"""

import ast
import inspect
from pathlib import Path

from app.repositories.inventory_repo import InventoryRepository


def _import_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_inventory_repository_has_no_business_or_transport_dependencies() -> None:
    """Repository 只能依赖 ORM、Model 与 common 类型，不能反向依赖上层。"""

    path = Path("app/repositories/inventory_repo.py")
    source = path.read_text(encoding="utf-8")
    imports = _import_modules(path)
    forbidden_prefixes = (
        "fastapi",
        "app.api",
        "app.services",
        "app.validators",
        "app.schemas",
        "app.common.exceptions",
        "app.core.redis",
    )

    assert not any(
        module.startswith(forbidden_prefixes) for module in imports
    )
    assert "in_transaction" not in source
    assert "raise " not in source


def test_inventory_repository_public_methods_are_async_and_typed() -> None:
    """公开数据访问接口必须异步并提供返回类型。"""

    public_methods = [
        member
        for name, member in inspect.getmembers(
            InventoryRepository,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    ]

    assert public_methods
    for method in public_methods:
        assert inspect.iscoroutinefunction(method)
        assert inspect.signature(method).return_annotation is not inspect.Signature.empty


def test_inventory_lock_methods_keep_transaction_and_stable_order() -> None:
    """单 Kit 与多 Kit 锁都必须保留悲观锁，多 Kit 明确按 Product ID 排序。"""

    single_source = inspect.getsource(InventoryRepository.get_kit_for_update)
    multi_source = inspect.getsource(InventoryRepository.get_kits_for_update)

    assert ".select_for_update()" in single_source
    assert ".using_db(using_db)" in single_source
    assert ".select_for_update()" in multi_source
    assert ".using_db(using_db)" in multi_source
    assert "sorted(product_ids)" in multi_source
    assert '.order_by("product_id")' in multi_source


def test_inventory_automatic_writes_are_bulk_and_not_awaited_in_a_loop() -> None:
    """多 Kit 自动流水必须一次批量写入，不能退化为循环单条 INSERT。"""

    source = inspect.getsource(InventoryRepository.bulk_create_transactions)
    stock_source = inspect.getsource(InventoryRepository.bulk_update_stocks)

    assert "InventoryTransaction.bulk_create" in source
    assert "await InventoryTransaction.create" not in source
    assert "for data in transactions" in source
    assert "ProductKit.bulk_update" in stock_source
    assert "await update.kit.save" not in stock_source


def test_inventory_restore_identities_are_loaded_as_one_set_query() -> None:
    """取消恢复幂等检查不得退化为逐 Product 查询。"""

    source = inspect.getsource(
        InventoryRepository.get_transactions_by_idempotency_keys
    )

    assert "idempotency_key__in=idempotency_keys" in source
    assert ".using_db(using_db)" in source
    assert "if not idempotency_keys" in source
    assert "for " not in source


def test_inventory_pagination_preloads_operator_and_batches_order_sources() -> None:
    """分页 Repository 必须准备 Mapper 所需元数据且不产生 N+1。"""

    list_source = inspect.getsource(InventoryRepository.list_transactions)
    hydration_source = inspect.getsource(
        InventoryRepository._attach_source_order_numbers
    )

    assert '.select_related("operator")' in list_source
    assert "Order.filter(id__in=source_ids)" in hydration_source
    assert ".values_list(" in hydration_source
    assert "await" not in hydration_source.split("for transaction in transactions:")[1]
