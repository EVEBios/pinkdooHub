"""无套餐预约的 HTTP 闭环、日历、快照及账户生命周期回归。"""

from datetime import date, datetime, time, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.api.deps import get_reservation_service
from app.api.mappers.reservation import map_reservation
from app.common.constants.reservation import RESERVATION_UNSELECTED_CONFIRMED_MESSAGE
from app.common.enums.reservation import ReservationStatus, ReservationWeekday
from app.common.enums.user import UserRole
from app.common.exceptions.reservation import ReservationPhoneRequired, ReservationScheduleUnavailable
from app.main import app
from app.models.audit_log import AuditLog
from app.models.reservation import Reservation, ReservationSettings, StoreBusinessDay
from app.repositories.reservation_repo import ReservationRepository
from app.validators.reservation_validator import ReservationValidator
from tests.reservation.support import FROZEN_NOW, create_option, create_user, make_service
from tests.reservation.test_reservation_http import _headers

SELECTION_FIELDS = (
    "product_id", "experience_option_id", "product_name", "duration_minutes",
    "participants", "day_type", "price", "end_time", "scheduled_end_at",
)


@pytest.fixture
def frozen_service():
    app.dependency_overrides[get_reservation_service] = lambda: make_service()
    yield
    app.dependency_overrides.pop(get_reservation_service, None)


@pytest.mark.parametrize("selection", [{}, {"experience_option_id": None}])
async def test_no_package_http_calendar_create_review_cancel_and_mixed_list(
    client: AsyncClient, frozen_service, selection: dict,
) -> None:
    owner = await create_user("optional-http")
    admin = await create_user("optional-admin", role=UserRole.ADMIN, phone=None)
    stranger = await create_user("optional-stranger", phone=None)
    headers = _headers(owner.id)
    calendar = await client.get("/api/v1/reservations/booking-options", headers=headers)
    assert calendar.status_code == 200
    options = calendar.json()["data"]
    assert all(options[field] is None for field in SELECTION_FIELDS[:7])
    day = next(day for day in options["dates"] if day["date"] == "2026-09-09")
    assert day["start_times"][0] == "11:00"
    assert day["start_times"][-1] == "19:30"

    response = await client.post("/api/v1/reservations", headers=headers, json={
        **selection, "reservation_date": "2026-09-09", "start_time": "19:30",
    })
    assert response.status_code == 201, response.text
    item = response.json()["data"]
    assert all(item[field] is None for field in SELECTION_FIELDS)
    assert item["cancellation_deadline_at"] == "2026-09-09T08:30:00Z"
    reservation_id = item["id"]
    assert (await client.get(f"/api/v1/reservations/{reservation_id}", headers=_headers(stranger.id))).status_code == 404

    _, option = await create_option("mixed")
    await make_service().create_reservation(user_id=owner.id, experience_option_id=option.id,
        reservation_date=date(2026, 9, 9), start_time="11:00", ip_address="127.0.0.1")
    listed = await client.get("/api/v1/reservations", headers=headers)
    assert listed.json()["data"]["total"] == 2
    admin_list = await client.get("/api/v1/admin/reservations", headers=_headers(admin.id))
    assert admin_list.status_code == 200
    assert admin_list.json()["data"]["total"] == 2
    detail = await client.get(f"/api/v1/admin/reservations/{reservation_id}", headers=_headers(admin.id))
    assert detail.json()["data"]["user_phone"] == owner.phone
    confirmed = await client.patch(f"/api/v1/admin/reservations/{reservation_id}/confirm", headers=_headers(admin.id))
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["customer_message"] == RESERVATION_UNSELECTED_CONFIRMED_MESSAGE
    cancelled = await client.patch(f"/api/v1/reservations/{reservation_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["cancellation_reason"]["value"] == "customer_request"


@pytest.mark.parametrize("business_date,start_time", [
    (date(2026, 9, 8), "10:30"), (date(2026, 9, 8), "20:00"),
    (date(2026, 9, 14), "11:00"), (date(2026, 10, 9), "11:00"),
])
async def test_unselected_invalid_schedule_leaves_no_facts(business_date, start_time):
    owner = await create_user("invalid")
    with pytest.raises(ReservationScheduleUnavailable):
        await make_service().create_reservation(user_id=owner.id,
            reservation_date=business_date, start_time=start_time, ip_address="127.0.0.1")
    assert not await Reservation.exists()
    assert not await StoreBusinessDay.exists()
    assert not await AuditLog.exists()


async def test_unselected_phone_requirement_and_audit_failure_are_atomic(monkeypatch):
    owner = await create_user("no-phone", phone=None)
    request = dict(user_id=owner.id, reservation_date=date(2026, 9, 9), start_time="11:00", ip_address="127.0.0.1")
    with pytest.raises(ReservationPhoneRequired):
        await make_service().create_reservation(**request)
    owner.phone = "13800138000"
    await owner.save()
    service = make_service()
    monkeypatch.setattr(service.audit_log_service, "log", AsyncMock(side_effect=RuntimeError("audit unavailable")))
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await service.create_reservation(**request)
    assert not await Reservation.exists()
    assert not await StoreBusinessDay.exists()


async def test_unselected_closure_cancels_and_calendar_respects_configured_weekday():
    owner = await create_user("closure")
    service = make_service()
    booking = await service.create_reservation(user_id=owner.id, reservation_date=date(2026, 9, 9), start_time="11:00", ip_address="127.0.0.1")
    await service.close_store_day(date(2026, 9, 9), operator_id=owner.id, ip_address="127.0.0.1")
    await booking.refresh_from_db()
    assert booking.status == ReservationStatus.CANCELLED
    assert map_reservation(booking).cancellation_reason.value == "store_closed"
    settings = await ReservationSettings.get(singleton_key=True)
    settings.weekly_closed_weekday = ReservationWeekday.WEDNESDAY
    await settings.save()
    calendar = await service.get_booking_options()
    assert date(2026, 9, 14) in [day.date for day in calendar.dates]
    assert all(day.date.weekday() != 2 for day in calendar.dates)


async def test_unselected_exact_lead_boundary_and_complete_snapshot_invariant():
    validator = ReservationValidator()
    args = dict(business_date=date(2026, 9, 8), start_time=time(11), duration_minutes=None,
        option_day_type=None, is_store_closed=False)
    assert validator.validate_schedule(**args, now_utc=FROZEN_NOW) == (FROZEN_NOW + timedelta(hours=3), None)
    with pytest.raises(ReservationScheduleUnavailable):
        validator.validate_schedule(**args, now_utc=FROZEN_NOW + timedelta(microseconds=1))
    owner = await create_user("snapshot")
    booking = await make_service().create_reservation(user_id=owner.id, reservation_date=date(2026, 9, 9), start_time="11:00", ip_address="127.0.0.1")
    booking.product_name = "incomplete snapshot"
    with pytest.raises(ValidationError, match="entirely absent or complete"):
        map_reservation(booking)


async def test_unselected_activity_checks_include_booking_day_until_closing():
    owner = await create_user("activity")
    booking = await make_service().create_reservation(user_id=owner.id, reservation_date=date(2026, 9, 9), start_time="11:00", ip_address="127.0.0.1")
    repo = ReservationRepository()
    assert await repo.has_active_reservations_for_user(owner.id, now_utc=datetime(2026, 9, 9, 11, 59, tzinfo=timezone.utc), unselected_active_from_date=date(2026, 9, 9))
    assert not await repo.has_active_reservations_for_user(owner.id, now_utc=datetime(2026, 9, 9, 12, tzinfo=timezone.utc), unselected_active_from_date=date(2026, 9, 10))
    booking.status = ReservationStatus.CANCELLED
    await booking.save()
    assert not await repo.has_active_reservations_for_user(owner.id, now_utc=FROZEN_NOW, unselected_active_from_date=date(2026, 9, 8))


async def test_m10_only_relaxes_package_fields_and_refuses_lossy_downgrade():
    path, = Path("migrations/models").glob("10_*_optional_reservation_package.py")
    spec = spec_from_file_location("optional_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    ddl = await module.upgrade(None)
    assert module.RUN_IN_TRANSACTION is False
    assert ddl.count("MODIFY COLUMN") == 8
    assert "DROP" not in ddl and "NOT NULL" not in ddl
    db = AsyncMock()
    db.execute_query_dict.return_value = [{"total": 1}]
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        await module.downgrade(db)
    db.execute_query_dict.return_value = [{"total": 0}]
    assert (await module.downgrade(db)).count("NOT NULL") == 8
