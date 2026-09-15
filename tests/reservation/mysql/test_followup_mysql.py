"""一次性 MySQL 真正双连接的预约跟进并发与查询验证。"""
import asyncio
import pytest
from tortoise import connections
from app.common.enums.reservation_followup import FollowupKind as Kind, FollowupOutcome as Outcome
from app.common.exceptions.reservation_followup import FollowupConflict
from app.models.reservation_followup import ReservationFollowup
from tests.reservation.test_followups import (
    service, write, setup_reservation,
    test_closure_contact_is_independent_of_customer_read_and_shared_completion,
    test_overdue_boundary_and_completion_never_rewrites_reservation,
    test_replay_version_conflict_and_no_overwrite_after_completion,
    test_changed_reservation_and_non_closure_cancellation_not_followup,
    test_failure_rolls_back_record_and_counts,
    test_admin_http_permissions_validation_and_history,
)
pytestmark = pytest.mark.mysql


async def test_concurrent_same_key_and_different_admin_intents():
    _, admin, reservation = await setup_reservation()
    followup = service(reservation.scheduled_start_at)
    data = write()
    results = await asyncio.gather(*[followup.write(reservation.id, Kind.OVERDUE, data, admin.id) for _ in range(2)])
    assert [result.revision for result in results] == [1, 1]
    assert await ReservationFollowup.all().count() == 1
    results = await asyncio.gather(
        followup.write(reservation.id, Kind.OVERDUE, write(Outcome.RESOLVED, 1), admin.id),
        followup.write(reservation.id, Kind.OVERDUE, write(Outcome.UNREACHABLE, 1), admin.id),
        return_exceptions=True,
    )
    assert sum(isinstance(result, FollowupConflict) for result in results) == 1, results
    assert await ReservationFollowup.all().count() == 2
    rows = await connections.get('default').execute_query_dict('EXPLAIN SELECT reservation_id FROM reservation_followups WHERE kind=\'overdue\' AND outcome IN (\'contacted\',\'resolved\')')
    assert rows[0]['key'] == 'idx_followup_completed'
