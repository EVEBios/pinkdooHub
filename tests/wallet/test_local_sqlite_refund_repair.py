"""Contracts for the narrow local SQLite refunds schema repair."""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path
import sys

import pytest

from scripts.local import repair_sqlite_refunds_schema
from scripts.local.repair_sqlite_refunds_schema import (
    ORDER_UNIQUE_INDEX,
    RefundSchemaRepairError,
    all_table_counts,
    apply_repair,
    inspect_schema,
)


def create_refund_database(
    path: Path,
    *,
    include_inventory_restored: bool = False,
    include_order_unique: bool = False,
    include_refund: bool = False,
) -> None:
    inventory_column = (
        ', "inventory_restored" INT NOT NULL DEFAULT 0'
        if include_inventory_restored
        else ""
    )
    order_unique = " UNIQUE" if include_order_unique else ""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            f"""
            PRAGMA foreign_keys = ON;
            CREATE TABLE "users" ("id" INTEGER PRIMARY KEY);
            CREATE TABLE "orders" ("id" INTEGER PRIMARY KEY);
            CREATE TABLE "payment_settlements" ("id" INTEGER PRIMARY KEY);
            CREATE TABLE "preserved_rows" (
                "id" INTEGER PRIMARY KEY,
                "value" TEXT NOT NULL
            );
            INSERT INTO "preserved_rows" VALUES (1, 'must survive');
            CREATE TABLE "refunds" (
                "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                "created_at" TIMESTAMP NOT NULL,
                "updated_at" TIMESTAMP NOT NULL,
                "refund_no" VARCHAR(28) NOT NULL UNIQUE,
                "amount" VARCHAR(40) NOT NULL,
                "status" VARCHAR(32) NOT NULL DEFAULT 'pending',
                "reason" VARCHAR(256) NOT NULL,
                "idempotency_key" VARCHAR(256) NOT NULL,
                "provider_refund_id" VARCHAR(128),
                "succeeded_at" TIMESTAMP,
                "operator_id" BIGINT NOT NULL
                    REFERENCES "users" ("id") ON DELETE RESTRICT,
                "order_id" BIGINT NOT NULL{order_unique}
                    REFERENCES "orders" ("id") ON DELETE RESTRICT,
                "settlement_id" BIGINT NOT NULL UNIQUE
                    REFERENCES "payment_settlements" ("id") ON DELETE RESTRICT
                {inventory_column}
            );
            CREATE UNIQUE INDEX "uidx_refund_idempotency"
                ON "refunds" ("idempotency_key");
            CREATE UNIQUE INDEX "uidx_refund_provider_reference"
                ON "refunds" ("provider_refund_id");
            CREATE INDEX "idx_refund_order_created_id"
                ON "refunds" ("order_id", "created_at", "id");
            CREATE INDEX "idx_refund_status_created_id"
                ON "refunds" ("status", "created_at", "id");
            """
        )
        if include_refund:
            connection.executescript(
                """
                INSERT INTO "users" VALUES (1);
                INSERT INTO "orders" VALUES (1);
                INSERT INTO "payment_settlements" VALUES (1);
                INSERT INTO "refunds" (
                    "created_at", "updated_at", "refund_no", "amount",
                    "status", "reason", "idempotency_key", "operator_id",
                    "order_id", "settlement_id"
                ) VALUES (
                    '2026-09-07', '2026-09-07', 'RF20260907000000000000000001',
                    '19.90', 'succeeded', 'test', 'refund-key-1', 1, 1, 1
                );
                """
            )
        connection.commit()
    finally:
        connection.close()


def test_repair_adds_only_supported_schema_and_preserves_every_row(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    backup_dir = tmp_path / "backups"
    create_refund_database(database)
    with sqlite3.connect(database) as connection:
        before_counts = all_table_counts(connection)

    backup = apply_repair(database, backup_dir)

    assert backup is not None and backup.is_file()
    with sqlite3.connect(database) as connection:
        assert inspect_schema(connection).already_current is True
        assert all_table_counts(connection) == before_counts
        inventory = next(
            row
            for row in connection.execute('PRAGMA table_info("refunds")')
            if row[1] == "inventory_restored"
        )
        assert inventory[2:6] == ("INT", 1, "0", 0)
        order_index = connection.execute(
            f"PRAGMA index_info(\"{ORDER_UNIQUE_INDEX}\")"
        ).fetchall()
        assert [row[2] for row in order_index] == ["order_id"]
        listed = {
            row[1]: row[2]
            for row in connection.execute('PRAGMA index_list("refunds")')
        }
        assert listed[ORDER_UNIQUE_INDEX] == 1
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute('INSERT INTO "users" VALUES (1)')
        connection.execute('INSERT INTO "orders" VALUES (1)')
        connection.executemany(
            'INSERT INTO "payment_settlements" VALUES (?)',
            ((1,), (2,)),
        )
        connection.execute(
            """INSERT INTO "refunds" (
                "created_at", "updated_at", "refund_no", "amount",
                "status", "reason", "idempotency_key", "operator_id",
                "order_id", "settlement_id"
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "2026-09-07",
                "2026-09-07",
                "RF20260907000000000000000001",
                "19.90",
                "succeeded",
                "test",
                "refund-key-1",
                1,
                1,
                1,
            ),
        )
        assert connection.execute(
            'SELECT "inventory_restored" FROM "refunds"'
        ).fetchone() == (0,)
        with pytest.raises(sqlite3.IntegrityError, match="order_id"):
            connection.execute(
                """INSERT INTO "refunds" (
                    "created_at", "updated_at", "refund_no", "amount",
                    "status", "reason", "idempotency_key", "operator_id",
                    "order_id", "settlement_id"
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "2026-09-07",
                    "2026-09-07",
                    "RF20260907000000000000000002",
                    "19.90",
                    "succeeded",
                    "test",
                    "refund-key-2",
                    1,
                    1,
                    2,
                ),
            )
        connection.rollback()


def test_already_current_replay_is_zero_write_and_creates_no_backup(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    backup_dir = tmp_path / "backups"
    create_refund_database(
        database,
        include_inventory_restored=True,
        include_order_unique=True,
    )
    before_bytes = database.read_bytes()
    before_mtime_ns = database.stat().st_mtime_ns

    backup = apply_repair(database, backup_dir)

    assert backup is None
    assert database.read_bytes() == before_bytes
    assert database.stat().st_mtime_ns == before_mtime_ns
    assert not backup_dir.exists()


@pytest.mark.parametrize(
    ("include_inventory_restored", "include_order_unique"),
    [(False, False), (True, False), (False, True)],
)
def test_incomplete_schema_with_existing_refund_fails_closed(
    tmp_path: Path,
    include_inventory_restored: bool,
    include_order_unique: bool,
) -> None:
    database = tmp_path / "db.sqlite3"
    backup_dir = tmp_path / "backups"
    create_refund_database(
        database,
        include_inventory_restored=include_inventory_restored,
        include_order_unique=include_order_unique,
        include_refund=True,
    )
    before = database.read_bytes()

    with pytest.raises(
        RefundSchemaRepairError,
        match="contains rows while its schema is incomplete",
    ):
        apply_repair(database, backup_dir)

    assert database.read_bytes() == before
    assert not backup_dir.exists()


def test_backup_is_private_verified_and_contains_committed_wal_rows(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    backup_dir = tmp_path / "backups"
    create_refund_database(database)
    writer = sqlite3.connect(database)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        writer.execute(
            'INSERT INTO "preserved_rows" ("id", "value") VALUES (2, ?)',
            ("committed in WAL",),
        )
        writer.commit()

        backup = apply_repair(database, backup_dir)
    finally:
        writer.close()

    assert backup is not None
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as connection:
        assert connection.execute(
            'SELECT "value" FROM "preserved_rows" WHERE "id" = 2'
        ).fetchone() == ("committed in WAL",)
        assert inspect_schema(connection).already_current is False
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_database_symlink_is_rejected_before_any_backup(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite3"
    link = tmp_path / "linked.sqlite3"
    backup_dir = tmp_path / "backups"
    create_refund_database(database)
    link.symlink_to(database)

    with pytest.raises(RefundSchemaRepairError, match="must not be a symlink"):
        apply_repair(link, backup_dir)

    assert not backup_dir.exists()


def test_cli_apply_requires_explicit_local_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "db.sqlite3"
    backup_dir = tmp_path / "backups"
    create_refund_database(database)
    monkeypatch.setattr(
        repair_sqlite_refunds_schema,
        "REPOSITORY_ROOT",
        tmp_path,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "repair_sqlite_refunds_schema.py",
            "--database",
            str(database),
            "--backup-dir",
            str(backup_dir),
            "--apply",
        ],
    )

    with pytest.raises(SystemExit, match="--apply requires --confirm-local-only"):
        repair_sqlite_refunds_schema.main()

    with sqlite3.connect(database) as connection:
        state = inspect_schema(connection)
        assert state.missing_inventory_restored is True
        assert state.missing_order_unique is True
    assert not backup_dir.exists()
