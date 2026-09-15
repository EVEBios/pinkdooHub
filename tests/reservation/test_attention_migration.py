"""M12 增量结构与不可丢弃提醒历史的降级边界。"""

import importlib
from unittest.mock import AsyncMock

import pytest
from aerich.utils import decompress_dict


async def test_attention_migration_is_additive_and_preserves_existing_events():
    migration = importlib.import_module("migrations.models.12_20260914163509_attention_events")
    sql = await migration.upgrade(None)
    assert migration.RUN_IN_TRANSACTION is False
    assert "CREATE TABLE IF NOT EXISTS `attention_events`" in sql
    assert "ALTER TABLE" not in sql
    assert "INSERT INTO" not in sql
    assert sql.count("ON DELETE RESTRICT") == 3
    for name in ["uidx_attention_event_key", "idx_attention_recipient_unread", "idx_attention_reservation_recipient"]:
        assert name in sql
    state = decompress_dict(migration.MODELS_STATE)
    assert state["models.AttentionEvent"]["table"] == "attention_events"
    assert "models.TableSession" in state
    db = AsyncMock()
    db.execute_query_dict.return_value = [{"total": 1}]
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        await migration.downgrade(db)
    db.execute_query_dict.return_value = [{"total": 0}]
    assert "DROP TABLE" in await migration.downgrade(db)
