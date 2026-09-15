"""顾客与 ADMIN+ 站内提醒入口。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_current_admin, get_current_customer
from app.api.mappers.reservation import map_admin_reservation_page, map_reservation_page
from app.api.responses import error_responses, success_responses
from app.common.constants.attention import ATTENTION_EVENT_LABELS
from app.common.pagination import Page, PageParams
from app.common.response import success
from app.models.user import User
from app.repositories.attention_repo import AttentionRepository
from app.repositories.reservation_repo import ReservationRepository
from app.schemas.attention import (
    CommerceAttentionQuery, CommerceAttentionItemOut, CommerceAttentionSnapshotOut,
    AdminAttentionQuery, AttentionEventOut, AttentionReadRequest, AttentionSummaryOut,
    CustomerAttentionQuery, ReservationAttentionSnapshotOut,
    WalletAttentionQuery,
)
from app.schemas.reservation_response import AdminReservationListItemOut, ReservationOut
from app.services.attention_service import AttentionService
from app.schemas.table_session import TableSessionNumber

CommerceScope = Annotated[Literal["orders", "tables"], Path()]

router = APIRouter(prefix="/attention", tags=["attention"], responses=error_responses(400, 401, 403, 404, 422))
admin_router = APIRouter(prefix="/admin/attention", tags=["admin-attention"], responses=error_responses(400, 401, 403, 404, 422))


def get_attention_service(
    repository: AttentionRepository = Depends(),
    reservations: ReservationRepository = Depends(),
) -> AttentionService:
    return AttentionService(repository, reservations)


Service = Annotated[AttentionService, Depends(get_attention_service)]
Customer = Annotated[User, Depends(get_current_customer)]
Admin = Annotated[User, Depends(get_current_admin)]
ReservationId = Annotated[int, Path(gt=0)]


@router.get("", response_model=None, responses=success_responses(AttentionSummaryOut))
async def customer_summary(customer: Customer, service: Service) -> dict:
    result = AttentionSummaryOut.model_validate(await service.summary(user_id=customer.id))
    return success(data=result.model_dump(mode="json"))


@admin_router.get("", response_model=None, responses=success_responses(AttentionSummaryOut))
async def admin_summary(admin: Admin, service: Service) -> dict:
    result = AttentionSummaryOut.model_validate(await service.summary(user_id=None))
    return success(data=result.model_dump(mode="json"))


@router.get("/reservations", response_model=None, responses=success_responses(Page[ReservationOut]))
async def customer_reservations(query: Annotated[CustomerAttentionQuery, Query()], customer: Customer, service: Service) -> dict:
    page = await service.list_reservations(user_id=customer.id, view=query.view, page=query.page, page_size=query.page_size)
    return success(data=map_reservation_page(page).model_dump(mode="json"))


@admin_router.get("/reservations", response_model=None, responses=success_responses(Page[AdminReservationListItemOut]))
async def admin_reservations(query: Annotated[AdminAttentionQuery, Query()], admin: Admin, service: Service) -> dict:
    page = await service.list_reservations(user_id=None, view=query.view.value, page=query.page, page_size=query.page_size)
    return success(data=map_admin_reservation_page(page).model_dump(mode="json"))


async def _snapshot(service: AttentionService, reservation_id: int, user_id: int | None) -> dict:
    reservation, events, now = await service.reservation_snapshot(reservation_id, user_id=user_id)
    result = ReservationAttentionSnapshotOut(
        reservation_id=reservation.id, reservation_updated_at=reservation.updated_at, server_now=now,
        events=[AttentionEventOut(id=event.id, event_type=event.event_type, label=ATTENTION_EVENT_LABELS[event.event_type], occurred_at=event.occurred_at) for event in events],
    )
    return success(data=result.model_dump(mode="json"))


@router.get("/reservations/{reservation_id}", response_model=None, responses=success_responses(ReservationAttentionSnapshotOut))
async def customer_snapshot(reservation_id: ReservationId, customer: Customer, service: Service) -> dict:
    return await _snapshot(service, reservation_id, customer.id)


@admin_router.get("/reservations/{reservation_id}", response_model=None, responses=success_responses(ReservationAttentionSnapshotOut))
async def admin_snapshot(reservation_id: ReservationId, admin: Admin, service: Service) -> dict:
    return await _snapshot(service, reservation_id, None)


@router.post("/read", response_model=None)
async def customer_read(data: AttentionReadRequest, customer: Customer, service: Service) -> dict:
    await service.mark_read(data.event_ids, user_id=customer.id, reader_id=customer.id)
    return success()


@admin_router.post("/acknowledge", response_model=None)
async def admin_acknowledge(data: AttentionReadRequest, admin: Admin, service: Service) -> dict:
    await service.mark_read(data.event_ids, user_id=None, reader_id=admin.id)
    return success()


@router.get("/commerce/{scope}", response_model=None, responses=success_responses(Page[CommerceAttentionItemOut]))
async def customer_commerce(scope: CommerceScope, query: Annotated[CommerceAttentionQuery, Query()], customer: Customer, service: Service) -> dict:
    page = await service.list_commerce(user_id=customer.id, scope=scope, view=query.view, page=query.page, page_size=query.page_size)
    return success(data=page.model_dump(mode="json"))


@router.get("/table-sessions", response_model=None, responses=success_responses(Page[CommerceAttentionItemOut]))
async def customer_table_sessions(query: Annotated[PageParams, Query()], customer: Customer, service: Service) -> dict:
    """顾客本人的全部开台记录；已付款或结果已读后仍可查询。"""
    page = await service.list_commerce(
        user_id=customer.id, scope="tables", view="all", page=query.page,
        page_size=query.page_size, include_all_sessions=True,
    )
    return success(data=page.model_dump(mode="json"))


@admin_router.get("/commerce/{scope}", response_model=None, responses=success_responses(Page[CommerceAttentionItemOut]))
async def admin_commerce(scope: CommerceScope, query: Annotated[CommerceAttentionQuery, Query()], admin: Admin, service: Service) -> dict:
    page = await service.list_commerce(user_id=None, scope=scope, view=query.view, page=query.page, page_size=query.page_size)
    return success(data=page.model_dump(mode="json"))


@router.get("/orders/{order_id}", response_model=None, responses=success_responses(CommerceAttentionSnapshotOut))
async def customer_order_snapshot(order_id: Annotated[int, Path(gt=0)], customer: Customer, service: Service) -> dict:
    result = await service.commerce_snapshot(user_id=customer.id, order_id=order_id)
    return success(data=result.model_dump(mode="json"))


@router.get("/wallet", response_model=None, responses=success_responses(Page[CommerceAttentionItemOut]))
async def customer_wallet_results(query: Annotated[WalletAttentionQuery, Query()], customer: Customer, service: Service) -> dict:
    page = await service.list_wallet(user_id=customer.id, view=query.view, page=query.page, page_size=query.page_size)
    return success(data=page.model_dump(mode="json"))


@router.get("/wallet/{event_id}", response_model=None, responses=success_responses(CommerceAttentionSnapshotOut))
async def customer_wallet_snapshot(event_id: Annotated[int, Path(gt=0)], customer: Customer, service: Service) -> dict:
    result = await service.wallet_snapshot(user_id=customer.id, event_id=event_id)
    return success(data=result.model_dump(mode="json"))


@router.get("/tables/{session_no}", response_model=None, responses=success_responses(CommerceAttentionSnapshotOut))
async def customer_table_snapshot(session_no: Annotated[TableSessionNumber, Path()], customer: Customer, service: Service) -> dict:
    result = await service.commerce_snapshot(user_id=customer.id, session_no=session_no)
    return success(data=result.model_dump(mode="json"))
