"""M13 增量和保留已产生的订单/桌台结果历史。"""

import importlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aerich.utils import decompress_dict


async def test_commerce_migration_preserves_data_and_blocks_lossy_downgrade():
    module = next(Path('migrations/models').glob('13_*commerce_attention.py')).stem
    migration = importlib.import_module(f'migrations.models.{module}')
    sql = await migration.upgrade(None)
    assert migration.RUN_IN_TRANSACTION is False
    assert 'DROP ' not in sql and 'DELETE FROM' not in sql and 'INSERT ' not in sql
    assert sql.count('ON DELETE RESTRICT') == 2
    state = decompress_dict(migration.MODELS_STATE)['models.AttentionEvent']
    assert {field['name'] for field in state['fk_fields']} >= {'order', 'session', 'reservation'}
    db = AsyncMock()
    db.execute_query_dict.return_value = [{'total': 1}]
    with pytest.raises(RuntimeError, match='Cannot downgrade'):
        await migration.downgrade(db)
    db.execute_query_dict.return_value = [{'total': 0}]
    assert 'MODIFY COLUMN `reservation_id` BIGINT NOT NULL' in await migration.downgrade(db)
