"""ProductRepository 的 Product 主表写入契约测试。"""

import pytest
from tortoise.transactions import in_transaction

from app.common.enums.product import ProductStatus, ProductType
from app.models.product import Product
from app.repositories.product_repo import ProductRepository


async def test_create_product_persists_draft_with_model_defaults() -> None:
    """创建方法只接收业务输入，状态与逻辑删除使用 Model 默认值。"""

    created = await ProductRepository().create_product(
        name="零基础拼豆体验",
        product_type=ProductType.EXPERIENCE,
        description="适合第一次体验拼豆的顾客",
    )

    assert created.id is not None
    assert created.name == "零基础拼豆体验"
    assert created.product_type is ProductType.EXPERIENCE
    assert created.description == "适合第一次体验拼豆的顾客"
    assert created.status is ProductStatus.DRAFT
    assert created.is_deleted is False

    stored = await Product.get(id=created.id)
    assert stored.name == created.name
    assert stored.product_type is ProductType.EXPERIENCE
    assert stored.description == created.description
    assert stored.status is ProductStatus.DRAFT
    assert stored.is_deleted is False


async def test_update_product_only_changes_supplied_fields() -> None:
    """部分更新保留未提交字段，并持久化状态与逻辑删除变更。"""

    product = await Product.create(
        name="原商品名称",
        product_type=ProductType.KIT,
        description="原商品描述",
    )
    previous_updated_at = product.updated_at
    repository = ProductRepository()

    updated = await repository.update_product(
        product,
        name="新商品名称",
        status=ProductStatus.OFFLINE,
        is_deleted=True,
    )

    assert updated is product
    assert updated.name == "新商品名称"
    assert updated.product_type is ProductType.KIT
    assert updated.description == "原商品描述"
    assert updated.status is ProductStatus.OFFLINE
    assert updated.is_deleted is True
    assert updated.updated_at > previous_updated_at

    stored = await Product.get(id=product.id)
    assert stored.name == "新商品名称"
    assert stored.product_type is ProductType.KIT
    assert stored.description == "原商品描述"
    assert stored.status is ProductStatus.OFFLINE
    assert stored.is_deleted is True


async def test_create_product_joins_caller_transaction() -> None:
    """创建 Product 必须使用 Service 传入的事务连接并随事务回滚。"""

    created_id: int | None = None

    with pytest.raises(RuntimeError, match="rollback product create"):
        async with in_transaction() as connection:
            created = await ProductRepository().create_product(
                name="事务内创建商品",
                product_type=ProductType.EXPERIENCE,
                using_db=connection,
            )
            created_id = created.id
            raise RuntimeError("rollback product create")

    assert created_id is not None
    assert not await Product.filter(id=created_id).exists()


async def test_update_product_joins_caller_transaction() -> None:
    """更新 Product 必须使用 Service 传入的事务连接并随事务回滚。"""

    product = await Product.create(
        name="事务更新前",
        product_type=ProductType.EXPERIENCE,
        description="应保留的描述",
    )

    with pytest.raises(RuntimeError, match="rollback product update"):
        async with in_transaction() as connection:
            await ProductRepository().update_product(
                product,
                name="事务更新后",
                is_deleted=True,
                using_db=connection,
            )
            raise RuntimeError("rollback product update")

    stored = await Product.get(id=product.id)
    assert stored.name == "事务更新前"
    assert stored.description == "应保留的描述"
    assert stored.is_deleted is False
