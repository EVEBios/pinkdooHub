"""Data-preserving local SQLite M8 swatch HEX upgrade contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.tasks.mard_catalog import load_manifest
from scripts.local import upgrade_sqlite_m8_swatch_hex as migration


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPOSITORY_ROOT / "app/tasks/manifests/mard_221.json"


def _create_m7_database(path: Path, *, with_column: bool = False) -> None:
    swatch_column = ", swatch_hex VARCHAR(7)" if with_column else ""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            f"""
            PRAGMA foreign_keys = ON;
            CREATE TABLE retained_products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            INSERT INTO retained_products (id, name) VALUES (7, '保留商品');
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
                {swatch_column}
            );
            """
        )
        connection.executemany(
            "INSERT INTO bead_colors "
            "(created_at, updated_at, slot_no, color_code, name, "
            "swatch_image_url, sort, is_active) "
            "VALUES ('2026-09-07', '2026-09-07', ?, NULL, NULL, NULL, ?, 0)",
            ((slot_no, slot_no) for slot_no in range(1, 222)),
        )
        connection.commit()
    finally:
        connection.close()


def test_m8_upgrade_preserves_data_backfills_exact_hex_and_replays(
    tmp_path: Path,
) -> None:
    database = tmp_path / "db.sqlite3"
    backup_dir = tmp_path / "backups"
    _create_m7_database(database)
    colors = load_manifest(MANIFEST)

    with sqlite3.connect(database) as connection:
        state = migration.inspect_schema(connection, colors)
        assert state.column_present is False
        assert state.missing_hex_values == 221

    backup = migration.apply_upgrade(database, MANIFEST, backup_dir)

    assert backup is not None and backup.is_file()
    assert backup.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(database) as connection:
        state = migration.inspect_schema(connection, colors)
        assert state.already_current is True
        assert connection.execute(
            "SELECT id, name FROM retained_products"
        ).fetchall() == [(7, "保留商品")]
        assert connection.execute(
            "SELECT slot_no, swatch_hex FROM bead_colors "
            "WHERE slot_no IN (1, 221) ORDER BY slot_no"
        ).fetchall() == [(1, colors[0].hex), (221, colors[-1].hex)]
        assert connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT swatch_hex) FROM bead_colors"
        ).fetchone() == (221, 221)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    assert migration.apply_upgrade(database, MANIFEST, backup_dir) is None
    assert len(list(backup_dir.iterdir())) == 1


def test_m8_upgrade_completes_safe_partial_state_and_rejects_conflict(
    tmp_path: Path,
) -> None:
    colors = load_manifest(MANIFEST)
    database = tmp_path / "partial.sqlite3"
    _create_m7_database(database, with_column=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE bead_colors SET swatch_hex=? WHERE slot_no=1",
            (colors[0].hex,),
        )
        connection.commit()

    migration.apply_upgrade(database, MANIFEST, tmp_path / "partial-backups")
    with sqlite3.connect(database) as connection:
        assert migration.inspect_schema(connection, colors).already_current is True

    conflicting = tmp_path / "conflicting.sqlite3"
    _create_m7_database(conflicting, with_column=True)
    with sqlite3.connect(conflicting) as connection:
        connection.execute(
            "UPDATE bead_colors SET swatch_hex='#000000' WHERE slot_no=1"
        )
        connection.commit()
    with pytest.raises(migration.MigrationError, match="conflicting existing"):
        migration.apply_upgrade(
            conflicting,
            MANIFEST,
            tmp_path / "conflicting-backups",
        )
    assert not (tmp_path / "conflicting-backups").exists()


def test_m8_upgrade_rolls_back_schema_and_data_on_verification_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "db.sqlite3"
    backup_dir = tmp_path / "backups"
    _create_m7_database(database)

    def fail_verification(*args: object, **kwargs: object) -> None:
        raise migration.MigrationError("injected verification failure")

    monkeypatch.setattr(migration, "verify_post_upgrade", fail_verification)
    with pytest.raises(migration.MigrationError, match="injected verification"):
        migration.apply_upgrade(database, MANIFEST, backup_dir)

    assert len(list(backup_dir.iterdir())) == 1
    with sqlite3.connect(database) as connection:
        assert "swatch_hex" not in migration.column_names(
            connection,
            "bead_colors",
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM bead_colors"
        ).fetchone() == (221,)


def test_m8_upgrade_rejects_an_ambiguous_existing_column_shape(
    tmp_path: Path,
) -> None:
    database = tmp_path / "wrong-shape.sqlite3"
    _create_m7_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "ALTER TABLE bead_colors ADD COLUMN swatch_hex TEXT NOT NULL "
            "DEFAULT '#000000'"
        )
        connection.commit()

    with pytest.raises(migration.MigrationError, match="nullable VARCHAR\\(7\\)"):
        migration.apply_upgrade(database, MANIFEST, tmp_path / "backups")
    assert not (tmp_path / "backups").exists()
