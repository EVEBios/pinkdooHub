"""M8 BeadColor HEX MySQL migration static contracts."""

from __future__ import annotations

import hashlib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from app.tasks.mard_catalog import load_manifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPOSITORY_ROOT / "app/tasks/manifests/mard_221.json"


def _load_migration() -> ModuleType:
    files = list(
        Path("migrations/models").glob("8_*_add_bead_color_swatch_hex.py")
    )
    assert len(files) == 1
    spec = spec_from_file_location("bead_color_swatch_hex_migration", files[0])
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_m8_adds_nullable_hex_and_exactly_backfills_frozen_manifest() -> None:
    migration = _load_migration()
    colors = load_manifest(MANIFEST)
    sql = await migration.upgrade(None)

    assert migration.RUN_IN_TRANSACTION is False
    assert migration.MARD_MANIFEST_SHA256 == hashlib.sha256(
        MANIFEST.read_bytes()
    ).hexdigest()
    assert migration.SWATCH_HEX_BY_SLOT == tuple(color.hex for color in colors)
    assert "ADD COLUMN `swatch_hex` VARCHAR(7) NULL" in sql
    assert "CHECK" not in sql
    assert sql.index("ADD COLUMN `swatch_hex`") < sql.index("UPDATE `bead_colors`")
    assert sql.count("WHEN ") == 221
    for color in colors:
        assert f"WHEN {color.slot_no} THEN '{color.hex}'" in sql
    assert "WHERE `slot_no` BETWEEN 1 AND 221" in sql


async def test_m8_downgrade_only_drops_swatch_hex() -> None:
    sql = await _load_migration().downgrade(None)

    assert "ALTER TABLE `bead_colors`" in sql
    assert "DROP COLUMN `swatch_hex`" in sql
    assert "DROP TABLE" not in sql
    assert "UPDATE" not in sql
