"""Gate A 专用 T01 Token 比较交换；仅通过有界 stdin 接收新值，输出摘要。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys

from tortoise import Tortoise
from tortoise.transactions import in_transaction

from app.common.enums.table_session import TableSessionStatus
from app.db.database import TORTOISE_ORM
from app.models.table_session import StoreTable, TableOccupancy, TableSession
from app.tasks.gatea_m9_failed_acceptance_verify import _reject_duplicate_keys


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def rotate(payload: dict) -> dict:
    mode = payload.get('mode')
    expected_keys = ({'mode'} if mode == 'inspect' else
                     {'mode', 'old_sha256', 'new_sha256'} if mode == 'verify' else
                     {'mode', 'old_sha256', 'new_token'})
    if set(payload) != expected_keys or mode not in {'inspect', 'apply', 'verify'}:
        raise ValueError('invalid rotation protocol')
    if mode == 'apply' and (
        re.fullmatch('[0-9a-f]{64}', str(payload['old_sha256'])) is None
        or re.fullmatch('[A-Za-z0-9]{32}', str(payload['new_token'])) is None
        or digest(payload['new_token']) == payload['old_sha256']
    ):
        raise ValueError('invalid rotation binding')
    if mode == 'verify' and any(re.fullmatch('[0-9a-f]{64}', str(payload[key])) is None for key in ('old_sha256', 'new_sha256')):
        raise ValueError('invalid rotation verification')
    async with in_transaction() as connection:
        table = await StoreTable.filter(table_no='T01').using_db(connection).select_for_update().get()
        if (await TableOccupancy.all().using_db(connection).exists()
                or await TableSession.exclude(status=TableSessionStatus.CLOSED).using_db(connection).exists()):
            raise ValueError('rotation requires a released runtime')
        current = digest(table.qr_token)
        if mode == 'apply':
            new_hash = digest(payload['new_token'])
            if current == payload['old_sha256']:
                # QuerySet.update 只修改 Token，不触碰 updated_at 或任何业务事实。
                await StoreTable.filter(id=table.id, qr_token=table.qr_token).using_db(connection).update(qr_token=payload['new_token'])
                current = new_hash
            elif current != new_hash:
                raise ValueError('rotation checkpoint drift')
            hashes = {digest(value) for value in await StoreTable.all().using_db(connection).values_list('qr_token', flat=True)}
            if payload['old_sha256'] in hashes or new_hash not in hashes:
                raise ValueError('old token remains resolvable')
        if mode == 'verify':
            hashes = {digest(value) for value in await StoreTable.all().using_db(connection).values_list('qr_token', flat=True)}
            if current != payload['new_sha256'] or payload['old_sha256'] in hashes:
                raise ValueError('rotation verification drift')
        return {'schema_version': 1, 'table_no': 'T01', 'current_sha256': current,
                'released': True, 'secret_values_recorded': False}


async def run(payload: dict) -> dict:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        return await rotate(payload)
    finally:
        await Tortoise.close_connections()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(1025)
        if len(sys.argv) != 1 or not 0 < len(raw) <= 1024:
            raise ValueError('invalid protocol')
        result = asyncio.run(run(json.loads(raw, object_pairs_hook=_reject_duplicate_keys)))
    except Exception:
        print('{"passed":false,"reason_code":"ROTATION_REFUSED","secret_values_recorded":false}')
        return 2
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
