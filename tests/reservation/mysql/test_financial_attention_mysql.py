"""P1 资金交接的真实 MySQL 并发、晚提交与索引验收。"""

import asyncio
from datetime import datetime, timezone

import pytest
from tortoise import connections
from tortoise.transactions import in_transaction

from app.common.enums.attention import AttentionEventType
from app.models.attention import AttentionEvent
from app.models.payment import Refund
from app.models.wallet import WalletTransaction
from app.models.table_session import TableOccupancy, TableSession
from app.repositories.attention_repo import AttentionRepository
from app.repositories.table_session_repo import TableSessionRepository
from tests.reservation.test_attention_joint_acceptance import (
    test_all_scopes_transfer_and_read_independently_with_legacy_records,
)
from tests.reservation.test_commerce_attention import attention, setup, claim
from tests.reservation.test_financial_attention import (
    adjust, adjustment_setup,
    test_adjustments_count_per_transaction_and_keep_exact_read_history,
    test_adjustment_http_is_owner_only_and_whitelists_ledger_fields,
    test_disabled_customer_gets_adjustment_result_without_login_rights,
    test_ledger_reference_corruption_cannot_expose_another_wallet,
    test_refund_merges_order_wallet_and_table_results_without_duplicate,
    test_assisted_order_emits_one_safe_result_and_keeps_idempotent_replay,
    test_result_failure_rolls_back_money_inventory_and_event,
)
from tests.table_sessions.test_table_session_service import _order
from tests.wallet.services.test_wallet_payment_refund_service_integration import _services

pytestmark = pytest.mark.mysql


async def test_same_adjustment_two_requests_share_one_event_and_two_readers():
    user, admin, _, service = await adjustment_setup()
    results = await asyncio.gather(*[adjust(service, user, admin) for _ in range(2)])
    assert sorted(result.is_replay for result in results) == [False, True]
    assert await WalletTransaction.all().count() == await AttentionEvent.all().count() == 1
    event = await AttentionEvent.get()
    await asyncio.gather(*[attention(event.occurred_at).mark_read([event.id], user_id=user.id, reader_id=user.id) for _ in range(2)])
    assert (await attention(event.occurred_at).summary(user_id=user.id))['wallet_unread'] == 0
    plans = await connections.get('default').execute_query_dict(
        'EXPLAIN SELECT id FROM attention_events WHERE user_id=%s AND read_at IS NULL AND event_type=%s',
        [user.id, 'wallet_adjusted'],
    )
    assert any(row.get('key') and row.get('type') in ('ref', 'range', 'const') for row in plans), plans


async def test_concurrent_wallet_refund_replays_single_event():
    now, user, admin, order, table, tables, payment = await setup()
    session = await claim(tables, user, order, table)
    await payment.pay_order_with_wallet(user=user, order_id=order.id, idempotency_key='refund-race-paid', table_session_no=session.session_no, ip_address='127.0.0.1')
    _, _, service = _services()
    service.table_session_repository = TableSessionRepository()
    results = await asyncio.gather(*[service.refund_order(order.id, operator=admin, reason='并发退款验收', idempotency_key='same-refund', ip_address='127.0.0.1') for _ in range(2)])
    assert sorted(result.is_replay for result in results) == [False, True]
    assert await Refund.all().count() == 1
    assert await AttentionEvent.filter(event_type=AttentionEventType.ORDER_WALLET_REFUNDED).count() == 1
    assert await TableOccupancy.all().count() == 0
    assert (await TableSession.get(id=session.id)).status == 'closed'


async def test_late_lower_event_id_is_not_cleared_by_reading_committed_higher_id():
    now, user, _, order, _, _, _ = await setup()
    other_order = await _order(user, sequence=2, durations=[(60, 1)])
    inserted = asyncio.Event()
    release = asyncio.Event()
    repo = AttentionRepository()

    async def late_transaction():
        async with in_transaction() as connection:
            await repo.create_commerce_event(event_type=AttentionEventType.ORDER_MANUAL_PAID, user_id=user.id,
                order_id=order.id, session_id=None, message='较晚提交的收款结果', occurred_at=now, using_db=connection)
            inserted.set()
            await asyncio.wait_for(release.wait(), 10)

    task = asyncio.create_task(late_transaction())
    try:
        await asyncio.wait_for(inserted.wait(), 5)
        async with in_transaction() as connection:
            await repo.create_commerce_event(event_type=AttentionEventType.ORDER_MANUAL_PAID, user_id=user.id,
                order_id=other_order.id, session_id=None, message='先提交的收款结果', occurred_at=now, using_db=connection)
        visible = await attention(now).commerce_snapshot(user_id=user.id, order_id=other_order.id)
        assert len(visible.events) == 1
        await attention(now).mark_read([visible.events[0].id], user_id=user.id, reader_id=user.id)
    finally:
        release.set()
        await task
    late = await attention(now).commerce_snapshot(user_id=user.id, order_id=order.id)
    assert late.events[0].id < visible.events[0].id
    assert not late.events[0].read
    assert (await attention(datetime.now(timezone.utc)).summary(user_id=user.id))['order_unread'] == 1
