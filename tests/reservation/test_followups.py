"""P2 真实预约、共享跟进、幂等与管理员 HTTP 权限。"""
from datetime import timedelta, date
from uuid import uuid4
import pytest
from app.api.v1.reservation_followups import get_followup_service
from app.common.enums.reservation_followup import FollowupKind as Kind, FollowupOutcome as Outcome
from app.common.enums.reservation import ReservationWeekday
from app.common.enums.user import UserRole, UserStatus
from app.common.exceptions.reservation_followup import FollowupConflict
from app.core.security import create_access_token
from app.main import app
from app.models.reservation import Reservation
from app.models.reservation_followup import ReservationFollowup
from app.repositories.reservation_followup_repo import ReservationFollowupRepository
from app.repositories.reservation_repo import ReservationRepository
from app.schemas.reservation_followup import FollowupWrite
from app.services.reservation_followup_service import ReservationFollowupService
from tests.reservation.test_attention import setup_reservation, attention
from tests.reservation.support import FROZEN_NOW, make_service, create_user


def service(now=FROZEN_NOW):
    return ReservationFollowupService(ReservationFollowupRepository(), ReservationRepository(), now_provider=lambda: now)


def write(outcome=Outcome.RETRY, revision=0, note="电话未接通，明日再次联系"):
    return FollowupWrite(expected_revision=revision, request_key=uuid4(), outcome=outcome, note=note)


@pytest.mark.parametrize("weekly", [False, True])
async def test_closure_contact_is_independent_of_customer_read_and_shared_completion(weekly):
    customer, admin, reservation = await setup_reservation()
    if weekly:
        await make_service().update_weekly_closed_day(weekly_closed_weekday=ReservationWeekday.WEDNESDAY, operator_id=admin.id, ip_address="127.0.0.1")
    else:
        await make_service().close_store_day(date(2026, 9, 9), operator_id=admin.id, ip_address="127.0.0.1")
    followup = service()
    assert (await followup.counts()).contact_pending == 1
    _, events, _ = await attention().reservation_snapshot(reservation.id, user_id=customer.id)
    await attention().mark_read([event.id for event in events], user_id=customer.id, reader_id=customer.id)
    assert (await followup.counts()).contact_pending == 1
    page = await followup.list_queue(Kind.CONTACT, "pending", 1, 20)
    assert page.total == 1 and page.items[0].revision == 0
    assert await ReservationFollowup.all().count() == 0
    await followup.write(reservation.id, Kind.CONTACT, write(), admin.id)
    other = await create_user("followup-second", role=UserRole.SUPER_ADMIN, phone=None)
    await followup.write(reservation.id, Kind.CONTACT, write(Outcome.UNREACHABLE, 1, "号码停机，寻找其他联系渠道"), other.id)
    assert (await followup.counts()).contact_pending == 1
    await followup.write(reservation.id, Kind.CONTACT, write(Outcome.CONTACTED, 2, "已告知店休，顾客知悉"), other.id)
    assert (await followup.counts()).contact_pending == 0
    assert (await followup.list_queue(Kind.CONTACT, "completed", 1, 20)).total == 1
    history = await followup.history(reservation.id, Kind.CONTACT, 1, 2)
    assert history.total == 3 and history.pages == 2
    assert [row.revision for row in history.items] == [3, 2]
    assert history.items[0].operator_id == other.id
    assert (await Reservation.get(id=reservation.id)).status == "cancelled"


async def test_overdue_boundary_and_completion_never_rewrites_reservation():
    _, admin, reservation = await setup_reservation()
    assert (await service(reservation.scheduled_start_at - timedelta(microseconds=1)).counts()).overdue_pending == 0
    followup = service(reservation.scheduled_start_at)
    assert (await followup.counts()).overdue_pending == 1
    with pytest.raises(FollowupConflict):
        await followup.write(reservation.id, Kind.OVERDUE, write(Outcome.CONTACTED), admin.id)
    before = await Reservation.get(id=reservation.id)
    await followup.write(reservation.id, Kind.OVERDUE, write(Outcome.RESOLVED, note="已核实顾客未到店，无需继续跟进"), admin.id)
    after = await Reservation.get(id=reservation.id)
    assert (after.status, after.updated_at) == (before.status, before.updated_at)
    assert (await followup.counts()).overdue_pending == 0
    assert (await followup.list_queue(Kind.OVERDUE, "completed", 1, 20)).total == 1


async def test_replay_version_conflict_and_no_overwrite_after_completion():
    _, admin, reservation = await setup_reservation()
    followup = service(reservation.scheduled_start_at)
    first = write()
    await followup.write(reservation.id, Kind.OVERDUE, first, admin.id)
    await followup.write(reservation.id, Kind.OVERDUE, first, admin.id)
    assert await ReservationFollowup.all().count() == 1
    with pytest.raises(FollowupConflict):
        await followup.write(reservation.id, Kind.OVERDUE, write(), admin.id)
    with pytest.raises(FollowupConflict):
        await followup.write(reservation.id, Kind.OVERDUE, first.model_copy(update={"note": "另一项记录"}), admin.id)
    await followup.write(reservation.id, Kind.OVERDUE, write(Outcome.RESOLVED, 1), admin.id)
    assert (await followup.write(reservation.id, Kind.OVERDUE, first, admin.id)).completed
    with pytest.raises(FollowupConflict):
        await followup.write(reservation.id, Kind.OVERDUE, write(revision=2), admin.id)
    assert await ReservationFollowup.all().count() == 2


async def test_changed_reservation_and_non_closure_cancellation_not_followup():
    customer, admin, reservation = await setup_reservation()
    with pytest.raises(FollowupConflict):
        await service().write(reservation.id, Kind.CONTACT, write(), admin.id)
    with pytest.raises(FollowupConflict):
        await service().write(reservation.id, Kind.OVERDUE, write(), admin.id)
    await make_service().cancel_reservation(reservation.id, user_id=customer.id, ip_address="127.0.0.1")
    assert (await service(reservation.scheduled_start_at).counts()).model_dump(exclude={"server_now"}) == {"contact_pending": 0, "overdue_pending": 0}


async def test_failure_rolls_back_record_and_counts(monkeypatch):
    _, admin, reservation = await setup_reservation()
    followup = service(reservation.scheduled_start_at)
    original = followup.repository.append
    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("write failed")
    monkeypatch.setattr(followup.repository, "append", fail)
    with pytest.raises(RuntimeError):
        await followup.write(reservation.id, Kind.OVERDUE, write(Outcome.RESOLVED), admin.id)
    assert await ReservationFollowup.all().count() == 0
    assert (await followup.counts()).overdue_pending == 1


async def test_admin_http_permissions_validation_and_history(client):
    customer, admin, reservation = await setup_reservation()
    app.dependency_overrides[get_followup_service] = lambda: service(reservation.scheduled_start_at)
    def headers(user):
        return {"Authorization": f"Bearer {create_access_token(user.id, str(uuid4()), auth_version=user.auth_version)}"}
    base = "/api/v1/admin/reservation-followups"
    path = f"{base}/{reservation.id}/overdue"
    try:
        for suffix in ["/summary", "?kind=overdue", f"/{reservation.id}/overdue", f"/{reservation.id}/overdue/history"]:
            assert (await client.get(base + suffix)).status_code == 401
            assert (await client.get(base + suffix, headers=headers(customer))).status_code == 403
            assert (await client.get(base + suffix, headers=headers(admin))).status_code == 200
        payload = write().model_dump(mode="json")
        assert (await client.post(path, json=payload, headers=headers(customer))).status_code == 403
        for update in [{"note": "  "}, {"note": "字" * 501}, {"expected_revision": True}, {"request_key": "invalid"}, {"operator_id": customer.id}]:
            assert (await client.post(path, json={**payload, **update}, headers=headers(admin))).status_code == 422
        assert (await client.post(path, json=payload, headers=headers(admin))).status_code == 200
        assert (await client.post(path, json=write().model_dump(mode="json"), headers=headers(admin))).status_code == 409
        assert (await client.get(f"{base}/999999/overdue", headers=headers(admin))).status_code == 404
        admin.status = UserStatus.DISABLED.value
        await admin.save()
        assert (await client.get(base + "/summary", headers=headers(admin))).status_code != 200
    finally:
        app.dependency_overrides.pop(get_followup_service, None)
