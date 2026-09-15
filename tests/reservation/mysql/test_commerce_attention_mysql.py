"""M13 真 MySQL 付款竞争、双设备阅读与订单/桌台结果回归。"""

import asyncio

import pytest
from tortoise import connections

from app.common.exceptions.order import OrderStatusConflict
from app.models.attention import AttentionEvent
from app.models.payment import PaymentSettlement
from app.models.table_session import TableSessionTimer
from tests.reservation.test_commerce_attention import (
    attention, setup, claim,
    test_payment_transfers_one_session_to_one_order_result_and_fulfillment,
    test_deadline_projection_then_timeout_retains_exact_old_session_after_reclaim,
    test_event_failure_rolls_back_business_and_money,
    test_timeout_blocks_payment_and_keeps_independent_table_reminder,
    test_refunds_excluded_and_list_paginates_before_mapping,
    test_independent_expiry_and_admin_release_are_single_results,
)
from tests.table_sessions.test_table_session_service import _manual_order_service

pytestmark = pytest.mark.mysql


@pytest.mark.parametrize('competing', ['manual', 'wallet'])
async def test_two_payments_share_one_result_and_two_readers_do_not_duplicate(competing):
    now, user, admin, order, table, tables, wallet = await setup()
    session = await claim(tables, user, order, table)
    manual = _manual_order_service(now=now)
    async def pay_manual():
        return await manual.mark_order_paid(order.id, operator_id=admin.id, ip_address='127.0.0.1', table_session_no=session.session_no)
    async def pay_wallet():
        return await wallet.pay_order_with_wallet(user=user, order_id=order.id, idempotency_key='race-wallet', table_session_no=session.session_no, ip_address='127.0.0.1')
    results = await asyncio.gather(pay_manual(), pay_manual() if competing == 'manual' else pay_wallet(), return_exceptions=True)
    assert sum(not isinstance(value, Exception) for value in results) == 1
    assert sum(isinstance(value, OrderStatusConflict) for value in results) == 1
    assert await PaymentSettlement.all().count() == await AttentionEvent.all().count() == 1
    assert await TableSessionTimer.all().count() == 2
    event = await AttentionEvent.get()
    plans = await connections.get('default').execute_query_dict(
        'EXPLAIN SELECT order_id FROM attention_events WHERE user_id=%s AND read_at IS NULL', [user.id],
    )
    assert any('idx_attention_order_unread' in (row.get('possible_keys') or '') and row.get('type') in ('ref', 'range') and row.get('key') for row in plans), plans
    await asyncio.gather(*[attention(now).mark_read([event.id], user_id=user.id, reader_id=user.id) for _ in range(2)])
    assert (await attention(now).summary(user_id=user.id))['order_unread'] == 0
