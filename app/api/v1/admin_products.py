"""管理端 Product API —— 查询与普通 JSON mutation。"""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Form,
    Path,
    Query,
    Request,
    Response,
    status,
)
from app.api.deps import (
    get_current_admin,
    get_product_image_storage,
    get_product_service,
)
from app.api.forms.product import OptionImageUploadForm, ProductImageUploadForm
from app.api.mappers.product import (
    map_admin_experience_product_detail,
    map_admin_kit_product_detail,
    map_admin_product_page,
    map_deleted_resource,
    map_experience_option,
    map_experience_option_base,
    map_experience_product_create,
    map_kit_price,
    map_kit_product_create,
    map_product_basic_info,
    map_product_image_by_owner,
    map_product_offline,
    map_product_online,
)
from app.api.mappers.audit import map_audit_log_page
from app.api.responses import error_responses, success_responses
from app.api.uploads import store_image_and_call
from app.common.enums.product import ProductType
from app.common.pagination import Page
from app.common.response import success
from app.models.user import User
from app.schemas.product import (
    AdminProductListQuery,
    ExperienceOptionCreate,
    ExperienceOptionUpdate,
    ExperienceProductCreate,
    KitPriceUpdate,
    KitProductCreate,
    ProductImageUpdate,
    ProductUpdate,
)
from app.schemas.audit import AuditLogListQuery
from app.schemas.audit import AuditLogOut
from app.schemas.product_response import (
    AdminExperienceProductDetailOut,
    AdminKitProductDetailOut,
    AdminProductListItemOut,
    DeletedResourceOut,
    ExperienceOptionBaseOut,
    ExperienceOptionOut,
    ExperienceProductCreateOut,
    KitPriceOut,
    KitProductCreateOut,
    OptionImageOut,
    ProductBasicInfoOut,
    ProductImageOut,
    ProductOfflineOut,
    ProductOnlineOut,
)
from app.services.product_service import ProductService
from app.storage.image import ImageStorage
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/admin",
    tags=["admin-products"],
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
ProductId = Annotated[int, Path(gt=0)]
OptionId = Annotated[int, Path(gt=0)]
ImageId = Annotated[int, Path(gt=0)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
ProductServiceDependency = Annotated[
    ProductService,
    Depends(get_product_service),
]
ProductImageStorageDependency = Annotated[
    ImageStorage,
    Depends(get_product_image_storage),
]


@router.get(
    "/products",
    response_model=None,
    responses=success_responses(Page[AdminProductListItemOut]),
)
async def list_admin_products(
    query: Annotated[AdminProductListQuery, Query()],
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """分页查询管理端 Product 摘要。"""

    page = await service.list_admin_products(
        page=query.page,
        page_size=query.page_size,
        product_type=query.product_type,
        status=query.status,
        keyword=query.keyword,
        include_deleted=query.include_deleted,
    )
    return success(data=map_admin_product_page(page).model_dump(mode="json"))


@router.get(
    "/products/{product_id}/audit-logs",
    response_model=None,
    responses=success_responses(Page[AuditLogOut]),
)
async def list_product_audit_logs(
    product_id: ProductId,
    query: Annotated[AuditLogListQuery, Query()],
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """分页查询 Product 操作历史，包括已逻辑删除的 Product。"""

    page = await service.list_product_audit_logs(
        product_id,
        page=query.page,
        page_size=query.page_size,
    )
    return success(data=map_audit_log_page(page).model_dump(mode="json"))


@router.get(
    "/products/experience/{product_id}",
    response_model=None,
    responses=success_responses(AdminExperienceProductDetailOut),
)
async def get_admin_experience_product(
    product_id: ProductId,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """查询管理端 Experience 详情。"""

    product = await service.get_admin_product_detail(
        product_id,
        product_type=ProductType.EXPERIENCE,
    )
    return success(
        data=map_admin_experience_product_detail(product).model_dump(mode="json")
    )


@router.get(
    "/products/kit/{product_id}",
    response_model=None,
    responses=success_responses(AdminKitProductDetailOut),
)
async def get_admin_kit_product(
    product_id: ProductId,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """查询管理端 Kit 详情。"""

    product = await service.get_admin_product_detail(
        product_id,
        product_type=ProductType.KIT,
    )
    return success(
        data=map_admin_kit_product_detail(product).model_dump(mode="json")
    )


@router.post(
    "/products/experience",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        ExperienceProductCreateOut,
        status.HTTP_201_CREATED,
    ),
)
async def create_experience_product(
    data: ExperienceProductCreate,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """创建 Experience Draft Product。"""

    product = await service.create_experience_product(
        name=data.name,
        description=data.description,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_experience_product_create(product).model_dump(mode="json")
    )


@router.post(
    "/products/kit",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        KitProductCreateOut,
        status.HTTP_201_CREATED,
    ),
)
async def create_kit_product(
    data: KitProductCreate,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """创建 Kit Draft 聚合。"""

    product = await service.create_kit_product(
        name=data.name,
        description=data.description,
        price=data.price,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_kit_product_create(product).model_dump(mode="json"))


@router.post(
    "/products/experience/{product_id}/options",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        ExperienceOptionOut,
        status.HTTP_200_OK,
        status.HTTP_201_CREATED,
    ),
)
async def create_experience_option(
    product_id: ProductId,
    data: ExperienceOptionCreate,
    request: Request,
    response: Response,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """创建新 Option，或以 HTTP 200 恢复历史 Option。"""

    result = await service.create_experience_option(
        product_id,
        duration_minutes=data.duration_minutes,
        participants=data.participants,
        day_type=data.day_type,
        price=data.price,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    if result.restored:
        response.status_code = status.HTTP_200_OK
    return success(
        data=map_experience_option(result.option).model_dump(mode="json")
    )


@router.patch(
    "/products/kit/{product_id}/price",
    response_model=None,
    responses=success_responses(KitPriceOut),
)
async def update_kit_price(
    product_id: ProductId,
    data: KitPriceUpdate,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """修改 Kit 当前售价。"""

    kit = await service.update_kit_price(
        product_id,
        price=data.price,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_kit_price(kit).model_dump(mode="json"))


@router.patch(
    "/options/{option_id}",
    response_model=None,
    responses=success_responses(ExperienceOptionBaseOut),
)
async def update_experience_option(
    option_id: OptionId,
    data: ExperienceOptionUpdate,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """部分修改 Experience Option。"""

    option = await service.update_experience_option(
        option_id,
        updates=data.model_dump(exclude_unset=True),
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_experience_option_base(option).model_dump(mode="json")
    )


@router.delete(
    "/options/{option_id}",
    response_model=None,
    responses=success_responses(DeletedResourceOut),
)
async def delete_experience_option(
    option_id: OptionId,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """逻辑删除 Experience Option。"""

    option = await service.delete_experience_option(
        option_id,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_deleted_resource(option).model_dump(mode="json"))


@router.post(
    "/products/{product_id}/images",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        ProductImageOut,
        status.HTTP_201_CREATED,
    ),
)
async def upload_product_image(
    product_id: ProductId,
    data: Annotated[
        ProductImageUploadForm,
        Form(media_type="multipart/form-data"),
    ],
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
    storage: ProductImageStorageDependency,
) -> dict:
    """上传 Product 公共图片，业务失败时删除已存储文件。"""

    image = await store_image_and_call(
        data.file,
        storage,
        service.create_product_image,
        product_id,
        is_cover=data.is_cover,
        sort=data.sort,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_product_image_by_owner(image).model_dump(mode="json"))


@router.post(
    "/options/{option_id}/images",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        OptionImageOut,
        status.HTTP_201_CREATED,
    ),
)
async def upload_option_image(
    option_id: OptionId,
    data: Annotated[
        OptionImageUploadForm,
        Form(media_type="multipart/form-data"),
    ],
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
    storage: ProductImageStorageDependency,
) -> dict:
    """上传 ExperienceOption 专属图片，固定不参与封面规则。"""

    image = await store_image_and_call(
        data.file,
        storage,
        service.create_option_image,
        option_id,
        sort=data.sort,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_product_image_by_owner(image).model_dump(mode="json"))


@router.patch(
    "/product-images/{image_id}",
    response_model=None,
    responses=success_responses(ProductImageOut | OptionImageOut),
)
async def update_product_image(
    image_id: ImageId,
    data: ProductImageUpdate,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """修改图片排序，或将公共图片设为封面。"""

    image = await service.update_product_image(
        image_id,
        updates=data.model_dump(exclude_unset=True),
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_product_image_by_owner(image).model_dump(mode="json")
    )


@router.delete(
    "/product-images/{image_id}",
    response_model=None,
    responses=success_responses(DeletedResourceOut),
)
async def delete_product_image(
    image_id: ImageId,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """逻辑删除 ProductImage；文件对象延迟清理。"""

    image = await service.delete_product_image(
        image_id,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_deleted_resource(image).model_dump(mode="json"))


@router.patch(
    "/products/{product_id}/online",
    response_model=None,
    responses=success_responses(ProductOnlineOut),
)
async def online_product(
    product_id: ProductId,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """校验完整聚合并上架 Product。"""

    product = await service.online_product(
        product_id,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_product_online(product).model_dump(mode="json"))


@router.patch(
    "/products/{product_id}/offline",
    response_model=None,
    responses=success_responses(ProductOfflineOut),
)
async def offline_product(
    product_id: ProductId,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """下架 Product。"""

    product = await service.offline_product(
        product_id,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_product_offline(product).model_dump(mode="json"))


@router.patch(
    "/products/{product_id}",
    response_model=None,
    responses=success_responses(ProductBasicInfoOut),
)
async def update_product(
    product_id: ProductId,
    data: ProductUpdate,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """修改 Product 名称或描述。"""

    product = await service.update_product(
        product_id,
        updates=data.model_dump(exclude_unset=True),
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_product_basic_info(product).model_dump(mode="json"))


@router.delete(
    "/products/{product_id}",
    response_model=None,
    responses=success_responses(DeletedResourceOut),
)
async def delete_product(
    product_id: ProductId,
    request: Request,
    current_admin: CurrentAdmin,
    service: ProductServiceDependency,
) -> dict:
    """逻辑删除 Draft/Offline Product。"""

    product = await service.delete_product(
        product_id,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(data=map_deleted_resource(product).model_dump(mode="json"))
