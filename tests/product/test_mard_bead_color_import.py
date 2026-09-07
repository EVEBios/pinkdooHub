"""Contracts for the crawled MARD 221 manifest and local SQLite importer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.local.fetch_mard_bead_colors import (
    EXPECTED_COLOR_COUNT,
    ManifestSourceError,
    expected_codes,
    extract_colors,
)
from scripts.local.import_mard_bead_colors import (
    PNG_END,
    PNG_SIGNATURE,
    BeadColorImportError,
    apply_import,
    build_swatch_png,
    load_manifest,
    plan_import,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPOSITORY_ROOT / "app/tasks/manifests/mard_221.json"


def _source_html(*, first_code: str | None = None) -> str:
    cards: list[str] = []
    for slot_no, code in enumerate(expected_codes(), start=1):
        red = (slot_no >> 16) & 0xFF
        green = (slot_no >> 8) & 0xFF
        blue = slot_no & 0xFF
        displayed_code = first_code if slot_no == 1 and first_code else code
        hex_value = f"#{red:02X}{green:02X}{blue:02X}"
        cards.append(
            '<div class="color-block" '
            f'style="background-color: rgb({red}, {green}, {blue});">'
            f'<span class="color-code">{displayed_code}</span></div>'
            '<div class="color-info">'
            f'<div class="color-hex">{hex_value}</div>'
            f'<div class="color-rgb">RGB({red}, {green}, {blue})</div>'
            "</div>"
        )
    return "".join(cards)


def _create_m6_database(path: Path, *, online_reference: bool = False) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                status VARCHAR(20) NOT NULL,
                is_deleted INT NOT NULL DEFAULT 0
            );
            CREATE TABLE bead_colors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                slot_no SMALLINT NOT NULL UNIQUE,
                color_code VARCHAR(50) UNIQUE,
                name VARCHAR(100),
                swatch_image_url VARCHAR(2048),
                sort SMALLINT NOT NULL,
                is_active INT NOT NULL DEFAULT 0
            );
            CREATE TABLE product_kit_colors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id BIGINT NOT NULL REFERENCES products (id),
                bead_color_id BIGINT NOT NULL REFERENCES bead_colors (id),
                is_enabled INT NOT NULL DEFAULT 0,
                stock_units INT NOT NULL DEFAULT 0,
                UNIQUE (product_id, bead_color_id)
            );
            """
        )
        connection.executemany(
            "INSERT INTO bead_colors "
            "(created_at, updated_at, slot_no, sort, is_active) "
            "VALUES ('2026-09-07', '2026-09-07', ?, ?, 0)",
            ((slot_no, slot_no) for slot_no in range(1, 222)),
        )
        if online_reference:
            connection.execute(
                "INSERT INTO products (id, status, is_deleted) "
                "VALUES (1, 'online', 0)"
            )
            connection.execute(
                "INSERT INTO product_kit_colors "
                "(product_id, bead_color_id, is_enabled, stock_units) "
                "VALUES (1, 1, 1, 0)"
            )
        connection.commit()
    finally:
        connection.close()


def test_source_parser_requires_exact_221_order_and_rgb_consistency() -> None:
    colors = extract_colors(_source_html())

    assert len(colors) == EXPECTED_COLOR_COUNT
    assert colors[0].color_code == "A1"
    assert colors[-1].color_code == "M15"
    assert colors[0].rgb == (0, 0, 1)
    assert colors[-1].hex == "#0000DD"

    with pytest.raises(ManifestSourceError, match="ordering changed"):
        extract_colors(_source_html(first_code="A2"))


def test_committed_manifest_and_generated_png_are_complete_and_small() -> None:
    colors = load_manifest(MANIFEST)
    images = [build_swatch_png(color.rgb) for color in colors]

    assert len(colors) == EXPECTED_COLOR_COUNT
    assert [color.color_code for color in colors[:3]] == ["A1", "A2", "A3"]
    assert colors[-1].color_code == "M15"
    assert len({color.image_filename for color in colors}) == EXPECTED_COLOR_COUNT
    assert all(image.startswith(PNG_SIGNATURE) for image in images)
    assert all(image.endswith(PNG_END) for image in images)
    assert max(map(len, images)) < 25 * 1024
    assert sum(map(len, images)) < 256 * 1024


def test_import_preview_apply_and_replay_are_safe(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite3"
    storage_root = tmp_path / "uploads" / "products"
    backup_dir = tmp_path / "backups"
    _create_m6_database(database)

    preview = plan_import(
        database=database,
        manifest=MANIFEST,
        storage_root=storage_root,
        base_url="/uploads/products",
    )

    assert preview.database_changes == EXPECTED_COLOR_COUNT
    assert preview.images_to_create == EXPECTED_COLOR_COUNT
    assert preview.images_reused == 0
    assert preview.already_current is False
    assert not storage_root.exists()
    assert not backup_dir.exists()

    result = apply_import(
        database=database,
        manifest=MANIFEST,
        storage_root=storage_root,
        base_url="/uploads/products",
        backup_dir=backup_dir,
    )

    assert result.backup is not None and result.backup.is_file()
    assert result.created_images == EXPECTED_COLOR_COUNT
    assert len(list(storage_root.glob("*.png"))) == EXPECTED_COLOR_COUNT
    assert all(
        path.stat().st_mode & 0o777 == 0o644
        for path in storage_root.glob("*.png")
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*), SUM(is_active), COUNT(DISTINCT color_code), "
            "COUNT(DISTINCT swatch_image_url) FROM bead_colors"
        ).fetchone() == (221, 221, 221, 221)
        assert connection.execute(
            "SELECT slot_no, color_code, name, sort FROM bead_colors "
            "WHERE slot_no IN (1, 221) ORDER BY slot_no"
        ).fetchall() == [(1, "A1", "A1", 1), (221, "M15", "M15", 221)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    replay = apply_import(
        database=database,
        manifest=MANIFEST,
        storage_root=storage_root,
        base_url="/uploads/products",
        backup_dir=backup_dir,
    )
    assert replay.plan.already_current is True
    assert replay.backup is None
    assert replay.created_images == 0
    assert len(list(backup_dir.iterdir())) == 1


def test_import_refuses_conflicting_metadata_and_online_references(
    tmp_path: Path,
) -> None:
    conflicting_database = tmp_path / "conflicting.sqlite3"
    _create_m6_database(conflicting_database)
    with sqlite3.connect(conflicting_database) as connection:
        connection.execute(
            "UPDATE bead_colors SET color_code='OTHER' WHERE slot_no=1"
        )
        connection.commit()

    with pytest.raises(BeadColorImportError, match="conflicting existing color_code"):
        plan_import(
            database=conflicting_database,
            manifest=MANIFEST,
            storage_root=tmp_path / "conflicting-images",
            base_url="/uploads/products",
        )

    online_database = tmp_path / "online.sqlite3"
    _create_m6_database(online_database, online_reference=True)
    with pytest.raises(BeadColorImportError, match="Online product"):
        plan_import(
            database=online_database,
            manifest=MANIFEST,
            storage_root=tmp_path / "online-images",
            base_url="/uploads/products",
        )


def test_database_failure_rolls_back_and_removes_new_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.local import import_mard_bead_colors as importer

    database = tmp_path / "db.sqlite3"
    storage_root = tmp_path / "uploads"
    backup_dir = tmp_path / "backups"
    _create_m6_database(database)

    def fail_verification(*args: object, **kwargs: object) -> None:
        raise BeadColorImportError("injected verification failure")

    monkeypatch.setattr(importer, "_verify_database", fail_verification)
    with pytest.raises(BeadColorImportError, match="injected verification failure"):
        apply_import(
            database=database,
            manifest=MANIFEST,
            storage_root=storage_root,
            base_url="/uploads/products",
            backup_dir=backup_dir,
        )

    assert list(storage_root.glob("*.png")) == []
    assert len(list(backup_dir.iterdir())) == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM bead_colors WHERE color_code IS NOT NULL"
        ).fetchone()[0] == 0
