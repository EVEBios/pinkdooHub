"""用户端 Product API —— 已上架商品列表与分类详情。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_product_service
from app.api.mappers.product import (
    map_experience_product_detail,
    map_kit_product_detail,
    map_product_page,
)
from app.api.responses import error_responses, success_responses
from app.common.enums.product import ProductType
from app.common.pagination import Page
from app.common.response import success
from app.schemas.product import ProductListQuery
from app.schemas.product_response import (
    ExperienceProductDetailOut,
    KitProductDetailOut,
    ProductListItemOut,
)
from app.services.product_service import ProductService

router = APIRouter(
    prefix="/products",
    tags=["products"],
    responses=error_responses(404, 422),
)
ProductId = Annotated[int, Path(gt=0)]


@router.get(
    "",
    response_model=None,
    responses=success_responses(Page[ProductListItemOut]),
)
async def list_products(
    query: Annotated[ProductListQuery, Query()],
    service: Annotated[ProductService, Depends(get_product_service)],
) -> dict:
    """分页查询用户可见的已上架商品。"""

    page = await service.list_online_products(
        page=query.page,
        page_size=query.page_size,
        product_type=query.product_type,
        keyword=query.keyword,
    )
    return success(data=map_product_page(page).model_dump(mode="json"))


@router.get(
    "/experience/{product_id}",
    response_model=None,
    responses=success_responses(ExperienceProductDetailOut),
)
async def get_experience_product(
    product_id: ProductId,
    service: Annotated[ProductService, Depends(get_product_service)],
) -> dict:
    """查询用户端已上架 Experience 详情。"""

    product = await service.get_online_product_detail(
        product_id,
        product_type=ProductType.EXPERIENCE,
    )
    return success(
        data=map_experience_product_detail(product).model_dump(mode="json")
    )


@router.get(
    "/kit/{product_id}",
    response_model=None,
    responses=success_responses(KitProductDetailOut),
)
async def get_kit_product(
    product_id: ProductId,
    service: Annotated[ProductService, Depends(get_product_service)],
) -> dict:
    """查询用户端已上架 Kit 详情。"""

    product = await service.get_online_product_detail(
        product_id,
        product_type=ProductType.KIT,
    )
    return success(data=map_kit_product_detail(product).model_dump(mode="json"))
