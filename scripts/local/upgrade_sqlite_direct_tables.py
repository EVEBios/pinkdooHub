#!/usr/bin/env python3
"""本地 SQLite 直接开台升级。默认只读预览；应用前必须停止写入者并备份。

SQLite 不支持放宽列的 NOT NULL，因此仅在本次迁移连接内重建两张表。
保留全部旧列、记录、索引和外键；提交前核对数据与 foreign_key_check。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3

SESSION_COLUMNS = {
    'id', 'created_at', 'updated_at', 'session_no', 'table_id', 'user_id', 'order_id',
    'payment_id', 'status', 'claim_idempotency_key', 'claim_request_fingerprint',
    'release_idempotency_key', 'claimed_at', 'payment_deadline_at', 'started_at',
    'table_release_at', 'closed_at', 'close_reason', 'closed_by_user_id', 'admin_close_reason',
}
OCCUPANCY_COLUMNS = {'id', 'created_at', 'updated_at', 'table_id', 'session_id', 'user_id', 'order_id'}
NEW_COLUMNS = {'source', 'opened_by_user_id', 'source_option_id', 'direct_duration_minutes', 'opening_note'}


def columns(connection: sqlite3.Connection, table: str) -> dict[str, tuple]:
    return {row[1]: row for row in connection.execute(f'PRAGMA table_info("{table}")')}


def inspect(connection: sqlite3.Connection) -> bool:
    """只接受完整 M9/M10 桌台结构或完整升级结构，拒绝部分应用。"""
    sessions = columns(connection, 'table_sessions')
    occupancy = columns(connection, 'table_occupancies')
    if set(occupancy) != OCCUPANCY_COLUMNS:
        raise RuntimeError('Unexpected table_occupancies schema')
    current = set(sessions) == SESSION_COLUMNS | NEW_COLUMNS
    if not current and set(sessions) != SESSION_COLUMNS:
        raise RuntimeError('Unexpected or partially applied table_sessions schema')
    for table, fields in [('table_sessions', ('user_id', 'order_id', 'payment_deadline_at')),
                          ('table_occupancies', ('user_id', 'order_id'))]:
        shape = columns(connection, table)
        if any(bool(shape[field][3]) == current for field in fields):
            raise RuntimeError(f'Unexpected nullability in {table}')
    if current:
        if sessions['source'][3] != 1 or sessions['source'][4] != "'order'":
            raise RuntimeError('Unexpected source definition')
        foreign_keys = {(row[3], row[2], row[4]) for row in connection.execute('PRAGMA foreign_key_list("table_sessions")')}
        if not {('opened_by_user_id', 'users', 'id'), ('source_option_id', 'experience_options', 'id')} <= foreign_keys:
            raise RuntimeError('Missing direct session foreign keys')
    if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise RuntimeError('Database integrity check failed')
    if connection.execute('PRAGMA foreign_key_check').fetchall():
        raise RuntimeError('Database contains invalid foreign keys')
    return current


def rebuild(connection: sqlite3.Connection, table: str, nullable: tuple[str, ...], extra: str = '') -> None:
    original = connection.execute('SELECT sql FROM sqlite_master WHERE type = ? AND name = ?', ('table', table)).fetchone()[0]
    indexes = [row[0] for row in connection.execute(
        'SELECT sql FROM sqlite_master WHERE type = ? AND tbl_name = ? AND sql IS NOT NULL', ('index', table),
    )]
    if connection.execute('SELECT 1 FROM sqlite_master WHERE type = ? AND tbl_name = ?', ('trigger', table)).fetchone():
        raise RuntimeError(f'Unexpected trigger on {table}')
    temporary = table + '__direct_new'
    sql, count = re.subn(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?["`]' + table + r'["`]', f'CREATE TABLE "{temporary}"', original, count=1, flags=re.I)
    if count != 1:
        raise RuntimeError(f'Unsupported CREATE TABLE spelling for {table}')
    for field in nullable:
        sql, count = re.subn(r'(["`]' + field + r'["`]\s+\w+(?:\(\d+\))?)\s+NOT NULL', r'\1', sql, count=1, flags=re.I)
        if count != 1:
            raise RuntimeError(f'Cannot safely relax {table}.{field}')
    if extra:
        # 字段必须位于表级约束之前，因此紧跟开括号插入。
        pos = sql.index('(') + 1
        sql = sql[:pos] + extra + ',' + sql[pos:]
    old_columns = ','.join(f'"{field}"' for field in columns(connection, table))
    before = connection.execute(f'SELECT {old_columns} FROM "{table}" ORDER BY id').fetchall()
    sequence = connection.execute('SELECT seq FROM sqlite_sequence WHERE name = ?', (table,)).fetchone()
    connection.execute(sql)
    connection.execute(f'INSERT INTO "{temporary}" ({old_columns}) SELECT {old_columns} FROM "{table}"')
    connection.execute(f'DROP TABLE "{table}"')
    connection.execute(f'ALTER TABLE "{temporary}" RENAME TO "{table}"')
    for index in indexes:
        connection.execute(index)
    if sequence:
        connection.execute('UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?', (sequence[0], table))
    after = connection.execute(f'SELECT {old_columns} FROM "{table}" ORDER BY id').fetchall()
    if before != after:
        raise RuntimeError(f'Existing data changed in {table}')


def apply_upgrade(database: Path, backup_dir: Path) -> Path | None:
    database = database.absolute()
    if database.is_symlink() or not database.is_file():
        raise RuntimeError('Database must be an existing regular local SQLite file')
    connection = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, isolation_level=None)
    backup = None
    try:
        if inspect(connection):
            return None
        # 重建父表期间仅本连接暂缓 FK 执行；锁定写入，提交前完整核验，再恢复 FK。
        connection.execute('PRAGMA foreign_keys = OFF')
        connection.execute('BEGIN IMMEDIATE')
        if inspect(connection):
            connection.execute('ROLLBACK')
            return None
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / ('direct-tables-before-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
        with backup.open('xb'):
            pass
        backup.chmod(0o600)
        source = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
            if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup integrity check failed')
        finally:
            source.close()
            destination.close()
        rebuild(connection, 'table_sessions', ('user_id', 'order_id', 'payment_deadline_at'), '''
            "source" VARCHAR(20) NOT NULL DEFAULT 'order',
            "opened_by_user_id" BIGINT REFERENCES "users" ("id") ON DELETE RESTRICT,
            "source_option_id" BIGINT REFERENCES "experience_options" ("id") ON DELETE RESTRICT,
            "direct_duration_minutes" INT,
            "opening_note" VARCHAR(200)''')
        rebuild(connection, 'table_occupancies', ('user_id', 'order_id'))
        if not inspect(connection):
            raise RuntimeError('Upgrade verification failed')
        connection.execute('COMMIT')
        connection.execute('PRAGMA foreign_keys = ON')
        if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1 or not inspect(connection):
            raise RuntimeError('Post-commit verification failed; retain the backup')
        return backup
    except BaseException:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        raise
    finally:
        connection.execute('PRAGMA foreign_keys = ON')
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('db.sqlite3'))
    parser.add_argument('--backup-dir', type=Path, default=Path('backups/local-sqlite-migrations'))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-local-only', action='store_true')
    parser.add_argument('--confirm-writers-stopped', action='store_true')
    args = parser.parse_args()
    if args.database.is_symlink() or not args.database.is_file():
        parser.error('Database must be an existing regular local file')
    if args.apply:
        if not args.confirm_local_only or not args.confirm_writers_stopped:
            parser.error('--apply requires --confirm-local-only and --confirm-writers-stopped')
        print('Backup:', apply_upgrade(args.database, args.backup_dir))
    else:
        connection = sqlite3.connect(args.database.absolute().as_uri() + '?mode=ro', uri=True)
        try:
            print('already_current' if inspect(connection) else 'upgrade_required (read-only preview)')
        finally:
            connection.close()


if __name__ == '__main__':
    main()
