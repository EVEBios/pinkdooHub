"""M12 在受保护命名的可销毁 MySQL Schema 上验证交接与并发。"""

import asyncio

import pytest
from tortoise import connections

from app.common.exceptions.reservation import ReservationStatusConflict
from app.models.attention import AttentionEvent
from tests.reservation.support import make_service
from tests.reservation.test_attention import (
    attention,
    setup_reservation,
    test_customer_cancellation_shared_ack_only_for_confirmed,
    test_event_failure_rolls_back_confirmation_and_store_closure,
    test_new_store_closure_is_not_cleared_by_reading_previous_confirmation,
    test_read_foreign_event_rolls_back_entire_batch,
    test_review_transfers_one_task_to_owner_and_read_is_idempotent,
    test_weekly_closure_two_results_are_atomic_and_read_independently,
)

pytestmark = pytest.mark.mysql


async def test_concurrent_admin_review_creates_one_result_and_indexed_unread():
    customer, admin, reservation = await setup_reservation()
    results = await asyncio.gather(
        make_service().confirm_reservation(reservation.id, operator_id=admin.id, ip_address="127.0.0.1"),
        make_service().reject_reservation(reservation.id, operator_id=admin.id, ip_address="127.0.0.1"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, ReservationStatusConflict) for result in results) == 1
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert await AttentionEvent.all().count() == 1
    assert (await attention().summary(user_id=customer.id))["reservation_total"] == 1
    page = await attention().list_reservations(user_id=customer.id, view="unread", page=1, page_size=20)
    assert page.total == 1
    event = await AttentionEvent.get()
    await asyncio.gather(*[
        attention().mark_read([event.id], user_id=customer.id, reader_id=customer.id)
        for _ in range(2)
    ])
    assert (await attention().summary(user_id=customer.id))["reservation_total"] == 0
    plan = await connections.get("default").execute_query_dict(
        "EXPLAIN SELECT reservation_id FROM attention_events WHERE user_id=%s AND read_at IS NULL", [customer.id],
    )
    assert any(row.get("key") == "idx_attention_recipient_unread" for row in plan)
