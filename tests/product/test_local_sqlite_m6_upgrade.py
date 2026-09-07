"""Contract tests for the data-preserving local SQLite M6 upgrade."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.local.upgrade_sqlite_m6 import (
    BEAD_COLOR_SLOT_COUNT,
    apply_upgrade,
    column_names,
    inspect_schema,
)


def create_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE product_kits (
                id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                price VARCHAR(40) NOT NULL,
                stock INT NOT NULL DEFAULT 0,
                product_id BIGINT NOT NULL UNIQUE
                    REFERENCES products (id) ON DELETE RESTRICT
            );
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                product_id BIGINT NOT NULL REFERENCES products (id)
            );
            CREATE TABLE inventory_transactions (
                id INTEGER PRIMARY KEY,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                product_id BIGINT NOT NULL REFERENCES products (id)
            );
            INSERT INTO products (id, name) VALUES (1, '保留商品');
            INSERT INTO product_kits (
                id, created_at, updated_at, price, stock, product_id
            ) VALUES (7, '2026-09-01', '2026-09-01', '19.90', 8, 1);
            INSERT INTO order_items (
                id, created_at, updated_at, product_id
            ) VALUES (11, '2026-09-01', '2026-09-01', 1);
            INSERT INTO inventory_transactions (
                id, created_at, updated_at, product_id
            ) VALUES (13, '2026-09-01', '2026-09-01', 1);
            """
        )
    finally:
        connection.close()


def test_m6_upgrade_preserves_rows_and_is_replay_safe(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite3"
    backup_dir = tmp_path / "backups"
    create_legacy_database(database)

    backup = apply_upgrade(database, backup_dir)

    assert backup is not None and backup.is_file()
    with sqlite3.connect(database) as connection:
        assert inspect_schema(connection).already_current is True
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM inventory_transactions"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT id, price, stock, kit_kind, sale_unit_grams, product_id "
            "FROM product_kits"
        ).fetchone() == (7, "19.90", 8, "fixed", None, 1)
        assert connection.execute(
            "SELECT COUNT(*), MIN(slot_no), MAX(slot_no) FROM bead_colors"
        ).fetchone() == (BEAD_COLOR_SLOT_COUNT, 1, BEAD_COLOR_SLOT_COUNT)
        assert connection.execute(
            "SELECT COUNT(*) FROM product_kit_colors"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT COUNT(*) FROM pragma_table_info('product_kits') "
            "WHERE name = 'stock' AND \"notnull\" = 0"
        ).fetchone()[0] == 1

    second_backup = apply_upgrade(database, backup_dir)
    assert second_backup is None
    assert len(list(backup_dir.iterdir())) == 1


def test_m6_upgrade_adds_all_referencing_columns(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite3"
    create_legacy_database(database)

    apply_upgrade(database, tmp_path / "backups")

    with sqlite3.connect(database) as connection:
        assert {
            "kit_color_id",
            "kit_color_slot_no",
            "kit_color_code",
            "kit_color_name",
            "sale_unit_grams",
        } <= column_names(connection, "order_items")
        assert "kit_color_id" in column_names(
            connection, "inventory_transactions"
        )
        index_columns = connection.execute(
            'PRAGMA index_info("idx_inventory_color_created_id")'
        ).fetchall()
        assert [row[2] for row in index_columns] == [
            "kit_color_id",
            "created_at",
            "id",
        ]
