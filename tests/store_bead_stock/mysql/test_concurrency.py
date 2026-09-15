"""M15 完成迁移的专用 MySQL 上核验真实连接并发；默认跳过。"""
import asyncio
from uuid import uuid4
import pytest
from app.common.enums.user import UserRole
from app.common.exceptions.store_bead_stock import StoreBeadStockConflict
from app.models.bead_color import BeadColor
from app.models.store_bead_stock import StoreBeadStockBatch, StoreBeadStockEntry
from tests.reservation.support import create_user
from tests.store_bead_stock.test_store_bead_stock import payload, service

pytestmark = pytest.mark.mysql


async def test_mysql_first_stocktake_competing_admins():
    first = await create_user('p24first', role=UserRole.ADMIN, phone=None)
    second = await create_user('p24second', role=UserRole.ADMIN, phone=None)
    colors = await BeadColor.all().order_by('slot_no').limit(3)
    assert len(colors) == 3, 'Requires migrated catalog'
    svc = service()
    outcomes = await asyncio.gather(
        svc.write(payload(colors, [1, 2, 3]), first.id, ''),
        svc.write(payload(colors, [4, 5, 6]), second.id, ''),
        return_exceptions=True,
    )
    assert sum(isinstance(item, StoreBeadStockConflict) for item in outcomes) == 1, outcomes
    assert await StoreBeadStockBatch.all().count() == 1
    assert await StoreBeadStockEntry.all().count() == 3


async def test_mysql_simultaneous_same_request_replays_one_batch():
    admin = await create_user('p24replay', role=UserRole.ADMIN, phone=None)
    colors = await BeadColor.all().order_by('slot_no').limit(3)
    assert len(colors) == 3
    intent = payload(colors, [0, 1, 2], key=uuid4())
    svc = service()
    saved = await asyncio.gather(*(svc.write(intent, admin.id, '') for _ in range(2)))
    assert saved[0] == saved[1]
    assert await StoreBeadStockBatch.all().count() == 1
    assert await StoreBeadStockEntry.all().count() == 3
