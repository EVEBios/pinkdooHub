"""Reservation Mapper 的状态一致性、零 SQL 和隐私白名单测试。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from tortoise import connections

from app.api.mappers.reservation import (
    map_admin_reservation_detail,
    map_admin_reservation_page,
    map_reservation,
    map_reservation_page,
    mask_phone,
)
from app.common.constants.reservation import RESERVATION_CUSTOMER_MESSAGES
from app.common.enums.product import DayType
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationStatus,
)
from app.repositories.reservation_repo import ReservationRepository
from tests.reservation.support import (
    create_option,
    create_reservation_record,
    create_user,
)

START = datetime(2026, 9, 9, 3, 0, tzinfo=timezone.utc)
STAMP = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)


def _reservation_stub(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 11,
        "user_id": 7,
        "business_day_id": 3,
        "product_id": 5,
        "experience_option_id": 9,
        "product_name": "Mapper 拼豆体验",
        "option_duration_minutes": 60,
        "option_participants": 2,
        "option_day_type": DayType.WEEKDAY,
        "option_price": Decimal("88.50"),
        "scheduled_start_at": START,
        "scheduled_end_at": START + timedelta(hours=1),
        "status": ReservationStatus.PENDING,
        "rejection_reason": None,
        "cancellation_reason": None,
        "confirmed_at": None,
        "rejected_at": None,
        "cancelled_at": None,
        "created_at": STAMP,
        "updated_at": STAMP,
        # These fields deliberately look sensitive/internal. Explicit projection
        # must keep them out of every customer response.
        "password": "must-not-leak",
        "idempotency_key": "must-not-leak",
        "internal_note": "must-not-leak",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("overrides", "expected_reason", "expected_message_key"),
    [
        ({}, None, ReservationStatus.PENDING),
        (
            {
                "status": ReservationStatus.CONFIRMED,
                "confirmed_at": STAMP,
            },
            None,
            ReservationStatus.CONFIRMED,
        ),
        (
            {
                "status": ReservationStatus.REJECTED,
                "rejection_reason": ReservationRejectionReason.NO_CAPACITY,
                "rejected_at": STAMP,
            },
            "no_capacity",
            ReservationStatus.REJECTED,
        ),
        (
            {
                "status": ReservationStatus.CANCELLED,
                "cancellation_reason": ReservationCancellationReason.CUSTOMER_REQUEST,
                "cancelled_at": STAMP,
            },
            "customer_request",
            ReservationCancellationReason.CUSTOMER_REQUEST,
        ),
        (
            {
                "status": ReservationStatus.CANCELLED,
                "cancellation_reason": ReservationCancellationReason.STORE_CLOSED,
                "cancelled_at": STAMP,
                "confirmed_at": STAMP - timedelta(hours=1),
            },
            "store_closed",
            ReservationCancellationReason.STORE_CLOSED,
        ),
    ],
)
def test_valid_state_projections_have_exact_customer_message_and_no_sensitive_fields(
    overrides: dict[str, object],
    expected_reason: str | None,
    expected_message_key: ReservationStatus | ReservationCancellationReason,
) -> None:
    payload = map_reservation(_reservation_stub(**overrides)).model_dump(mode="json")

    reason = payload["rejection_reason"] or payload["cancellation_reason"]
    assert (reason["value"] if reason is not None else None) == expected_reason
    assert payload["customer_message"] == RESERVATION_CUSTOMER_MESSAGES[
        expected_message_key
    ]
    assert not (
        {
            "user_id",
            "user_nickname",
            "user_phone",
            "user_phone_masked",
            "business_day_id",
            "password",
            "idempotency_key",
            "internal_note",
        }
        & payload.keys()
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "status": ReservationStatus.PENDING,
            "rejection_reason": ReservationRejectionReason.NO_CAPACITY,
            "rejected_at": STAMP,
        },
        {"status": ReservationStatus.CONFIRMED, "confirmed_at": None},
        {"status": ReservationStatus.REJECTED, "rejected_at": STAMP},
        {
            "status": ReservationStatus.REJECTED,
            "rejection_reason": ReservationRejectionReason.NO_CAPACITY,
            "rejected_at": STAMP,
            "confirmed_at": STAMP,
        },
        {
            "status": ReservationStatus.CANCELLED,
            "cancellation_reason": ReservationCancellationReason.CUSTOMER_REQUEST,
            "cancelled_at": STAMP,
            "rejected_at": STAMP,
        },
    ],
)
def test_mapper_rejects_cross_status_field_inconsistencies(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        map_reservation(_reservation_stub(**overrides))


def test_cancelled_mapper_rejects_missing_reason_before_projection() -> None:
    with pytest.raises(
        ValueError,
        match="Cancelled reservation is missing cancellation reason",
    ):
        map_reservation(
            _reservation_stub(
                status=ReservationStatus.CANCELLED,
                cancelled_at=STAMP,
            )
        )


@pytest.mark.parametrize(
    ("phone", "expected"),
    [(None, None), ("13800138000", "138****8000")],
)
def test_phone_masking_is_server_controlled(phone: str | None, expected: str | None) -> None:
    assert mask_phone(phone) == expected


@pytest.mark.parametrize("phone", ["1380013800", "138001380000", "12800138000"])
def test_phone_masking_rejects_values_outside_persisted_contract(phone: str) -> None:
    with pytest.raises(ValueError, match="persisted phone contract"):
        mask_phone(phone)


def _snapshot(reservation: object) -> tuple[object, ...]:
    return tuple(
        getattr(reservation, name)
        for name in (
            "id",
            "user_id",
            "product_id",
            "experience_option_id",
            "product_name",
            "option_duration_minutes",
            "option_participants",
            "option_day_type",
            "option_price",
            "scheduled_start_at",
            "scheduled_end_at",
            "status",
            "rejection_reason",
            "cancellation_reason",
            "confirmed_at",
            "rejected_at",
            "cancelled_at",
            "created_at",
            "updated_at",
        )
    )


async def test_repository_results_map_without_additional_sql_or_orm_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await create_user("mapper-db")
    product, option = await create_option("mapper-db")
    reservation = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
    )
    repository = ReservationRepository()
    customer_page = await repository.list_user_reservations(
        user_id=owner.id,
        page=1,
        page_size=20,
    )
    admin_page = await repository.list_admin_reservations(
        page=1,
        page_size=20,
    )
    detail = await repository.get_reservation_detail(reservation.id)
    assert detail is not None
    snapshots = (
        tuple(_snapshot(item) for item in customer_page.items),
        tuple(_snapshot(item) for item in admin_page.items),
        _snapshot(detail),
    )
    connection = connections.get("default")

    def fail_on_query(*args: object, **kwargs: object) -> None:
        raise AssertionError("Reservation Mapper must not execute SQL")

    monkeypatch.setattr(connection, "execute_query", fail_on_query)

    customer_data = map_reservation_page(customer_page).model_dump(mode="json")
    admin_list_data = map_admin_reservation_page(admin_page).model_dump(mode="json")
    admin_detail_data = map_admin_reservation_detail(detail).model_dump(mode="json")

    assert customer_data["items"][0]["id"] == reservation.id
    assert "user_phone" not in customer_data["items"][0]
    assert admin_list_data["items"][0]["user_phone_masked"] == "138****8000"
    assert "user_phone" not in admin_list_data["items"][0]
    assert admin_detail_data["user_phone"] == "13800138000"
    assert "user_phone_masked" not in admin_detail_data
    assert snapshots == (
        tuple(_snapshot(item) for item in customer_page.items),
        tuple(_snapshot(item) for item in admin_page.items),
        _snapshot(detail),
    )
