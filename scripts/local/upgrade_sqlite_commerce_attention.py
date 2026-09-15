"""本地 SQLite 提醒表 M12→M13 保数据升级；默认只读，应用前须停写并单独授权。"""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3


LEGACY_COLUMNS = {
    'id': ('INTEGER', 1), 'created_at': ('TIMESTAMP', 1),
    'updated_at': ('TIMESTAMP', 1), 'event_key': ('VARCHAR(128)', 1),
    'event_type': ('VARCHAR(40)', 1), 'occurred_at': ('TIMESTAMP', 1),
    'read_at': ('TIMESTAMP', 0), 'read_by_id': ('BIGINT', 0),
    'reservation_id': ('BIGINT', 1), 'user_id': ('BIGINT', 0),
}
TARGET_COLUMNS = {
    **LEGACY_COLUMNS, 'reservation_id': ('BIGINT', 0),
    'order_id': ('BIGINT', 0), 'session_id': ('BIGINT', 0),
    'result_message': ('VARCHAR(255)', 0),
}
LEGACY_INDEXES = {
    'uidx_attention_event_key': (True, ('event_key',)),
    'idx_attention_recipient_unread': (False, ('user_id', 'read_at', 'reservation_id')),
    'idx_attention_reservation_recipient': (False, ('reservation_id', 'user_id', 'id')),
}
NEW_INDEXES = {
    'idx_attention_order_unread': (False, ('user_id', 'read_at', 'order_id')),
    'idx_attention_session_unread': (False, ('user_id', 'read_at', 'session_id')),
}


def identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def check_integrity(connection: sqlite3.Connection) -> None:
    if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise RuntimeError('Database integrity check failed')
    if connection.execute('PRAGMA foreign_key_check').fetchall():
        raise RuntimeError('Database contains invalid foreign keys')


def inspect(connection: sqlite3.Connection) -> bool:
    """仅接受 M12、已知启动产生的表达式索引形态或完整 M13；拒绝未知部分升级。"""
    columns = connection.execute('PRAGMA table_info(attention_events)').fetchall()
    shape = {row[1]: (row[2].upper(), row[3]) for row in columns}
    current = shape == TARGET_COLUMNS
    if not current and shape != LEGACY_COLUMNS:
        raise RuntimeError('Unexpected or partially upgraded attention_events columns')
    if any(row[4] is not None or row[5] != int(row[1] == 'id') for row in columns):
        raise RuntimeError('Unexpected attention_events defaults or primary key')
    expected_fks = {('read_by_id', 'users', 'id'), ('user_id', 'users', 'id'),
                    ('reservation_id', 'reservations', 'id')}
    if current:
        expected_fks |= {('order_id', 'orders', 'id'), ('session_id', 'table_sessions', 'id')}
    foreign_keys = connection.execute('PRAGMA foreign_key_list(attention_events)').fetchall()
    if {(row[3], row[2], row[4]) for row in foreign_keys} != expected_fks or any(
        row[5] != 'NO ACTION' or row[6] != 'RESTRICT' for row in foreign_keys
    ):
        raise RuntimeError('Unexpected attention_events foreign keys')
    indexes = {row[1]: row for row in connection.execute('PRAGMA index_list(attention_events)')}
    expected = LEGACY_INDEXES | NEW_INDEXES
    if not set(LEGACY_INDEXES) <= indexes.keys() or not indexes.keys() <= expected.keys():
        raise RuntimeError('Unexpected attention_events indexes')
    if current and indexes.keys() != expected.keys():
        raise RuntimeError('Missing commerce attention indexes')
    for name, row in indexes.items():
        unique, fields = expected[name]
        if bool(row[2]) != unique or row[4]:
            raise RuntimeError('Unexpected unique or partial attention index')
        actual = tuple(item[2] for item in connection.execute(f'PRAGMA index_info({identifier(name)})'))
        if actual == fields:
            continue
        # SQLite 将旧表不存在的双引号列名当成字符串，启动建索引可留下该已知形态。
        sql = connection.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0]
        known_sql = f'CREATE INDEX "{name}" ON "attention_events" ("user_id", "read_at", "{fields[-1]}")'
        if current or name not in NEW_INDEXES or actual != ('user_id', 'read_at', None) or sql != known_sql:
            raise RuntimeError('Unexpected attention index columns')
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND tbl_name='attention_events'").fetchone():
        raise RuntimeError('Unexpected attention_events trigger')
    for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if any(row[2] == 'attention_events' for row in connection.execute(f'PRAGMA foreign_key_list({identifier(table)})')):
            raise RuntimeError('Unexpected incoming attention_events foreign key')
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='attention_events__commerce_new'").fetchone():
        raise RuntimeError('Temporary upgrade table already exists')
    for parent in ('orders', 'table_sessions'):
        if not connection.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', parent)).fetchone():
            raise RuntimeError('Missing commerce parent table')
    check_integrity(connection)
    return current


def rebuild(connection: sqlite3.Connection) -> None:
    original = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='attention_events'").fetchone()[0]
    sql, count = re.subn(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?"attention_events"',
                         'CREATE TABLE "attention_events__commerce_new"', original, count=1, flags=re.I)
    if count != 1:
        raise RuntimeError('Unsupported attention_events table definition')
    sql, count = re.subn(r'("reservation_id"\s+BIGINT)\s+NOT NULL', r'\1', sql, count=1, flags=re.I)
    if count != 1:
        raise RuntimeError('Cannot safely relax reservation_id')
    position = sql.index('(') + 1
    sql = sql[:position] + '''
        "order_id" BIGINT REFERENCES "orders" ("id") ON DELETE RESTRICT,
        "session_id" BIGINT REFERENCES "table_sessions" ("id") ON DELETE RESTRICT,
        "result_message" VARCHAR(255),''' + sql[position:]
    fields = ','.join(identifier(name) for name in LEGACY_COLUMNS)
    before = connection.execute(f'SELECT {fields} FROM attention_events ORDER BY id').fetchall()
    sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='attention_events'").fetchone()
    connection.execute(sql)
    connection.execute(f'INSERT INTO attention_events__commerce_new ({fields}) SELECT {fields} FROM attention_events')
    connection.execute('DROP TABLE attention_events')
    connection.execute('ALTER TABLE attention_events__commerce_new RENAME TO attention_events')
    for name, (unique, columns) in (LEGACY_INDEXES | NEW_INDEXES).items():
        connection.execute(f'CREATE {"UNIQUE " if unique else ""}INDEX {identifier(name)} ON attention_events ({",".join(identifier(column) for column in columns)})')
    if sequence:
        connection.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name='attention_events'", sequence)
    if connection.execute(f'SELECT {fields} FROM attention_events ORDER BY id').fetchall() != before:
        raise RuntimeError('Existing attention events changed')
    if connection.execute('SELECT 1 FROM attention_events WHERE order_id IS NOT NULL OR session_id IS NOT NULL OR result_message IS NOT NULL').fetchone():
        raise RuntimeError('Unexpected historical commerce result backfill')


def database_path(database: Path) -> Path:
    if database.is_symlink() or not database.is_file():
        raise RuntimeError('Database must be an existing regular local SQLite file')
    return database.resolve()


def apply_upgrade(database: Path, backup_dir: Path) -> Path | None:
    database = database_path(database)
    connection = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        if inspect(connection):
            return None
        connection.execute('BEGIN IMMEDIATE')
        if inspect(connection):
            connection.execute('ROLLBACK')
            return None
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / ('commerce-attention-before-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
        with backup.open('xb'):
            pass
        backup.chmod(0o600)
        source = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
            check_integrity(destination)
        finally:
            source.close()
            destination.close()
        rebuild(connection)
        if not inspect(connection):
            raise RuntimeError('Upgrade verification failed')
        connection.execute('COMMIT')
        if not inspect(connection):
            raise RuntimeError('Post-commit verification failed; retain backup')
        return backup
    except BaseException:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('db.sqlite3'))
    parser.add_argument('--backup-dir', type=Path, default=Path('backups/local-sqlite-migrations'))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-local-only', action='store_true')
    parser.add_argument('--confirm-writers-stopped', action='store_true')
    args = parser.parse_args()
    if args.apply and not (args.confirm_local_only and args.confirm_writers_stopped):
        parser.error('--apply requires --confirm-local-only and --confirm-writers-stopped')
    database = database_path(args.database)
    if args.apply:
        print('Backup:', apply_upgrade(database, args.backup_dir))
    else:
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        try:
            print('already_current' if inspect(connection) else 'upgrade_required (read-only preview)')
        finally:
            connection.close()


if __name__ == '__main__':
    main()
