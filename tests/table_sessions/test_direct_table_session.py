from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.api.mappers.table_session import map_admin_table_session
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.enums.user import UserRole
from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.experience_option import ExperienceOption
from app.models.order import Order
from app.models.payment import Payment, PaymentSettlement
from app.models.product import Product
from app.models.table_session import StoreTable, TableOccupancy, TableSession, TableSessionTimer
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.table_session_repo import TableSessionRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.table_session_service import TableSessionService
from app.tasks.table_reconcile import reconcile
from tests.table_sessions.test_table_session_http import _user, _headers, _experience_order


def service(now):
    return TableSessionService(
        TableSessionRepository(), OrderRepository(), UserRepository(), PaymentRepository(),
        AuditLogService(AuditLogRepository()), product_repository=ProductRepository(),
        now_provider=lambda: now,
    )


async def setup_direct():
    admin = await _user('direct-admin', role=UserRole.ADMIN)
    table = await StoreTable.create(table_no='T01', display_name='T01号桌', qr_token='A' * 32)
    product = await Product.create(name='拼豆体验', product_type=ProductType.EXPERIENCE, status=ProductStatus.OFFLINE)
    option = await ExperienceOption.create(product=product, duration=60, participants=1, day_type=DayType.WEEKDAY, price=Decimal('60'))
    return admin, table, product, option


async def test_direct_open_replay_conflict_release_and_no_financial_records(client):
    admin, table, product, option = await setup_direct()
    headers = _headers(admin, key='direct-one')
    path = f'/api/v1/admin/tables/{table.id}/direct-sessions'
    body = {'option_id': option.id, 'duration_minutes': 60, 'note': ' 美团 '}
    response = await client.post(path, headers=headers, json=body)
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['source'] == 'direct'
    assert data['order_id'] is None and data['user_id'] is None and data['payment_id'] is None
    assert data['payment_deadline_at'] is None
    assert data['opening_note'] == '美团'
    assert data['timers'][0]['experience_items'] == []
    assert data['status']['value'] == 'active'
    assert data['started_at'] == data['claimed_at']
    start = datetime.fromisoformat(data['started_at'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(data['table_release_at'].replace('Z', '+00:00'))
    assert end - start == timedelta(minutes=70)
    replay = await client.post(path, headers=headers, json=body)
    assert replay.status_code == 200
    assert replay.json()['data']['session_no'] == data['session_no']
    assert replay.json()['data']['started_at'] == data['started_at']
    conflict = await client.post(path, headers=headers, json={**body, 'note': '其他'})
    assert conflict.json()['code'] == 40965
    occupied = await client.post(path, headers=_headers(admin, key='other'), json=body)
    assert occupied.json()['code'] == 40961
    assert await TableSession.all().count() == await TableOccupancy.all().count() == await TableSessionTimer.all().count() == 1
    assert await Order.all().count() == await Payment.all().count() == await PaymentSettlement.all().count() == 0
    assert await AuditLog.filter(action='DIRECT_OPEN_TABLE_SESSION').count() == 1
    assert (await reconcile(TableSessionRepository()))['violations'] == 0
    listing = (await client.get('/api/v1/admin/tables', headers=headers)).json()['data']['items'][0]
    assert listing['current_source'] == 'direct' and listing['timer_count'] == 1
    assert listing['service_ends_at'] == data['timers'][0]['service_ends_at']
    assert listing['timers'] == [{key: data['timers'][0][key] for key in ('id', 'duration_minutes', 'service_ends_at', 'grace_ends_at')}]
    history = await client.get('/api/v1/admin/table-sessions', headers=headers)
    assert history.status_code == 200, history.text
    released = await client.post(f"/api/v1/admin/table-sessions/{data['session_no']}/release", headers=_headers(admin, key='release-direct'), json={'reason': '顾客提前离店'})
    assert released.status_code == 200, released.text
    cleared = (await client.get('/api/v1/admin/tables', headers=headers)).json()['data']['items'][0]
    assert cleared['timers'] == [] and cleared['current_status'] is None
    assert await TableOccupancy.all().count() == 0
    assert (await reconcile(TableSessionRepository()))['violations'] == 0


async def test_options_deduplicate_and_reject_changed_deleted_draft_and_disabled(client):
    admin, table, product, option = await setup_direct()
    await ExperienceOption.create(product=product, duration=60, participants=2, day_type=DayType.HOLIDAY, price=Decimal('90'))
    await ExperienceOption.create(product=product, duration=120, participants=1, day_type=DayType.WEEKDAY, price=Decimal('100'))
    headers = _headers(admin, key='invalid-option')
    options = await client.get('/api/v1/admin/table-duration-options', headers=headers)
    assert [x['duration_minutes'] for x in options.json()['data']['items']] == [60, 120]
    path = f'/api/v1/admin/tables/{table.id}/direct-sessions'
    body = {'option_id': option.id, 'duration_minutes': 120}
    assert (await client.post(path, headers=headers, json=body)).json()['code'] == 42262
    body['duration_minutes'] = 60
    product.status = ProductStatus.DRAFT
    await product.save()
    assert (await client.post(path, headers=headers, json=body)).json()['code'] == 42262
    product.status = ProductStatus.OFFLINE
    await product.save()
    option.is_deleted = True
    await option.save()
    assert (await client.post(path, headers=headers, json=body)).json()['code'] == 42262
    option.is_deleted = False
    await option.save()
    table.is_enabled = False
    await table.save()
    assert (await client.post(path, headers=headers, json=body)).json()['code'] == 40961
    assert await TableSession.all().count() == 0


async def test_direct_permissions_validation_and_feature_flag(client, monkeypatch):
    admin, table, _, option = await setup_direct()
    path = f'/api/v1/admin/tables/{table.id}/direct-sessions'
    body = {'option_id': option.id, 'duration_minutes': 60}
    assert (await client.post(path, json=body)).status_code == 401
    customer = await _user('direct-customer')
    assert (await client.post(path, headers=_headers(customer, key='forbidden'), json=body)).status_code == 403
    assert (await client.post(path, headers=_headers(admin), json=body)).status_code == 422
    assert (await client.post(path, headers=_headers(admin, key='invalid'), json={**body, 'duration_minutes': True})).status_code == 422
    monkeypatch.setattr(settings, 'app_env', 'production')
    monkeypatch.setattr(settings, 'table_session_claims_enabled', False)
    assert (await client.post(path, headers=_headers(admin, key='disabled'), json=body)).status_code == 503
    assert await TableSession.all().count() == await AuditLog.all().count() == 0


async def test_direct_snapshot_and_exact_expiry():
    admin, table, product, option = await setup_direct()
    start = datetime.now(timezone.utc)
    svc = service(start)
    result = await svc.create_direct_session(table_id=table.id, option_id=option.id, duration_minutes=60, note=None, operator_id=admin.id, idempotency_key='snapshot', ip_address='127.0.0.1')
    option.duration = 120
    await option.save()
    detail = map_admin_table_session(result.session, server_now=start + timedelta(minutes=60))
    assert detail.timers[0].phase.value == 'grace'
    assert await svc.converge_session(result.session.id, now=start + timedelta(minutes=70, microseconds=-1)) is False
    assert await svc.converge_session(result.session.id, now=start + timedelta(minutes=70)) is True
    assert await TableOccupancy.all().count() == 0
    assert (await reconcile(TableSessionRepository()))['violations'] == 0


async def test_direct_audit_failure_rolls_back(monkeypatch):
    admin, table, _, option = await setup_direct()
    svc = service(datetime.now(timezone.utc))
    async def fail(*args, **kwargs):
        raise RuntimeError('audit unavailable')
    monkeypatch.setattr(svc.audit_log_service, 'log', fail)
    with pytest.raises(RuntimeError, match='audit unavailable'):
        await svc.create_direct_session(table_id=table.id, option_id=option.id, duration_minutes=60, note=None, operator_id=admin.id, idempotency_key='rollback', ip_address='127.0.0.1')
    assert await TableSession.all().count() == await TableOccupancy.all().count() == await TableSessionTimer.all().count() == 0


async def test_manual_payment_from_table_starts_timer_once(client):
    admin, table, _, _ = await setup_direct()
    customer = await _user('manual-customer')
    order = await _experience_order(customer)
    created = await client.post('/api/v1/table-sessions', headers=_headers(customer, key='manual-claim'), json={'qr_token': table.qr_token, 'order_id': order.id})
    session_no = created.json()['data']['session_no']
    headers = {**_headers(admin), 'Table-Session-No': session_no}
    paid = await client.patch(f'/api/v1/admin/orders/{order.id}/paid', headers=headers)
    assert paid.status_code == 200, paid.text
    detail = (await client.get(f'/api/v1/admin/table-sessions/{session_no}', headers=headers)).json()['data']
    assert detail['status']['value'] == 'active' and detail['source'] == 'order'
    assert detail['order_total_amount'] == '80.00'
    duplicate = await client.patch(f'/api/v1/admin/orders/{order.id}/paid', headers=headers)
    assert duplicate.status_code == 409
    assert await Payment.all().count() == await PaymentSettlement.all().count() == 1
    assert await TableSessionTimer.all().count() == 2
    current = (await client.get('/api/v1/table-sessions/current', headers=_headers(customer))).json()['data']
    assert current['started_at'] == detail['started_at']


async def test_independent_direct_tables_allow_multiple_null_user_order_and_block_customer_claim(client):
    admin, first, _, option = await setup_direct()
    second = await StoreTable.create(table_no='T02', display_name='T02号桌', qr_token='B' * 32)
    body = {'option_id': option.id, 'duration_minutes': 60}
    for table in (first, second):
        result = await client.post(f'/api/v1/admin/tables/{table.id}/direct-sessions', headers=_headers(admin, key=f'direct-{table.id}'), json=body)
        assert result.status_code == 200, result.text
    assert await TableOccupancy.filter(user_id=None, order_id=None).count() == 2
    customer = await _user('blocked-scan-customer')
    order = await _experience_order(customer, sequence=9)
    claimed = await client.post('/api/v1/table-sessions', headers=_headers(customer, key='occupied-scan'), json={'qr_token': first.qr_token, 'order_id': order.id})
    assert claimed.status_code == 409 and claimed.json()['code'] == 40961
    assert await TableSession.all().count() == 2
    assert (await client.get('/api/v1/table-sessions/current', headers=_headers(customer))).json()['data'] is None
    assert (await reconcile(TableSessionRepository()))['violations'] == 0


async def test_direct_open_refuses_table_held_by_unpaid_order(client):
    admin, table, _, option = await setup_direct()
    customer = await _user('first-claim-customer')
    order = await _experience_order(customer, sequence=10)
    claimed = await client.post('/api/v1/table-sessions', headers=_headers(customer, key='first-claim'), json={'qr_token': table.qr_token, 'order_id': order.id})
    assert claimed.status_code == 201
    direct = await client.post(f'/api/v1/admin/tables/{table.id}/direct-sessions', headers=_headers(admin, key='second-direct'), json={'option_id': option.id, 'duration_minutes': 60})
    assert direct.status_code == 409 and direct.json()['code'] == 40961
    assert await TableSession.all().count() == 1
    assert await TableSessionTimer.all().count() == 0
