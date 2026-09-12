#!/usr/bin/env python3
"""Safely add and backfill ``bead_colors.swatch_hex`` in local SQLite.

The authoritative production migration is the MySQL/Aerich M8 migration. This
utility only upgrades an existing local development SQLite database while
preserving all rows. It previews by default; ``--apply`` creates a mode-0600
backup before the first write, then applies and verifies the change in one
SQLite transaction.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.tasks.mard_catalog import (
    EXPECTED_COLOR_COUNT,
    ManifestColor,
    MardCatalogError,
    load_manifest,
)


DEFAULT_DATABASE: Final = Path("db.sqlite3")
DEFAULT_MANIFEST: Final = Path("app/tasks/manifests/mard_221.json")
DEFAULT_BACKUP_DIR: Final = Path("backups/local-sqlite-migrations")
REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "id",
        "created_at",
        "updated_at",
        "slot_no",
        "color_code",
        "name",
        "swatch_image_url",
        "sort",
        "is_active",
    }
)


class MigrationError(RuntimeError):
    """Raised when a local database is not a safe M8 upgrade target."""


@dataclass(frozen=True, slots=True)
class SchemaState:
    column_present: bool
    missing_hex_values: int
    already_current: bool


@dataclass(frozen=True, slots=True)
class DataSnapshot:
    table_counts: dict[str, int]
    bead_color_rows_without_hex: tuple[tuple[object, ...], ...]


def quote_identifier(identifier: str) -> str:
    """Quote an internally controlled SQLite identifier."""

    return '"' + identifier.replace('"', '""') + '"'


def table_names(connection: sqlite3.Connection) -> frozenset[str]:
    return frozenset(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    )


def column_names(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({quote_identifier(table)})"
        ).fetchall()
    )


def inspect_schema(
    connection: sqlite3.Connection,
    colors: tuple[ManifestColor, ...],
) -> SchemaState:
    """Accept a clean pre-M8, partial safe M8, or exact post-M8 state."""

    if "bead_colors" not in table_names(connection):
        raise MigrationError("unsupported SQLite baseline; bead_colors is missing")
    columns = frozenset(column_names(connection, "bead_colors"))
    missing_columns = REQUIRED_COLUMNS - columns
    if missing_columns:
        raise MigrationError(
            "unsupported bead_colors shape; missing columns: "
            + ", ".join(sorted(missing_columns))
        )

    column_present = "swatch_hex" in columns
    if column_present:
        swatch_column = next(
            row
            for row in connection.execute("PRAGMA table_info(bead_colors)").fetchall()
            if str(row[1]) == "swatch_hex"
        )
        if str(swatch_column[2]).upper() != "VARCHAR(7)" or int(
            swatch_column[3]
        ) != 0:
            raise MigrationError(
                "existing swatch_hex must be nullable VARCHAR(7)"
            )
    projection = "slot_no, swatch_hex" if column_present else "slot_no, NULL"
    rows = tuple(
        connection.execute(
            f"SELECT {projection} FROM bead_colors ORDER BY slot_no"
        ).fetchall()
    )
    if tuple(int(row[0]) for row in rows) != tuple(
        range(1, EXPECTED_COLOR_COUNT + 1)
    ):
        raise MigrationError("bead_colors must contain exactly slots 1..221")

    missing_hex_values = 0
    for row, color in zip(rows, colors):
        current = row[1]
        if current is None:
            missing_hex_values += 1
        elif current != color.hex:
            raise MigrationError(
                f"slot {color.slot_no} has a conflicting existing swatch_hex"
            )
    return SchemaState(
        column_present=column_present,
        missing_hex_values=missing_hex_values,
        already_current=column_present and missing_hex_values == 0,
    )


def snapshot_data(connection: sqlite3.Connection) -> DataSnapshot:
    """Snapshot row counts and every pre-M8 BeadColor value."""

    tables = table_names(connection) - frozenset({"sqlite_sequence", "aerich"})
    counts = {
        table: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table)}"
            ).fetchone()[0]
        )
        for table in sorted(tables)
    }
    fields = tuple(
        field
        for field in column_names(connection, "bead_colors")
        if field != "swatch_hex"
    )
    projection = ", ".join(quote_identifier(field) for field in fields)
    rows = tuple(
        tuple(row)
        for row in connection.execute(
            f"SELECT {projection} FROM bead_colors ORDER BY slot_no"
        ).fetchall()
    )
    return DataSnapshot(
        table_counts=counts,
        bead_color_rows_without_hex=rows,
    )


def create_backup(database: Path, backup_dir: Path) -> Path:
    """Create a consistent, private SQLite backup before any write."""

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = backup_dir / f"{database.name}.pre-m8-swatch-hex-{timestamp}.bak"
    if backup.exists():
        raise MigrationError(f"backup path already exists: {backup}")
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        source = sqlite3.connect(database)
        try:
            destination = sqlite3.connect(backup)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
        os.chmod(backup, 0o600)
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def verify_post_upgrade(
    connection: sqlite3.Connection,
    *,
    colors: tuple[ManifestColor, ...],
    before: DataSnapshot,
) -> None:
    state = inspect_schema(connection, colors)
    if not state.already_current:
        raise MigrationError("post-upgrade swatch_hex backfill is incomplete")
    if snapshot_data(connection) != before:
        raise MigrationError("non-swatch data changed during the M8 upgrade")
    row = connection.execute("PRAGMA integrity_check").fetchone()
    if row is None or row[0] != "ok":
        raise MigrationError("SQLite integrity_check failed")
    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise MigrationError(
            f"foreign key check failed with {len(foreign_key_errors)} violation(s)"
        )
    distinct_hex = int(
        connection.execute(
            "SELECT COUNT(DISTINCT swatch_hex) FROM bead_colors"
        ).fetchone()[0]
    )
    if distinct_hex != EXPECTED_COLOR_COUNT:
        raise MigrationError("swatch_hex values are not the exact unique MARD set")


def apply_upgrade(
    database: Path,
    manifest: Path,
    backup_dir: Path,
) -> Path | None:
    """Apply the data-preserving local M8 upgrade and return its backup."""

    colors = load_manifest(manifest)
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as preflight:
        state = inspect_schema(preflight, colors)
        before = snapshot_data(preflight)
        if state.already_current:
            verify_post_upgrade(preflight, colors=colors, before=before)
            return None

    backup = create_backup(database, backup_dir)
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        locked_state = inspect_schema(connection, colors)
        locked_before = snapshot_data(connection)
        if locked_before != before:
            raise MigrationError("database changed after M8 preview")
        if not locked_state.column_present:
            connection.execute(
                "ALTER TABLE bead_colors ADD COLUMN swatch_hex VARCHAR(7) NULL"
            )
        connection.executemany(
            "UPDATE bead_colors SET swatch_hex=? "
            "WHERE slot_no=? AND swatch_hex IS NULL",
            ((color.hex, color.slot_no) for color in colors),
        )
        verify_post_upgrade(connection, colors=colors, before=before)
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as verify:
        verify_post_upgrade(verify, colors=colors, before=before)
    return backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply the local SQLite M8 swatch HEX upgrade.",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create a backup and apply M8. Without this flag, only preview.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database = args.database.resolve()
    manifest = args.manifest.resolve()
    if not database.is_file():
        raise SystemExit(f"database does not exist: {database}")
    if not manifest.is_file():
        raise SystemExit(f"manifest does not exist: {manifest}")
    try:
        colors = load_manifest(manifest)
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            state = inspect_schema(connection, colors)
    except (OSError, sqlite3.Error, MardCatalogError, MigrationError) as error:
        raise SystemExit(f"M8 SQLite preflight failed: {error}") from error

    print(f"database={database}")
    print(f"manifest={manifest}")
    print(f"colors={len(colors)}")
    print(f"column_present={str(state.column_present).lower()}")
    print(f"missing_hex_values={state.missing_hex_values}")
    print(f"already_current={str(state.already_current).lower()}")
    if not args.apply:
        print("mode=preview")
        print("next=review, then rerun with --apply")
        return 0

    try:
        backup = apply_upgrade(database, manifest, args.backup_dir.resolve())
    except (OSError, sqlite3.Error, MardCatalogError, MigrationError) as error:
        raise SystemExit(f"M8 SQLite upgrade failed: {error}") from error
    print("mode=apply")
    print(f"backup={backup or 'not-created-already-current'}")
    print("result=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
