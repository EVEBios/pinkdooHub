"""ProductService 管理端与用户端查询契约测试。"""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.common.enums.product import ProductStatus, ProductType
from app.common.exceptions import ProductNotFound
from app.common.pagination import Page
from app.models.product import Product
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService


def _service(repository: ProductRepository) -> ProductService:
    return ProductService(
        repository,
        AuditLogService(AuditLogRepository()),
    )


async def test_admin_list_forwards_filters_without_description_search() -> None:
    repository = AsyncMock(spec=ProductRepository)
    expected = Page[Product](
        items=[],
        total=0,
        page=2,
        page_size=10,
        pages=0,
    )
    repository.list_products.return_value = expected
    service = _service(repository)

    result = await service.list_admin_products(
        page=2,
        page_size=10,
        product_type=ProductType.KIT,
        status=ProductStatus.OFFLINE,
        keyword="套装",
        include_deleted=True,
    )

    assert result is expected
    repository.list_products.assert_awaited_once_with(
        page=2,
        page_size=10,
        product_type=ProductType.KIT,
        status=ProductStatus.OFFLINE,
        keyword="套装",
        include_deleted=True,
        search_description=False,
    )


async def test_user_list_forces_online_visibility_and_description_search(
) -> None:
    repository = AsyncMock(spec=ProductRepository)
    expected = Page[Product](
        items=[],
        total=0,
        page=1,
        page_size=20,
        pages=0,
    )
    repository.list_products.return_value = expected
    service = _service(repository)

    result = await service.list_online_products(
        page=1,
        page_size=20,
        product_type=ProductType.EXPERIENCE,
        keyword="现场指导",
    )

    assert result is expected
    repository.list_products.assert_awaited_once_with(
        page=1,
        page_size=20,
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
        keyword="现场指导",
        include_deleted=False,
        search_description=True,
    )


@pytest.mark.parametrize(
    "actual_type,requested_type",
    [
        (ProductType.EXPERIENCE, ProductType.KIT),
        (ProductType.KIT, ProductType.EXPERIENCE),
    ],
)
async def test_admin_detail_hides_type_mismatch_as_not_found(
    actual_type: ProductType,
    requested_type: ProductType,
) -> None:
    product = Product(
        id=1,
        name="商品",
        product_type=actual_type,
        status=ProductStatus.DRAFT,
        is_deleted=True,
    )
    repository = AsyncMock(spec=ProductRepository)
    repository.get_product_detail.return_value = product
    service = _service(repository)

    with pytest.raises(ProductNotFound):
        await service.get_admin_product_detail(
            product.id,
            product_type=requested_type,
        )

    repository.get_product_detail.assert_awaited_once_with(
        product.id,
        include_deleted=True,
    )


async def test_admin_detail_returns_deleted_matching_product() -> None:
    product = Product(
        id=1,
        name="已删除套装",
        product_type=ProductType.KIT,
        status=ProductStatus.OFFLINE,
        is_deleted=True,
    )
    repository = AsyncMock(spec=ProductRepository)
    repository.get_product_detail.return_value = product

    result = await _service(repository).get_admin_product_detail(
        product.id,
        product_type=ProductType.KIT,
    )

    assert result is product


@pytest.mark.parametrize(
    "product",
    [
        None,
        Product(
            id=1,
            name="草稿",
            product_type=ProductType.KIT,
            status=ProductStatus.DRAFT,
            is_deleted=False,
        ),
        Product(
            id=2,
            name="已删除",
            product_type=ProductType.KIT,
            status=ProductStatus.ONLINE,
            is_deleted=True,
        ),
        Product(
            id=3,
            name="类型不同",
            product_type=ProductType.EXPERIENCE,
            status=ProductStatus.ONLINE,
            is_deleted=False,
        ),
    ],
)
async def test_user_detail_hides_all_non_public_cases(
    product: Product | None,
) -> None:
    repository = AsyncMock(spec=ProductRepository)
    repository.get_product_detail.return_value = product
    service = _service(repository)

    with pytest.raises(ProductNotFound):
        await service.get_online_product_detail(
            1,
            product_type=ProductType.KIT,
        )

    repository.get_product_detail.assert_awaited_once_with(
        1,
        include_deleted=False,
    )


async def _create_product(
    *,
    name: str,
    description: str,
    product_type: ProductType,
    status: ProductStatus,
    is_deleted: bool = False,
) -> Product:
    repository = ProductRepository()
    product = await repository.create_product(
        name=name,
        description=description,
        product_type=product_type,
    )
    if status is not ProductStatus.DRAFT or is_deleted:
        await repository.update_product(
            product,
            status=status,
            is_deleted=is_deleted,
        )
    if product_type is ProductType.KIT:
        await repository.create_kit(
            product=product,
            price=Decimal("99.00"),
            stock=5,
        )
    return product


async def test_real_user_list_only_returns_online_non_deleted_and_searches_description(
) -> None:
    online = await _create_product(
        name="体验 A",
        description="包含现场指导",
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
    )
    await _create_product(
        name="草稿 B",
        description="包含现场指导",
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.DRAFT,
    )
    await _create_product(
        name="删除 C",
        description="包含现场指导",
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
        is_deleted=True,
    )

    result = await _service(ProductRepository()).list_online_products(
        page=1,
        page_size=20,
        keyword="现场指导",
    )

    assert [item.id for item in result.items] == [online.id]
    assert result.total == 1


async def test_real_admin_detail_returns_preloaded_deleted_kit() -> None:
    product = await _create_product(
        name="历史套装",
        description="管理员可查看",
        product_type=ProductType.KIT,
        status=ProductStatus.OFFLINE,
        is_deleted=True,
    )

    result = await _service(ProductRepository()).get_admin_product_detail(
        product.id,
        product_type=ProductType.KIT,
    )

    assert result.id == product.id
    assert result.is_deleted is True
    assert result.kit.price == Decimal("99.00")


async def test_real_user_detail_returns_only_matching_online_product() -> None:
    product = await _create_product(
        name="在线套装",
        description="用户可查看",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )

    result = await _service(ProductRepository()).get_online_product_detail(
        product.id,
        product_type=ProductType.KIT,
    )

    assert result.id == product.id
    assert result.status is ProductStatus.ONLINE
    assert result.kit.stock == 5
