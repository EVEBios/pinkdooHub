"""只增建跟进表；已有历史禁止有损降级。"""
import importlib
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from aerich.utils import decompress_dict


async def test_followup_migration_is_additive_and_guards_history():
    path = next(Path('migrations/models').glob('14_*reservation_followups.py'))
    module = importlib.import_module(f'migrations.models.{path.stem}')
    sql = await module.upgrade(None)
    assert module.RUN_IN_TRANSACTION is False
    assert 'ALTER TABLE' not in sql and 'DELETE FROM' not in sql and 'DROP ' not in sql
    assert sql.count('ON DELETE RESTRICT') == 2
    state = decompress_dict(module.MODELS_STATE)['models.ReservationFollowup']
    assert state['table'] == 'reservation_followups'
    db = AsyncMock()
    db.execute_query_dict.return_value = [{'total': 1}]
    with pytest.raises(RuntimeError, match='Cannot downgrade'):
        await module.downgrade(db)
    db.execute_query_dict.return_value = [{'total': 0}]
    assert 'DROP TABLE IF EXISTS `reservation_followups`' in await module.downgrade(db)
