"""绑定 M15 验收、韧性和数据后恢复，最后推进 current 与 finalized lineage。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

from scripts.release import gatea_backup as backup
from scripts.release import gatea_candidate as candidate
from scripts.release import gatea_m15_acceptance as acceptance
from scripts.release import gatea_m15_upgrade as upgrade
from scripts.release import gatea_m9_acceptance as m9
from scripts.release import gatea_operations as gatea
from scripts.release import gatea_resilience as resilience


class M15FinalizeError(gatea.GateAError):
    """M15 收口证据或受控恢复未完成。"""


def _time(value: Any) -> datetime:
    if not candidate._is_utc_timestamp(value):
        raise M15FinalizeError("Gate A M15 evidence timestamp is invalid")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _context(*, config_file: Path, secret_dir: Path, release_root: Path, record_dir: Path,
             acceptance_dir: Path, current_link: Path, target_sha: str,
             own_pending: Path | None = None) -> SimpleNamespace:
    candidate._require_execution_release(release_root, target_sha)
    gatea._validate_root_directory(record_dir, 0o755, "Gate A release records")
    allowance = None
    if own_pending is not None:
        journal, _ = upgrade._load(own_pending, "M15 finalization pending")
        if (type(journal.get("schema_version")) is not int or journal.get("schema_version") != 3 or journal.get("record_type") != "gatea-m15-finalization-pending"
                or journal.get("candidate_sha") != target_sha
                or own_pending != candidate._final_pending_path(record_dir, target_sha)):
            raise M15FinalizeError("Gate A M15 pending identity is invalid")
        allowance = gatea.CandidateTransitionRecoveryAllowance(path=own_pending,
                    kind="current-finalization", candidate_sha=target_sha)
    gatea.reject_unresolved_candidate_transition_journals(record_dir=record_dir,
        candidate_sha=target_sha if allowance else None, recovery_allowance=allowance)
    gatea.reject_unresolved_m9_acceptance_sidecars(record_dir=gatea.DEFAULT_M9_ACCEPTANCE_RECORD_DIR)
    values = gatea._validated_inputs(config_file=config_file, secret_dir=secret_dir,
                                    mode="loopback", require_available_port=False)
    if gatea._candidate_sha(values) != target_sha:
        raise M15FinalizeError("Gate A M15 live candidate differs")
    image_id = gatea.validate_app_image(values)
    stage = candidate._load_stage(release_root=release_root, release_record_dir=record_dir, target_sha=target_sha)
    if stage.get("schema_version") != 4 or stage.get("image_id") != image_id:
        raise M15FinalizeError("Gate A M15 stage differs from the live image")
    upgrade_record = gatea._require_upgrade_record(record_dir=record_dir, candidate_sha=target_sha, image_id=image_id)
    if upgrade_record.get("transition_kind") != upgrade.TRANSITION_KIND:
        raise M15FinalizeError("Gate A M15 upgrade is missing")
    upgrade.require_replay(record_dir=record_dir, candidate_sha=target_sha, image_id=image_id, upgrade_record=upgrade_record)
    upgrade_digest = upgrade._load(gatea._upgrade_marker(record_dir, target_sha), "M15 upgrade")[1]
    accepted, acceptance_digest = upgrade._load(acceptance.record_path(acceptance_dir, target_sha), "M15 acceptance")
    acceptance.require_result(accepted, sha=target_sha, image_id=image_id, upgrade_sha256=upgrade_digest)
    link = candidate._read_current_target(current_link, release_root)
    if link != release_root / upgrade.SOURCE_SHA and not (own_pending and link == release_root / target_sha):
        raise M15FinalizeError("Gate A M15 current lineage is not the approved source")
    return SimpleNamespace(values=values, pinned={**values, "GATEA_APP_IMAGE": image_id},
        config_file=config_file, secret_dir=secret_dir, image_id=image_id, sha=target_sha,
        record_dir=record_dir, release_root=release_root, current_link=current_link,
        acceptance=accepted, acceptance_digest=acceptance_digest, upgrade_digest=upgrade_digest,
        upgrade_record=upgrade_record, acceptance_path=acceptance.record_path(acceptance_dir, target_sha))


def _state(ctx: SimpleNamespace) -> dict[str, Any]:
    return upgrade.read_state(ctx.pinned, ctx.config_file, ctx.secret_dir, 15)


def _images(ctx: SimpleNamespace) -> list[str]:
    return backup._source_image_manifest(ctx.values, ctx.config_file, ctx.secret_dir, "loopback")


def _restore(ctx: SimpleNamespace) -> None:
    resilience._restore_all_services(values=ctx.pinned, config_file=ctx.config_file,
        secret_dir=ctx.secret_dir, services=upgrade.SERVICES, timeout=180)


def _require_acceptance_unchanged(ctx: SimpleNamespace) -> None:
    if upgrade._load(ctx.acceptance_path, "M15 acceptance")[1] != ctx.acceptance_digest:
        raise M15FinalizeError("Gate A M15 acceptance changed during the operation")


def _require_resilience(payload: dict[str, Any], ctx: SimpleNamespace) -> None:
    if (type(payload.get("schema_version")) is not int or payload["schema_version"] != 1
            or payload.get("record_type") != "gatea-m15-resilience"
            or payload.get("candidate_sha") != ctx.sha or payload.get("image_id") != ctx.image_id
            or payload.get("acceptance_sha256") != ctx.acceptance_digest
            or payload.get("upgrade_sha256") != ctx.upgrade_digest
            or payload.get("passed") is not True or payload.get("runtime_restored") is not True
            or payload.get("data_preserved") is not True or payload.get("images_preserved") is not True
            or payload.get("secret_values_recorded") is not False
            or payload.get("before_state") != payload.get("after_state")
            or not isinstance(payload.get("before_images"), list)
            or payload.get("before_images") != payload.get("after_images")):
        raise M15FinalizeError("Gate A M15 resilience evidence is invalid")
    upgrade.snapshots.validate_snapshot(payload["after_state"], 15)
    drills = payload.get("dependency_drills")
    if not isinstance(drills, list) or len(drills) != 2:
        raise M15FinalizeError("Gate A M15 dependency drills are incomplete")
    for service, drill in zip(("mysql", "redis"), drills):
        if (drill.get("service") != service or drill.get("passed") is not True
                or drill.get("outage_readiness_status") != 503 or drill.get("outage_liveness_status") != 200
                or drill.get("recovered_readiness_status") != 200):
            raise M15FinalizeError("Gate A M15 dependency recovery is invalid")
    if (payload.get("app_restart", {}).get("passed") is not True
            or payload["app_restart"].get("readiness_status") != 200
            or payload.get("log_scan", {}).get("passed") is not True
            or payload["log_scan"].get("exact_secret_matches") != 0
            or payload["log_scan"].get("forbidden_pattern_matches") != 0
            or _time(payload["started_at"]) < _time(ctx.acceptance["completed_at"])
            or _time(payload["completed_at"]) < _time(payload["started_at"])):
        raise M15FinalizeError("Gate A M15 resilience must follow acceptance and restore readiness")


def run_resilience(ctx: SimpleNamespace, resilience_dir: Path) -> dict[str, Any]:
    candidate._require_root_directory(resilience_dir, 0o755, "M15 resilience records")
    target = resilience_dir / f"gatea-m15-resilience-{ctx.sha}.json"
    pending = ctx.record_dir / f"{ctx.sha}.m15-resilience.pending.json"
    if target.exists() or target.is_symlink() or pending.exists() or pending.is_symlink():
        raise M15FinalizeError("Gate A M15 resilience already has evidence")
    m9._ensure_m9_services(ctx)
    before, images = _state(ctx), _images(ctx)
    reconcile = gatea._run_m9_table_reconcile(values=ctx.pinned, config_file=ctx.config_file,
        secret_dir=ctx.secret_dir, mode="loopback")
    if reconcile["open_sessions"] or reconcile["occupancies"]:
        raise M15FinalizeError("Gate A M15 resilience requires all sessions closed")
    started = upgrade.legacy._iso_now()
    candidate._write_json_exclusive(pending, {"record_type": "gatea-m15-resilience-pending",
        "candidate_sha": ctx.sha, "started_at": started, "acceptance_sha256": ctx.acceptance_digest})
    failure = None
    recovery_failure = None
    drills = []
    with resilience._resilience_termination_guard() as termination:
        try:
            for service in ("mysql", "redis"):
                drills.append(resilience._dependency_drill(service=service, values=ctx.pinned,
                    config_file=ctx.config_file, secret_dir=ctx.secret_dir,
                    port=int(ctx.values.get("GATEA_LOOPBACK_PORT", "18080")), timeout=180))
            restart = resilience._app_restart_drill(values=ctx.pinned, config_file=ctx.config_file,
                secret_dir=ctx.secret_dir, port=int(ctx.values.get("GATEA_LOOPBACK_PORT", "18080")), timeout=180)
        except BaseException as error:
            failure = error
        finally:
            try:
                termination.begin_recovery()
            finally:
                try: _restore(ctx)
                except BaseException as error: recovery_failure = error
        if recovery_failure is not None:
            raise M15FinalizeError("Gate A M15 resilience could not restore all services") from recovery_failure
        if failure is not None: raise failure
        if termination.interruption is not None: raise termination.interruption
    after, after_images = _state(ctx), _images(ctx)
    _require_acceptance_unchanged(ctx)
    logs = m9._verify_log_redaction(ctx, transient_secrets=())
    payload = {"schema_version": 1, "record_type": "gatea-m15-resilience", "candidate_sha": ctx.sha,
        "image_id": ctx.image_id, "acceptance_sha256": ctx.acceptance_digest, "upgrade_sha256": ctx.upgrade_digest,
        "before_state": before, "after_state": after, "before_images": images, "after_images": after_images,
        "started_at": started, "completed_at": upgrade.legacy._iso_now(), "dependency_drills": drills,
        "app_restart": restart, "log_scan": logs, "data_preserved": before == after,
        "images_preserved": images == after_images, "runtime_restored": True,
        "secret_values_recorded": False, "passed": True}
    _require_resilience(payload, ctx)
    candidate._write_json_exclusive(target, payload)
    pending.unlink(); candidate._fsync_directory(ctx.record_dir)
    return payload


def _post_backup(ctx: SimpleNamespace, backup_id: str, backup_root: Path,
                 resilience_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    backup_id = backup._backup_id(backup_id)
    root = ctx.record_dir.parent
    pending = root / "backups" / f".{backup_id}.pending.json"
    if pending.exists() or pending.is_symlink():
        raise M15FinalizeError("Gate A M15 post backup still has a pending journal")
    payload, backup_digest = upgrade._load(root / "backups" / f"{backup_id}.json", "M15 post backup")
    payload, _, _ = backup._validate_loaded_backup_record(payload=payload, backup_id=backup_id, backup_root=backup_root)
    restore, restore_digest = upgrade._load(root / "restores" / f"{backup_id}.json", "M15 post restore")
    now = datetime.now(timezone.utc)
    if (payload.get("candidate_sha") != ctx.sha or payload.get("image_id") != ctx.image_id
            or payload.get("application_restarted") is not True or payload.get("table_sweeper_restarted") is not True
            or payload.get("consistency") != "nginx-and-app-stopped"
            or _time(payload["started_at"]) < _time(resilience_payload["completed_at"])
            or not _time(payload["started_at"]) <= _time(payload["completed_at"]) <= _time(restore["started_at"]) <= _time(restore["completed_at"])
            or now - _time(payload["completed_at"]) > timedelta(hours=24)
            or _time(restore["completed_at"]) > now + timedelta(minutes=5)
            or restore.get("backup_id") != backup_id or restore.get("candidate_sha") != ctx.sha
            or restore.get("backup_record_sha256") != backup_digest
            or restore.get("restore_project") != backup.restore_project(backup_id)
            or restore.get("mysql_artifact_sha256") != payload["artifacts"]["mysql"]["sha256"]
            or restore.get("image_artifact_sha256") != payload["artifacts"]["images"]["sha256"]
            or restore.get("m15_content_snapshot") != payload.get("m15_content_snapshot")
            or restore.get("host_ports_published") is not False
            or any(restore.get(k) is not True for k in ("passed", "database_matches", "images_match", "m15_content_matches",
                "restore_app_ready", "redis_started_empty", "refresh_sessions_invalidated", "temporary_resources_removed"))):
        raise M15FinalizeError("Gate A M15 post-acceptance backup/restore binding is invalid")
    backup._restore_cleanup_verified(backup.restore_project(backup_id))
    return payload, restore, {"post_backup_id": backup_id, "post_backup_sha256": backup_digest, "post_restore_sha256": restore_digest}


def _link_current(ctx: SimpleNamespace) -> None:
    live = candidate._read_current_target(ctx.current_link, ctx.release_root)
    if live == ctx.release_root / ctx.sha: return
    if live != ctx.release_root / upgrade.SOURCE_SHA:
        raise M15FinalizeError("Gate A current changed during finalization")
    temporary = ctx.current_link.parent / f".current.m15-{ctx.sha}"
    if temporary.exists() or temporary.is_symlink():
        raise M15FinalizeError("Gate A M15 temporary current link needs inspection")
    try:
        os.symlink(os.path.relpath(ctx.release_root / ctx.sha, ctx.current_link.parent), temporary)
        os.chown(temporary, 0, 0, follow_symlinks=False)
        candidate._fsync_directory(ctx.current_link.parent)
        os.replace(temporary, ctx.current_link)
        candidate._fsync_directory(ctx.current_link.parent)
    finally:
        temporary.unlink(missing_ok=True)


def finalize(ctx: SimpleNamespace, *, resilience_dir: Path, backup_root: Path,
             backup_id: str, confirm_target_sha: str) -> dict[str, Any]:
    if confirm_target_sha != ctx.sha:
        raise M15FinalizeError("Gate A M15 finalization must confirm its exact target")
    resilience_record, resilience_digest = upgrade._load(resilience_dir / f"gatea-m15-resilience-{ctx.sha}.json", "M15 resilience")
    _require_resilience(resilience_record, ctx)
    post, _, post_binding = _post_backup(ctx, backup_id, backup_root, resilience_record)
    pending, target = candidate._final_pending_path(ctx.record_dir, ctx.sha), candidate._final_record_path(ctx.record_dir, ctx.sha)
    binding = {"candidate_sha": ctx.sha, "image_id": ctx.image_id,
        "source_candidate_sha": upgrade.SOURCE_SHA, "source_finalization_sha256": ctx.upgrade_record["source_finalization_sha256"],
        "upgrade_sha256": ctx.upgrade_digest, "acceptance_sha256": ctx.acceptance_digest,
        "resilience_sha256": resilience_digest, **post_binding,
        "config_sha256": candidate._sha256(ctx.config_file)}
    if pending.exists():
        journal, _ = upgrade._load(pending, "M15 finalization pending")
        if (set(journal) != {"schema_version", "record_type", "phase", "started_at"} | set(binding)
                or type(journal.get("schema_version")) is not int or journal.get("schema_version") != 3 or journal.get("record_type") != "gatea-m15-finalization-pending"
                or journal.get("phase") not in {"prepared", "runtime-restored", "current-linked"}
                or not candidate._is_utc_timestamp(journal.get("started_at"))
                or any(journal.get(k) != v for k, v in binding.items())):
            raise M15FinalizeError("Gate A M15 recovery journal no longer matches its evidence")
    else:
        if target.exists() or target.is_symlink():
            raise M15FinalizeError("Gate A M15 is already finalized")
        journal = {"schema_version": 3, "record_type": "gatea-m15-finalization-pending", "phase": "prepared",
                   "started_at": upgrade.legacy._iso_now(), **binding}
        candidate._write_json_exclusive(pending, journal)
    failure = None
    with resilience._resilience_termination_guard() as termination:
        try:
            gatea._run_compose(values=ctx.pinned, config_file=ctx.config_file, secret_dir=ctx.secret_dir,
                               mode="loopback", arguments=("stop", *upgrade.WRITERS))
            upgrade._require_stopped(ctx.pinned, ctx.config_file, ctx.secret_dir)
            if _state(ctx) != post["m15_content_snapshot"] or _images(ctx) != post["image_manifest"]:
                raise M15FinalizeError("Gate A M15 live content differs from the independently restored backup")
            _require_acceptance_unchanged(ctx)
            if gatea.validate_app_image(ctx.values) != ctx.image_id or candidate._sha256(ctx.config_file) != binding["config_sha256"]:
                raise M15FinalizeError("Gate A M15 image or configuration changed")
        except BaseException as error:
            failure = error
        finally:
            try: termination.begin_recovery()
            finally: _restore(ctx)
        if failure is not None: raise failure
        if termination.interruption is not None: raise termination.interruption
    journal["phase"] = "runtime-restored"
    candidate._atomic_replace_json(pending, journal, 0o644)
    _require_acceptance_unchanged(ctx)
    _link_current(ctx)
    journal["phase"] = "current-linked"
    candidate._atomic_replace_json(pending, journal, 0o644)
    result = {"schema_version": 3, "record_type": "gatea-current-finalization", "transition_kind": upgrade.TRANSITION_KIND,
        "phase": "runtime-restored", "source_version": 9, "target_version": 15, **binding,
        "source_link": str(ctx.release_root / upgrade.SOURCE_SHA), "target_link": str(ctx.release_root / ctx.sha),
        "runtime_services": list(upgrade.SERVICES), "started_at": journal["started_at"],
        "completed_at": upgrade.legacy._iso_now(), "passed": True, "secret_values_recorded": False}
    if target.exists():
        previous, _ = upgrade._load(target, "M15 finalization")
        # 仅允许发布成功后、删除 pending 前的重入；完成时间保留第一次发布值。
        result["completed_at"] = previous.get("completed_at")
        if previous != result: raise M15FinalizeError("Gate A M15 finalized record differs from recovery")
    else:
        candidate._write_json_exclusive(target, result)
    if candidate._read_current_target(ctx.current_link, ctx.release_root) != ctx.release_root / ctx.sha:
        raise M15FinalizeError("Gate A M15 current publication did not persist")
    pending.unlink(); candidate._fsync_directory(ctx.record_dir)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("resilience", "finalize"))
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--confirm-target-sha")
    parser.add_argument("--backup-id")
    for name, default in (("config-file", gatea.DEFAULT_CONFIG_FILE), ("secret-dir", gatea.DEFAULT_SECRET_DIR),
        ("release-root", Path("/srv/pinkdoohub/gatea/releases")), ("record-dir", gatea.DEFAULT_RECORD_DIR),
        ("acceptance-dir", acceptance.DEFAULT_RECORD_DIR), ("current-link", Path("/srv/pinkdoohub/gatea/current")),
        ("resilience-dir", Path("/srv/pinkdoohub/gatea/records/resilience")), ("backup-root", backup.DEFAULT_BACKUP_ROOT)):
        parser.add_argument(f"--{name}", type=Path, default=default)
    args = parser.parse_args(argv)
    try:
        with gatea.operation_lock(), gatea.operation_termination_guard():
            pending = candidate._final_pending_path(args.record_dir, args.target_sha)
            ctx = _context(**{key: getattr(args, key) for key in ("config_file", "secret_dir", "release_root", "record_dir", "acceptance_dir", "current_link", "target_sha")},
                           own_pending=pending if args.command == "finalize" and pending.exists() else None)
            if args.command == "resilience": result = run_resilience(ctx, args.resilience_dir)
            else:
                if args.backup_id is None: raise M15FinalizeError("Gate A M15 finalization requires its post backup ID")
                result = finalize(ctx, resilience_dir=args.resilience_dir, backup_root=args.backup_root,
                                  backup_id=args.backup_id, confirm_target_sha=args.confirm_target_sha)
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}), file=sys.stderr); return 1
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
