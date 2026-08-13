"""创建订单所需的 ProductRepository 批量读取契约测试。"""

from decimal import Decimal

from collections.abc import Awaitable, Callable
from typing import Any

from pytest import MonkeyPatch
from tortoise import connections
from tortoise.transactions import in_transaction

from app.common.enums.product import DayType, ProductType
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.repositories.product_repo import ProductRepository


async def _create_product_with_option(
    number: int,
    *,
    product_deleted: bool = False,
    option_deleted: bool = False,
) -> tuple[Product, ExperienceOption]:
    product = await Product.create(
        name=f"批量订单商品 {number}",
        product_type=ProductType.EXPERIENCE,
        is_deleted=product_deleted,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("299.00"),
        is_deleted=option_deleted,
    )
    return product, option


async def test_batch_loaders_return_requested_rows_in_stable_order(
    monkeypatch: MonkeyPatch,
) -> None:
    """批量读取不逐项查询，并保留逻辑删除记录供 Service 精确判定。"""

    active_product, active_option = await _create_product_with_option(1)
    deleted_product, deleted_option = await _create_product_with_option(
        2,
        product_deleted=True,
        option_deleted=True,
    )
    repository = ProductRepository()
    connection = connections.get("default")
    original_execute_query: Callable[..., Awaitable[Any]] = connection.execute_query
    select_queries: list[str] = []

    async def capture_query(query: str, values: list[Any] | None = None) -> Any:
        if query.lstrip().upper().startswith("SELECT"):
            select_queries.append(query)
        return await original_execute_query(query, values)

    monkeypatch.setattr(connection, "execute_query", capture_query)

    products = await repository.get_products_by_ids(
        {deleted_product.id, active_product.id, 99999}
    )
    options = await repository.get_options_by_ids(
        {deleted_option.id, active_option.id, 99999}
    )

    assert [product.id for product in products] == [
        active_product.id,
        deleted_product.id,
    ]
    assert [option.id for option in options] == [
        active_option.id,
        deleted_option.id,
    ]
    assert products[1].is_deleted is True
    assert options[1].is_deleted is True
    assert len(select_queries) == 2


async def test_empty_batch_loaders_execute_no_sql(monkeypatch: MonkeyPatch) -> None:
    """空 ID 集合直接返回，避免生成无意义 IN 查询。"""

    connection = connections.get("default")
    calls = 0
    original_execute_query = connection.execute_query

    async def capture_query(query: str, values: list[object] | None = None) -> object:
        nonlocal calls
        calls += 1
        return await original_execute_query(query, values)

    monkeypatch.setattr(connection, "execute_query", capture_query)
    repository = ProductRepository()

    assert await repository.get_products_by_ids(set()) == []
    assert await repository.get_options_by_ids(set()) == []
    assert calls == 0


async def test_batch_loaders_accept_caller_transaction_connection() -> None:
    """创建事务中的商品与 Option 读取可使用同一连接。"""

    product, option = await _create_product_with_option(1)
    repository = ProductRepository()

    async with in_transaction() as connection:
        products = await repository.get_products_by_ids(
            {product.id},
            using_db=connection,
        )
        options = await repository.get_options_by_ids(
            {option.id},
            using_db=connection,
        )

    assert products == [product]
    assert options == [option]
