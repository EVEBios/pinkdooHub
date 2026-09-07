"""Reservation ORM/Service 结果到严格 API 白名单的纯同步映射。"""

import re
from datetime import timedelta

from app.common.constants.product import DAY_TYPE_LABELS
from app.common.constants.reservation import (
    RESERVATION_BOOKING_WINDOW_DAYS,
    RESERVATION_CANCELLATION_REASON_LABELS,
    RESERVATION_CLOSE_TIME_VALUE,
    RESERVATION_CUSTOMER_MESSAGES,
    RESERVATION_MINIMUM_LEAD_HOURS,
    RESERVATION_OPEN_TIME_VALUE,
    RESERVATION_REJECTION_REASON_LABELS,
    RESERVATION_SLOT_INTERVAL_MINUTES,
    RESERVATION_STATUS_LABELS,
    RESERVATION_TIMEZONE,
)
from app.common.constants.validation import PHONE_PATTERN
from app.common.enums.product import DayType
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationStatus,
)
from app.common.pagination import Page
from app.models.reservation import Reservation, StoreBusinessDay
from app.schemas.reservation_response import (
    AdminReservationDetailOut,
    AdminReservationListItemOut,
    ReservationBookingDateOut,
    ReservationBookingOptionsOut,
    ReservationCancellationReasonOut,
    ReservationDayTypeOut,
    ReservationOut,
    ReservationRejectionReasonOut,
    ReservationStatusOut,
    StoreBusinessDayOut,
    StoreClosureMutationOut,
)
from app.services.reservation_service import (
    ReservationBookingOptions,
    StoreClosureMutationResult,
)
from app.validators.reservation_validator import STORE_TIMEZONE


def map_reservation_status(value: ReservationStatus | str) -> ReservationStatusOut:
    normalized = ReservationStatus(value)
    return ReservationStatusOut.model_validate(
        {"value": normalized, "label": RESERVATION_STATUS_LABELS[normalized]}
    )


def map_reservation_day_type(value: DayType | str) -> ReservationDayTypeOut:
    normalized = DayType(value)
    return ReservationDayTypeOut.model_validate(
        {"value": normalized, "label": DAY_TYPE_LABELS[normalized]}
    )


def map_rejection_reason(
    value: ReservationRejectionReason | str | None,
) -> ReservationRejectionReasonOut | None:
    if value is None:
        return None
    normalized = ReservationRejectionReason(value)
    return ReservationRejectionReasonOut.model_validate(
        {
            "value": normalized,
            "label": RESERVATION_REJECTION_REASON_LABELS[normalized],
        }
    )


def map_cancellation_reason(
    value: ReservationCancellationReason | str | None,
) -> ReservationCancellationReasonOut | None:
    if value is None:
        return None
    normalized = ReservationCancellationReason(value)
    return ReservationCancellationReasonOut.model_validate(
        {
            "value": normalized,
            "label": RESERVATION_CANCELLATION_REASON_LABELS[normalized],
        }
    )


def _customer_message(reservation: Reservation) -> str:
    status = ReservationStatus(reservation.status)
    if status is ReservationStatus.CANCELLED:
        if reservation.cancellation_reason is None:
            raise ValueError("Cancelled reservation is missing cancellation reason")
        return RESERVATION_CUSTOMER_MESSAGES[
            ReservationCancellationReason(reservation.cancellation_reason)
        ]
    return RESERVATION_CUSTOMER_MESSAGES[status]


def _reservation_payload(reservation: Reservation) -> dict[str, object]:
    local_start = reservation.scheduled_start_at.astimezone(STORE_TIMEZONE)
    local_end = reservation.scheduled_end_at.astimezone(STORE_TIMEZONE)
    return {
        "id": reservation.id,
        "product_id": reservation.product_id,
        "experience_option_id": reservation.experience_option_id,
        "product_name": reservation.product_name,
        "duration_minutes": reservation.option_duration_minutes,
        "participants": reservation.option_participants,
        "day_type": map_reservation_day_type(reservation.option_day_type),
        "price": reservation.option_price,
        "status": map_reservation_status(reservation.status),
        "rejection_reason": map_rejection_reason(reservation.rejection_reason),
        "cancellation_reason": map_cancellation_reason(
            reservation.cancellation_reason
        ),
        "customer_message": _customer_message(reservation),
        "reservation_date": local_start.date(),
        "start_time": local_start.strftime("%H:%M"),
        "end_time": local_end.strftime("%H:%M"),
        "scheduled_start_at": reservation.scheduled_start_at,
        "scheduled_end_at": reservation.scheduled_end_at,
        "cancellation_deadline_at": reservation.scheduled_start_at
        - timedelta(hours=RESERVATION_MINIMUM_LEAD_HOURS),
        "confirmed_at": reservation.confirmed_at,
        "rejected_at": reservation.rejected_at,
        "cancelled_at": reservation.cancelled_at,
        "created_at": reservation.created_at,
        "updated_at": reservation.updated_at,
    }


def map_reservation(reservation: Reservation) -> ReservationOut:
    """映射顾客预约，不读取或输出 User 关系。"""

    return ReservationOut.model_validate(_reservation_payload(reservation))


def mask_phone(phone: str | None) -> str | None:
    """只为管理列表生成固定 11 位中国大陆手机号掩码。"""

    if phone is None:
        return None
    if re.fullmatch(PHONE_PATTERN, phone) is None:
        raise ValueError("User phone does not match the persisted phone contract")
    return f"{phone[:3]}****{phone[-4:]}"


def map_admin_reservation_list_item(
    reservation: Reservation,
) -> AdminReservationListItemOut:
    return AdminReservationListItemOut.model_validate(
        {
            **_reservation_payload(reservation),
            "user_id": reservation.user_id,
            "user_nickname": reservation.user.nickname,
            "user_phone_masked": mask_phone(reservation.user.phone),
        }
    )


def map_admin_reservation_detail(
    reservation: Reservation,
) -> AdminReservationDetailOut:
    return AdminReservationDetailOut.model_validate(
        {
            **_reservation_payload(reservation),
            "user_id": reservation.user_id,
            "user_nickname": reservation.user.nickname,
            "user_phone": reservation.user.phone,
        }
    )


def map_reservation_page(page: Page[Reservation]) -> Page[ReservationOut]:
    return Page[ReservationOut](
        items=[map_reservation(item) for item in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def map_admin_reservation_page(
    page: Page[Reservation],
) -> Page[AdminReservationListItemOut]:
    return Page[AdminReservationListItemOut](
        items=[map_admin_reservation_list_item(item) for item in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def map_booking_options(
    options: ReservationBookingOptions,
) -> ReservationBookingOptionsOut:
    return ReservationBookingOptionsOut.model_validate(
        {
            "experience_option_id": options.experience_option_id,
            "product_id": options.product_id,
            "product_name": options.product_name,
            "duration_minutes": options.duration_minutes,
            "participants": options.participants,
            "day_type": map_reservation_day_type(options.day_type),
            "price": options.price,
            "timezone": RESERVATION_TIMEZONE,
            "server_now": options.server_now,
            "booking_window_end_date": options.booking_window_end_date,
            "minimum_lead_hours": RESERVATION_MINIMUM_LEAD_HOURS,
            "slot_interval_minutes": RESERVATION_SLOT_INTERVAL_MINUTES,
            "booking_window_days": RESERVATION_BOOKING_WINDOW_DAYS,
            "opens_at": RESERVATION_OPEN_TIME_VALUE,
            "closes_at": RESERVATION_CLOSE_TIME_VALUE,
            "dates": [
                ReservationBookingDateOut.model_validate(
                    {
                        "date": item.date,
                        "day_type": map_reservation_day_type(item.day_type),
                        "start_times": list(item.start_times),
                    }
                )
                for item in options.dates
            ],
        }
    )


def map_store_business_day(day: StoreBusinessDay) -> StoreBusinessDayOut:
    return StoreBusinessDayOut.model_validate(
        {
            "id": day.id,
            "business_date": day.business_date,
            "is_closed": day.is_closed,
            "created_at": day.created_at,
            "updated_at": day.updated_at,
        }
    )


def map_store_business_day_page(
    page: Page[StoreBusinessDay],
) -> Page[StoreBusinessDayOut]:
    return Page[StoreBusinessDayOut](
        items=[map_store_business_day(item) for item in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def map_store_closure_mutation(
    result: StoreClosureMutationResult,
) -> StoreClosureMutationOut:
    day = result.business_day
    return StoreClosureMutationOut.model_validate(
        {
            "id": day.id,
            "business_date": day.business_date,
            "is_closed": day.is_closed,
            "created_at": day.created_at,
            "updated_at": day.updated_at,
            "newly_cancelled_count": result.newly_cancelled_count,
            "cancelled_pending_count": result.cancelled_pending_count,
            "cancelled_confirmed_count": result.cancelled_confirmed_count,
            "is_replay": result.is_replay,
        }
    )
