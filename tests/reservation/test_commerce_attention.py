from app.common.exceptions.table_session import TablePaymentWindowExpired
"""订单/桌台交接的真实业务事务、去重计数和精确历史归属。"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.common.enums.attention import AttentionEventType
from app.common.enums.order import OrderStatus
from app.common.enums.user import UserRole
from app.common.exceptions.attention import AttentionNotFound
from app.common.exceptions.table_session import TableSessionNotFound
from app.models.attention import AttentionEvent
from app.models.order import Order
from app.models.payment import Payment, PaymentSettlement, Refund
from app.models.table_session import StoreTable, TableSession, TableSessionTimer
from app.repositories.attention_repo import AttentionRepository
from app.repositories.reservation_repo import ReservationRepository
from app.services.attention_service import AttentionService
from tests.table_sessions.test_table_session_service import _user, _order, _services, _manual_order_service
from tests.table_sessions.test_table_session_http import _headers


def attention(now):
    return AttentionService(AttentionRepository(), ReservationRepository(), now_provider=lambda: now)


async def setup():
    now = datetime.now(timezone.utc)
    user = await _user('commerce-customer')
    admin = await _user('commerce-admin')
    admin.role = UserRole.ADMIN.value
    await admin.save()
    order = await _order(user, sequence=1, durations=[(60, 1), (120, 2)])
    table = await StoreTable.create(table_no='T01', display_name='T01号桌', qr_token='A' * 32)
    tables, payment = _services(now=now)
    return now, user, admin, order, table, tables, payment


async def claim(tables, user, order, table, key='commerce-claim'):
    return (await tables.create_session(user=user, qr_token=table.qr_token, order_id=order.id, idempotency_key=key, ip_address='127.0.0.1')).session


@pytest.mark.parametrize('method', ['manual', 'wallet'])
async def test_payment_transfers_one_session_to_one_order_result_and_fulfillment(method):
    now, user, admin, order, table, tables, payment = await setup()
    service = attention(now)
    assert (await service.summary(user_id=None))['order_pending'] == 1
    session = await claim(tables, user, order, table)
    for target in (None, user.id):
        summary = await service.summary(user_id=target)
        assert summary['table_pending'] == 1 and summary['table_total'] == 1
        assert summary['order_pending'] == summary['order_total'] == 0
    if method == 'manual':
        await _manual_order_service(now=now).mark_order_paid(order.id, operator_id=admin.id, ip_address='127.0.0.1', table_session_no=session.session_no)
    else:
        for _ in range(2):
            await payment.pay_order_with_wallet(user=user, order_id=order.id, idempotency_key='one-wallet-payment', table_session_no=session.session_no, ip_address='127.0.0.1')
    assert await PaymentSettlement.all().count() == 1
    assert await TableSessionTimer.all().count() == 2
    assert await AttentionEvent.all().count() == 1
    assert (await service.summary(user_id=None))['order_fulfillment'] == 1
    assert (await service.summary(user_id=user.id))['order_unread'] == 1
    assert (await service.summary(user_id=user.id))['table_total'] == 0
    page = await service.list_commerce(user_id=None, scope='orders', view='fulfillment', page=1, page_size=20)
    assert page.items[0].status_label == '服务中'
    snapshot = await service.commerce_snapshot(user_id=user.id, order_id=order.id)
    event = snapshot.events[0]
    assert '100.00' in event.message and '开始计时' in event.message
    assert event.session_no == session.session_no
    # 同一事件也可在本次桌台看到；读取本身不消除。
    assert (await service.commerce_snapshot(user_id=user.id, session_no=session.session_no)).events[0].id == event.id
    assert (await service.summary(user_id=user.id))['order_unread'] == 1
    await service.mark_read([event.id], user_id=user.id, reader_id=user.id)
    assert (await service.summary(user_id=user.id))['order_total'] == 0
    sessions = await service.list_commerce(user_id=user.id, scope='tables', view='all', page=1, page_size=20, include_all_sessions=True)
    assert sessions.total == 1 and sessions.items[0].session_no == session.session_no
    assert sessions.items[0].status_label == '体验中' and not sessions.items[0].unread
    assert (await service.summary(user_id=user.id))['table_total'] == 0
    await _manual_order_service(now=now).complete_order(order.id, operator_id=admin.id, ip_address='127.0.0.1')
    assert (await service.summary(user_id=None))['order_total'] == 0
    assert (await service.summary(user_id=user.id))['order_total'] == 1
    assert (await service.summary(user_id=user.id))['table_total'] == 0
    sessions = await service.list_commerce(user_id=user.id, scope='tables', view='all', page=1, page_size=20, include_all_sessions=True)
    assert sessions.total == 1 and sessions.items[0].status_label == '本次桌台已结束'
    # 旧付款回执不会清掉后来新增的完成结果。
    await service.mark_read([event.id], user_id=user.id, reader_id=user.id)
    assert (await service.summary(user_id=user.id))['order_unread'] == 1


async def test_deadline_projection_then_timeout_retains_exact_old_session_after_reclaim():
    now, user, _, order, table, tables, _ = await setup()
    first = await claim(tables, user, order, table)
    deadline = first.payment_deadline_at
    assert (await attention(deadline).summary(user_id=None))['table_pending'] == 1
    after = deadline + timedelta(microseconds=1)
    summary = await attention(after).summary(user_id=None)
    assert summary['table_pending'] == 0 and summary['order_pending'] == 1
    # 即使后台尚未收敛，计数也不会继续把超时桌台当成可收款。
    assert (await TableSession.get(id=first.id)).status == 'awaiting_payment'
    assert await tables.converge_session(first.id, now=after)
    assert not await tables.converge_session(first.id, now=after)
    tables.now_provider = lambda: after
    second = await claim(tables, user, order, table, 'claim-after-timeout')
    assert second.session_no != first.session_no
    old = await tables.get_user_session(first.session_no, user_id=user.id)
    assert old.id == first.id and old.close_reason == 'payment_timeout'
    results = await attention(after).list_commerce(user_id=user.id, scope='tables', view='all', page=1, page_size=1)
    assert results.total == results.pages == 2
    old_result = await attention(after).commerce_snapshot(user_id=user.id, session_no=first.session_no)
    assert old_result.events[0].session_no == first.session_no
    assert '当时订单尚未付款' in old_result.events[0].message
    await attention(after).mark_read([old_result.events[0].id], user_id=user.id, reader_id=user.id)
    assert (await attention(after).summary(user_id=user.id))['table_total'] == 1
    stranger = await _user('unrelated-owner')
    with pytest.raises(TableSessionNotFound):
        await tables.get_user_session(first.session_no, user_id=stranger.id)
    with pytest.raises(AttentionNotFound):
        await attention(after).mark_read([old_result.events[0].id], user_id=stranger.id, reader_id=stranger.id)


@pytest.mark.parametrize('operation', ['payment', 'release', 'timeout'])
async def test_event_failure_rolls_back_business_and_money(operation, monkeypatch):
    now, user, admin, order, table, tables, payment = await setup()
    session = await claim(tables, user, order, table)
    repository = payment.attention_repository if operation == 'payment' else tables.attention_repository
    monkeypatch.setattr(repository, 'create_commerce_event', AsyncMock(side_effect=RuntimeError('event unavailable')))
    with pytest.raises(RuntimeError, match='event unavailable'):
        if operation == 'payment':
            await payment.pay_order_with_wallet(user=user, order_id=order.id, idempotency_key='rollback-wallet', table_session_no=session.session_no, ip_address='127.0.0.1')
        elif operation == 'release':
            await tables.release_session(session_no=session.session_no, operator_id=admin.id, reason='顾客离店', idempotency_key='release-test', ip_address='127.0.0.1')
        else:
            await tables.converge_session(session.id, now=session.payment_deadline_at + timedelta(seconds=1))
    assert (await Order.get(id=order.id)).status == OrderStatus.PENDING
    assert (await TableSession.get(id=session.id)).status == 'awaiting_payment'
    assert await Payment.all().count() == await AttentionEvent.all().count() == 0


async def test_timeout_blocks_payment_and_keeps_independent_table_reminder():
    now, user, admin, order, table, tables, _ = await setup()
    session = await claim(tables, user, order, table)
    after = session.payment_deadline_at + timedelta(seconds=1)
    with pytest.raises(TablePaymentWindowExpired):
        await _manual_order_service(now=after).mark_order_paid(order.id, operator_id=admin.id, ip_address='127.0.0.1')
    assert await Payment.all().count() == 0
    assert (await attention(after).commerce_snapshot(user_id=user.id, order_id=order.id)).events == []
    await tables.converge_session(session.id, now=after)
    snapshot = await attention(after).commerce_snapshot(user_id=user.id, session_no=session.session_no)
    assert len(snapshot.events) == 1
    assert snapshot.events[0].session_no == session.session_no
    assert (await attention(after).summary(user_id=user.id))['table_total'] == 1


async def test_refunds_excluded_and_list_paginates_before_mapping():
    now, user, admin, order, _, _, _ = await setup()
    await _manual_order_service(now=now).mark_order_paid(order.id, operator_id=admin.id, ip_address='127.0.0.1')
    settlement = await PaymentSettlement.get(order_id=order.id)
    refund = await Refund.create(refund_no='RF' + '1' * 26, settlement=settlement, order=order, operator=admin, amount=order.total_amount, reason='测试退款', idempotency_key='refund-test')
    for status in ['pending', 'succeeded']:
        refund.status = status
        await refund.save()
        assert (await attention(now).summary(user_id=None))['order_fulfillment'] == 0
    for sequence in range(2, 5):
        await _order(user, sequence=sequence, durations=[(60, 1)])
    page = await attention(now).list_commerce(user_id=None, scope='orders', view='all', page=2, page_size=2)
    assert page.total == 3 and page.pages == 2 and len(page.items) == 1


async def test_http_snapshot_and_history_are_owner_only(client):
    now, user, admin, order, table, tables, _ = await setup()
    session = await claim(tables, user, order, table)
    stranger = await _user('http-stranger')
    for path in (f'/api/v1/attention/orders/{order.id}', f'/api/v1/attention/tables/{session.session_no}', f'/api/v1/table-sessions/history/{session.session_no}'):
        assert (await client.get(path)).status_code == 401
        response = await client.get(path, headers=_headers(user))
        assert response.status_code == 200, response.text
        assert (await client.get(path, headers=_headers(stranger))).status_code == 404
        assert (await client.get(path, headers=_headers(admin))).status_code == 403
    assert (await client.get('/api/v1/admin/attention/commerce/orders', headers=_headers(user))).status_code == 403
    result = await client.get('/api/v1/admin/attention/commerce/tables', headers=_headers(admin))
    assert result.status_code == 200, result.text
    assert result.json()['data']['total'] == 1
    assert (await client.get('/api/v1/attention/commerce/invalid', headers=_headers(user))).status_code == 422


async def test_independent_expiry_and_admin_release_are_single_results():
    now, user, admin, order, table, tables, payment = await setup()
    first = await claim(tables, user, order, table)
    await payment.pay_order_with_wallet(user=user, order_id=order.id, idempotency_key='expiry-wallet', table_session_no=first.session_no, ip_address='127.0.0.1')
    first = await TableSession.get(id=first.id)
    await tables.converge_session(first.id, now=first.table_release_at)
    await tables.converge_session(first.id, now=first.table_release_at)
    assert await AttentionEvent.filter(event_type=AttentionEventType.SESSION_TIME_EXPIRED).count() == 1
    second_order = await _order(user, sequence=2, durations=[(60, 1)])
    tables.now_provider = lambda: first.table_release_at
    second = await claim(tables, user, second_order, table, 'release-new-session')
    for _ in range(2):
        await tables.release_session(session_no=second.session_no, operator_id=admin.id, reason='顾客离店', idempotency_key='release-same', ip_address='127.0.0.1')
    assert await AttentionEvent.filter(event_type=AttentionEventType.SESSION_ADMIN_RELEASED).count() == 1
    assert (await attention(first.table_release_at).summary(user_id=user.id))['table_unread'] == 2


async def test_customer_session_list_paginates_own_history_without_creating_reminders(client):
    now, user, admin, order, table, tables, payment = await setup()
    first = await claim(tables, user, order, table)
    expired = first.payment_deadline_at + timedelta(seconds=1)
    await tables.converge_session(first.id, now=expired)
    tables.now_provider = lambda: expired
    second = await claim(tables, user, order, table, 'second-history-session')
    events = await AttentionEvent.filter(user_id=user.id)
    await attention(expired).mark_read([event.id for event in events], user_id=user.id, reader_id=user.id)
    stranger = await _user('history-stranger')
    path = '/api/v1/attention/table-sessions'
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=_headers(admin))).status_code == 403
    assert (await client.get(path, headers=_headers(stranger))).json()['data']['total'] == 0
    assert (await client.get(path, params={'page': 0}, headers=_headers(user))).status_code == 422
    pages = []
    for page_number in (1, 2):
        response = await client.get(path, params={'page': page_number, 'page_size': 1}, headers=_headers(user))
        assert response.status_code == 200, response.text
        page = response.json()['data']
        assert page['total'] == page['pages'] == 2
        pages.append(page['items'][0])
    assert [item['session_no'] for item in pages] == [second.session_no, first.session_no]
    assert pages[1]['status_label'] == '本次桌台已结束' and not pages[1]['unread']
    assert 'qr_token' not in pages[0]
    assert (await attention(expired).summary(user_id=user.id))['table_total'] == 1
    assert (await attention(expired).summary(user_id=None))['table_total'] == 1


async def test_full_session_list_projects_expiry_without_background_convergence():
    now, user, _, order, table, tables, payment = await setup()
    session = await claim(tables, user, order, table)
    async def label_at(instant):
        result = await attention(instant).list_commerce(user_id=user.id, scope='tables', view='all', page=1, page_size=20, include_all_sessions=True)
        return result.items[0].status_label
    assert await label_at(session.payment_deadline_at) == '待付款'
    assert await label_at(session.payment_deadline_at + timedelta(microseconds=1)) == '本次桌台已结束'
    await payment.pay_order_with_wallet(user=user, order_id=order.id, idempotency_key='full-list-payment', table_session_no=session.session_no, ip_address='127.0.0.1')
    await session.refresh_from_db()
    assert await label_at(now) == '体验中'
    assert await label_at(session.table_release_at) == '本次桌台已结束'
    assert (await TableSession.get(id=session.id)).status == 'active'
