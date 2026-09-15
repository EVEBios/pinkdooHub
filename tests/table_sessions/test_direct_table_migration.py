import importlib
import sqlite3
from unittest.mock import AsyncMock

import pytest
from aerich.utils import decompress_dict

from scripts.local.upgrade_sqlite_direct_tables import apply_upgrade, inspect, SESSION_COLUMNS


async def test_mysql_direct_migration_state_and_refuse_lossy_downgrade():
    migration = importlib.import_module('migrations.models.11_20260914120000_direct_table_sessions')
    sql = await migration.upgrade(None)
    assert migration.RUN_IN_TRANSACTION is False
    assert "DEFAULT 'order'" in sql
    assert sql.count('MODIFY COLUMN') == 5
    assert sql.count('ON DELETE RESTRICT') == 2
    state = decompress_dict(migration.MODELS_STATE)
    session = state['models.TableSession']
    data_fields = {field['name']: field for field in session['data_fields']}
    assert data_fields['source']['default'] == 'order'
    assert data_fields['payment_deadline_at']['nullable'] is True
    db = AsyncMock()
    db.execute_query_dict.side_effect = [[{'total': 1}], [{'total': 0}]]
    with pytest.raises(RuntimeError, match='Cannot downgrade'):
        await migration.downgrade(db)
    db.execute_query_dict.side_effect = [[{'total': 0}], [{'total': 0}]]
    assert 'BIGINT NOT NULL' in await migration.downgrade(db)


def legacy_database(path):
    connection = sqlite3.connect(path)
    connection.executescript('''
    CREATE TABLE "users" ("id" INTEGER PRIMARY KEY);
    CREATE TABLE "orders" ("id" INTEGER PRIMARY KEY);
    CREATE TABLE "experience_options" ("id" INTEGER PRIMARY KEY);
    CREATE TABLE "store_tables" ("id" INTEGER PRIMARY KEY, "qr_token" TEXT);
    CREATE TABLE "payments" ("id" INTEGER PRIMARY KEY);
    INSERT INTO users VALUES (1);
    INSERT INTO orders VALUES (1);
    INSERT INTO store_tables VALUES (1, 'unchanged-token');
    ''')
    fields = []
    for name in sorted(SESSION_COLUMNS):
        if name == 'id': fields.append('"id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL')
        elif name in ('user_id', 'order_id', 'table_id'):
            parent = {'user_id': 'users', 'order_id': 'orders', 'table_id': 'store_tables'}[name]
            fields.append(f'"{name}" BIGINT NOT NULL REFERENCES "{parent}" ("id") ON DELETE RESTRICT')
        elif name == 'payment_deadline_at': fields.append('"payment_deadline_at" TIMESTAMP NOT NULL')
        else: fields.append(f'"{name}" TEXT')
    connection.execute('CREATE TABLE "table_sessions" (' + ','.join(fields) + ')')
    connection.executescript('''
    CREATE UNIQUE INDEX uidx_table_session_no ON table_sessions(session_no);
    CREATE TABLE "table_occupancies" (
      "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, "created_at" TIMESTAMP,
      "updated_at" TIMESTAMP, "table_id" BIGINT NOT NULL REFERENCES store_tables(id),
      "session_id" BIGINT NOT NULL REFERENCES table_sessions(id),
      "user_id" BIGINT NOT NULL REFERENCES users(id), "order_id" BIGINT NOT NULL REFERENCES orders(id)
    );
    CREATE UNIQUE INDEX uidx_table_occupancy_table ON table_occupancies(table_id);
    CREATE UNIQUE INDEX uidx_table_occupancy_user ON table_occupancies(user_id);
    CREATE UNIQUE INDEX uidx_table_occupancy_order ON table_occupancies(order_id);
    CREATE UNIQUE INDEX uidx_table_occupancy_session ON table_occupancies(session_id);
    CREATE TABLE "table_session_timers" (id INTEGER PRIMARY KEY, session_id BIGINT REFERENCES table_sessions(id));
    INSERT INTO table_sessions(id, session_no, user_id, order_id, table_id, payment_deadline_at) VALUES (10, 'original', 1, 1, 1, '2026-09-14');
    INSERT INTO table_occupancies(id,session_id,table_id,user_id,order_id) VALUES (5,10,1,1,1);
    INSERT INTO table_session_timers VALUES (3,10);
    ''')
    connection.commit()
    connection.close()


def test_sqlite_upgrade_preserves_rows_tokens_foreign_keys_indexes_and_backup(tmp_path):
    database = tmp_path / 'test.sqlite3'
    legacy_database(database)
    backup = apply_upgrade(database, tmp_path / 'backups')
    assert backup and backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert inspect(connection) is False
    with sqlite3.connect(database) as connection:
        assert inspect(connection) is True
        assert connection.execute('SELECT session_no,source FROM table_sessions').fetchall() == [('original', 'order')]
        assert connection.execute('SELECT qr_token FROM store_tables').fetchone()[0] == 'unchanged-token'
        assert connection.execute('SELECT * FROM table_session_timers').fetchall() == [(3, 10)]
        assert len(connection.execute('PRAGMA index_list(table_occupancies)').fetchall()) == 4
        connection.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute('UPDATE table_sessions SET opened_by_user_id=99')
    assert apply_upgrade(database, tmp_path / 'backups') is None


def test_sqlite_upgrade_rolls_back_partial_failure(tmp_path, monkeypatch):
    database = tmp_path / 'test.sqlite3'
    legacy_database(database)
    from scripts.local import upgrade_sqlite_direct_tables as migration
    rebuild = migration.rebuild
    def fail_second(connection, table, nullable, extra=''):
        if table == 'table_occupancies':
            raise RuntimeError('simulated rebuild failure')
        rebuild(connection, table, nullable, extra)
    monkeypatch.setattr(migration, 'rebuild', fail_second)
    with pytest.raises(RuntimeError, match='simulated'):
        apply_upgrade(database, tmp_path / 'backups')
    with sqlite3.connect(database) as connection:
        assert inspect(connection) is False
        assert connection.execute('SELECT session_no FROM table_sessions').fetchone()[0] == 'original'
