"""统一结算：真实 HTTP 下单、占台、库存和所有付款入口的保护。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.common.enums.order import OrderStatus
from app.common.enums.product import ProductStatus
from app.common.enums.user import UserRole
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PaymentSettlement
from app.models.inventory_transaction import InventoryTransaction
from app.models.table_session import StoreTable, TableSession, TableOccupancy, TableSessionTimer
from app.models.wallet import WalletAccount
from app.tasks.table_reconcile import reconcile
from app.repositories.table_session_repo import TableSessionRepository
from tests.order.api.test_order_api_integration import _create_online_option
from tests.order.services.test_color_selectable_order_integration import _color_kit
from tests.table_sessions.test_table_session_http import _headers, _user


async def setup_checkout():
    user = await _user('checkout-customer')
    table = await StoreTable.create(table_no='T08', display_name='8号桌', qr_token='A' * 32)
    product, option = await _create_online_option()
    await WalletAccount.create(user=user, balance=Decimal('500'))
    body = {'items': [{'product_id': product.id, 'experience_option_id': option.id, 'quantity': 1}],
            'table_no': 'T08', 'table_checkout_key': 'checkout-one', 'remark': '到店体验'}
    return user, table, product, body


async def test_atomic_checkout_replay_and_cart_payment_start_table(client):
    user, table, product, body = await setup_checkout()
    kit_product, color = await _color_kit()
    body['items'].append({'product_id': kit_product.id, 'kit_color_id': color.id, 'quantity': 2})
    response = await client.post('/api/v1/orders', headers=_headers(user), json=body)
    assert response.status_code == 201, response.text
    order = response.json()['data']
    session = await TableSession.get(order_id=order['id'])
    assert session.table_id == table.id and session.status == 'awaiting_payment'
    assert session.payment_deadline_at - session.claimed_at == timedelta(minutes=15)
    assert await TableSessionTimer.all().count() == 0
    await color.refresh_from_db()
    assert color.stock_units == 3
    # 重试必须先命中已提交结果，即使商品此后下架，也不能再建单或扣库存。
    product.status = ProductStatus.OFFLINE
    await product.save()
    replay = await client.post('/api/v1/orders', headers=_headers(user), json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()['data']['id'] == order['id']
    assert await Order.all().count() == await TableSession.all().count() == 1
    assert await InventoryTransaction.all().count() == 1
    for changed in ({**body, 'remark': '另一笔'}, {**body, 'table_no': 'T09'}):
        conflict = await client.post('/api/v1/orders', headers=_headers(user), json=changed)
        assert conflict.status_code == 409, conflict.text
    other = await _user('checkout-other')
    conflict = await client.post('/api/v1/orders', headers=_headers(other), json=body)
    assert conflict.status_code == 409
    assert str(order['order_no']) not in conflict.text
    paid = await client.post(f"/api/v1/orders/{order['id']}/payments/wallet", headers=_headers(user, key='cart-payment'))
    assert paid.status_code == 201, paid.text
    await session.refresh_from_db()
    payment = await Payment.get(order_id=order['id'])
    assert session.status == 'active' and session.started_at == payment.succeeded_at
    assert await TableSessionTimer.filter(session=session).count() == 1
    assert (await reconcile(TableSessionRepository()))['violations'] == 0


@pytest.mark.parametrize('failure', ['disabled', 'occupied', 'stock', 'pure_kit'])
async def test_checkout_failures_leave_no_partial_order_or_stock(client, failure):
    user, table, _, body = await setup_checkout()
    product, color = await _color_kit(stock_units=1)
    if failure == 'occupied':
        other = await _user('checkout-occupant')
        occupied = await client.post('/api/v1/orders', headers=_headers(other), json={**body, 'table_checkout_key': 'occupied'})
        assert occupied.status_code == 201
    if failure == 'disabled':
        table.is_enabled = False
        await table.save()
    body['items'].append({'product_id': product.id, 'kit_color_id': color.id, 'quantity': 2 if failure == 'stock' else 1})
    if failure == 'pure_kit':
        body['items'] = body['items'][1:]
    counts = [await model.all().count() for model in (Order, OrderItem, TableSession, TableOccupancy, InventoryTransaction)]
    response = await client.post('/api/v1/orders', headers=_headers(user), json=body)
    assert response.status_code in (400, 409, 422), response.text
    assert [await model.all().count() for model in (Order, OrderItem, TableSession, TableOccupancy, InventoryTransaction)] == counts
    await color.refresh_from_db()
    assert color.stock_units == 1


@pytest.mark.parametrize('method', ['wallet', 'manual'])
@pytest.mark.parametrize('converged', [False, True])
async def test_expired_checkout_cannot_be_paid_as_ordinary_order(client, method, converged):
    user, table, _, body = await setup_checkout()
    response = await client.post('/api/v1/orders', headers=_headers(user), json=body)
    assert response.status_code == 201, response.text
    order_id = response.json()['data']['id']
    session = await TableSession.get(order_id=order_id)
    session.payment_deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.claimed_at = session.payment_deadline_at - timedelta(minutes=15)
    await session.save()
    if converged:
        await client.get(f'/api/v1/orders/{order_id}/table-session', headers=_headers(user))
    if method == 'wallet':
        response = await client.post(f'/api/v1/orders/{order_id}/payments/wallet', headers=_headers(user, key='expired-pay'))
    else:
        admin = await _user('checkout-admin', role=UserRole.ADMIN)
        response = await client.patch(f'/api/v1/admin/orders/{order_id}/paid', headers=_headers(admin))
    assert response.status_code == 409, response.text
    assert await Payment.all().count() == await PaymentSettlement.all().count() == await TableSessionTimer.all().count() == 0
    assert (await Order.get(id=order_id)).status == OrderStatus.PENDING
    assert (await WalletAccount.get(user=user)).balance == Decimal('500')
    # 释放过期占用，再用同一笔待付款订单重新选桌并支付。
    await client.get(f'/api/v1/orders/{order_id}/table-session', headers=_headers(user))
    rebound = await client.post('/api/v1/table-sessions', headers=_headers(user, key='rebind'), json={'table_no': 'T08', 'order_id': order_id})
    assert rebound.status_code == 201, rebound.text
    paid = await client.post(f'/api/v1/orders/{order_id}/payments/wallet', headers=_headers(user, key='rebound-pay'))
    assert paid.status_code == 201, paid.text


async def test_number_lookup_and_request_validation(client):
    user, _, _, body = await setup_checkout()
    assert (await client.get('/api/v1/tables/by-number/T08')).status_code == 401
    response = await client.get('/api/v1/tables/by-number/T08', headers=_headers(user))
    assert response.status_code == 200
    assert response.json()['data']['table_no'] == 'T08'
    assert 'qr_token' not in response.text
    for patch in ({'table_no': 'T31'}, {'table_checkout_key': None}, {'table_no': None}):
        response = await client.post('/api/v1/orders', headers=_headers(user), json={**body, **patch})
        assert response.status_code == 422, response.text
    assert await Order.all().count() == 0
