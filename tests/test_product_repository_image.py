"""ProductRepository 的 ProductImage 查询与写入契约测试。"""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from pytest import MonkeyPatch
from tortoise import connections
from tortoise.transactions import in_transaction

from app.common.enums.product import DayType, ProductType
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
from app.repositories.product_repo import ProductRepository


async def _create_product(name: str) -> Product:
    """创建 Product 测试数据。"""

    return await Product.create(
        name=name,
        product_type=ProductType.EXPERIENCE,
    )


async def _create_option(product: Product) -> ExperienceOption:
    """创建 ExperienceOption 测试数据。"""

    return await ExperienceOption.create(
        product=product,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("299.00"),
    )


async def _create_image(
    product: Product,
    *,
    image_url: str,
    experience_option: ExperienceOption | None = None,
    is_cover: bool = False,
    sort: int = 0,
    is_deleted: bool = False,
) -> ProductImage:
    """直接创建 ProductImage 测试数据。"""

    return await ProductImage.create(
        product=product,
        experience_option=experience_option,
        image_url=image_url,
        is_cover=is_cover,
        sort=sort,
        is_deleted=is_deleted,
    )


async def test_get_image_by_id_excludes_deleted_unless_explicitly_included(
) -> None:
    """普通 ID 查询隐藏已删除 Image，历史查询可显式包含。"""

    product = await _create_product("图片查询商品")
    active = await _create_image(
        product,
        image_url="https://example.com/active.jpg",
    )
    deleted = await _create_image(
        product,
        image_url="https://example.com/deleted.jpg",
        is_deleted=True,
    )
    repository = ProductRepository()

    assert await repository.get_image_by_id(active.id) == active
    assert await repository.get_image_by_id(deleted.id) is None
    assert (
        await repository.get_image_by_id(deleted.id, include_deleted=True)
        == deleted
    )


async def test_create_image_supports_public_and_option_ownership() -> None:
    """创建方法正确保存公共图和 Option 专属图的归属与默认值。"""

    product = await _create_product("图片创建商品")
    option = await _create_option(product)
    repository = ProductRepository()

    public_image = await repository.create_image(
        product=product,
        image_url="https://example.com/public.jpg",
        is_cover=True,
    )
    option_image = await repository.create_image(
        product=product,
        experience_option=option,
        image_url="https://example.com/option.jpg",
        sort=10,
    )

    assert public_image.product_id == product.id
    assert public_image.experience_option_id is None
    assert public_image.is_cover is True
    assert public_image.sort == 0
    assert public_image.is_deleted is False

    assert option_image.product_id == product.id
    assert option_image.experience_option_id == option.id
    assert option_image.is_cover is False
    assert option_image.sort == 10
    assert option_image.is_deleted is False


async def test_update_image_changes_only_requested_fields() -> None:
    """图片部分更新保留归属和 URL，并支持排序与逻辑删除。"""

    product = await _create_product("图片更新商品")
    option = await _create_option(product)
    image = await _create_image(
        product,
        experience_option=option,
        image_url="https://example.com/original.jpg",
        sort=0,
    )
    previous_updated_at = image.updated_at
    repository = ProductRepository()

    updated = await repository.update_image(image, sort=20)

    assert updated is image
    assert updated.product_id == product.id
    assert updated.experience_option_id == option.id
    assert updated.image_url == "https://example.com/original.jpg"
    assert updated.is_cover is False
    assert updated.sort == 20
    assert updated.is_deleted is False
    assert updated.updated_at > previous_updated_at

    deleted = await repository.update_image(image, is_deleted=True)
    stored = await ProductImage.get(id=image.id)
    assert deleted.is_deleted is True
    assert stored.sort == 20
    assert stored.is_deleted is True


async def test_clear_product_covers_is_scoped_and_uses_one_update(
    monkeypatch: MonkeyPatch,
) -> None:
    """批量清理只影响同 Product 的有效公共旧封面，并执行一条 UPDATE。"""

    product = await _create_product("封面清理商品")
    other_product = await _create_product("其他商品")
    option = await _create_option(product)
    first_old_cover = await _create_image(
        product,
        image_url="https://example.com/old-1.jpg",
        is_cover=True,
    )
    second_old_cover = await _create_image(
        product,
        image_url="https://example.com/old-2.jpg",
        is_cover=True,
    )
    new_cover = await _create_image(
        product,
        image_url="https://example.com/new.jpg",
        is_cover=True,
    )
    deleted_cover = await _create_image(
        product,
        image_url="https://example.com/deleted-cover.jpg",
        is_cover=True,
        is_deleted=True,
    )
    option_cover = await _create_image(
        product,
        experience_option=option,
        image_url="https://example.com/invalid-option-cover.jpg",
        is_cover=True,
    )
    other_product_cover = await _create_image(
        other_product,
        image_url="https://example.com/other-cover.jpg",
        is_cover=True,
    )
    previous_updated_at = first_old_cover.updated_at

    connection = connections.get("default")
    original_execute_query: Callable[..., Awaitable[Any]] = (
        connection.execute_query
    )
    update_queries: list[str] = []

    async def capture_query(query: str, values: list[Any] | None = None) -> Any:
        if query.lstrip().upper().startswith("UPDATE"):
            update_queries.append(query)
        return await original_execute_query(query, values)

    monkeypatch.setattr(connection, "execute_query", capture_query)

    cleared = await ProductRepository().clear_product_covers(
        product.id,
        exclude_image_id=new_cover.id,
    )

    stored_first = await ProductImage.get(id=first_old_cover.id)
    stored_second = await ProductImage.get(id=second_old_cover.id)
    stored_new = await ProductImage.get(id=new_cover.id)
    stored_deleted = await ProductImage.get(id=deleted_cover.id)
    stored_option = await ProductImage.get(id=option_cover.id)
    stored_other = await ProductImage.get(id=other_product_cover.id)

    assert cleared == 2
    assert stored_first.is_cover is False
    assert stored_second.is_cover is False
    assert stored_first.updated_at > previous_updated_at
    assert stored_new.is_cover is True
    assert stored_deleted.is_cover is True
    assert stored_option.is_cover is True
    assert stored_other.is_cover is True
    assert len(update_queries) == 1


async def test_create_image_uses_supplied_transaction_connection() -> None:
    """图片创建必须加入 Service 提供的事务并随异常回滚。"""

    product = await _create_product("图片创建事务商品")
    created_id: int | None = None

    with pytest.raises(RuntimeError, match="rollback image create"):
        async with in_transaction() as connection:
            created = await ProductRepository().create_image(
                product=product,
                image_url="https://example.com/transaction-create.jpg",
                using_db=connection,
            )
            created_id = created.id
            raise RuntimeError("rollback image create")

    assert created_id is not None
    assert not await ProductImage.filter(id=created_id).exists()


async def test_update_image_uses_supplied_transaction_connection() -> None:
    """图片更新必须加入 Service 提供的事务并随异常回滚。"""

    product = await _create_product("图片更新事务商品")
    image = await _create_image(
        product,
        image_url="https://example.com/transaction-update.jpg",
        sort=0,
    )

    with pytest.raises(RuntimeError, match="rollback image update"):
        async with in_transaction() as connection:
            await ProductRepository().update_image(
                image,
                sort=30,
                is_deleted=True,
                using_db=connection,
            )
            raise RuntimeError("rollback image update")

    stored = await ProductImage.get(id=image.id)
    assert stored.sort == 0
    assert stored.is_deleted is False


async def test_clear_product_covers_uses_supplied_transaction_connection(
) -> None:
    """批量清封面必须加入 Service 提供的事务并随异常回滚。"""

    product = await _create_product("封面事务商品")
    first_cover = await _create_image(
        product,
        image_url="https://example.com/transaction-cover-1.jpg",
        is_cover=True,
    )
    second_cover = await _create_image(
        product,
        image_url="https://example.com/transaction-cover-2.jpg",
        is_cover=True,
    )

    with pytest.raises(RuntimeError, match="rollback clear covers"):
        async with in_transaction() as connection:
            cleared = await ProductRepository().clear_product_covers(
                product.id,
                using_db=connection,
            )
            assert cleared == 2
            raise RuntimeError("rollback clear covers")

    stored_first = await ProductImage.get(id=first_cover.id)
    stored_second = await ProductImage.get(id=second_cover.id)
    assert stored_first.is_cover is True
    assert stored_second.is_cover is True
