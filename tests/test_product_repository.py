"""ProductRepository 基础查询与分页契约测试。"""

from app.common.enums.product import ProductStatus, ProductType
from app.common.pagination import Page
from app.models.product import Product
from app.repositories.product_repo import ProductRepository


async def _create_product(
    name: str,
    *,
    product_type: ProductType = ProductType.EXPERIENCE,
    description: str | None = None,
    status: ProductStatus = ProductStatus.DRAFT,
    is_deleted: bool = False,
) -> Product:
    """创建最小 Product 测试数据。"""

    return await Product.create(
        name=name,
        product_type=product_type,
        description=description,
        status=status,
        is_deleted=is_deleted,
    )


async def test_page_supports_product_model_items() -> None:
    """Repository 分页容器必须保留 Product 类型，而非退化成 object。"""

    product = await _create_product("分页类型契约")

    result = Page[Product](
        items=[product],
        total=1,
        page=1,
        page_size=20,
        pages=1,
    )

    assert result.items == [product]


async def test_get_product_by_id_excludes_deleted_unless_explicitly_included(
) -> None:
    """普通查询隐藏逻辑删除记录，管理历史查询可显式包含。"""

    active = await _create_product("有效体验")
    deleted = await _create_product("已删除体验", is_deleted=True)
    repository = ProductRepository()

    assert await repository.get_product_by_id(active.id) == active
    assert await repository.get_product_by_id(deleted.id) is None
    assert (
        await repository.get_product_by_id(deleted.id, include_deleted=True)
        == deleted
    )


async def test_list_products_filters_type_status_and_deleted_scope() -> None:
    """列表组合筛选只返回符合范围的 Product。"""

    expected = await _create_product(
        "已上架体验",
        status=ProductStatus.ONLINE,
    )
    await _create_product(
        "草稿体验",
        status=ProductStatus.DRAFT,
    )
    await _create_product(
        "已上架套装",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    await _create_product(
        "已删除上架体验",
        status=ProductStatus.ONLINE,
        is_deleted=True,
    )
    repository = ProductRepository()

    result = await repository.list_products(
        page=1,
        page_size=20,
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
    )

    assert isinstance(result, Page)
    assert [product.id for product in result.items] == [expected.id]
    assert result.total == 1


async def test_list_products_controls_description_keyword_search() -> None:
    """同一查询可表达管理端名称搜索和用户端名称/描述搜索。"""

    name_match = await _create_product("夏日海浪拼豆")
    description_match = await _create_product(
        "清凉主题",
        description="可以制作夏日海浪图案",
    )
    await _create_product("森林主题", description="制作绿色植物图案")
    repository = ProductRepository()

    name_only = await repository.list_products(
        page=1,
        page_size=20,
        keyword="海浪",
    )
    name_or_description = await repository.list_products(
        page=1,
        page_size=20,
        keyword="海浪",
        search_description=True,
    )

    assert [product.id for product in name_only.items] == [name_match.id]
    assert {product.id for product in name_or_description.items} == {
        name_match.id,
        description_match.id,
    }


async def test_list_products_returns_page_metadata_and_stable_latest_first_order(
) -> None:
    """分页返回完整元数据，并以创建时间和 ID 确保稳定倒序。"""

    products = [
        await _create_product(f"商品 {number}") for number in range(1, 6)
    ]
    repository = ProductRepository()

    result = await repository.list_products(page=2, page_size=2)

    assert isinstance(result, Page)
    assert [product.id for product in result.items] == [
        products[2].id,
        products[1].id,
    ]
    assert result.total == 5
    assert result.page == 2
    assert result.page_size == 2
    assert result.pages == 3
