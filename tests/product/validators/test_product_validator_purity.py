"""ProductValidator 纯度与真实聚合集成边界测试。"""

import ast
import inspect
from decimal import Decimal
from pathlib import Path

import pytest
from tortoise import connections
from tortoise.exceptions import NoValuesFetched

from app.common.enums.product import DayType, ProductType
from app.common.exceptions import ProductNotReadyForOnline
from app.repositories.product_repo import ProductRepository
from app.validators.product_validator import ProductValidator


async def _create_experience_aggregate(
    *,
    with_option_image: bool = True,
) -> tuple[ProductRepository, int]:
    """通过 Repository 创建可由详情查询完整预加载的 Experience 聚合。"""

    repository = ProductRepository()
    product = await repository.create_product(
        name="零基础拼豆体验",
        product_type=ProductType.EXPERIENCE,
        description="包含材料与现场指导",
    )
    await repository.create_image(
        product=product,
        image_url="https://example.com/product-cover.png",
        is_cover=True,
    )
    option = await repository.create_option(
        product=product,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("39.00"),
    )
    if with_option_image:
        await repository.create_image(
            product=product,
            experience_option=option,
            image_url="https://example.com/option.png",
        )
    return repository, product.id


def _aggregate_snapshot(product: object) -> tuple[object, ...]:
    """记录 Validator 可见字段，确认校验前后聚合没有被修改。"""

    options = list(product.experience_options)
    return (
        product.name,
        product.description,
        product.product_type,
        product.status,
        product.is_deleted,
        tuple(
            (image.id, image.image_url, image.is_cover, image.sort)
            for image in product.images
        ),
        tuple(
            (
                option.id,
                option.price,
                option.is_deleted,
                tuple(
                    (image.id, image.image_url, image.is_cover, image.sort)
                    for image in option.images
                ),
            )
            for option in options
        ),
    )


def test_validator_is_sync_and_has_no_data_access_imports() -> None:
    """Validator 保持同步，且源码不依赖 Repository、Service 或 Redis。"""

    assert not inspect.iscoroutinefunction(
        ProductValidator.validate_before_online,
    )

    source_path = Path(inspect.getsourcefile(ProductValidator) or "")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert not any(
        forbidden in imported
        for imported in imports
        for forbidden in ("repositories", "services", "redis")
    )


@pytest.mark.asyncio
async def test_repository_loaded_aggregate_validates_without_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, product_id = await _create_experience_aggregate()
    product = await repository.get_product_detail(
        product_id,
        include_deleted=True,
    )
    assert product is not None

    connection = connections.get("default")

    def fail_on_query(*args: object, **kwargs: object) -> None:
        raise AssertionError("Validator must not execute SQL")

    monkeypatch.setattr(connection, "execute_query", fail_on_query)

    assert ProductValidator.validate_before_online(product) is None


@pytest.mark.asyncio
async def test_validation_does_not_mutate_repository_loaded_aggregate() -> None:
    repository, product_id = await _create_experience_aggregate()
    product = await repository.get_product_detail(
        product_id,
        include_deleted=True,
    )
    assert product is not None
    before = _aggregate_snapshot(product)

    ProductValidator.validate_before_online(product)

    assert _aggregate_snapshot(product) == before


@pytest.mark.asyncio
async def test_same_loaded_aggregate_returns_same_ordered_issues() -> None:
    repository, product_id = await _create_experience_aggregate(
        with_option_image=False,
    )
    product = await repository.get_product_detail(
        product_id,
        include_deleted=True,
    )
    assert product is not None
    product.name = " "
    product.description = None
    product.experience_options[0].price = Decimal("0.00")
    before = _aggregate_snapshot(product)

    collected: list[list[str]] = []
    for _ in range(2):
        with pytest.raises(ProductNotReadyForOnline) as exc_info:
            ProductValidator.validate_before_online(product)
        assert exc_info.value.data is not None
        collected.append(exc_info.value.data["issues"])

    option_id = product.experience_options[0].id
    assert collected == [
        [
            "product name is required",
            "product description is required",
            f"option {option_id} price must be greater than 0",
            f"option {option_id} has no image",
        ],
        [
            "product name is required",
            "product description is required",
            f"option {option_id} price must be greater than 0",
            f"option {option_id} has no image",
        ],
    ]
    assert _aggregate_snapshot(product) == before


@pytest.mark.asyncio
async def test_unprefetched_relation_is_a_programming_error_not_business_error(
) -> None:
    repository, product_id = await _create_experience_aggregate()
    product = await repository.get_product_by_id(
        product_id,
        include_deleted=True,
    )
    assert product is not None

    with pytest.raises(NoValuesFetched):
        ProductValidator.validate_before_online(product)
