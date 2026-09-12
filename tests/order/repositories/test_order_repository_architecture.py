"""Order Repository 与订单号组件的分层架构契约测试。"""

import ast
import inspect
from pathlib import Path

from app.repositories.order_repo import OrderRepository


def _import_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_order_repository_has_no_business_or_transport_dependencies() -> None:
    """Repository 只能依赖 ORM、Model 与公共类型，不反向依赖上层。"""

    path = Path("app/repositories/order_repo.py")
    source = path.read_text(encoding="utf-8")
    imports = _import_modules(path)

    forbidden_prefixes = (
        "fastapi",
        "app.api",
        "app.services",
        "app.validators",
        "app.common.exceptions",
        "app.core.redis",
    )
    assert not any(
        module.startswith(forbidden_prefixes) for module in imports
    )
    assert "in_transaction" not in source
    assert "ProductKit" not in source
    assert "raise " not in source


def test_order_repository_public_methods_are_async_and_typed() -> None:
    """公开数据访问接口应保持异步并提供完整返回类型。"""

    public_methods = [
        member
        for name, member in inspect.getmembers(
            OrderRepository,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    ]

    assert public_methods
    for method in public_methods:
        assert inspect.iscoroutinefunction(method)
        assert inspect.signature(method).return_annotation is not inspect.Signature.empty


def test_order_status_lock_method_keeps_select_for_update() -> None:
    """MySQL 状态变迁必须保留悲观行锁，不能退化为普通读取。"""

    source = inspect.getsource(OrderRepository.get_order_for_update)

    assert ".select_for_update()" in source
    assert "using_db" in source


def test_order_number_generator_uses_only_standard_library_and_common_constants(
) -> None:
    """编号组件不得引入 Redis、数据库、第三方 ULID 或全局可变状态。"""

    path = Path("app/common/order_number.py")
    source = path.read_text(encoding="utf-8")
    imports = _import_modules(path)

    assert imports == {"secrets", "time", "app.common.constants.order"}
    assert "redis" not in source.lower()
    assert "tortoise" not in source.lower()
