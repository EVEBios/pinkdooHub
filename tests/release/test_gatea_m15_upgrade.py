"""M15 停写编排、失败现场与启动证据的可观察约束。"""

import json
from pathlib import Path
import subprocess

import pytest

from scripts.release import gatea_m15_upgrade as upgrade
from scripts.release import gatea_operations as gatea
from tests.release.test_gatea_m15_snapshot import snapshot


TARGET = "a" * 40
IMAGE = "sha256:" + "b" * 64
NOW = "2026-09-15T18:00:00+00:00"


def migration(version):
    return {"target_version": version, "migration": upgrade.snapshots.APPROVED_MIGRATIONS[version],
            "applied": True, "aerich_versions": list(upgrade.snapshots.APPROVED_MIGRATIONS[:version + 1])}


@pytest.mark.parametrize("failure", (None, "ddl", "content", "checkpoint", "no-op", "writers"))
def test_steps_stop_at_first_failure_and_never_rerun_or_skip(monkeypatch, failure):
    calls, journal = [], []
    def stopped(*args):
        if failure == "writers" and calls == [10]:
            raise upgrade.M15UpgradeError("writer running")
    def task(values, config, secrets, module, *args):
        version = int(args[-1]); calls.append(version)
        if failure == "ddl" and version == 12:
            raise upgrade.M15UpgradeError("DDL partially committed")
        result = migration(version)
        if failure == "no-op" and version == 12:
            result["applied"] = False
        return result
    def state(values, config, secrets, version):
        result = snapshot(version)
        if failure == "content" and version == 12:
            result["m9_preserved"]["payments"]["rows"] += 1
        return result
    def checkpoint(item):
        if failure == "checkpoint" and item == {"phase": "before-migration", "version": 12}:
            raise OSError("disk full")
        journal.append(item)
    monkeypatch.setattr(upgrade, "_require_stopped", stopped)
    monkeypatch.setattr(upgrade, "_task", task)
    monkeypatch.setattr(upgrade, "read_state", state)
    args = dict(values={}, config_file=Path("/config"), secret_dir=Path("/secrets"),
                source_state=snapshot(9), checkpoint=checkpoint)
    if failure:
        with pytest.raises((upgrade.M15UpgradeError, upgrade.snapshots.M15SnapshotError, OSError)):
            upgrade.execute_steps(**args)
        assert calls == ([10] if failure == "writers" else [10, 11] if failure == "checkpoint" else [10, 11, 12])
        assert all(item["version"] < 12 for item in journal if item["phase"] == "migration-verified")
    else:
        result = upgrade.execute_steps(**args)
        assert calls == list(range(10, 16))
        assert len(journal) == 12
        assert upgrade._validate_steps(snapshot(9), result) == snapshot(15)


def record():
    return {"schema_version": 3, "record_type": "existing-database-upgrade",
        "transition_kind": upgrade.TRANSITION_KIND, "candidate_sha": TARGET, "image_id": IMAGE,
        "source_candidate_sha": upgrade.SOURCE_SHA, "source_version": 9, "target_version": 15,
        "source_image_id": IMAGE, "backup_id": "20260915t150000z",
        "backup_record_sha256": "c" * 64, "restore_record_sha256": "c" * 64,
        "source_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
        "target_aerich_versions": list(gatea.APPROVED_TARGET_M15_CHAIN),
        "source_state": snapshot(9), "target_state": snapshot(15),
        "steps": [{"phase": "migration-verified", "version": v, "migration": migration(v), "state": snapshot(v)} for v in range(10, 16)],
        "source_image_manifest": ["a synthetic image"], "target_image_manifest": ["a synthetic image"],
        "stage_record_sha256": "c" * 64, "source_finalization_sha256": "c" * 64,
        "activation_record_sha256": "c" * 64, "completed_at": NOW, "passed": True, "secret_values_recorded": False}


@pytest.mark.parametrize("change", (None, "version", "source", "chain", "step", "skipped", "content", "images", "dependency", "secret"))
def test_record_requires_complete_preserved_chain_and_unchanged_dependencies(monkeypatch, change):
    payload = record()
    if change == "version": payload["target_version"] = True
    if change == "source": payload["source_candidate_sha"] = "d" * 40
    if change == "chain": payload["target_aerich_versions"].pop()
    if change == "step": payload["steps"][2]["migration"]["applied"] = False
    if change == "skipped": payload["steps"].pop(2)
    if change == "content": payload["steps"][2]["state"]["m9_preserved"]["payments"]["rows"] += 1
    if change == "images": payload["target_image_manifest"] = []
    if change == "dependency": payload["activation_record_sha256"] = "d" * 64
    if change == "secret": payload["secret_values_recorded"] = True
    monkeypatch.setattr(upgrade, "_load", lambda *args: ({}, "c" * 64))
    args = dict(record_dir=Path("/records"), candidate_sha=TARGET, image_id=IMAGE)
    if change:
        with pytest.raises(upgrade.M15UpgradeError): upgrade.require_upgrade_record(payload, **args)
    else:
        assert upgrade.require_upgrade_record(payload, **args) == payload


@pytest.mark.parametrize("bad", (False, True))
def test_replay_binds_immutable_upgrade_and_exact_target_state(monkeypatch, bad):
    payload = record()
    replay = {"schema_version": 3, "record_type": "existing-database-upgrade-plan-replay",
              "transition_kind": upgrade.TRANSITION_KIND, "candidate_sha": TARGET, "image_id": IMAGE,
              "upgrade_record_sha256": "c" * 64, "target_state": snapshot(15),
              "passed": True, "already_current": True, "read_only": not bad, "completed_at": NOW}
    monkeypatch.setattr(upgrade, "_load", lambda path, _: (replay if "replay" in path.name else payload, "c" * 64))
    args = dict(record_dir=Path("/records"), candidate_sha=TARGET, image_id=IMAGE, upgrade_record=payload)
    if bad:
        with pytest.raises(upgrade.M15UpgradeError): upgrade.require_replay(**args)
    else: assert upgrade.require_replay(**args) == replay


def test_m15_pending_blocks_app_start_before_image_or_docker(tmp_path, monkeypatch):
    (tmp_path / f"{TARGET}.m15-upgrade.pending.json").write_text("{}")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: pytest.fail("must reject pending before config"))
    with pytest.raises(gatea.GateAError, match="pending"):
        gatea.app_up(config_file=Path("/config"), secret_dir=Path("/secrets"), record_dir=tmp_path,
                     mode="loopback", wait_timeout=30)


@pytest.mark.parametrize("change", (None, "live", "current", "phase", "image", "dependency"))
def test_source_requires_finalized_live_current_and_bound_m9_records(monkeypatch, change):
    root = Path("/releases")
    final = {"record_type": "gatea-current-finalization", "candidate_sha": upgrade.SOURCE_SHA,
             "image_id": IMAGE, "passed": True, "phase": "runtime-restored", "completed_at": NOW,
             "runtime_services": list(upgrade.SERVICES), "target_link": str(root / upgrade.SOURCE_SHA),
             **{k: "c" * 64 for k in ("stage_record_sha256", "activation_record_sha256",
                "upgrade_record_sha256", "upgrade_plan_replay_record_sha256")}}
    if change == "phase": final["phase"] = "prepared"
    if change == "image": final["image_id"] = "sha256:other"
    if change == "dependency": final["upgrade_record_sha256"] = "d" * 64
    monkeypatch.setattr(upgrade.candidate, "_read_current_target", lambda *args: root / (TARGET if change == "current" else upgrade.SOURCE_SHA))
    monkeypatch.setattr(gatea, "validate_app_image", lambda *args: IMAGE)
    monkeypatch.setattr(gatea, "_require_upgrade_record", lambda **kwargs: {})
    monkeypatch.setattr(gatea, "_require_m9_upgrade_replay_record", lambda **kwargs: {})
    monkeypatch.setattr(upgrade, "_load", lambda *args: (final, "c" * 64))
    args = dict(release_root=root, current_link=Path("/current"), record_dir=Path("/records"),
                values={"GATEA_APP_IMAGE": "pinkdoohub-gatea:" + (TARGET if change == "live" else upgrade.SOURCE_SHA)})
    if change:
        with pytest.raises(upgrade.M15UpgradeError): upgrade._require_source(**args)
    else: assert upgrade._require_source(**args) == (final, "c" * 64)


@pytest.mark.parametrize("returncode", (0, 1))
def test_state_capture_uses_secret_entrypoint_and_forwards_process_ownership(monkeypatch, returncode):
    calls = []
    monkeypatch.setattr(gatea, "_run_compose", lambda **kw: calls.append(kw) or
        subprocess.CompletedProcess([], returncode, json.dumps(snapshot(15)), ""))
    if returncode:
        with pytest.raises(upgrade.M15UpgradeError):
            upgrade.read_state({}, Path("/config"), Path("/secrets"), 15, start_new_session=True)
    else:
        assert upgrade.read_state({}, Path("/config"), Path("/secrets"), 15, start_new_session=True) == snapshot(15)
    assert calls[0]["start_new_session"] is True
    assert calls[0]["profiles"] == ("operations",)
    assert "--entrypoint" not in calls[0]["arguments"]


@pytest.mark.parametrize("schema_drift", (False, True))
def test_m15_app_start_checks_schema_but_allows_new_business_rows(tmp_path, monkeypatch, schema_drift):
    from tests.release.test_gatea_operations import _valid_values, _healthy_rows
    values = _valid_values()
    payload = record()
    commands = []
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "validate_app_image", lambda *args, **kwargs: IMAGE)
    monkeypatch.setattr(gatea, "_require_deployment_record", lambda **kwargs: payload)
    monkeypatch.setattr(gatea, "read_database_snapshot", lambda **kwargs: {"aerich_versions": list(gatea.APPROVED_TARGET_M15_CHAIN)})
    monkeypatch.setattr(upgrade, "require_replay", lambda **kwargs: {})
    def current(*args, **kwargs):
        if schema_drift: raise upgrade.M15UpgradeError("schema differs")
        result = snapshot(15)
        result["complete_content"]["payments"]["rows"] += 1
        return result
    monkeypatch.setattr(upgrade, "read_state", current)
    monkeypatch.setattr(gatea, "_run_m9_table_reconcile", lambda **kwargs: {k: 0 for k in gatea.M9_RECONCILE_KEYS})
    def ps(**kwargs):
        rows = _healthy_rows(*kwargs["services"])
        for row in rows:
            if row["Service"] == "nginx":
                row["Publishers"] = [{"URL": "127.0.0.1", "TargetPort": 8080, "PublishedPort": 18080, "Protocol": "tcp"}]
        return rows
    monkeypatch.setattr(gatea, "_compose_ps", ps)
    monkeypatch.setattr(gatea, "_run_compose", lambda **kwargs: commands.append(kwargs["arguments"]) or subprocess.CompletedProcess([], 0))
    args = dict(config_file=Path("/config"), secret_dir=Path("/secrets"), record_dir=tmp_path, mode="loopback", wait_timeout=30)
    if schema_drift:
        with pytest.raises(upgrade.M15UpgradeError): gatea.app_up(**args)
        assert commands == []
    else:
        gatea.app_up(**args)
        assert len(commands) == 1 and commands[0][0] == "up"


@pytest.mark.parametrize("failure", (None, "backup-drift", "migration", "config-drift", "replay", "plan"))
def test_upgrade_publishes_only_verified_steps_and_preserves_failure_journal(tmp_path, monkeypatch, failure):
    from tests.release.test_gatea_operations import _valid_values
    candidate, legacy, backup = upgrade.candidate, upgrade.legacy, upgrade.backup
    monkeypatch.setattr(candidate.os, "fchown", lambda *args: None)
    values = {**_valid_values(), "GATEA_APP_IMAGE": f"pinkdoohub-gatea:{upgrade.SOURCE_SHA}",
              "TABLE_SESSION_CLAIMS_ENABLED": "true"}
    config = tmp_path / "config.env"
    original = "".join(f"{k}={v}\n" for k, v in values.items()).encode()
    config.write_bytes(original); config.chmod(0o640)
    records, history = tmp_path / "records", tmp_path / "history"
    records.mkdir(); history.mkdir()
    base = {"aerich_versions": ",".join(gatea.APPROVED_TARGET_M9_CHAIN)}
    source_backup = {"image_id": IMAGE, "database_snapshot": base, "image_manifest": ["synthetic image"],
                     **{k: {} for k in ("m7_content_snapshot", "m8_swatch_content_snapshot", "m9_table_content_snapshot")}}
    final_path = candidate._final_record_path(records, upgrade.SOURCE_SHA)
    candidate._write_json_exclusive(final_path, {"candidate_sha": upgrade.SOURCE_SHA, "image_id": IMAGE})
    candidate._write_json_exclusive(candidate._stage_record_path(records, TARGET), {"candidate_sha": TARGET})
    monkeypatch.setattr(legacy, "_require_adoption_record_metadata", lambda *args: None)
    monkeypatch.setattr(candidate, "_require_execution_release", lambda *args: None)
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    monkeypatch.setattr(candidate, "_require_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(candidate, "_load_stage", lambda **kwargs: {"schema_version": 4, "target_version": 15, "image_id": IMAGE})
    monkeypatch.setattr(upgrade, "_require_source", lambda **kwargs: upgrade._load(final_path, "source"))
    for directory in (tmp_path / "backups", tmp_path / "restores"):
        directory.mkdir()
        candidate._write_json_exclusive(directory / "20260915t150000z.json", {})
    monkeypatch.setattr(legacy, "_load_verified_backup", lambda **kwargs: legacy._BoundBackupRecords(
        source_backup, upgrade._load(tmp_path / "backups/20260915t150000z.json", "backup")[1], {},
        upgrade._load(tmp_path / "restores/20260915t150000z.json", "restore")[1]))
    monkeypatch.setattr(gatea, "validate_app_image", lambda *args: IMAGE)
    monkeypatch.setattr(legacy, "_run_runtime_preflight", lambda **kwargs: {})
    monkeypatch.setattr(upgrade, "_require_stopped", lambda *args: None)
    monkeypatch.setattr(backup, "_source_snapshot", lambda *args: {} if failure == "backup-drift" else base)
    monkeypatch.setattr(backup, "_source_image_manifest", lambda *args: source_backup["image_manifest"])
    for name in ("_source_m7_content_snapshot", "_source_m8_swatch_content_snapshot", "_source_m9_table_content_snapshot"):
        monkeypatch.setattr(backup, name, lambda *args: {})
    commands, migrations, captures = [], [], []
    monkeypatch.setattr(gatea, "_run_compose", lambda **kw: commands.append(kw["arguments"]))
    def task(values, config, secrets, module, *args):
        version = int(args[-1]); migrations.append(version)
        if failure == "migration" and version == 12:
            raise upgrade.M15UpgradeError("partial DDL")
        return migration(version)
    def state(values, file, secrets, version):
        captures.append(version)
        if version == 15 and failure == "config-drift": file.write_bytes(original + b"# concurrent edit\n")
        result = snapshot(version)
        if version == 15 and captures.count(15) == 2 and failure == "replay":
            result["complete_content"]["payments"]["rows"] += 1
        return result
    monkeypatch.setattr(upgrade, "_task", task)
    monkeypatch.setattr(upgrade, "read_state", state)
    args = dict(config_file=config, secret_dir=tmp_path / "secrets", release_root=tmp_path / "releases",
                record_dir=records, current_link=tmp_path / "current", config_history_dir=history,
                backup_root=tmp_path / "backup-data", backup_record_dir=tmp_path / "backups",
                restore_record_dir=tmp_path / "restores", target_sha=TARGET, backup_id="20260915t150000z",
                apply=failure != "plan", confirm_source_sha=upgrade.SOURCE_SHA, confirm_target_sha=TARGET,
                confirm_backup_id="20260915t150000z")
    pending, success, replay = upgrade._paths(records, TARGET)
    if failure not in (None, "plan"):
        with pytest.raises(upgrade.M15UpgradeError): upgrade.upgrade(**args)
        journal = json.loads(pending.read_text())
        assert journal["phase"] == "failed" and journal["error_type"] == "M15UpgradeError"
        assert success.exists() is (failure == "replay")
        assert not replay.exists()
        assert commands == [("stop", *upgrade.WRITERS)]
        if failure == "migration": assert migrations == [10, 11, 12]
        if failure == "backup-drift": assert migrations == []
    else:
        result = upgrade.upgrade(**args)
        assert not pending.exists()
        if failure == "plan":
            assert result["writes_performed"] is False and commands == [] and migrations == []
            assert not success.exists() and config.read_bytes() == original and list(history.iterdir()) == []
        else:
            assert result["passed"] is True and result["application_stopped"] is True
            assert migrations == list(range(10, 16))
            assert success.exists() and replay.exists()
            assert gatea.parse_env_file(config)["GATEA_APP_IMAGE"] == f"pinkdoohub-gatea:{TARGET}"
            assert (history / f"{TARGET}.m15-source.env").read_bytes() == original
            assert json.loads(success.read_text())["target_state"] == snapshot(15)
