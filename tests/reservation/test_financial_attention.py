"""资金结果与业务同事务；逐笔阅读、退款合并、失败回滚和归属隔离。"""

from decimal import Decimal

import pytest

from app.common.enums.attention import AttentionEventType
from app.common.enums.product import ProductStatus, ProductType
from app.common.enums.user import UserRole, UserStatus
from app.common.exceptions.attention import AttentionNotFound
from app.models.attention import AttentionEvent
from app.models.order import Order
from app.models.payment import Payment, PaymentSettlement, Refund
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.table_session import TableOccupancy
from app.models.wallet import WalletAccount, WalletTransaction
from app.repositories.table_session_repo import TableSessionRepository
from app.services.order_service import OrderItemInput
from tests.reservation.test_commerce_attention import attention, setup, claim
from tests.table_sessions.test_table_session_http import _headers
from tests.table_sessions.test_table_session_service import _manual_order_service
from tests.wallet.services.test_assisted_wallet_order_service import _service as assisted_service
from tests.wallet.services.test_wallet_payment_refund_service_integration import _create_user, _create_wallet, _services


async def adjustment_setup():
    user = await _create_user('financial-customer')
    admin = await _create_user('financial-admin', role=UserRole.ADMIN)
    wallet = await _create_wallet(user, balance=Decimal('100.00'))
    service, _, _ = _services()
    return user, admin, wallet, service


async def adjust(service, user, admin, amount='10.00', key='adjust-result', reason='门店余额纠正'):
    return await service.adjust_balance(operator=admin, user_id=user.id, change=Decimal(amount),
                                        reason=reason, idempotency_key=key, ip_address='127.0.0.1')


async def test_adjustments_count_per_transaction_and_keep_exact_read_history():
    user, admin, wallet, service = await adjustment_setup()
    first = await adjust(service, user, admin, reason='调整说明' * 64)
    replay = await adjust(service, user, admin, reason='调整说明' * 64)
    second = await adjust(service, user, admin, '-5.00', 'adjust-negative')
    assert replay.is_replay and first.transaction.id == replay.transaction.id
    assert await AttentionEvent.all().count() == 2
    assert await WalletTransaction.all().count() == 2
    alerts = attention(first.transaction.created_at)
    summary = await alerts.summary(user_id=user.id)
    assert summary['wallet_unread'] == 2
    assert summary['order_total'] == summary['table_total'] == summary['reservation_total'] == 0
    assert (await alerts.summary(user_id=None))['wallet_unread'] == 0
    page = await alerts.list_wallet(user_id=user.id, view='unread', page=1, page_size=1)
    assert page.total == page.pages == 2
    assert page.items[0].scope == 'wallet'
    snapshot = await alerts.wallet_snapshot(user_id=user.id, event_id=page.items[0].id)
    event = snapshot.events[0]
    assert event.wallet_transaction.change_amount == Decimal('-5.00')
    assert event.wallet_transaction.id == second.transaction.id
    assert not event.read
    assert (await alerts.summary(user_id=user.id))['wallet_unread'] == 2  # GET 不代表已读
    await alerts.mark_read([event.id], user_id=user.id, reader_id=user.id)
    await alerts.mark_read([event.id], user_id=user.id, reader_id=user.id)
    assert (await alerts.summary(user_id=user.id))['wallet_unread'] == 1
    all_results = await alerts.list_wallet(user_id=user.id, view='all', page=1, page_size=20)
    assert all_results.total == 2 and not all_results.items[0].unread
    older = await alerts.wallet_snapshot(user_id=user.id, event_id=all_results.items[1].id)
    assert older.events[0].wallet_transaction.reason == '调整说明' * 64
    assert older.events[0].wallet_transaction.after_balance == Decimal('110.00')
    await wallet.refresh_from_db()
    assert wallet.balance == Decimal('105.00')


async def test_adjustment_http_is_owner_only_and_whitelists_ledger_fields(client):
    user, admin, _, service = await adjustment_setup()
    other = await _create_user('financial-other')
    adjustment = await adjust(service, user, admin)
    event = await AttentionEvent.get()
    endpoint = f'/api/v1/attention/wallet/{event.id}'
    assert (await client.get(endpoint)).status_code == 401
    assert (await client.get(endpoint, headers=_headers(admin))).status_code == 403
    assert (await client.get(endpoint, headers=_headers(other))).status_code == 404
    assert (await client.post('/api/v1/attention/read', headers=_headers(other), json={'event_ids': [event.id]})).status_code == 404
    response = await client.get(endpoint, headers=_headers(user))
    assert response.status_code == 200
    payload = response.json()['data']['events'][0]
    assert payload['wallet_transaction'] == {'id': adjustment.transaction.id, 'change_amount': '10.00', 'before_balance': '100.00', 'after_balance': '110.00', 'reason': '门店余额纠正'}
    assert 'operator_id' not in response.text and 'idempotency_key' not in response.text
    assert (await client.get('/api/v1/attention/wallet?view=pending', headers=_headers(user))).status_code == 422
    assert (await client.get('/api/v1/attention/wallet?page=0', headers=_headers(user))).status_code == 422
    listed = await client.get('/api/v1/attention/wallet', headers=_headers(other))
    assert listed.json()['data']['total'] == 0


async def test_disabled_customer_gets_adjustment_result_without_login_rights(client):
    user, admin, _, service = await adjustment_setup()
    user.status = UserStatus.DISABLED.value
    await user.save()
    await adjust(service, user, admin)
    event = await AttentionEvent.get()
    assert event.user_id == user.id and event.read_at is None
    response = await client.get('/api/v1/attention/wallet', headers=_headers(user))
    assert response.status_code == 400 and response.json()['code'] == 1005


async def test_ledger_reference_corruption_cannot_expose_another_wallet():
    user, admin, _, service = await adjustment_setup()
    other = await _create_user('ledger-other')
    await _create_wallet(other)
    foreign = await adjust(service, other, admin)
    await adjust(service, user, admin, key='own-adjustment')
    event = await AttentionEvent.get(user_id=user.id)
    # 同时验证归属，不只信任提醒接收者或解析出的流水 ID。
    await AttentionEvent.filter(id=event.id).update(event_key=f'wallet_transaction:{foreign.transaction.id}:wallet_adjusted-bad')
    with pytest.raises(AttentionNotFound):
        await attention(event.occurred_at).wallet_snapshot(user_id=user.id, event_id=event.id)
    await AttentionEvent.filter(user_id=other.id).update(event_key='corrupted-foreign-key')
    await AttentionEvent.filter(id=event.id).update(event_key=f'wallet_transaction:{foreign.transaction.id}:wallet_adjusted')
    with pytest.raises(AttentionNotFound):
        await attention(event.occurred_at).wallet_snapshot(user_id=user.id, event_id=event.id)


@pytest.mark.parametrize('method', ['wallet', 'manual'])
async def test_refund_merges_order_wallet_and_table_results_without_duplicate(method):
    now, user, admin, order, table, tables, payment = await setup()
    session = await claim(tables, user, order, table)
    if method == 'wallet':
        await payment.pay_order_with_wallet(user=user, order_id=order.id, idempotency_key='fund-pay', table_session_no=session.session_no, ip_address='127.0.0.1')
    else:
        await _manual_order_service(now=now).mark_order_paid(order.id, operator_id=admin.id, table_session_no=session.session_no, ip_address='127.0.0.1')
    _, _, refunds = _services()
    refunds.table_session_repository = TableSessionRepository()
    for _ in range(2):
        await refunds.refund_order(order.id, operator=admin, reason='测试退款说明', idempotency_key='fund-refund', ip_address='127.0.0.1')
    alerts = attention(now)
    assert (await alerts.summary(user_id=user.id))['order_unread'] == 1
    assert (await alerts.summary(user_id=user.id))['wallet_unread'] == 0
    assert (await alerts.summary(user_id=user.id))['table_unread'] == 0
    assert (await alerts.summary(user_id=None))['order_fulfillment'] == 0
    assert await Refund.all().count() == 1
    assert await AttentionEvent.all().count() == 2  # 一条付款和一条退款，订单入口只计一件。
    assert await TableOccupancy.all().count() == 0
    snapshot = await alerts.commerce_snapshot(user_id=user.id, order_id=order.id)
    refund = snapshot.events[-1]
    assert refund.session_no == session.session_no
    assert '100.00' in refund.message and '本次桌台已结束' in refund.message
    assert ('已退回会员余额' if method == 'wallet' else '具体到账请与门店核实') in refund.message
    await alerts.mark_read([snapshot.events[0].id], user_id=user.id, reader_id=user.id)
    assert (await alerts.summary(user_id=user.id))['order_unread'] == 1
    await alerts.mark_read([refund.id], user_id=user.id, reader_id=user.id)
    assert (await alerts.summary(user_id=user.id))['order_unread'] == 0


async def assisted_setup():
    user, admin, wallet, _ = await adjustment_setup()
    product = await Product.create(name='代客购买测试', product_type=ProductType.KIT, status=ProductStatus.ONLINE)
    kit = await ProductKit.create(product=product, price=Decimal('25.00'), stock=3)
    service = assisted_service()
    args = dict(operator=admin, user_id=user.id, items=[OrderItemInput(product_id=product.id, experience_option_id=None, quantity=1)], remark='内部下单备注', idempotency_key='assisted-result', ip_address='127.0.0.1')
    return user, wallet, kit, service, args


async def test_assisted_order_emits_one_safe_result_and_keeps_idempotent_replay():
    user, _, _, service, args = await assisted_setup()
    result = await service.create_assisted_wallet_order(**args)
    await service.create_assisted_wallet_order(**args)
    event = await AttentionEvent.get()
    assert event.event_type == AttentionEventType.ORDER_ASSISTED_WALLET_PAID
    assert event.order_id == result.order.id and event.user_id == user.id
    assert '25.00' in event.result_message and '75.00' in event.result_message
    assert '内部下单备注' not in event.result_message
    assert (await attention(event.occurred_at).summary(user_id=user.id))['order_unread'] == 1
    assert (await attention(event.occurred_at).summary(user_id=None))['order_fulfillment'] == 1


@pytest.mark.parametrize('operation', ['adjustment', 'assisted', 'refund'])
async def test_result_failure_rolls_back_money_inventory_and_event(monkeypatch, operation):
    if operation == 'assisted':
        user, account, kit, service, args = await assisted_setup()
        method = 'create_commerce_event'
        execute = lambda: service.create_assisted_wallet_order(**args)
    elif operation == 'adjustment':
        user, admin, account, service = await adjustment_setup()
        method = 'create_wallet_event'
        execute = lambda: adjust(service, user, admin)
    else:
        now, user, admin, order, table, tables, payment = await setup()
        session = await claim(tables, user, order, table)
        await payment.pay_order_with_wallet(user=user, order_id=order.id, idempotency_key='rollback-pay', table_session_no=session.session_no, ip_address='127.0.0.1')
        account = await WalletAccount.get(user_id=user.id)
        _, _, service = _services()
        service.table_session_repository = TableSessionRepository()
        method = 'create_commerce_event'
        execute = lambda: service.refund_order(order.id, operator=admin, reason='回滚测试', idempotency_key='rollback-refund', ip_address='127.0.0.1')
    balance = account.balance
    counts = [await model.all().count() for model in (WalletTransaction, Payment, PaymentSettlement, Order, AttentionEvent, TableOccupancy)]
    original = getattr(service.attention_repository, method)
    async def fail_after_insert(**kwargs):
        await original(**kwargs)
        raise RuntimeError('injected result failure')
    monkeypatch.setattr(service.attention_repository, method, fail_after_insert)
    with pytest.raises(RuntimeError, match='injected result failure'):
        await execute()
    await account.refresh_from_db()
    assert account.balance == balance
    assert [await model.all().count() for model in (WalletTransaction, Payment, PaymentSettlement, Order, AttentionEvent, TableOccupancy)] == counts
    assert await Refund.all().count() == 0
    if operation == 'assisted':
        await kit.refresh_from_db()
        assert kit.stock == 3
    if operation == 'refund':
        await session.refresh_from_db()
        assert session.status.value == 'active'
