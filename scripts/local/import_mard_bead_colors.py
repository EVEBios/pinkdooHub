#!/usr/bin/env python3
"""Import the frozen MARD 221 manifest into a local M6 SQLite database.

The command is preview-only by default.  Apply mode requires an explicit local
confirmation, creates a consistent database backup before metadata changes,
publishes deterministic generated PNG swatches atomically, and removes newly
created files if the database transaction fails.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.tasks.mard_catalog import (
    EXPECTED_COLOR_COUNT,
    PNG_END,
    PNG_SIGNATURE,
    ManifestColor,
    MardCatalogError,
    build_swatch_png,
    load_manifest as load_catalog_manifest,
)


DEFAULT_DATABASE: Final = Path("db.sqlite3")
DEFAULT_MANIFEST: Final = Path("app/tasks/manifests/mard_221.json")
DEFAULT_STORAGE_ROOT: Final = Path("uploads/products")
DEFAULT_BASE_URL: Final = "/uploads/products"
DEFAULT_BACKUP_DIR: Final = Path("backups/local-sqlite-migrations")


class BeadColorImportError(RuntimeError):
    """Raised when the manifest or local import target is unsafe."""


@dataclass(frozen=True, slots=True)
class ImportPlan:
    colors: tuple[ManifestColor, ...]
    database_changes: int
    images_to_create: int
    images_reused: int
    total_image_bytes: int
    already_current: bool


@dataclass(frozen=True, slots=True)
class ImportResult:
    plan: ImportPlan
    backup: Path | None
    created_images: int


def load_manifest(path: Path) -> tuple[ManifestColor, ...]:
    """保留本地工具原有异常类型的共享清单读取适配。"""
    try:
        return load_catalog_manifest(path)
    except MardCatalogError as error:
        raise BeadColorImportError(str(error)) from error


def create_backup(database: Path, backup_dir: Path) -> Path:
    """Create a transactionally consistent SQLite backup."""

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = backup_dir / f"{database.name}.pre-mard-221-{timestamp}.bak"
    source = sqlite3.connect(database)
    destination = sqlite3.connect(backup)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return backup


def _table_names(connection: sqlite3.Connection) -> frozenset[str]:
    return frozenset(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    )


def _database_rows(connection: sqlite3.Connection) -> tuple[tuple, ...]:
    required_tables = {"bead_colors", "product_kit_colors", "products"}
    missing = required_tables - _table_names(connection)
    if missing:
        raise BeadColorImportError(
            "database is not an M6 target; missing tables: "
            + ", ".join(sorted(missing))
        )
    rows = tuple(
        connection.execute(
            "SELECT slot_no, color_code, name, swatch_image_url, sort, is_active "
            "FROM bead_colors ORDER BY slot_no"
        ).fetchall()
    )
    slots = tuple(int(row[0]) for row in rows)
    if len(rows) != EXPECTED_COLOR_COUNT or slots != tuple(
        range(1, EXPECTED_COLOR_COUNT + 1)
    ):
        raise BeadColorImportError("database must contain exactly slots 1..221")
    return rows


def _target_url(base_url: str, color: ManifestColor) -> str:
    normalized = base_url.rstrip("/")
    if not normalized:
        raise BeadColorImportError("base URL must not be empty")
    return f"{normalized}/{color.image_filename}"


def _desired_row(base_url: str, color: ManifestColor) -> tuple:
    return (
        color.slot_no,
        color.color_code,
        color.name,
        _target_url(base_url, color),
        color.sort,
        1,
    )


def _assert_safe_existing_rows(
    rows: tuple[tuple, ...],
    *,
    colors: tuple[ManifestColor, ...],
    base_url: str,
) -> None:
    for existing, color in zip(rows, colors):
        desired = _desired_row(base_url, color)
        for field_name, current, target in zip(
            ("slot_no", "color_code", "name", "swatch_image_url", "sort"),
            existing[:5],
            desired[:5],
        ):
            if field_name == "slot_no":
                continue
            if field_name == "sort":
                if int(current) != int(target):
                    raise BeadColorImportError(
                        f"slot {color.slot_no} has a conflicting existing sort"
                    )
                continue
            if current is not None and current != target:
                raise BeadColorImportError(
                    f"slot {color.slot_no} has conflicting existing {field_name}"
                )


def _assert_no_online_references(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT p.id FROM products AS p "
        "JOIN product_kit_colors AS pkc ON pkc.product_id = p.id "
        "WHERE p.status = 'online' AND p.is_deleted = 0 AND pkc.is_enabled = 1 "
        "LIMIT 1"
    ).fetchone()
    if row is not None:
        raise BeadColorImportError(
            "refuse offline catalog import while an Online product enables colors"
        )


def plan_import(
    *,
    database: Path,
    manifest: Path,
    storage_root: Path,
    base_url: str,
) -> ImportPlan:
    """Validate every input and return a side-effect-free import plan."""

    colors = load_manifest(manifest)
    try:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise BeadColorImportError(f"cannot open database read-only: {error}") from error
    try:
        rows = _database_rows(connection)
        _assert_safe_existing_rows(rows, colors=colors, base_url=base_url)
        _assert_no_online_references(connection)
    finally:
        connection.close()

    desired_rows = tuple(_desired_row(base_url, color) for color in colors)
    database_changes = sum(
        tuple(existing) != desired
        for existing, desired in zip(rows, desired_rows)
    )
    images_to_create = 0
    images_reused = 0
    total_image_bytes = 0
    for color in colors:
        content = build_swatch_png(color.rgb)
        total_image_bytes += len(content)
        target = storage_root / color.image_filename
        if not target.exists():
            images_to_create += 1
            continue
        try:
            existing_content = target.read_bytes()
        except OSError as error:
            raise BeadColorImportError(f"cannot read existing image {target}: {error}") from error
        if existing_content != content:
            raise BeadColorImportError(
                f"existing image conflicts with generated content: {target}"
            )
        images_reused += 1

    return ImportPlan(
        colors=colors,
        database_changes=database_changes,
        images_to_create=images_to_create,
        images_reused=images_reused,
        total_image_bytes=total_image_bytes,
        already_current=database_changes == 0 and images_to_create == 0,
    )


def _publish_images(
    colors: tuple[ManifestColor, ...],
    storage_root: Path,
) -> tuple[Path, ...]:
    storage_root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        for color in colors:
            content = build_swatch_png(color.rgb)
            target = storage_root / color.image_filename
            if target.exists():
                if target.read_bytes() != content:
                    raise BeadColorImportError(
                        f"existing image changed after preview: {target}"
                    )
                continue
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=storage_root,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    os.fchmod(output.fileno(), 0o644)
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.link(temporary, target)
                    created.append(target)
                except FileExistsError:
                    if target.read_bytes() != content:
                        raise BeadColorImportError(
                            f"image publication raced with different content: {target}"
                        )
            finally:
                temporary.unlink(missing_ok=True)
    except BaseException:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise
    return tuple(created)


def _verify_database(
    connection: sqlite3.Connection,
    *,
    colors: tuple[ManifestColor, ...],
    base_url: str,
) -> None:
    rows = _database_rows(connection)
    desired = tuple(_desired_row(base_url, color) for color in colors)
    if rows != desired:
        raise BeadColorImportError("database catalog does not match the manifest")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise BeadColorImportError("database foreign-key verification failed")


def apply_import(
    *,
    database: Path,
    manifest: Path,
    storage_root: Path,
    base_url: str,
    backup_dir: Path,
) -> ImportResult:
    """Apply one safe, idempotent local SQLite manifest import."""

    plan = plan_import(
        database=database,
        manifest=manifest,
        storage_root=storage_root,
        base_url=base_url,
    )
    if plan.already_current:
        return ImportResult(plan=plan, backup=None, created_images=0)

    backup = (
        create_backup(database, backup_dir)
        if plan.database_changes
        else None
    )
    created = _publish_images(plan.colors, storage_root)
    if not plan.database_changes:
        return ImportResult(plan=plan, backup=backup, created_images=len(created))

    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        current_rows = _database_rows(connection)
        _assert_safe_existing_rows(
            current_rows,
            colors=plan.colors,
            base_url=base_url,
        )
        _assert_no_online_references(connection)
        now = datetime.now(timezone.utc).isoformat(sep=" ")
        connection.executemany(
            "UPDATE bead_colors SET color_code=?, name=?, swatch_image_url=?, "
            "sort=?, is_active=1, updated_at=? WHERE slot_no=?",
            (
                (
                    color.color_code,
                    color.name,
                    _target_url(base_url, color),
                    color.sort,
                    now,
                    color.slot_no,
                )
                for color in plan.colors
            ),
        )
        _verify_database(connection, colors=plan.colors, base_url=base_url)
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise
    finally:
        connection.close()

    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as verify:
        _verify_database(verify, colors=plan.colors, base_url=base_url)
    return ImportResult(plan=plan, backup=backup, created_images=len(created))


def _inside_project(path: Path, project_root: Path) -> bool:
    try:
        path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply the MARD 221 manifest to local SQLite.",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create files and update SQLite. Without this flag, preview only.",
    )
    parser.add_argument(
        "--confirm-local-only",
        action="store_true",
        help="Confirm that the target is this repository's local development data.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project_root = Path.cwd().resolve()
    database = args.database.resolve()
    manifest = args.manifest.resolve()
    storage_root = args.storage_root.resolve()
    backup_dir = args.backup_dir.resolve()
    controlled_paths = (database, manifest, storage_root, backup_dir)
    if not all(_inside_project(path, project_root) for path in controlled_paths):
        raise SystemExit("all paths must remain inside the current project root")
    if not database.is_file():
        raise SystemExit(f"database does not exist: {database}")
    if not manifest.is_file():
        raise SystemExit(f"manifest does not exist: {manifest}")

    try:
        plan = plan_import(
            database=database,
            manifest=manifest,
            storage_root=storage_root,
            base_url=args.base_url,
        )
    except (OSError, sqlite3.Error, BeadColorImportError) as error:
        raise SystemExit(f"MARD 221 import preflight failed: {error}") from error

    print(f"database={database}")
    print(f"manifest={manifest}")
    print(f"colors={len(plan.colors)}")
    print(f"database_changes={plan.database_changes}")
    print(f"images_to_create={plan.images_to_create}")
    print(f"images_reused={plan.images_reused}")
    print(f"total_image_bytes={plan.total_image_bytes}")
    print(f"already_current={str(plan.already_current).lower()}")
    if not args.apply:
        print("mode=preview")
        print("next=review, then rerun with --apply --confirm-local-only")
        return 0
    if not args.confirm_local_only:
        raise SystemExit("--apply requires --confirm-local-only")

    try:
        result = apply_import(
            database=database,
            manifest=manifest,
            storage_root=storage_root,
            base_url=args.base_url,
            backup_dir=backup_dir,
        )
    except (OSError, sqlite3.Error, BeadColorImportError) as error:
        raise SystemExit(f"MARD 221 import failed: {error}") from error
    print("mode=apply")
    print(f"created_images={result.created_images}")
    print(f"backup={result.backup or 'not-created-no-database-change'}")
    print("result=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
