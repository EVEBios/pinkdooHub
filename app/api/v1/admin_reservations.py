"""管理端 Reservation API —— 预约审核、审计与自定义店休。"""

from datetime import date
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Path,
    Query,
    Request,
    Response,
    status,
)

from app.api.deps import (
    get_current_admin,
    get_reservation_service,
    reject_request_body,
)
from app.api.mappers.audit import map_audit_log_page
from app.api.mappers.reservation import (
    map_admin_reservation_detail,
    map_admin_reservation_page,
    map_reservation,
    map_reservation_settings,
    map_store_business_day_page,
    map_store_closure_mutation,
    map_weekly_closure_mutation,
)
from app.api.responses import error_responses, success_responses
from app.common.pagination import Page
from app.common.response import success
from app.models.user import User
from app.schemas.audit import AuditLogListQuery, AuditLogOut
from app.schemas.reservation import (
    AdminReservationListQuery,
    StoreClosureListQuery,
    WeeklyClosureUpdateRequest,
)
from app.schemas.reservation_response import (
    AdminReservationDetailOut,
    AdminReservationListItemOut,
    ReservationOut,
    StoreBusinessDayOut,
    StoreClosureMutationOut,
    ReservationSettingsOut,
    WeeklyClosureMutationOut,
)
from app.services.reservation_service import ReservationService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/admin",
    tags=["admin-reservations"],
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
ReservationId = Annotated[int, Path(gt=0)]
BusinessDatePath = Annotated[date, Path()]
CurrentAdmin = Annotated[User, Depends(get_current_admin)]
ReservationServiceDependency = Annotated[
    ReservationService,
    Depends(get_reservation_service),
]


@router.get(
    "/reservation-settings",
    response_model=None,
    responses=success_responses(ReservationSettingsOut),
)
async def get_reservation_settings(
    current_admin: CurrentAdmin,
    service: ReservationServiceDependency,
) -> dict:
    settings = await service.get_reservation_settings()
    return success(data=map_reservation_settings(settings).model_dump(mode="json"))


@router.put(
    "/reservation-settings/weekly-closed-day",
    response_model=None,
    responses=success_responses(WeeklyClosureMutationOut),
)
async def update_weekly_closed_day(
    data: WeeklyClosureUpdateRequest,
    request: Request,
    current_admin: CurrentAdmin,
    service: ReservationServiceDependency,
) -> dict:
    result = await service.update_weekly_closed_day(
        weekly_closed_weekday=data.weekly_closed_weekday,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_weekly_closure_mutation(result).model_dump(mode="json"),
        message="Weekly store closure updated",
    )


@router.get(
    "/reservations",
    response_model=None,
    responses=success_responses(Page[AdminReservationListItemOut]),
)
async def list_admin_reservations(
    query: Annotated[AdminReservationListQuery, Query()],
    current_admin: CurrentAdmin,
    service: ReservationServiceDependency,
) -> dict:
    page = await service.list_admin_reservations(
        page=query.page,
        page_size=query.page_size,
        status=query.status,
        business_date=query.business_date,
        user_id=query.user_id,
        product_id=query.product_id,
    )
    return success(data=map_admin_reservation_page(page).model_dump(mode="json"))


@router.get(
    "/reservations/{reservation_id}/audit-logs",
    response_model=None,
    responses=success_responses(Page[AuditLogOut]),
)
async def list_reservation_audit_logs(
    reservation_id: ReservationId,
    query: Annotated[AuditLogListQuery, Query()],
    current_admin: CurrentAdmin,
    service: ReservationServiceDependency,
) -> dict:
    page = await service.list_reservation_audit_logs(
        reservation_id,
        page=query.page,
        page_size=query.page_size,
    )
    return success(data=map_audit_log_page(page).model_dump(mode="json"))


@router.get(
    "/reservations/{reservation_id}",
    response_model=None,
    responses=success_responses(AdminReservationDetailOut),
)
async def get_admin_reservation_detail(
    reservation_id: ReservationId,
    current_admin: CurrentAdmin,
    service: ReservationServiceDependency,
) -> dict:
    reservation = await service.get_admin_reservation_detail(reservation_id)
    return success(
        data=map_admin_reservation_detail(reservation).model_dump(mode="json")
    )


@router.patch(
    "/reservations/{reservation_id}/confirm",
    response_model=None,
    responses=success_responses(ReservationOut),
)
async def confirm_reservation(
    reservation_id: ReservationId,
    request: Request,
    current_admin: CurrentAdmin,
    service: ReservationServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
) -> dict:
    reservation = await service.confirm_reservation(
        reservation_id,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_reservation(reservation).model_dump(mode="json"),
        message="Reservation confirmed",
    )


@router.patch(
    "/reservations/{reservation_id}/reject",
    response_model=None,
    responses=success_responses(ReservationOut),
)
async def reject_reservation(
    reservation_id: ReservationId,
    request: Request,
    current_admin: CurrentAdmin,
    service: ReservationServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
) -> dict:
    """以固定原因 no_capacity 拒绝 Pending 预约。"""

    reservation = await service.reject_reservation(
        reservation_id,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_reservation(reservation).model_dump(mode="json"),
        message="Reservation rejected because no capacity is available",
    )


@router.get(
    "/store-closures",
    response_model=None,
    responses=success_responses(Page[StoreBusinessDayOut]),
)
async def list_store_closures(
    query: Annotated[StoreClosureListQuery, Query()],
    current_admin: CurrentAdmin,
    service: ReservationServiceDependency,
) -> dict:
    page = await service.list_store_business_days(
        page=query.page,
        page_size=query.page_size,
        date_from=query.date_from,
        date_to=query.date_to,
        is_closed=query.is_closed,
    )
    return success(
        data=map_store_business_day_page(page).model_dump(mode="json")
    )


@router.put(
    "/store-closures/{business_date}",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(
        StoreClosureMutationOut,
        status.HTTP_200_OK,
        status.HTTP_201_CREATED,
    ),
)
async def close_store_day(
    business_date: BusinessDatePath,
    request: Request,
    response: Response,
    current_admin: CurrentAdmin,
    service: ReservationServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
) -> dict:
    result = await service.close_store_day(
        business_date,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    if result.is_replay:
        response.status_code = status.HTTP_200_OK
    return success(
        data=map_store_closure_mutation(result).model_dump(mode="json"),
        message="Store closure applied",
    )


@router.delete(
    "/store-closures/{business_date}",
    response_model=None,
    responses=success_responses(StoreClosureMutationOut),
)
async def reopen_store_day(
    business_date: BusinessDatePath,
    request: Request,
    current_admin: CurrentAdmin,
    service: ReservationServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
) -> dict:
    result = await service.reopen_store_day(
        business_date,
        operator_id=current_admin.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_store_closure_mutation(result).model_dump(mode="json"),
        message=(
            "Store reopened; previously cancelled reservations remain cancelled"
        ),
    )
