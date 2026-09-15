"""M15 收口必须使用数据后的同 ID 恢复，失败仍恢复服务并保留可重入记录。"""

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from scripts.release import gatea_m15_finalize as finalizer
from tests.release.test_gatea_m15_snapshot import snapshot


@pytest.fixture
def context(tmp_path, monkeypatch):
    c, u = finalizer.candidate, finalizer.upgrade
    monkeypatch.setattr(c.os, "fchown", lambda *args: None)
    monkeypatch.setattr(c.os, "chown", lambda *args, **kwargs: None)
    monkeypatch.setattr(u.legacy, "_require_adoption_record_metadata", lambda *args: None)
    monkeypatch.setattr(c, "_read_current_target", lambda current, root: current.resolve())
    monkeypatch.setattr(finalizer.backup, "_restore_cleanup_verified", lambda *args: None)
    records = tmp_path / "records/releases"; records.mkdir(parents=True)
    releases = tmp_path / "releases"; releases.mkdir()
    sha = "a" * 40
    for name in (sha, u.SOURCE_SHA): (releases / name).mkdir()
    current = tmp_path / "current"; current.symlink_to(releases / u.SOURCE_SHA)
    config = tmp_path / "config.env"; config.write_text("synthetic configuration")
    now = datetime.now(timezone.utc)
    at = lambda minutes: (now - timedelta(minutes=minutes)).isoformat()
    ctx = SimpleNamespace(sha=sha, image_id="sha256:" + "b" * 64, record_dir=records,
        release_root=releases, current_link=current, config_file=config, secret_dir=tmp_path / "secrets",
        values={}, pinned={}, upgrade_digest="c" * 64, acceptance_digest="d" * 64,
        acceptance={"completed_at": at(10)}, acceptance_path=tmp_path / "acceptance.json",
        upgrade_record={"source_finalization_sha256": "e" * 64})
    resilience_dir = tmp_path / "records/resilience"; resilience_dir.mkdir()
    state = snapshot(15)
    resilience = {"schema_version": 1, "record_type": "gatea-m15-resilience", "candidate_sha": sha,
        "image_id": ctx.image_id, "acceptance_sha256": ctx.acceptance_digest, "upgrade_sha256": ctx.upgrade_digest,
        "passed": True, "runtime_restored": True, "data_preserved": True, "images_preserved": True,
        "secret_values_recorded": False, "before_state": state, "after_state": state,
        "before_images": ["fixture"], "after_images": ["fixture"], "started_at": at(9), "completed_at": at(8),
        "dependency_drills": [{"service": service, "passed": True, "outage_readiness_status": 503,
            "outage_liveness_status": 200, "recovered_readiness_status": 200} for service in ("mysql", "redis")],
        "app_restart": {"passed": True, "readiness_status": 200},
        "log_scan": {"passed": True, "exact_secret_matches": 0, "forbidden_pattern_matches": 0}}
    c._write_json_exclusive(resilience_dir / f"gatea-m15-resilience-{sha}.json", resilience)
    backup_root = tmp_path / "backup-data"; backup_id = "20260915t150000z"
    artifacts = {}
    for name, path in zip(("mysql", "images"), finalizer.backup._backup_paths(backup_root, backup_id)):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"synthetic backup bytes")
        artifacts[name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": finalizer.backup._sha256(path)}
    post = {"schema_version": 1, "candidate_sha": sha, "image_id": ctx.image_id, "backup_id": backup_id,
        "passed": True, "application_restarted": True, "table_sweeper_restarted": True,
        "consistency": "nginx-and-app-stopped", "started_at": at(7), "completed_at": at(6),
        "database_snapshot": {"aerich_versions": ",".join(finalizer.gatea.APPROVED_TARGET_M15_CHAIN)},
        "m15_content_snapshot": state, "image_manifest": ["fixture"], "artifacts": artifacts}
    backup_record = tmp_path / "records/backups" / f"{backup_id}.json"; backup_record.parent.mkdir()
    c._write_json_exclusive(backup_record, post)
    restore = {"schema_version": 1, "candidate_sha": sha, "backup_id": backup_id,
        "backup_record_sha256": u._load(backup_record, "backup")[1], "started_at": at(5), "completed_at": at(4),
        "restore_project": finalizer.backup.restore_project(backup_id), "m15_content_snapshot": state,
        "mysql_artifact_sha256": artifacts["mysql"]["sha256"], "image_artifact_sha256": artifacts["images"]["sha256"],
        "host_ports_published": False, **{k: True for k in ("passed", "database_matches", "images_match", "m15_content_matches",
            "restore_app_ready", "redis_started_empty", "refresh_sessions_invalidated", "temporary_resources_removed")}}
    restore_record = tmp_path / "records/restores" / f"{backup_id}.json"; restore_record.parent.mkdir()
    c._write_json_exclusive(restore_record, restore)
    return ctx, dict(resilience_dir=resilience_dir, backup_root=backup_root, backup_id=backup_id,
                     confirm_target_sha=sha), resilience, post, restore, backup_record, restore_record


@pytest.mark.parametrize("change", (None, "different-id", "not-restored", "data-mismatch", "pending", "before-resilience", "newer-backup", "residual"))
def test_post_backup_binds_current_data_order_and_complete_cleanup(context, monkeypatch, change):
    ctx, args, resilience, post, restore, backup_path, restore_path = context
    if change == "different-id": restore["backup_id"] = "20260915t160000z"
    if change == "not-restored": restore["m15_content_matches"] = False
    if change == "data-mismatch":
        restore["m15_content_snapshot"] = snapshot(15)
        restore["m15_content_snapshot"]["complete_content"]["payments"]["rows"] += 1
    if change == "pending": (backup_path.parent / f".{args['backup_id']}.pending.json").write_text("{}")
    if change == "before-resilience": post["started_at"] = ctx.acceptance["completed_at"]
    if change == "newer-backup": post["extra"] = "changed after restore"
    if change == "residual":
        monkeypatch.setattr(finalizer.backup, "_restore_cleanup_verified", lambda *args: (_ for _ in ()).throw(finalizer.gatea.GateAError("restore resources remain")))
    backup_path.write_text(json.dumps(post)); backup_path.chmod(0o644)
    # 刻意保留旧摘要仅用于 newer-backup；其余测试聚焦各自的拒绝原因。
    if change != "newer-backup": restore["backup_record_sha256"] = finalizer.upgrade._load(backup_path, "backup")[1]
    restore_path.write_text(json.dumps(restore)); restore_path.chmod(0o644)
    if change:
        with pytest.raises(finalizer.gatea.GateAError):
            finalizer._post_backup(ctx, args["backup_id"], args["backup_root"], resilience)
    else:
        _, _, binding = finalizer._post_backup(ctx, args["backup_id"], args["backup_root"], resilience)
        assert binding["post_backup_id"] == args["backup_id"]


@pytest.mark.parametrize("failure", (None, "live-data", "restore-services", "after-link", "after-record"))
def test_finalization_keeps_source_on_validation_failure_and_recovers_publication(context, monkeypatch, failure):
    ctx, args, _, post, _, _, _ = context
    c = finalizer.candidate
    calls = []
    monkeypatch.setattr(finalizer.gatea, "_run_compose", lambda **kw: calls.append("stop"))
    monkeypatch.setattr(finalizer.upgrade, "_require_stopped", lambda *args: None)
    monkeypatch.setattr(finalizer, "_state", lambda _: snapshot(14) if failure == "live-data" else post["m15_content_snapshot"])
    monkeypatch.setattr(finalizer, "_images", lambda _: ["fixture"])
    monkeypatch.setattr(finalizer, "_require_acceptance_unchanged", lambda _: None)
    monkeypatch.setattr(finalizer.gatea, "validate_app_image", lambda _: ctx.image_id)
    def restore(_):
        calls.append("restore")
        if failure == "restore-services": raise finalizer.M15FinalizeError("recovery failed")
    monkeypatch.setattr(finalizer, "_restore", restore)
    pending = c._final_pending_path(ctx.record_dir, ctx.sha)
    target = c._final_record_path(ctx.record_dir, ctx.sha)
    write = c._write_json_exclusive
    interrupted = False
    def interrupted_write(path, payload, *args):
        nonlocal interrupted
        if path == target and failure in {"after-link", "after-record"} and not interrupted:
            interrupted = True
            if failure == "after-record": write(path, payload, *args)
            raise OSError("publication interrupted")
        return write(path, payload, *args)
    monkeypatch.setattr(c, "_write_json_exclusive", interrupted_write)
    if failure:
        with pytest.raises((finalizer.gatea.GateAError, OSError)): finalizer.finalize(ctx, **args)
        assert calls == ["stop", "restore"] and pending.exists()
        if failure in {"after-link", "after-record"}:
            assert ctx.current_link.resolve() == ctx.release_root / ctx.sha
            result = finalizer.finalize(ctx, **args)
            assert result["passed"] is True and not pending.exists()
        else:
            assert ctx.current_link.resolve() == ctx.release_root / finalizer.upgrade.SOURCE_SHA
            assert not target.exists()
    else:
        result = finalizer.finalize(ctx, **args)
        assert result["passed"] is True and not pending.exists()
        assert ctx.current_link.resolve() == ctx.release_root / ctx.sha
        assert json.loads(target.read_text()) == result


@pytest.mark.parametrize("failure", (None, "dependency", "restart", "data", "recovery"))
def test_resilience_restores_services_and_retains_failure_journal(context, monkeypatch, failure):
    ctx, args, proof, post, *_ = context
    path = args["resilience_dir"] / f"gatea-m15-resilience-{ctx.sha}.json"
    path.unlink()
    calls = []
    monkeypatch.setattr(finalizer.candidate, "_require_root_directory", lambda *a: None)
    monkeypatch.setattr(finalizer.m9, "_ensure_m9_services", lambda *a: None)
    monkeypatch.setattr(finalizer.gatea, "_run_m9_table_reconcile", lambda **kw: {"open_sessions": 0, "occupancies": 0})
    states = iter((post["m15_content_snapshot"], snapshot(14) if failure == "data" else post["m15_content_snapshot"]))
    monkeypatch.setattr(finalizer, "_state", lambda _: next(states))
    monkeypatch.setattr(finalizer, "_images", lambda _: ["fixture"])
    monkeypatch.setattr(finalizer, "_require_acceptance_unchanged", lambda _: None)
    monkeypatch.setattr(finalizer.m9, "_verify_log_redaction", lambda *a, **kw: proof["log_scan"])
    def drill(**kw):
        calls.append(kw["service"])
        if failure == "dependency": raise finalizer.M15FinalizeError("dependency failed")
        return next(row for row in proof["dependency_drills"] if row["service"] == kw["service"])
    def restart(**kw):
        calls.append("restart")
        if failure == "restart": raise finalizer.M15FinalizeError("restart failed")
        return proof["app_restart"]
    def restore(_):
        calls.append("restore")
        if failure == "recovery": raise finalizer.M15FinalizeError("restore failed")
    monkeypatch.setattr(finalizer.resilience, "_dependency_drill", drill)
    monkeypatch.setattr(finalizer.resilience, "_app_restart_drill", restart)
    monkeypatch.setattr(finalizer, "_restore", restore)
    pending = ctx.record_dir / f"{ctx.sha}.m15-resilience.pending.json"
    if failure:
        with pytest.raises((ValueError, finalizer.gatea.GateAError)):
            finalizer.run_resilience(ctx, args["resilience_dir"])
        assert pending.exists() and not path.exists()
    else:
        assert finalizer.run_resilience(ctx, args["resilience_dir"])["passed"] is True
        assert not pending.exists() and path.exists()
    assert calls[-1] == "restore" and calls.count("restore") == 1
