"""真实事务与 HTTP 验证预约交接，不依赖本机已读缓存。"""

from datetime import date, timedelta
from unittest.mock import AsyncMock
import uuid

import pytest

from app.api.v1.attention import get_attention_service
from app.common.enums.attention import AttentionEventType
from app.common.enums.reservation import ReservationStatus, ReservationWeekday
from app.common.enums.user import UserRole, UserStatus
from app.common.exceptions.attention import AttentionNotFound
from app.core.security import create_access_token
from app.main import app
from app.models.attention import AttentionEvent
from app.models.reservation import Reservation
from app.repositories.attention_repo import AttentionRepository
from app.repositories.reservation_repo import ReservationRepository
from app.services.attention_service import AttentionService
from tests.reservation.support import FROZEN_NOW, create_option, create_reservation_record, create_user, make_service


def attention(now=FROZEN_NOW):
    return AttentionService(AttentionRepository(), ReservationRepository(), now_provider=lambda: now)


async def setup_reservation(suffix="attention"):
    customer = await create_user(suffix, phone=None)
    admin = await create_user(f"{suffix}-admin", role=UserRole.ADMIN, phone=None)
    product, option = await create_option(suffix)
    reservation = await create_reservation_record(user=customer, product=product, option=option, business_date=date(2026, 9, 9))
    return customer, admin, reservation


@pytest.mark.parametrize("method", ["confirm_reservation", "reject_reservation"])
async def test_review_transfers_one_task_to_owner_and_read_is_idempotent(method):
    customer, admin, reservation = await setup_reservation()
    service = attention()
    assert (await service.summary(user_id=None))["reservation_total"] == 1
    assert (await service.summary(user_id=customer.id))["reservation_total"] == 0

    await getattr(make_service(), method)(reservation.id, operator_id=admin.id, ip_address="127.0.0.1")

    assert (await service.summary(user_id=None))["reservation_total"] == 0
    assert (await service.summary(user_id=customer.id))["reservation_total"] == 1
    _, events, _ = await service.reservation_snapshot(reservation.id, user_id=customer.id)
    assert (await service.summary(user_id=customer.id))["reservation_total"] == 1
    await service.mark_read([events[0].id], user_id=customer.id, reader_id=customer.id)
    first = await AttentionEvent.get(id=events[0].id)
    await attention(FROZEN_NOW + timedelta(hours=1)).mark_read([events[0].id], user_id=customer.id, reader_id=customer.id)
    replay = await AttentionEvent.get(id=events[0].id)
    assert first.read_at == replay.read_at
    assert replay.read_by_id == customer.id
    assert (await service.summary(user_id=customer.id))["reservation_total"] == 0


async def test_new_store_closure_is_not_cleared_by_reading_previous_confirmation():
    customer, admin, reservation = await setup_reservation()
    writer = make_service()
    await writer.confirm_reservation(reservation.id, operator_id=admin.id, ip_address="127.0.0.1")
    _, old_events, _ = await attention().reservation_snapshot(reservation.id, user_id=customer.id)
    await writer.close_store_day(date(2026, 9, 9), operator_id=admin.id, ip_address="127.0.0.1")
    assert (await attention().summary(user_id=customer.id))["reservation_unread"] == 1
    page = await attention().list_reservations(user_id=customer.id, view="unread", page=1, page_size=1)
    assert page.total == 1
    assert page.items[0].status == ReservationStatus.CANCELLED
    await attention().mark_read([old_events[0].id], user_id=customer.id, reader_id=customer.id)
    assert (await attention().summary(user_id=customer.id))["reservation_unread"] == 1
    await writer.close_store_day(date(2026, 9, 9), operator_id=admin.id, ip_address="127.0.0.1")
    assert await AttentionEvent.all().count() == 2


async def test_weekly_closure_two_results_are_atomic_and_read_independently(monkeypatch):
    customer, admin, first = await setup_reservation()
    product, option = await create_option("second-booking")
    second = await create_reservation_record(
        user=customer, product=product, option=option, business_date=date(2026, 9, 9),
    )
    writer = make_service()
    original = writer.attention_repository.create_reservation_events
    monkeypatch.setattr(
        writer.attention_repository, "create_reservation_events",
        AsyncMock(side_effect=RuntimeError("event write failed")),
    )
    with pytest.raises(RuntimeError, match="event write failed"):
        await writer.update_weekly_closed_day(
            weekly_closed_weekday=ReservationWeekday.WEDNESDAY,
            operator_id=admin.id, ip_address="127.0.0.1",
        )
    assert (await attention().summary(user_id=None))["reservation_actionable"] == 2
    assert await AttentionEvent.all().count() == 0

    monkeypatch.setattr(writer.attention_repository, "create_reservation_events", original)
    result = await writer.update_weekly_closed_day(
        weekly_closed_weekday=ReservationWeekday.WEDNESDAY,
        operator_id=admin.id, ip_address="127.0.0.1",
    )
    assert result.newly_cancelled_count == 2
    assert (await attention().summary(user_id=customer.id))["reservation_total"] == 2
    page = await attention().list_reservations(
        user_id=customer.id, view="unread", page=1, page_size=1,
    )
    assert page.total == page.pages == 2
    _, events, _ = await attention().reservation_snapshot(first.id, user_id=customer.id)
    await attention().mark_read([event.id for event in events], user_id=customer.id, reader_id=customer.id)
    assert (await attention().summary(user_id=customer.id))["reservation_total"] == 1
    remaining = await attention().list_reservations(
        user_id=customer.id, view="unread", page=1, page_size=20,
    )
    assert [item.id for item in remaining.items] == [second.id]


@pytest.mark.parametrize("confirmed", [False, True])
async def test_customer_cancellation_shared_ack_only_for_confirmed(confirmed):
    customer, admin, reservation = await setup_reservation()
    second_admin = await create_user("second-admin", role=UserRole.SUPER_ADMIN, phone=None)
    writer = make_service()
    if confirmed:
        await writer.confirm_reservation(reservation.id, operator_id=admin.id, ip_address="127.0.0.1")
    await writer.cancel_reservation(reservation.id, user_id=customer.id, ip_address="127.0.0.1")
    assert (await attention().summary(user_id=None))["reservation_total"] == int(confirmed)
    if confirmed:
        _, events, _ = await attention().reservation_snapshot(reservation.id, user_id=None)
        await attention().mark_read([events[0].id], user_id=None, reader_id=admin.id)
        await attention().mark_read([events[0].id], user_id=None, reader_id=second_admin.id)
        assert (await AttentionEvent.get(id=events[0].id)).read_by_id == admin.id
        assert (await attention().summary(user_id=None))["reservation_total"] == 0


async def test_exact_start_time_excludes_unactionable_pending_and_keeps_overdue():
    _, _, reservation = await setup_reservation()
    service = attention(reservation.scheduled_start_at)
    summary = await service.summary(user_id=None)
    assert summary["reservation_actionable"] == 0
    assert summary["reservation_overdue"] == 1
    page = await service.list_reservations(user_id=None, view="overdue", page=1, page_size=20)
    assert [item.id for item in page.items] == [reservation.id]
    assert (await Reservation.get(id=reservation.id)).status == ReservationStatus.PENDING


async def test_event_failure_rolls_back_confirmation_and_store_closure(monkeypatch):
    customer, admin, reservation = await setup_reservation()
    writer = make_service()
    monkeypatch.setattr(writer.attention_repository, "create_reservation_events", AsyncMock(side_effect=RuntimeError("event write failed")))
    with pytest.raises(RuntimeError, match="event write failed"):
        await writer.confirm_reservation(reservation.id, operator_id=admin.id, ip_address="127.0.0.1")
    assert (await Reservation.get(id=reservation.id)).status == ReservationStatus.PENDING
    with pytest.raises(RuntimeError, match="event write failed"):
        await writer.close_store_day(date(2026, 9, 9), operator_id=admin.id, ip_address="127.0.0.1")
    assert (await Reservation.get(id=reservation.id)).status == ReservationStatus.PENDING
    assert (await attention().summary(user_id=customer.id))["reservation_unread"] == 0


async def test_read_foreign_event_rolls_back_entire_batch():
    customer, admin, reservation = await setup_reservation()
    stranger, _, other = await setup_reservation("stranger")
    for item in [reservation, other]:
        await make_service().confirm_reservation(item.id, operator_id=admin.id, ip_address="127.0.0.1")
    ids = await AttentionEvent.all().values_list("id", flat=True)
    with pytest.raises(AttentionNotFound):
        await attention().mark_read(ids, user_id=customer.id, reader_id=customer.id)
    assert await AttentionEvent.filter(read_at__not_isnull=True).count() == 0
    assert (await attention().summary(user_id=stranger.id))["reservation_total"] == 1


async def test_http_permissions_strict_read_and_snapshot(client):
    customer, admin, reservation = await setup_reservation()
    stranger = await create_user("other", phone=None)
    await make_service().confirm_reservation(reservation.id, operator_id=admin.id, ip_address="127.0.0.1")
    def headers(user):
        return {"Authorization": f"Bearer {create_access_token(user.id, str(uuid.uuid4()), auth_version=user.auth_version)}"}
    app.dependency_overrides[get_attention_service] = attention
    try:
        assert (await client.get("/api/v1/attention")).status_code == 401
        assert (await client.get("/api/v1/admin/attention", headers=headers(customer))).status_code == 403
        assert (await client.get("/api/v1/attention", headers=headers(admin))).status_code == 403
        snapshot = await client.get(f"/api/v1/attention/reservations/{reservation.id}", headers=headers(customer))
        assert snapshot.status_code == 200, snapshot.text
        event = snapshot.json()["data"]["events"][0]
        assert event["event_type"] == AttentionEventType.RESERVATION_CONFIRMED.value
        assert (await client.get(f"/api/v1/attention/reservations/{reservation.id}", headers=headers(stranger))).status_code == 404
        for ids in [[], [True], [str(event["id"])], [event["id"], event["id"]], list(range(1, 102))]:
            assert (await client.post("/api/v1/attention/read", json={"event_ids": ids}, headers=headers(customer))).status_code == 422
        page = await client.get("/api/v1/attention/reservations", headers=headers(customer))
        assert page.status_code == 200, page.text
        assert page.json()["data"]["total"] == 1
        assert (await client.post("/api/v1/attention/read", json={"event_ids": [event["id"]]}, headers=headers(stranger))).status_code == 404
        assert (await client.post("/api/v1/attention/read", json={"event_ids": [event["id"]]}, headers=headers(customer))).status_code == 200
        customer.status = UserStatus.DISABLED
        await customer.save()
        assert (await client.get("/api/v1/attention", headers=headers(customer))).status_code == 400
    finally:
        app.dependency_overrides.pop(get_attention_service, None)
