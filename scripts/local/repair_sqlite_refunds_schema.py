#!/usr/bin/env python3
"""Repair the one supported local SQLite ``refunds`` schema drift.

This deliberately narrow tool only adds the M4 ``inventory_restored`` column
and the missing one-refund-per-order UNIQUE index.  It previews by default and
requires both ``--apply`` and ``--confirm-local-only`` before writing.  A
verified SQLite backup is mandatory before the first schema change.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import stat
from typing import Final


DEFAULT_DATABASE: Final = Path("db.sqlite3")
DEFAULT_BACKUP_DIR: Final = Path("backups/local-sqlite-migrations")
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
SQLITE_HEADER: Final = b"SQLite format 3\x00"
ORDER_UNIQUE_INDEX: Final = "uidx_refund_order_id"


class RefundSchemaRepairError(RuntimeError):
    """Raised when the SQLite target is not the one supported drift."""


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    declared_type: str
    not_null: bool
    default: str | None = None
    primary_key: bool = False


@dataclass(frozen=True, slots=True)
class RefundSchemaState:
    missing_inventory_restored: bool
    missing_order_unique: bool
    refund_count: int

    @property
    def already_current(self) -> bool:
        return not self.missing_inventory_restored and not self.missing_order_unique


LEGACY_COLUMN_SPECS: Final[dict[str, ColumnSpec]] = {
    "id": ColumnSpec("INTEGER", True, primary_key=True),
    "created_at": ColumnSpec("TIMESTAMP", True),
    "updated_at": ColumnSpec("TIMESTAMP", True),
    "refund_no": ColumnSpec("VARCHAR(28)", True),
    "amount": ColumnSpec("VARCHAR(40)", True),
    "status": ColumnSpec("VARCHAR(32)", True, default="pending"),
    "reason": ColumnSpec("VARCHAR(256)", True),
    "idempotency_key": ColumnSpec("VARCHAR(256)", True),
    "provider_refund_id": ColumnSpec("VARCHAR(128)", False),
    "succeeded_at": ColumnSpec("TIMESTAMP", False),
    "operator_id": ColumnSpec("BIGINT", True),
    "order_id": ColumnSpec("BIGINT", True),
    "settlement_id": ColumnSpec("BIGINT", True),
}
INVENTORY_RESTORED_SPEC: Final = ColumnSpec("INT", True, default="0")
REQUIRED_NAMED_INDEXES: Final[dict[str, tuple[bool, tuple[str, ...]]]] = {
    "uidx_refund_idempotency": (True, ("idempotency_key",)),
    "uidx_refund_provider_reference": (True, ("provider_refund_id",)),
    "idx_refund_order_created_id": (
        False,
        ("order_id", "created_at", "id"),
    ),
    "idx_refund_status_created_id": (
        False,
        ("status", "created_at", "id"),
    ),
}
REQUIRED_FOREIGN_KEYS: Final = frozenset(
    {
        ("operator_id", "users", "id", "RESTRICT"),
        ("order_id", "orders", "id", "RESTRICT"),
        (
            "settlement_id",
            "payment_settlements",
            "id",
            "RESTRICT",
        ),
    }
)


def quote_identifier(identifier: str) -> str:
    """Quote an internally controlled SQLite identifier."""

    return '"' + identifier.replace('"', '""') + '"'


def validate_database_file(database: Path) -> Path:
    """Require an existing regular, non-symlink SQLite database file."""

    path = database.absolute()
    try:
        file_stat = path.lstat()
    except OSError as error:
        raise RefundSchemaRepairError(
            f"cannot inspect database file: {error}"
        ) from error
    if stat.S_ISLNK(file_stat.st_mode):
        raise RefundSchemaRepairError("database must not be a symlink")
    if not stat.S_ISREG(file_stat.st_mode):
        raise RefundSchemaRepairError("database must be a regular file")
    try:
        with path.open("rb") as database_file:
            header = database_file.read(len(SQLITE_HEADER))
    except OSError as error:
        raise RefundSchemaRepairError(f"cannot read database file: {error}") from error
    if header != SQLITE_HEADER:
        raise RefundSchemaRepairError("database does not have a SQLite 3 header")
    return path


def _read_only_connection(database: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)


def _normalise_default(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    return text


def _table_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def all_table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """Snapshot the row count of every table, including SQLite metadata tables."""

    return {
        table: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table)}"
            ).fetchone()[0]
        )
        for table in _table_names(connection)
    }


def _index_columns(connection: sqlite3.Connection, index_name: str) -> tuple[str, ...]:
    rows = connection.execute(
        f"PRAGMA index_info({quote_identifier(index_name)})"
    ).fetchall()
    return tuple(str(row[2]) for row in rows)


def _index_definitions(
    connection: sqlite3.Connection,
) -> dict[str, tuple[bool, tuple[str, ...]]]:
    rows = connection.execute('PRAGMA index_list("refunds")').fetchall()
    return {
        str(row[1]): (bool(row[2]), _index_columns(connection, str(row[1])))
        for row in rows
    }


def _validate_columns(connection: sqlite3.Connection) -> bool:
    rows = connection.execute('PRAGMA table_info("refunds")').fetchall()
    if not rows:
        raise RefundSchemaRepairError("unsupported baseline; refunds table is missing")
    by_name = {str(row[1]): row for row in rows}
    allowed_names = set(LEGACY_COLUMN_SPECS) | {"inventory_restored"}
    names = set(by_name)
    missing_legacy = set(LEGACY_COLUMN_SPECS) - names
    unexpected = names - allowed_names
    if missing_legacy or unexpected:
        details: list[str] = []
        if missing_legacy:
            details.append("missing=" + ",".join(sorted(missing_legacy)))
        if unexpected:
            details.append("unexpected=" + ",".join(sorted(unexpected)))
        raise RefundSchemaRepairError(
            "unsupported refunds column baseline; " + "; ".join(details)
        )

    specs = dict(LEGACY_COLUMN_SPECS)
    if "inventory_restored" in names:
        specs["inventory_restored"] = INVENTORY_RESTORED_SPEC
    for name, spec in specs.items():
        row = by_name[name]
        actual = ColumnSpec(
            declared_type=str(row[2]).upper(),
            not_null=bool(row[3]),
            default=_normalise_default(row[4]),
            primary_key=bool(row[5]),
        )
        if actual != spec:
            raise RefundSchemaRepairError(
                f"unsupported refunds column definition: {name}"
            )
    return "inventory_restored" not in names


def _validate_foreign_keys(connection: sqlite3.Connection) -> None:
    actual = frozenset(
        (
            str(row[3]),
            str(row[2]),
            str(row[4]),
            str(row[6]).upper(),
        )
        for row in connection.execute('PRAGMA foreign_key_list("refunds")')
    )
    if actual != REQUIRED_FOREIGN_KEYS:
        raise RefundSchemaRepairError("unsupported refunds foreign-key baseline")


def _validate_indexes(connection: sqlite3.Connection) -> bool:
    indexes = _index_definitions(connection)
    for name, expected in REQUIRED_NAMED_INDEXES.items():
        if indexes.get(name) != expected:
            raise RefundSchemaRepairError(
                f"unsupported refunds index baseline: {name}"
            )
    unique_shapes = {
        columns for is_unique, columns in indexes.values() if is_unique
    }
    for columns in (("refund_no",), ("settlement_id",)):
        if columns not in unique_shapes:
            raise RefundSchemaRepairError(
                "unsupported refunds UNIQUE baseline: " + columns[0]
            )
    if (
        ORDER_UNIQUE_INDEX in indexes
        and indexes[ORDER_UNIQUE_INDEX] != (True, ("order_id",))
    ):
        raise RefundSchemaRepairError(
            f"unsupported index definition: {ORDER_UNIQUE_INDEX}"
        )
    return ("order_id",) not in unique_shapes


def inspect_schema(connection: sqlite3.Connection) -> RefundSchemaState:
    """Accept only the exact legacy/current refunds table and known drift."""

    missing_column = _validate_columns(connection)
    _validate_foreign_keys(connection)
    missing_unique = _validate_indexes(connection)
    refund_count = int(
        connection.execute('SELECT COUNT(*) FROM "refunds"').fetchone()[0]
    )
    if refund_count and (missing_column or missing_unique):
        raise RefundSchemaRepairError(
            "refunds contains rows while its schema is incomplete; refuse repair"
        )
    return RefundSchemaState(
        missing_inventory_restored=missing_column,
        missing_order_unique=missing_unique,
        refund_count=refund_count,
    )


def _verify_integrity(connection: sqlite3.Connection) -> None:
    integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
    if integrity_rows != [("ok",)]:
        raise RefundSchemaRepairError("SQLite integrity_check failed")
    foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_rows:
        raise RefundSchemaRepairError(
            f"foreign_key_check found {len(foreign_key_rows)} violation(s)"
        )


def verify_current_schema(
    connection: sqlite3.Connection,
    *,
    expected_counts: dict[str, int],
) -> None:
    """Verify the repaired schema, row preservation, and database integrity."""

    state = inspect_schema(connection)
    if not state.already_current:
        raise RefundSchemaRepairError("post-repair refunds schema is incomplete")
    if all_table_counts(connection) != expected_counts:
        raise RefundSchemaRepairError("table row counts changed during repair")
    _verify_integrity(connection)


def _backup_path(database: Path, backup_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return backup_dir / f"{database.name}.pre-refunds-repair-{timestamp}.bak"


def create_verified_backup(
    database: Path,
    backup_dir: Path,
    *,
    expected_counts: dict[str, int],
) -> Path:
    """Create and verify a 0600, WAL-aware backup through SQLite Backup API."""

    if backup_dir.exists() and (backup_dir.is_symlink() or not backup_dir.is_dir()):
        raise RefundSchemaRepairError(
            "backup directory must be a non-symlink directory"
        )
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = _backup_path(database, backup_dir)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            backup,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.close(descriptor)
        descriptor = None
        source = _read_only_connection(database)
        destination = sqlite3.connect(backup)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        os.chmod(backup, 0o600)
        backup_descriptor = os.open(backup, os.O_RDONLY)
        try:
            os.fsync(backup_descriptor)
        finally:
            os.close(backup_descriptor)
        if stat.S_IMODE(backup.stat().st_mode) != 0o600:
            raise RefundSchemaRepairError("backup permissions are not 0600")
        validate_database_file(backup)
        with _read_only_connection(backup) as verification:
            inspect_schema(verification)
            if all_table_counts(verification) != expected_counts:
                raise RefundSchemaRepairError(
                    "backup row counts do not match the source"
                )
            _verify_integrity(verification)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        backup.unlink(missing_ok=True)
        raise
    return backup


def apply_repair(database: Path, backup_dir: Path) -> Path | None:
    """Apply the supported repair transactionally, or no-op if already current."""

    database = validate_database_file(database)
    with _read_only_connection(database) as preflight:
        state = inspect_schema(preflight)
        counts = all_table_counts(preflight)
        if state.already_current:
            verify_current_schema(preflight, expected_counts=counts)
            return None

    backup: Path | None = None
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        state = inspect_schema(connection)
        counts = all_table_counts(connection)
        if state.already_current:
            verify_current_schema(connection, expected_counts=counts)
            connection.execute("ROLLBACK")
            return None

        backup = create_verified_backup(
            database,
            backup_dir.absolute(),
            expected_counts=counts,
        )
        if state.missing_inventory_restored:
            connection.execute(
                'ALTER TABLE "refunds" ADD COLUMN "inventory_restored" '
                "INT NOT NULL DEFAULT 0"
            )
        if state.missing_order_unique:
            connection.execute(
                f"CREATE UNIQUE INDEX {quote_identifier(ORDER_UNIQUE_INDEX)} "
                'ON "refunds" ("order_id")'
            )
        verify_current_schema(connection, expected_counts=counts)
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    with _read_only_connection(database) as verification:
        verify_current_schema(verification, expected_counts=counts)
    return backup


def _inside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPOSITORY_ROOT)
    except ValueError:
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or repair the one supported local refunds drift.",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up and repair SQLite. Without this flag, preview only.",
    )
    parser.add_argument(
        "--confirm-local-only",
        action="store_true",
        help="Confirm this is repository-local development data.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not _inside_repository(args.database) or not _inside_repository(
        args.backup_dir
    ):
        raise SystemExit("database and backup directory must remain in repository")
    try:
        database = validate_database_file(args.database)
        with _read_only_connection(database) as connection:
            state = inspect_schema(connection)
            _verify_integrity(connection)
    except (OSError, sqlite3.Error, RefundSchemaRepairError) as error:
        raise SystemExit(f"refunds SQLite preflight failed: {error}") from error

    print(f"database={database}")
    print(f"refunds={state.refund_count}")
    print(
        "missing_inventory_restored="
        f"{str(state.missing_inventory_restored).lower()}"
    )
    print(f"missing_order_unique={str(state.missing_order_unique).lower()}")
    print(f"already_current={str(state.already_current).lower()}")
    if not args.apply:
        print("mode=preview")
        print("next=review, then rerun with --apply --confirm-local-only")
        return 0
    if not args.confirm_local_only:
        raise SystemExit("--apply requires --confirm-local-only")

    try:
        backup = apply_repair(database, args.backup_dir)
    except (OSError, sqlite3.Error, RefundSchemaRepairError) as error:
        raise SystemExit(f"refunds SQLite repair failed: {error}") from error
    print("mode=apply")
    print(f"backup={backup or 'not-created-already-current'}")
    print("result=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
