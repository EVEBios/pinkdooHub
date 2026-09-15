"""M15 迁移跨版本保留内容、结构清单及新增业务初始状态。"""
import copy
import hashlib
import json

import pytest

from app.tasks import gatea_m15_snapshot as state
from app.tasks.gatea_migrate_step import APPROVED_MIGRATIONS


def snapshot(version):
    legacy = {table: {"rows": 2, "sha256": hashlib.sha256(table.encode()).hexdigest()}
              for table in state.model_columns(9)}
    complete = {table: copy.deepcopy(legacy.get(table, {"rows": 0, "sha256": "a" * 64}))
                for table in [*state.model_columns(version), "aerich"]}
    return {"schema_version": 1, "profile": "gatea-m9-m15-state-v1", "version": version,
            "aerich_versions": list(APPROVED_MIGRATIONS[:version + 1]),
            "structure_sha256": state.schema_manifest()["versions"][str(version)]["structure_sha256"],
            "m9_preserved": legacy, "complete_content": complete,
            "new_session_fields_nondefault": 0, "secret_values_recorded": False, "raw_rows_recorded": False}


@pytest.mark.parametrize("version", range(10, 16))
def test_added_columns_do_not_change_legacy_projection(version):
    before, after = snapshot(9), snapshot(version)
    if version >= 11:
        after["complete_content"]["table_sessions"]["sha256"] = "b" * 64
    state.require_preserved(before, after, target=version)


@pytest.mark.parametrize("change", ("row", "count", "missing", "chain", "schema", "profile", "default", "raw", "bool_count", "bool_schema"))
def test_content_and_contract_changes_are_rejected(change):
    before, after = snapshot(9), snapshot(15)
    if change == "row": after["m9_preserved"]["payments"]["sha256"] = "c" * 64
    if change == "count": after["m9_preserved"]["payments"]["rows"] += 1
    if change == "missing": del after["m9_preserved"]["payments"]
    if change == "chain": after["aerich_versions"].pop()
    if change == "schema": after["structure_sha256"] = "c" * 64
    if change == "profile": after["profile"] = "other"
    if change == "default": after["new_session_fields_nondefault"] = 1
    if change == "raw": after["raw_rows_recorded"] = True
    if change == "bool_count": after["m9_preserved"]["payments"]["rows"] = True
    if change == "bool_schema": after["schema_version"] = True
    with pytest.raises(state.M15SnapshotError): state.require_preserved(before, after, target=15)


@pytest.mark.parametrize("table", [t for tables in state.NEW_TABLES.values() for t in tables])
def test_migration_cannot_backfill_new_business_tables(table):
    before, after = snapshot(9), snapshot(15)
    after["complete_content"][table]["rows"] = 1
    with pytest.raises(state.M15SnapshotError, match="populated"):
        state.require_preserved(before, after, target=15)


def test_manifest_rejects_migration_changed_since_drill(tmp_path, monkeypatch):
    path = tmp_path / 'schema.json'
    data = json.loads(state.SCHEMA_MANIFEST.read_text())
    data['migration_sha256'][APPROVED_MIGRATIONS[15]] = 'f' * 64
    path.write_text(json.dumps(data)); monkeypatch.setattr(state, 'SCHEMA_MANIFEST', path)
    with pytest.raises(state.M15SnapshotError, match="fresh isolated"):
        state.schema_manifest()


@pytest.mark.parametrize("name", ("users;DROP TABLE users", "users`", "../users", "", "users.name"))
def test_query_identifiers_are_closed(name):
    with pytest.raises(state.M15SnapshotError): state.quote(name)
