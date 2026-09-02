"""ProductRepository 的 ProductKit 查询与写入契约测试。"""

from decimal import Decimal

import pytest
from tortoise.transactions import in_transaction

from app.common.enums.product import ProductType
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.repositories.product_repo import ProductRepository


async def _create_product(
    name: str,
    *,
    product_type: ProductType = ProductType.KIT,
) -> Product:
    """创建 Product 测试数据。"""

    return await Product.create(name=name, product_type=product_type)


async def _create_kit(
    product: Product,
    *,
    price: Decimal = Decimal("599.00"),
    stock: int = 20,
) -> ProductKit:
    """直接创建 ProductKit 测试数据。"""

    return await ProductKit.create(
        product=product,
        price=price,
        stock=stock,
    )


async def test_get_kit_by_product_id_returns_extension_or_none() -> None:
    """按 Product ID 返回一对一 Kit，不存在扩展记录时返回 None。"""

    kit_product = await _create_product("新手套装")
    experience_product = await _create_product(
        "线下体验",
        product_type=ProductType.EXPERIENCE,
    )
    kit = await _create_kit(kit_product)
    repository = ProductRepository()

    assert await repository.get_kit_by_product_id(kit_product.id) == kit
    assert await repository.get_kit_by_product_id(experience_product.id) is None


async def test_create_kit_uses_zero_stock_default() -> None:
    """未提供初始库存时，Repository 与 Model/API 统一使用 0。"""

    product = await _create_product("零库存套装")

    created = await ProductRepository().create_kit(
        product=product,
        price=Decimal("399.00"),
    )

    assert created.id is not None
    assert created.product_id == product.id
    assert created.price == Decimal("399.00")
    assert created.stock == 0
    assert await ProductKit.get(id=created.id) == created


async def test_create_kit_persists_explicit_stock() -> None:
    """创建方法保存管理员显式提供的初始最终库存值。"""

    product = await _create_product("现货套装")

    created = await ProductRepository().create_kit(
        product=product,
        price=Decimal("599.00"),
        stock=25,
    )

    assert created.price == Decimal("599.00")
    assert created.stock == 25


async def test_update_kit_price_preserves_stock_and_refreshes_timestamp() -> None:
    """价格部分更新不覆盖库存，并刷新 updated_at。"""

    product = await _create_product("价格更新套装")
    kit = await _create_kit(product, price=Decimal("599.00"), stock=20)
    previous_updated_at = kit.updated_at

    updated = await ProductRepository().update_kit(
        kit,
        price=Decimal("699.00"),
    )

    assert updated is kit
    assert updated.price == Decimal("699.00")
    assert updated.stock == 20
    assert updated.updated_at > previous_updated_at

    stored = await ProductKit.get(id=kit.id)
    assert stored.price == Decimal("699.00")
    assert stored.stock == 20


async def test_update_kit_stock_preserves_price() -> None:
    """库存最终值部分更新不覆盖售价。"""

    product = await _create_product("库存更新套装")
    kit = await _create_kit(product, price=Decimal("599.00"), stock=20)

    updated = await ProductRepository().update_kit(kit, stock=35)

    assert updated.price == Decimal("599.00")
    assert updated.stock == 35

    stored = await ProductKit.get(id=kit.id)
    assert stored.price == Decimal("599.00")
    assert stored.stock == 35


async def test_create_kit_uses_supplied_transaction_connection() -> None:
    """Kit 创建必须加入 Service 提供的事务并随异常回滚。"""

    product = await _create_product("创建事务套装")
    created_id: int | None = None

    with pytest.raises(RuntimeError, match="rollback kit create"):
        async with in_transaction() as connection:
            created = await ProductRepository().create_kit(
                product=product,
                price=Decimal("599.00"),
                stock=10,
                using_db=connection,
            )
            created_id = created.id
            raise RuntimeError("rollback kit create")

    assert created_id is not None
    assert not await ProductKit.filter(id=created_id).exists()


async def test_update_kit_uses_supplied_transaction_connection() -> None:
    """Kit 更新必须加入 Service 提供的事务并随异常回滚。"""

    product = await _create_product("更新事务套装")
    kit = await _create_kit(product, price=Decimal("599.00"), stock=20)

    with pytest.raises(RuntimeError, match="rollback kit update"):
        async with in_transaction() as connection:
            await ProductRepository().update_kit(
                kit,
                price=Decimal("799.00"),
                stock=50,
                using_db=connection,
            )
            raise RuntimeError("rollback kit update")

    stored = await ProductKit.get(id=kit.id)
    assert stored.price == Decimal("599.00")
    assert stored.stock == 20
