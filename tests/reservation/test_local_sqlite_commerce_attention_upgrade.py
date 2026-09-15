"""旧提醒表保数据升级及 SQLite 启动遗留表达式索引的回归检查。"""

from pathlib import Path
import sqlite3

import pytest

from scripts.local import upgrade_sqlite_commerce_attention as upgrade


def legacy_database(path: Path, ghost_indexes: int = 0) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript('''
            CREATE TABLE users (id INTEGER PRIMARY KEY);
            CREATE TABLE reservations (id INTEGER PRIMARY KEY);
            CREATE TABLE orders (id INTEGER PRIMARY KEY, status INTEGER);
            CREATE TABLE table_sessions (id INTEGER PRIMARY KEY);
            INSERT INTO users VALUES(1);
            INSERT INTO reservations VALUES(2);
            INSERT INTO orders VALUES(3,0);
            INSERT INTO table_sessions VALUES(4);
            CREATE TABLE "attention_events" (
                "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                "created_at" TIMESTAMP NOT NULL, "updated_at" TIMESTAMP NOT NULL,
                "event_key" VARCHAR(128) NOT NULL, "event_type" VARCHAR(40) NOT NULL,
                "occurred_at" TIMESTAMP NOT NULL, "read_at" TIMESTAMP,
                "read_by_id" BIGINT REFERENCES "users" ("id") ON DELETE RESTRICT,
                "reservation_id" BIGINT NOT NULL REFERENCES "reservations" ("id") ON DELETE RESTRICT,
                "user_id" BIGINT REFERENCES "users" ("id") ON DELETE RESTRICT
            );
            INSERT INTO attention_events VALUES(8,'2026-09-14','2026-09-14','reservation:2:confirmed',
                'reservation_confirmed','2026-09-14','2026-09-14',1,2,1);
            UPDATE sqlite_sequence SET seq=50 WHERE name='attention_events';
        ''')
        for name, (unique, columns) in upgrade.LEGACY_INDEXES.items():
            connection.execute(f'CREATE {"UNIQUE " if unique else ""}INDEX "{name}" ON attention_events ({",".join(columns)})')
        for name, (_, columns) in list(upgrade.NEW_INDEXES.items())[:ghost_indexes]:
            connection.execute(f'CREATE INDEX "{name}" ON "attention_events" ("user_id", "read_at", "{columns[-1]}")')
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize('ghost_indexes', [0, 1, 2])
def test_upgrade_preserves_history_sequence_backup_and_real_indexes(tmp_path: Path, ghost_indexes: int) -> None:
    database = tmp_path / 'test.sqlite3'
    legacy_database(database, ghost_indexes)
    original = database.read_bytes()
    with sqlite3.connect(database) as connection:
        assert upgrade.inspect(connection) is False
        before = connection.execute('SELECT * FROM attention_events').fetchall()
    assert database.read_bytes() == original
    backup = upgrade.apply_upgrade(database, tmp_path / 'backup')
    assert backup and backup.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backup) as connection:
        assert upgrade.inspect(connection) is False
        assert connection.execute('SELECT * FROM attention_events').fetchall() == before
    with sqlite3.connect(database) as connection:
        assert upgrade.inspect(connection) is True
        fields = ','.join(upgrade.LEGACY_COLUMNS)
        assert connection.execute(f'SELECT {fields} FROM attention_events').fetchall() == before
        assert connection.execute('SELECT * FROM orders').fetchall() == [(3, 0)]
        assert connection.execute("SELECT seq FROM sqlite_sequence WHERE name='attention_events'").fetchone() == (50,)
        for name, (_, columns) in upgrade.NEW_INDEXES.items():
            info = connection.execute(f'PRAGMA index_info("{name}")').fetchall()
            assert tuple(row[2] for row in info) == columns
            assert all(row[1] >= 0 for row in info)
        connection.execute('PRAGMA foreign_keys=ON')
        statement = '''INSERT INTO attention_events(created_at,updated_at,event_key,event_type,
            occurred_at,user_id,order_id,session_id,result_message)
            VALUES('2026-09-14','2026-09-14','order:3:paid','order_manual_paid','2026-09-14',1,?,4,'收款结果')'''
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(statement, (99,))
        connection.execute(statement, (3,))
        assert connection.execute('SELECT id,reservation_id FROM attention_events WHERE order_id=3').fetchone() == (51, None)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(statement, (3,))
    after = database.read_bytes()
    assert upgrade.apply_upgrade(database, tmp_path / 'backup') is None
    assert database.read_bytes() == after
    assert len(list((tmp_path / 'backup').iterdir())) == 1


def test_upgrade_rolls_back_after_rebuild_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / 'test.sqlite3'
    legacy_database(database, 2)
    real_rebuild = upgrade.rebuild

    def fail(connection: sqlite3.Connection) -> None:
        real_rebuild(connection)
        raise RuntimeError('simulated post-rebuild failure')

    monkeypatch.setattr(upgrade, 'rebuild', fail)
    with pytest.raises(RuntimeError, match='simulated'):
        upgrade.apply_upgrade(database, tmp_path / 'backup')
    with sqlite3.connect(database) as connection:
        assert upgrade.inspect(connection) is False
        assert connection.execute('SELECT id,read_by_id FROM attention_events').fetchall() == [(8, 1)]
        assert connection.execute('SELECT * FROM orders').fetchall() == [(3, 0)]
    assert len(list((tmp_path / 'backup').iterdir())) == 1


@pytest.mark.parametrize('sql', [
    'ALTER TABLE attention_events ADD order_id BIGINT',
    'CREATE UNIQUE INDEX unexpected ON attention_events(user_id)',
    'CREATE TABLE incoming(id INTEGER PRIMARY KEY, event_id BIGINT REFERENCES attention_events(id))',
    'CREATE TRIGGER unexpected AFTER INSERT ON attention_events BEGIN SELECT 1; END',
])
def test_upgrade_refuses_unknown_schema_without_writes(tmp_path: Path, sql: str) -> None:
    database = tmp_path / 'test.sqlite3'
    legacy_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(sql)
    before = database.read_bytes()
    with pytest.raises(RuntimeError, match='Unexpected'):
        upgrade.apply_upgrade(database, tmp_path / 'backup')
    assert database.read_bytes() == before
    assert not (tmp_path / 'backup').exists()


def test_cli_defaults_read_only_and_requires_explicit_write_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    database = tmp_path / 'test.sqlite3'
    legacy_database(database, 2)
    before = database.read_bytes()
    monkeypatch.setattr('sys.argv', ['upgrade', '--database', str(database)])
    upgrade.main()
    assert 'upgrade_required (read-only preview)' in capsys.readouterr().out
    monkeypatch.setattr('sys.argv', ['upgrade', '--database', str(database), '--apply'])
    with pytest.raises(SystemExit) as error:
        upgrade.main()
    assert error.value.code == 2
    assert database.read_bytes() == before
