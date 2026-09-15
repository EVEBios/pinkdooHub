"""P1 跨预约、订单、桌台、资金的同一用户交接与存量启用验收。"""

from decimal import Decimal

from app.common.enums.order import OrderStatus
from app.common.enums.reservation import ReservationStatus
from app.models.attention import AttentionEvent
from app.models.table_session import StoreTable
from app.models.wallet import WalletAccount
from tests.reservation.test_attention import attention, setup_reservation
from tests.reservation.support import FROZEN_NOW, make_service
from tests.reservation.test_commerce_attention import claim
from tests.reservation.test_financial_attention import adjust
from tests.table_sessions.test_table_session_service import _order, _services
from tests.wallet.services.test_wallet_payment_refund_service_integration import _services as financial_services


async def test_all_scopes_transfer_and_read_independently_with_legacy_records():
    user, admin, booking = await setup_reservation('joint')
    _, _, historical_booking = await setup_reservation('historical')
    historical_booking.status = ReservationStatus.CONFIRMED.value
    await historical_booking.save()
    historical_order = await _order(user, sequence=90, durations=[(60, 1)])
    historical_order.status = OrderStatus.COMPLETED.value
    await historical_order.save()
    order = await _order(user, sequence=91, durations=[(60, 1)])
    await WalletAccount.create(user=user, balance=Decimal('200.00'))
    table = await StoreTable.create(table_no='T09', display_name='联合验收桌台', qr_token='J' * 32)
    tables, payment = _services(now=FROZEN_NOW)
    alerts = attention()

    # 存量待办由业务事实计算，不依赖补事件；历史完成事项不突然变为未读。
    assert await AttentionEvent.all().count() == 0
    before = await alerts.summary(user_id=None)
    assert before['reservation_total'] == before['order_pending'] == 1
    assert before['table_total'] == 0
    customer = await alerts.summary(user_id=user.id)
    assert customer['reservation_unread'] == customer['order_unread'] == customer['wallet_unread'] == 0

    session = await claim(tables, user, order, table)
    pending = await alerts.summary(user_id=None)
    assert pending['table_pending'] == 1 and pending['order_pending'] == 0
    await make_service().confirm_reservation(booking.id, operator_id=admin.id, ip_address='127.0.0.1')
    await payment.pay_order_with_wallet(user=user, order_id=order.id,
        idempotency_key='joint-payment', table_session_no=session.session_no, ip_address='127.0.0.1')
    wallet, _, _ = financial_services()
    await adjust(wallet, user, admin, key='joint-adjustment')
    combined = await alerts.summary(user_id=user.id)
    assert [combined[key] for key in ('reservation_total', 'order_total', 'table_total', 'wallet_unread')] == [1, 1, 0, 1]
    admin_summary = await alerts.summary(user_id=None)
    assert admin_summary['reservation_total'] == admin_summary['table_total'] == 0
    assert admin_summary['order_fulfillment'] == 1

    # 分页与 GET 不清提醒；读资金结果不影响预约/订单，另一个设备立即见到已读。
    wallet_page = await alerts.list_wallet(user_id=user.id, view='unread', page=1, page_size=1)
    result = await alerts.wallet_snapshot(user_id=user.id, event_id=wallet_page.items[0].id)
    assert (await alerts.summary(user_id=user.id))['wallet_unread'] == 1
    await alerts.mark_read([result.events[0].id], user_id=user.id, reader_id=user.id)
    other_device = await attention().summary(user_id=user.id)
    assert [other_device[key] for key in ('reservation_total', 'order_total', 'wallet_unread')] == [1, 1, 0]
    _, events, _ = await alerts.reservation_snapshot(booking.id, user_id=user.id)
    order_result = await alerts.commerce_snapshot(user_id=user.id, order_id=order.id)
    await alerts.mark_read([events[0].id, order_result.events[0].id], user_id=user.id, reader_id=user.id)
    final = await attention().summary(user_id=user.id)
    assert all(final[key] == 0 for key in ('reservation_total', 'order_total', 'table_total', 'wallet_unread'))
    assert (await attention().summary(user_id=None))['order_fulfillment'] == 1
