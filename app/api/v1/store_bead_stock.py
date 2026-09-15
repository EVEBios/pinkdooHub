"""管理员门店未拆封整包库存，独立于商城库存。"""
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Path, Query, Request
from app.api.deps import get_current_admin
from app.api.responses import error_responses, success_responses
from app.common.pagination import Page, PageParams
from app.common.response import success
from app.models.user import User
from app.repositories.store_bead_stock_repo import StoreBeadStockRepository
from app.repositories.audit_log_repo import AuditLogRepository
from app.services.audit_log_service import AuditLogService
from app.services.store_bead_stock_service import StoreBeadStockService
from app.schemas.store_bead_stock import StoreBeadStockOut, StoreBeadStockQuery, StoreBeadStockWrite, StoreBeadStockBatchOut, StoreBeadStockBatchSummary

router = APIRouter(prefix="/admin/store-bead-stock", tags=["admin-store-bead-stock"], responses=error_responses(400, 401, 403, 404, 409, 422))


def get_store_bead_stock_service(repository: StoreBeadStockRepository = Depends(), audit_repository: AuditLogRepository = Depends()) -> StoreBeadStockService:
    return StoreBeadStockService(repository, AuditLogService(audit_repository))


Service = Annotated[StoreBeadStockService, Depends(get_store_bead_stock_service)]
Admin = Annotated[User, Depends(get_current_admin)]


@router.get("", response_model=None, responses=success_responses(Page[StoreBeadStockOut]))
async def list_stock(query: Annotated[StoreBeadStockQuery, Query()], admin: Admin, service: Service) -> dict:
    return success(data=(await service.list_stock(query.page, query.page_size)).model_dump(mode="json"))


@router.get("/batches", response_model=None, responses=success_responses(Page[StoreBeadStockBatchSummary]))
async def history(query: Annotated[PageParams, Query()], admin: Admin, service: Service) -> dict:
    return success(data=(await service.history(query.page, query.page_size)).model_dump(mode="json"))


@router.get("/batches/by-request/{request_key}", response_model=None, responses=success_responses(StoreBeadStockBatchOut))
async def by_request(request_key: UUID, admin: Admin, service: Service) -> dict:
    return success(data=(await service.by_request(str(request_key), admin.id)).model_dump(mode="json"))


@router.get("/batches/{batch_id}", response_model=None, responses=success_responses(StoreBeadStockBatchOut))
async def detail(batch_id: Annotated[int, Path(gt=0)], admin: Admin, service: Service) -> dict:
    return success(data=(await service.detail(batch_id)).model_dump(mode="json"))


@router.post("/batches", response_model=None, responses=success_responses(StoreBeadStockBatchOut))
async def write(data: StoreBeadStockWrite, request: Request, admin: Admin, service: Service) -> dict:
    return success(data=(await service.write(data, admin.id, request.client.host if request.client else "unknown")).model_dump(mode="json"))
