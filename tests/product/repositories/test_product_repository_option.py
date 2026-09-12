"""ProductRepository 的 ExperienceOption 查询与写入契约测试。"""

from decimal import Decimal

import pytest
from tortoise.transactions import in_transaction

from app.common.enums.product import DayType, ProductType
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
from app.repositories.product_repo import ProductRepository


async def _create_product(name: str) -> Product:
    """创建 Experience Product 测试数据。"""

    return await Product.create(
        name=name,
        product_type=ProductType.EXPERIENCE,
    )


async def _create_option(
    product: Product,
    *,
    duration: int = 60,
    participants: int = 1,
    day_type: DayType = DayType.WEEKDAY,
    price: Decimal = Decimal("299.00"),
    is_deleted: bool = False,
) -> ExperienceOption:
    """直接创建 ExperienceOption 测试数据。"""

    return await ExperienceOption.create(
        product=product,
        duration=duration,
        participants=participants,
        day_type=day_type,
        price=price,
        is_deleted=is_deleted,
    )


async def test_get_option_by_id_excludes_deleted_unless_explicitly_included(
) -> None:
    """普通 ID 查询隐藏已删除 Option，历史查询可显式包含。"""

    product = await _create_product("查询体验")
    active = await _create_option(product, duration=60)
    deleted = await _create_option(product, duration=120, is_deleted=True)
    repository = ProductRepository()

    assert await repository.get_option_by_id(active.id) == active
    assert await repository.get_option_by_id(deleted.id) is None
    assert (
        await repository.get_option_by_id(deleted.id, include_deleted=True)
        == deleted
    )


async def test_get_option_by_combination_reads_history_and_scopes_product(
) -> None:
    """组合查询始终包含删除历史，并严格限制在指定 Product 内。"""

    first_product = await _create_product("第一体验")
    second_product = await _create_product("第二体验")
    deleted_history = await _create_option(
        first_product,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        is_deleted=True,
    )
    other_product_option = await _create_option(
        second_product,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
    )
    repository = ProductRepository()

    assert (
        await repository.get_option_by_combination(
            product_id=first_product.id,
            duration=120,
            participants=2,
            day_type=DayType.HOLIDAY,
        )
        == deleted_history
    )
    assert (
        await repository.get_option_by_combination(
            product_id=second_product.id,
            duration=120,
            participants=2,
            day_type=DayType.HOLIDAY,
        )
        == other_product_option
    )
    assert (
        await repository.get_option_by_combination(
            product_id=first_product.id,
            duration=120,
            participants=3,
            day_type=DayType.HOLIDAY,
        )
        is None
    )


async def test_get_option_detail_preloads_product_and_active_images() -> None:
    """Option 详情为写响应预加载所属 Product 与有效图片。"""

    product = await _create_product("Option 详情体验")
    option = await _create_option(product)
    active = await ProductImage.create(
        product=product,
        experience_option=option,
        image_url="https://example.com/active.jpg",
        sort=20,
    )
    first = await ProductImage.create(
        product=product,
        experience_option=option,
        image_url="https://example.com/first.jpg",
        sort=10,
    )
    await ProductImage.create(
        product=product,
        experience_option=option,
        image_url="https://example.com/deleted.jpg",
        is_deleted=True,
    )

    loaded = await ProductRepository().get_option_detail(option.id)

    assert loaded is not None
    assert loaded.product.id == product.id
    assert [image.id for image in loaded.images] == [first.id, active.id]


async def test_get_option_detail_uses_supplied_transaction_connection() -> None:
    """Option 响应聚合查询可加入 Service 当前事务。"""

    product = await _create_product("Option 事务详情")
    option = await _create_option(product)

    async with in_transaction() as connection:
        loaded = await ProductRepository().get_option_detail(
            option.id,
            using_db=connection,
        )

    assert loaded is not None
    assert loaded.id == option.id
    assert loaded.product.id == product.id


async def test_create_option_persists_and_returns_complete_model() -> None:
    """创建方法保存完整配置并返回带主键的 ExperienceOption。"""

    product = await _create_product("创建体验")

    created = await ProductRepository().create_option(
        product=product,
        duration=180,
        participants=3,
        day_type=DayType.HOLIDAY,
        price=Decimal("899.00"),
    )

    assert created.id is not None
    assert created.product_id == product.id
    assert created.duration == 180
    assert created.participants == 3
    assert created.day_type == DayType.HOLIDAY
    assert created.price == Decimal("899.00")
    assert created.is_deleted is False
    assert await ExperienceOption.get(id=created.id) == created


async def test_update_option_changes_only_requested_fields_and_keeps_images(
) -> None:
    """恢复式更新保留 ID、组合字段和图片外键，只修改指定字段。"""

    product = await _create_product("恢复体验")
    option = await _create_option(
        product,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("699.00"),
        is_deleted=True,
    )
    image = await ProductImage.create(
        product=product,
        experience_option=option,
        image_url="https://example.com/restored-option.jpg",
    )

    updated = await ProductRepository().update_option(
        option,
        price=Decimal("799.00"),
        is_deleted=False,
    )

    assert updated is option
    assert updated.id == option.id
    assert updated.duration == 120
    assert updated.participants == 2
    assert updated.day_type == DayType.HOLIDAY
    assert updated.price == Decimal("799.00")
    assert updated.is_deleted is False

    stored = await ExperienceOption.get(id=option.id)
    stored_image = await ProductImage.get(id=image.id)
    assert stored.price == Decimal("799.00")
    assert stored.is_deleted is False
    assert stored_image.experience_option_id == option.id


async def test_create_option_uses_supplied_transaction_connection() -> None:
    """创建写入必须加入 Service 提供的事务并随异常回滚。"""

    product = await _create_product("创建事务体验")
    created_id: int | None = None

    with pytest.raises(RuntimeError, match="rollback create"):
        async with in_transaction() as connection:
            created = await ProductRepository().create_option(
                product=product,
                duration=60,
                participants=1,
                day_type=DayType.WEEKDAY,
                price=Decimal("299.00"),
                using_db=connection,
            )
            created_id = created.id
            raise RuntimeError("rollback create")

    assert created_id is not None
    assert not await ExperienceOption.filter(id=created_id).exists()


async def test_update_option_uses_supplied_transaction_connection() -> None:
    """更新写入必须加入 Service 提供的事务并随异常回滚。"""

    product = await _create_product("更新事务体验")
    option = await _create_option(product, price=Decimal("299.00"))

    with pytest.raises(RuntimeError, match="rollback update"):
        async with in_transaction() as connection:
            await ProductRepository().update_option(
                option,
                price=Decimal("399.00"),
                using_db=connection,
            )
            raise RuntimeError("rollback update")

    stored = await ExperienceOption.get(id=option.id)
    assert stored.price == Decimal("299.00")
