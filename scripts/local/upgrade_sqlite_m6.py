#!/usr/bin/env python3
"""Safely upgrade a persistent local SQLite database to the M6 schema.

The production migration remains the MySQL/Aerich migration.  This script is
only for a local SQLite development database whose existing data must be kept.
It previews by default and requires ``--apply`` before making a timestamped
backup and applying the SQLite-specific schema changes.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final


M6_COLUMNS: Final[dict[str, frozenset[str]]] = {
    "product_kits": frozenset({"kit_kind", "sale_unit_grams"}),
    "order_items": frozenset(
        {
            "kit_color_id",
            "kit_color_slot_no",
            "kit_color_code",
            "kit_color_name",
            "sale_unit_grams",
        }
    ),
    "inventory_transactions": frozenset({"kit_color_id"}),
}
M6_TABLES: Final[frozenset[str]] = frozenset(
    {"bead_colors", "product_kit_colors"}
)
REQUIRED_BASELINE_TABLES: Final[frozenset[str]] = frozenset(M6_COLUMNS)
BEAD_COLOR_SLOT_COUNT: Final[int] = 221


class MigrationError(RuntimeError):
    """Raised when a local database is not a supported M6 upgrade target."""


@dataclass(frozen=True, slots=True)
class SchemaState:
    missing_columns: dict[str, frozenset[str]]
    missing_tables: frozenset[str]
    already_current: bool


def quote_identifier(identifier: str) -> str:
    """Quote an internally controlled SQLite identifier."""

    return '"' + identifier.replace('"', '""') + '"'


def table_names(connection: sqlite3.Connection) -> frozenset[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return frozenset(str(row[0]) for row in rows)


def column_names(connection: sqlite3.Connection, table: str) -> frozenset[str]:
    rows = connection.execute(
        f"PRAGMA table_info({quote_identifier(table)})"
    ).fetchall()
    return frozenset(str(row[1]) for row in rows)


def inspect_schema(connection: sqlite3.Connection) -> SchemaState:
    """Inspect whether the database is a supported pre- or post-M6 schema."""

    tables = table_names(connection)
    missing_baseline = REQUIRED_BASELINE_TABLES - tables
    if missing_baseline:
        raise MigrationError(
            "unsupported SQLite baseline; missing tables: "
            + ", ".join(sorted(missing_baseline))
        )

    missing_columns = {
        table: expected - column_names(connection, table)
        for table, expected in M6_COLUMNS.items()
    }
    missing_tables = M6_TABLES - tables
    already_current = not missing_tables and not any(missing_columns.values())
    return SchemaState(
        missing_columns=missing_columns,
        missing_tables=missing_tables,
        already_current=already_current,
    )


def validate_partial_color_tables(connection: sqlite3.Connection) -> None:
    """Accept only empty auto-created tables or a complete 221-slot catalog."""

    tables = table_names(connection)
    if "product_kit_colors" in tables:
        color_rows = connection.execute(
            "SELECT COUNT(*) FROM product_kit_colors"
        ).fetchone()[0]
        if color_rows:
            raise MigrationError(
                "product_kit_colors already contains data; refuse an ambiguous "
                "partial local migration"
            )
    if "bead_colors" not in tables:
        return
    count, minimum, maximum, distinct_count = connection.execute(
        "SELECT COUNT(*), MIN(slot_no), MAX(slot_no), COUNT(DISTINCT slot_no) "
        "FROM bead_colors"
    ).fetchone()
    if count not in (0, BEAD_COLOR_SLOT_COUNT):
        raise MigrationError(
            f"bead_colors has {count} rows; expected 0 or {BEAD_COLOR_SLOT_COUNT}"
        )
    if count and (minimum, maximum, distinct_count) != (
        1,
        BEAD_COLOR_SLOT_COUNT,
        BEAD_COLOR_SLOT_COUNT,
    ):
        raise MigrationError("bead_colors does not contain exactly slots 1..221")


def user_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """Snapshot all pre-existing business-table row counts."""

    excluded = M6_TABLES | frozenset({"sqlite_sequence", "aerich"})
    return {
        table: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table)}"
            ).fetchone()[0]
        )
        for table in sorted(table_names(connection) - excluded)
    }


def create_backup(database: Path, backup_dir: Path) -> Path:
    """Create a consistent SQLite backup before any schema write."""

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"{database.name}.pre-m6-{timestamp}.bak"
    if backup.exists():
        raise MigrationError(f"backup path already exists: {backup}")
    source = sqlite3.connect(database)
    destination = sqlite3.connect(backup)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return backup


def create_color_tables(connection: sqlite3.Connection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS "bead_colors" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            "created_at" TIMESTAMP NOT NULL,
            "updated_at" TIMESTAMP NOT NULL,
            "slot_no" SMALLINT NOT NULL UNIQUE,
            "color_code" VARCHAR(50) UNIQUE,
            "name" VARCHAR(100),
            "swatch_image_url" VARCHAR(2048),
            "sort" SMALLINT NOT NULL DEFAULT 0,
            "is_active" INT NOT NULL DEFAULT 0
        )""",
        """CREATE INDEX IF NOT EXISTS "idx_bead_colors_active_sort_slot"
            ON "bead_colors" ("is_active", "sort", "slot_no")""",
        """CREATE TABLE IF NOT EXISTS "product_kit_colors" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            "created_at" TIMESTAMP NOT NULL,
            "updated_at" TIMESTAMP NOT NULL,
            "is_enabled" INT NOT NULL DEFAULT 0,
            "stock_units" INT NOT NULL DEFAULT 0,
            "bead_color_id" BIGINT NOT NULL
                REFERENCES "bead_colors" ("id") ON DELETE RESTRICT,
            "product_id" BIGINT NOT NULL
                REFERENCES "products" ("id") ON DELETE RESTRICT,
            CONSTRAINT "uidx_product_kit_colors_product_color"
                UNIQUE ("product_id", "bead_color_id")
        )""",
        """CREATE INDEX IF NOT EXISTS "idx_product_kit_colors_product_enabled"
            ON "product_kit_colors" ("product_id", "is_enabled")""",
        """CREATE INDEX IF NOT EXISTS "idx_product_kit_colors_color_enabled"
            ON "product_kit_colors" ("bead_color_id", "is_enabled")""",
    )
    for statement in statements:
        connection.execute(statement)


def rebuild_product_kits(connection: sqlite3.Connection) -> None:
    existing = column_names(connection, "product_kits")
    if M6_COLUMNS["product_kits"] <= existing:
        return
    if existing != frozenset(
        {"id", "created_at", "updated_at", "price", "stock", "product_id"}
    ):
        raise MigrationError(
            "product_kits is neither the supported pre-M6 nor post-M6 shape"
        )
    statements = (
        """CREATE TABLE "product_kits__m6_new" (
            "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            "created_at" TIMESTAMP NOT NULL,
            "updated_at" TIMESTAMP NOT NULL,
            "price" VARCHAR(40) NOT NULL,
            "stock" INT DEFAULT 0,
            "kit_kind" VARCHAR(20) NOT NULL DEFAULT 'fixed',
            "sale_unit_grams" SMALLINT,
            "product_id" BIGINT NOT NULL UNIQUE
                REFERENCES "products" ("id") ON DELETE RESTRICT
        )""",
        """INSERT INTO "product_kits__m6_new" (
            "id", "created_at", "updated_at", "price", "stock",
            "kit_kind", "sale_unit_grams", "product_id"
        )
        SELECT
            "id", "created_at", "updated_at", "price", "stock",
            'fixed', NULL, "product_id"
        FROM product_kits""",
        'DROP TABLE "product_kits"',
        'ALTER TABLE "product_kits__m6_new" RENAME TO "product_kits"',
    )
    for statement in statements:
        connection.execute(statement)


def add_column_if_missing(
    connection: sqlite3.Connection,
    *,
    table: str,
    column: str,
    definition: str,
) -> None:
    if column not in column_names(connection, table):
        connection.execute(
            f"ALTER TABLE {quote_identifier(table)} "
            f"ADD COLUMN {quote_identifier(column)} {definition}"
        )


def extend_referencing_tables(connection: sqlite3.Connection) -> None:
    for column, definition in (
        (
            "kit_color_id",
            'BIGINT REFERENCES "product_kit_colors" ("id") ON DELETE RESTRICT',
        ),
        ("kit_color_slot_no", "SMALLINT"),
        ("kit_color_code", "VARCHAR(50)"),
        ("kit_color_name", "VARCHAR(100)"),
        ("sale_unit_grams", "SMALLINT"),
    ):
        add_column_if_missing(
            connection,
            table="order_items",
            column=column,
            definition=definition,
        )
    add_column_if_missing(
        connection,
        table="inventory_transactions",
        column="kit_color_id",
        definition=(
            'BIGINT REFERENCES "product_kit_colors" ("id") ON DELETE RESTRICT'
        ),
    )
    connection.execute(
        'CREATE INDEX IF NOT EXISTS "idx_inventory_color_created_id" '
        'ON "inventory_transactions" ("kit_color_id", "created_at", "id")'
    )


def seed_bead_color_slots(connection: sqlite3.Connection) -> None:
    count = connection.execute("SELECT COUNT(*) FROM bead_colors").fetchone()[0]
    if count == BEAD_COLOR_SLOT_COUNT:
        return
    if count:
        raise MigrationError("refuse to extend a partial bead_colors catalog")
    now = datetime.now(timezone.utc).isoformat(sep=" ")
    connection.executemany(
        "INSERT INTO bead_colors "
        "(created_at, updated_at, slot_no, color_code, name, "
        "swatch_image_url, sort, is_active) VALUES (?, ?, ?, NULL, NULL, NULL, ?, 0)",
        ((now, now, slot_no, slot_no) for slot_no in range(1, 222)),
    )


def verify_post_upgrade(
    connection: sqlite3.Connection,
    *,
    before_counts: dict[str, int],
) -> None:
    state = inspect_schema(connection)
    if not state.already_current:
        raise MigrationError("post-upgrade schema is incomplete")
    after_counts = user_table_counts(connection)
    if after_counts != before_counts:
        raise MigrationError("business-table row counts changed during migration")
    validate_partial_color_tables(connection)
    if connection.execute("SELECT COUNT(*) FROM product_kit_colors").fetchone()[0]:
        raise MigrationError("M6 local upgrade must not create product color mappings")
    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise MigrationError(
            f"foreign key check failed with {len(foreign_key_errors)} violation(s)"
        )


def apply_upgrade(database: Path, backup_dir: Path) -> Path | None:
    """Apply the M6 schema transactionally after making a backup."""

    with sqlite3.connect(database) as preflight:
        state = inspect_schema(preflight)
        validate_partial_color_tables(preflight)
        if state.already_current:
            verify_post_upgrade(
                preflight,
                before_counts=user_table_counts(preflight),
            )
            return None

    backup = create_backup(database, backup_dir)
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        before_counts = user_table_counts(connection)
        create_color_tables(connection)
        rebuild_product_kits(connection)
        extend_referencing_tables(connection)
        seed_bead_color_slots(connection)
        verify_post_upgrade(connection, before_counts=before_counts)
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as verification:
        verify_post_upgrade(
            verification,
            before_counts=user_table_counts(verification),
        )
    return backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply the local SQLite M6 schema upgrade.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("db.sqlite3"),
        help="Local SQLite database path (default: ./db.sqlite3).",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("backups/local-sqlite-migrations"),
        help="Directory for the mandatory pre-write backup.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create a backup and apply M6. Without this flag, only preview.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database = args.database.resolve()
    if not database.is_file():
        raise SystemExit(f"database does not exist: {database}")
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            state = inspect_schema(connection)
            validate_partial_color_tables(connection)
            counts = user_table_counts(connection)
    except (sqlite3.Error, MigrationError) as error:
        raise SystemExit(f"M6 SQLite preflight failed: {error}") from error

    print(f"database={database}")
    print(f"products={counts.get('products', 0)}")
    print(f"product_kits={counts.get('product_kits', 0)}")
    print(f"already_current={str(state.already_current).lower()}")
    if not args.apply:
        print("mode=preview")
        print("next=rerun with --apply to create a backup and migrate")
        return 0

    try:
        backup = apply_upgrade(database, args.backup_dir.resolve())
    except (sqlite3.Error, MigrationError) as error:
        raise SystemExit(f"M6 SQLite upgrade failed: {error}") from error
    print("mode=apply")
    print(f"backup={backup if backup is not None else 'not-created-already-current'}")
    print("result=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
