"""门店库存真实数据库与 HTTP 回归；不复用商城余额。"""
from uuid import uuid4
import pytest
from app.core.security import create_access_token
from app.common.enums.user import UserRole
from app.common.exceptions.store_bead_stock import StoreBeadStockConflict, StoreBeadBatchConflict, StoreBeadStockUnchanged
from app.models.bead_color import BeadColor
from app.models.store_bead_stock import StoreBeadStock, StoreBeadStockBatch, StoreBeadStockEntry
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.repositories.store_bead_stock_repo import StoreBeadStockRepository
from app.repositories.audit_log_repo import AuditLogRepository
from app.services.audit_log_service import AuditLogService
from app.services.store_bead_stock_service import StoreBeadStockService
from app.schemas.store_bead_stock import StoreBeadStockWrite
from tests.reservation.support import create_user


def service():
    return StoreBeadStockService(StoreBeadStockRepository(), AuditLogService(AuditLogRepository()))


async def setup():
    admin = await create_user('stockadmin', role=UserRole.ADMIN, phone=None)
    colors = [await BeadColor.create(slot_no=i, color_code=f'A{i}', name=f'A{i}', sort=i) for i in range(1,4)]
    return admin, colors


def payload(colors, packs, revisions=None, key=None):
    return StoreBeadStockWrite(request_key=key or uuid4(), items=[dict(bead_color_id=c.id, expected_revision=(revisions or [0]*len(colors))[i], packs=packs[i]) for i,c in enumerate(colors)])


async def test_first_stocktake_zero_is_not_uninitialized_and_does_not_touch_commerce():
    admin, colors = await setup()
    svc = service()
    initial = await svc.list_stock(1, 221)
    assert [i.packs for i in initial.items] == [None]*3
    assert await StoreBeadStock.all().count() == 0
    result = await svc.write(payload(colors, [0,1,2]), admin.id, '127.0.0.1')
    assert [i.before_packs for i in result.items] == [None]*3
    assert [i.after_packs for i in result.items] == [0,1,2]
    assert [i.revision for i in result.items] == [1]*3
    assert [i.packs for i in (await svc.list_stock(1,221)).items] == [0,1,2]
    assert await InventoryTransaction.all().count() == 0
    assert await AuditLog.filter(action='ADJUST_STORE_BEAD_STOCK').count() == 1


async def test_mixed_batch_and_exact_original_replay_after_later_changes():
    admin, colors = await setup(); svc = service()
    first = payload(colors, [3,0,2])
    await svc.write(first, admin.id, '')
    change = payload(colors,[2,5,1],[1]*3)
    saved = await svc.write(change,admin.id,'')
    assert [(i.before_packs,i.after_packs) for i in saved.items] == [(3,2),(0,5),(2,1)]
    await svc.write(payload(colors[:1],[9],[2]),admin.id,'')
    replay = await svc.write(change,admin.id,'')
    assert replay == saved
    assert (await svc.by_request(str(change.request_key),admin.id)) == saved
    assert (await svc.detail(saved.id)) == saved
    assert await StoreBeadStockBatch.all().count() == 3
    with pytest.raises(StoreBeadBatchConflict):
        await svc.write(payload(colors,[1,5,1],[1]*3,key=change.request_key),admin.id,'')


async def test_conflict_does_not_save_other_colors_or_audit():
    admin, colors = await setup(); svc=service()
    await svc.write(payload(colors,[3,3,3]),admin.id,'')
    other = await create_user('otheradmin',role=UserRole.ADMIN,phone=None)
    await svc.write(payload(colors[:1],[2],[1]),other.id,'')
    with pytest.raises(StoreBeadStockConflict) as caught:
        await svc.write(payload(colors,[1,1,1],[1]*3),admin.id,'')
    assert caught.value.data['conflicts'] == [{'bead_color_id':colors[0].id,'packs':2,'revision':2}]
    assert [i.packs for i in (await svc.list_stock(1,221)).items] == [2,3,3]
    assert await StoreBeadStockBatch.all().count() == 2
    assert await AuditLog.filter(action='ADJUST_STORE_BEAD_STOCK').count() == 2
    # 未修改颜色的独立变化不阻挡当前提交。
    await svc.write(payload(colors[1:],[0,1],[1,1]),admin.id,'')


async def test_unchanged_rejected_but_zero_initialization_allowed():
    admin, colors=await setup(); svc=service()
    await svc.write(payload(colors[:1],[0]),admin.id,'')
    with pytest.raises(StoreBeadStockUnchanged):
        await svc.write(payload(colors[:1],[0],[1]),admin.id,'')
    assert await StoreBeadStockEntry.all().count()==1


async def test_batch_atomic_rollback_on_audit_failure(monkeypatch):
    admin, colors=await setup(); svc=service()
    async def fail(**kwargs): raise RuntimeError('injected audit failure')
    monkeypatch.setattr(svc.audit,'log',fail)
    with pytest.raises(RuntimeError): await svc.write(payload(colors,[3,4,5]),admin.id,'')
    assert await StoreBeadStock.all().count()==0
    assert await StoreBeadStockBatch.all().count()==0
    assert await StoreBeadStockEntry.all().count()==0


async def test_history_pagination_and_snapshot_survives_catalog_rename():
    admin, colors=await setup(); svc=service()
    result=await svc.write(payload(colors,[2,1,0]),admin.id,'')
    colors[0].color_code='A-new'; await colors[0].save()
    assert (await svc.detail(result.id)).items[0].color_code=='A1'
    page=await svc.history(1,1)
    assert page.total==1 and page.items[0].changed_colors==3
    assert (await svc.history(2,1)).items==[]
    assert (await svc.list_stock(2,2)).items[0].bead_color_id==colors[2].id


async def test_http_permissions_validation_and_request_lookup(client):
    admin,colors=await setup()
    user=await create_user('stockcustomer',phone=None)
    def headers(u):return {'Authorization':f'Bearer {create_access_token(u.id,str(uuid4()),auth_version=u.auth_version)}'}
    root='/api/v1/admin/store-bead-stock'
    body=payload(colors,[0,1,2]).model_dump(mode='json')
    for path in [root,root+'/batches']:
        assert (await client.get(path)).status_code==401
        assert (await client.get(path,headers=headers(user))).status_code==403
        assert (await client.get(path,headers=headers(admin))).status_code==200
    assert (await client.post(root+'/batches',json=body,headers=headers(user))).status_code==403
    for bad in [[],body['items']*2,[{**body['items'][0],'packs':-1}],[{**body['items'][0],'packs':True}],[{**body['items'][0],'packs':1.5}],[{**body['items'][0],'expected_revision':True}]]:
        assert (await client.post(root+'/batches',json={**body,'items':bad},headers=headers(admin))).status_code==422
    for patch in [{'operator_id':user.id},{'reason':'bad'},{'note':'x'*501}]:
        assert (await client.post(root+'/batches',json={**body,**patch},headers=headers(admin))).status_code==422
    result=await client.post(root+'/batches',json=body,headers=headers(admin));assert result.status_code==200,result.text
    missing=await client.get(root+'/batches/by-request/'+str(uuid4()),headers=headers(admin));assert missing.status_code==404
    other=await create_user('stockadmin2',role=UserRole.ADMIN,phone=None)
    assert (await client.get(root+'/batches/by-request/'+body['request_key'],headers=headers(other))).status_code==404
    assert (await client.get(root+'/batches/by-request/'+body['request_key'],headers=headers(admin))).json()['data']==result.json()['data']
    assert (await client.get(root+'/batches/'+str(result.json()['data']['id']),headers=headers(admin))).status_code==200
    assert (await client.get(root+'?page_size=222',headers=headers(admin))).status_code==422


async def test_concurrent_first_stocktake_exactly_one_writer():
    import asyncio
    admin,colors=await setup();svc=service()
    outcomes=await asyncio.gather(svc.write(payload(colors,[1,2,3]),admin.id,''),svc.write(payload(colors,[4,5,6]),admin.id,''),return_exceptions=True)
    assert sum(isinstance(o,StoreBeadStockConflict) for o in outcomes)==1
    assert await StoreBeadStockBatch.all().count()==1
    assert await StoreBeadStockEntry.all().count()==3


async def test_simultaneous_duplicate_is_one_batch():
    import asyncio
    admin,colors=await setup();svc=service();intent=payload(colors,[0,1,2])
    outcomes=await asyncio.gather(svc.write(intent,admin.id,''),svc.write(intent,admin.id,''))
    assert outcomes[0].id==outcomes[1].id
    assert await StoreBeadStockBatch.all().count()==1
