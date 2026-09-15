"""ADMIN+ 预约联系与异常跟进；顾客端不暴露内部记录。"""
from typing import Annotated
from fastapi import APIRouter, Depends, Path, Query
from app.api.deps import get_current_admin
from app.api.responses import error_responses, success_responses
from app.common.enums.reservation_followup import FollowupKind
from app.common.pagination import Page, PageParams
from app.common.response import success
from app.models.user import User
from app.repositories.reservation_followup_repo import ReservationFollowupRepository
from app.repositories.reservation_repo import ReservationRepository
from app.schemas.reservation_followup import FollowupCounts, FollowupItemOut, FollowupQuery, FollowupRecordOut, FollowupSnapshotOut, FollowupWrite
from app.services.reservation_followup_service import ReservationFollowupService

router = APIRouter(prefix="/admin/reservation-followups", tags=["admin-reservation-followups"], responses=error_responses(400, 401, 403, 404, 409, 422))


def get_followup_service(repository: ReservationFollowupRepository = Depends(), reservations: ReservationRepository = Depends()) -> ReservationFollowupService:
    return ReservationFollowupService(repository, reservations)


Service = Annotated[ReservationFollowupService, Depends(get_followup_service)]
Admin = Annotated[User, Depends(get_current_admin)]
ReservationId = Annotated[int, Path(gt=0)]


@router.get("/summary", response_model=None, responses=success_responses(FollowupCounts))
async def counts(admin: Admin, service: Service) -> dict:
    return success(data=(await service.counts()).model_dump(mode="json"))


@router.get("", response_model=None, responses=success_responses(Page[FollowupItemOut]))
async def list_queue(query: Annotated[FollowupQuery, Query()], admin: Admin, service: Service) -> dict:
    result = await service.list_queue(query.kind, query.view, query.page, query.page_size)
    return success(data=result.model_dump(mode="json"))


@router.get("/{reservation_id}/{kind}", response_model=None, responses=success_responses(FollowupSnapshotOut))
async def detail(reservation_id: ReservationId, kind: FollowupKind, admin: Admin, service: Service) -> dict:
    return success(data=(await service.detail(reservation_id, kind)).model_dump(mode="json"))


@router.get("/{reservation_id}/{kind}/history", response_model=None, responses=success_responses(Page[FollowupRecordOut]))
async def history(reservation_id: ReservationId, kind: FollowupKind, query: Annotated[PageParams, Query()], admin: Admin, service: Service) -> dict:
    return success(data=(await service.history(reservation_id, kind, query.page, query.page_size)).model_dump(mode="json"))


@router.post("/{reservation_id}/{kind}", response_model=None, responses=success_responses(FollowupSnapshotOut))
async def write(reservation_id: ReservationId, kind: FollowupKind, data: FollowupWrite, admin: Admin, service: Service) -> dict:
    return success(data=(await service.write(reservation_id, kind, data, admin.id)).model_dump(mode="json"))
