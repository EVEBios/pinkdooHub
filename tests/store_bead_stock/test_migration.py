"""M15 只新增独立台账，有盘点/历史时拒绝有损降级。"""
import importlib
import re
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from aerich.utils import decompress_dict


async def test_additive_schema_and_guarded_downgrade():
    path = next(Path('migrations/models').glob('15_*store_bead_stock.py'))
    module = importlib.import_module(f'migrations.models.{path.stem}')
    sql = await module.upgrade(None)
    assert module.RUN_IN_TRANSACTION is False
    assert sql.count('CREATE TABLE') == 3
    assert not re.search(r'(?m)^\s*(ALTER|UPDATE|DELETE|DROP)\b', sql)
    assert sql.count('ON DELETE RESTRICT') == 4
    state=decompress_dict(module.MODELS_STATE)
    assert state['models.StoreBeadStock']['table']=='store_bead_stocks'
    assert state['models.StoreBeadStockEntry']['table']=='store_bead_stock_entries'
    db=AsyncMock();db.execute_query_dict.return_value=[{'total':1}]
    with pytest.raises(RuntimeError,match='Cannot downgrade'):await module.downgrade(db)
    db.execute_query_dict.return_value=[{'total':0}]
    down=await module.downgrade(db)
    assert down.index('store_bead_stock_entries') < down.index('store_bead_stock_batches')
