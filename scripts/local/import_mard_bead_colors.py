#!/usr/bin/env python3
"""Import the frozen MARD 221 manifest into a local M6 SQLite database.

The command is preview-only by default.  Apply mode requires an explicit local
confirmation, creates a consistent database backup before metadata changes,
publishes deterministic generated PNG swatches atomically, and removes newly
created files if the database transaction fails.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import struct
import sys
import tempfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.local.fetch_mard_bead_colors import (
    EXPECTED_COLOR_COUNT,
    SOURCE_URL,
    SWATCH_HEIGHT,
    SWATCH_WIDTH,
    expected_codes,
    image_filename,
)


DEFAULT_DATABASE: Final = Path("db.sqlite3")
DEFAULT_MANIFEST: Final = Path("app/tasks/manifests/mard_221.json")
DEFAULT_STORAGE_ROOT: Final = Path("uploads/products")
DEFAULT_BASE_URL: Final = "/uploads/products"
DEFAULT_BACKUP_DIR: Final = Path("backups/local-sqlite-migrations")
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
PNG_END: Final = b"\x00\x00\x00\x00IEND\xaeB`\x82"


class BeadColorImportError(RuntimeError):
    """Raised when the manifest or local import target is unsafe."""


@dataclass(frozen=True, slots=True)
class ManifestColor:
    slot_no: int
    color_code: str
    name: str
    sort: int
    is_active: bool
    hex: str
    rgb: tuple[int, int, int]
    image_filename: str


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
    """Load and strictly validate the committed MARD 221 manifest."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BeadColorImportError(f"cannot read manifest: {error}") from error

    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise BeadColorImportError("manifest schema_version must be 1")
    source = document.get("source")
    if not isinstance(source, dict) or source.get("url") != SOURCE_URL:
        raise BeadColorImportError("manifest source URL does not match MARD 221")
    if source.get("representation") != "css_rgb_swatch":
        raise BeadColorImportError("manifest source representation is unsupported")
    if source.get("individual_image_files") is not False:
        raise BeadColorImportError("manifest must describe CSS-rendered swatches")
    swatch = document.get("swatch")
    expected_swatch = {
        "format": "png",
        "width": SWATCH_WIDTH,
        "height": SWATCH_HEIGHT,
        "color_space": "sRGB",
        "representation": "solid_color_generated_from_source_rgb",
    }
    if swatch != expected_swatch:
        raise BeadColorImportError("manifest swatch contract changed")

    raw_colors = document.get("colors")
    if not isinstance(raw_colors, list) or len(raw_colors) != EXPECTED_COLOR_COUNT:
        raise BeadColorImportError(
            f"manifest must contain exactly {EXPECTED_COLOR_COUNT} colors"
        )

    colors: list[ManifestColor] = []
    for expected_slot, raw in enumerate(raw_colors, start=1):
        if not isinstance(raw, dict):
            raise BeadColorImportError(f"slot {expected_slot} is not an object")
        try:
            rgb_raw = raw["rgb"]
            if (
                not isinstance(rgb_raw, list)
                or len(rgb_raw) != 3
                or any(type(channel) is not int for channel in rgb_raw)
            ):
                raise ValueError("rgb must contain three integers")
            color = ManifestColor(
                slot_no=raw["slot_no"],
                color_code=raw["color_code"],
                name=raw["name"],
                sort=raw["sort"],
                is_active=raw["is_active"],
                hex=raw["hex"],
                rgb=tuple(rgb_raw),
                image_filename=raw["image_filename"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise BeadColorImportError(
                f"slot {expected_slot} has an invalid shape: {error}"
            ) from error

        if type(color.slot_no) is not int or color.slot_no != expected_slot:
            raise BeadColorImportError("manifest slots must be the ordered range 1..221")
        if color.color_code != expected_codes()[expected_slot - 1]:
            raise BeadColorImportError(
                f"unexpected color code at slot {expected_slot}: {color.color_code}"
            )
        if color.name != color.color_code:
            raise BeadColorImportError(
                f"source exposes no separate name; name must equal code for {color.color_code}"
            )
        if type(color.sort) is not int or color.sort != expected_slot:
            raise BeadColorImportError("manifest sort must match the frozen source order")
        if color.is_active is not True:
            raise BeadColorImportError("all validated manifest colors must be active")
        if not re_full_hex(color.hex):
            raise BeadColorImportError(f"invalid HEX value for {color.color_code}")
        if any(channel < 0 or channel > 255 for channel in color.rgb):
            raise BeadColorImportError(f"invalid RGB value for {color.color_code}")
        derived_hex = "#" + "".join(f"{channel:02X}" for channel in color.rgb)
        if derived_hex != color.hex:
            raise BeadColorImportError(
                f"HEX and RGB differ for {color.color_code}"
            )
        expected_filename = image_filename(
            color_code=color.color_code,
            hex_value=color.hex,
        )
        if color.image_filename != expected_filename:
            raise BeadColorImportError(
                f"image filename is not deterministic for {color.color_code}"
            )
        colors.append(color)

    if len({color.color_code for color in colors}) != EXPECTED_COLOR_COUNT:
        raise BeadColorImportError("manifest contains duplicate color codes")
    if len({color.hex for color in colors}) != EXPECTED_COLOR_COUNT:
        raise BeadColorImportError("manifest contains duplicate HEX values")
    if len({color.image_filename for color in colors}) != EXPECTED_COLOR_COUNT:
        raise BeadColorImportError("manifest contains duplicate image filenames")
    return tuple(colors)


def re_full_hex(value: object) -> bool:
    """Validate an uppercase six-digit HEX color without a regex dependency."""

    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        return False
    return all(character in "0123456789ABCDEF" for character in value[1:])


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def build_swatch_png(rgb: tuple[int, int, int]) -> bytes:
    """Create a deterministic 256×256 RGB PNG with an explicit sRGB chunk."""

    pixel_row = bytes(rgb) * SWATCH_WIDTH
    scanlines = b"".join(
        b"\x00" + pixel_row for _ in range(SWATCH_HEIGHT)
    )
    header = struct.pack(">IIBBBBB", SWATCH_WIDTH, SWATCH_HEIGHT, 8, 2, 0, 0, 0)
    return b"".join(
        (
            PNG_SIGNATURE,
            _png_chunk(b"IHDR", header),
            _png_chunk(b"sRGB", b"\x00"),
            _png_chunk(b"IDAT", zlib.compress(scanlines, level=9)),
            _png_chunk(b"IEND", b""),
        )
    )


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
