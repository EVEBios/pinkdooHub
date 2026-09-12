"""用户端 Reservation API —— 可预约时段、创建、查询与取消。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.api.deps import (
    get_current_customer,
    get_reservation_service,
    reject_request_body,
)
from app.api.mappers.reservation import (
    map_booking_options,
    map_reservation,
    map_reservation_page,
)
from app.api.responses import error_responses, success_responses
from app.common.pagination import Page
from app.common.response import success
from app.models.user import User
from app.schemas.reservation import (
    ReservationBookingOptionsQuery,
    ReservationCreate,
    ReservationListQuery,
)
from app.schemas.reservation_response import (
    ReservationBookingOptionsOut,
    ReservationOut,
)
from app.services.reservation_service import ReservationService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/reservations",
    tags=["reservations"],
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
ReservationId = Annotated[int, Path(gt=0)]
CurrentCustomer = Annotated[User, Depends(get_current_customer)]
ReservationServiceDependency = Annotated[
    ReservationService,
    Depends(get_reservation_service),
]


@router.get(
    "/booking-options",
    response_model=None,
    responses=success_responses(ReservationBookingOptionsOut),
)
async def get_reservation_booking_options(
    query: Annotated[ReservationBookingOptionsQuery, Query()],
    current_customer: CurrentCustomer,
    service: ReservationServiceDependency,
) -> dict:
    """返回服务端计算的当前 Option 可预约日期和半小时时段。"""

    options = await service.get_booking_options(
        experience_option_id=query.experience_option_id,
    )
    return success(data=map_booking_options(options).model_dump(mode="json"))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(ReservationOut, status.HTTP_201_CREATED),
)
async def create_reservation(
    data: ReservationCreate,
    request: Request,
    current_customer: CurrentCustomer,
    service: ReservationServiceDependency,
) -> dict:
    """创建独立于订单与支付的待门店确认预约。"""

    reservation = await service.create_reservation(
        user_id=current_customer.id,
        experience_option_id=data.experience_option_id,
        reservation_date=data.reservation_date,
        start_time=data.start_time,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_reservation(reservation).model_dump(mode="json"),
        message="Reservation submitted for store confirmation",
    )


@router.get(
    "",
    response_model=None,
    responses=success_responses(Page[ReservationOut]),
)
async def list_reservations(
    query: Annotated[ReservationListQuery, Query()],
    current_customer: CurrentCustomer,
    service: ReservationServiceDependency,
) -> dict:
    """分页查询当前顾客自己的预约历史。"""

    page = await service.list_user_reservations(
        user_id=current_customer.id,
        page=query.page,
        page_size=query.page_size,
        status=query.status,
    )
    return success(data=map_reservation_page(page).model_dump(mode="json"))


@router.get(
    "/{reservation_id}",
    response_model=None,
    responses=success_responses(ReservationOut),
)
async def get_reservation_detail(
    reservation_id: ReservationId,
    current_customer: CurrentCustomer,
    service: ReservationServiceDependency,
) -> dict:
    """查询当前顾客可见的预约详情。"""

    reservation = await service.get_user_reservation_detail(
        reservation_id,
        user_id=current_customer.id,
    )
    return success(data=map_reservation(reservation).model_dump(mode="json"))


@router.patch(
    "/{reservation_id}/cancel",
    response_model=None,
    responses=success_responses(ReservationOut),
)
async def cancel_reservation(
    reservation_id: ReservationId,
    request: Request,
    current_customer: CurrentCustomer,
    service: ReservationServiceDependency,
    _empty_body: Annotated[None, Depends(reject_request_body)],
) -> dict:
    """在开始前至少三小时取消自己的 Pending/Confirmed 预约。"""

    reservation = await service.cancel_reservation(
        reservation_id,
        user_id=current_customer.id,
        ip_address=get_client_ip(request),
    )
    return success(
        data=map_reservation(reservation).model_dump(mode="json"),
        message="Reservation cancelled",
    )
