"""管理端 Inventory API —— 库存调整与不可变流水查询。"""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Path,
    Query,
    Request,
    Response,
    status,
)

from app.api.deps import get_current_admin, get_inventory_service
from app.api.mappers.inventory import (
    map_inventory_adjustment,
    map_inventory_transaction_page,
)
from app.api.responses import error_responses, success_responses
from app.common.pagination import Page
from app.common.response import success
from app.models.user import User
from app.schemas.inventory import (
    InventoryAdjustmentCreate,
    InventoryIdempotencyKey,
    InventoryProductTransactionQuery,
    InventoryTransactionQuery,
)
from app.schemas.inventory_response import (
    InventoryAdjustmentOut,
    InventoryTransactionListItem,
)
from app.services.inventory_service import InventoryService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/admin",
    tags=["admin-inventory"],
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
ProductId = Annotated[int, Path(gt=0)]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
InventoryServiceDependency = Annotated[
    InventoryService,
    Depends(get_inventory_service),
]
IdempotencyKeyHeader = Annotated[
    InventoryIdempotencyKey,
    Header(alias="Idempotency-Key"),
]


@router.post(
    "/products/kit/{product_id}/inventory-adjustments",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        InventoryAdjustmentOut,
        status.HTTP_200_OK,
        status.HTTP_201_CREATED,
    ),
)
async def adjust_inventory(
    product_id: ProductId,
    data: InventoryAdjustmentCreate,
    idempotency_key: IdempotencyKeyHeader,
    request: Request,
    response: Response,
    current_admin: CurrentAdmin,
    service: InventoryServiceDependency,
) -> dict:
    """按变化量调整未删除 Kit 库存，幂等重放返回 HTTP 200。"""

    result = await service.adjust_stock(
        product_id,
        change=data.change,
        reason=data.reason,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
        idempotency_key=idempotency_key,
    )
    if result.is_replay:
        response.status_code = status.HTTP_200_OK
    mapped = map_inventory_adjustment(
        product_id=result.product_id,
        stock=result.stock,
        transaction=result.transaction,
    )
    return success(data=mapped.model_dump(mode="json"))


@router.get(
    "/products/kit/{product_id}/inventory-transactions",
    response_model=None,
    responses=success_responses(Page[InventoryTransactionListItem]),
)
async def list_product_inventory_transactions(
    product_id: ProductId,
    query: Annotated[InventoryProductTransactionQuery, Query()],
    current_admin: CurrentAdmin,
    service: InventoryServiceDependency,
) -> dict:
    """分页查询指定 Kit Product 的库存流水。"""

    page = await service.list_product_transactions(
        product_id,
        page=query.page,
        page_size=query.page_size,
        transaction_type=query.transaction_type,
        source_type=query.source_type,
        source_id=query.source_id,
        created_from=query.created_from,
        created_to=query.created_to,
    )
    return success(
        data=map_inventory_transaction_page(page).model_dump(mode="json")
    )


@router.get(
    "/inventory-transactions",
    response_model=None,
    responses=success_responses(Page[InventoryTransactionListItem]),
)
async def list_inventory_transactions(
    query: Annotated[InventoryTransactionQuery, Query()],
    current_admin: CurrentAdmin,
    service: InventoryServiceDependency,
) -> dict:
    """分页筛选全部库存流水。"""

    page = await service.list_transactions(
        page=query.page,
        page_size=query.page_size,
        product_id=query.product_id,
        transaction_type=query.transaction_type,
        source_type=query.source_type,
        source_id=query.source_id,
        created_from=query.created_from,
        created_to=query.created_to,
    )
    return success(
        data=map_inventory_transaction_page(page).model_dump(mode="json")
    )
