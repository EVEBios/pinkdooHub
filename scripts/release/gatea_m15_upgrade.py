"""从已收口 G/M9 执行一次停写的 M10–M15 前滚；失败保留现场，禁止自动降级。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping

from app.tasks import gatea_m15_snapshot as snapshots
from scripts.release import gatea_backup as backup
from scripts.release import gatea_candidate as candidate
from scripts.release import gatea_operations as gatea
from scripts.release import gatea_upgrade as legacy


SOURCE_SHA = candidate.SOURCE_M9_SHA
TARGET_VERSION = 15
TRANSITION_KIND = "m9-m15-upgrade"
WRITERS = ("nginx", "app", "table-sweeper")
SERVICES = ("mysql", "redis", "app", "table-sweeper", "nginx")


class M15UpgradeError(gatea.GateAError):
    """仅包含安全操作上下文，不输出数据库行或配置值。"""


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(snapshots.canonical(payload)).hexdigest()


def _load(path: Path, description: str) -> tuple[dict[str, Any], str]:
    return legacy._load_bound_json_with_sha256(path, description)


def _paths(record_dir: Path, target_sha: str) -> tuple[Path, Path, Path]:
    return (
        record_dir / f"{target_sha}.m15-upgrade.pending.json",
        gatea._upgrade_marker(record_dir, target_sha),
        gatea._upgrade_replay_marker(record_dir, target_sha),
    )


def _task(values: Mapping[str, str], config_file: Path, secret_dir: Path,
          module: str, *arguments: str) -> dict[str, Any]:
    return legacy._run_task(values=values, config_file=config_file,
        secret_dir=secret_dir, mode="loopback", service="migrate", module=module,
        arguments=arguments, operations_profile=True, description=module.rsplit(".", 1)[-1])


def read_state(values: Mapping[str, str], config_file: Path, secret_dir: Path,
               version: int, *, start_new_session: bool = False) -> dict[str, Any]:
    result = gatea._run_compose(values=values, config_file=config_file, secret_dir=secret_dir,
        mode="loopback", profiles=("operations",), arguments=("run", "--rm", "--no-deps", "-T",
        "migrate", "python", "-B", "-m", "app.tasks.gatea_m15_snapshot", "--version", str(version)),
        capture_output=True, check=False, start_new_session=start_new_session)
    if result.returncode != 0:
        raise M15UpgradeError(f"Gate A M{version} state capture failed")
    state = legacy._parse_json_object(result.stdout, "M15 state capture")
    snapshots.validate_snapshot(state, version)
    return state


def _require_stopped(values: Mapping[str, str], config_file: Path, secret_dir: Path) -> None:
    rows = gatea._compose_ps(values=values, config_file=config_file,
        secret_dir=secret_dir, mode="loopback", services=SERVICES)
    gatea._ensure_services_healthy(rows, "mysql", "redis")
    legacy._ensure_not_running(rows, *WRITERS)


def execute_steps(*, values: Mapping[str, str], config_file: Path, secret_dir: Path,
                  source_state: dict[str, Any], checkpoint: Callable[[dict[str, Any]], None]
                  ) -> list[dict[str, Any]]:
    """持久入口和隔离演练共用真实迁移路径；checkpoint 必须同步落盘。"""
    snapshots.validate_snapshot(source_state, 9)
    results: list[dict[str, Any]] = []
    for version in range(10, TARGET_VERSION + 1):
        _require_stopped(values, config_file, secret_dir)
        checkpoint({"phase": "before-migration", "version": version})
        result = _task(values, config_file, secret_dir, "app.tasks.gatea_migrate_step",
                       "--target-version", str(version))
        expected = {"target_version": version, "migration": snapshots.APPROVED_MIGRATIONS[version],
                    "applied": True, "aerich_versions": list(snapshots.APPROVED_MIGRATIONS[:version + 1])}
        if _digest(result) != _digest(expected):
            raise M15UpgradeError(f"Gate A M{version} did not apply exactly one migration")
        state = read_state(values, config_file, secret_dir, version)
        snapshots.require_preserved(source_state, state, target=version)
        item = {"phase": "migration-verified", "version": version,
                "migration": result, "state": state}
        checkpoint(item)
        results.append(item)
    return results


def _require_source(*, release_root: Path, current_link: Path, record_dir: Path,
                    values: Mapping[str, str]) -> tuple[dict[str, Any], str]:
    if (gatea._candidate_sha(values) != SOURCE_SHA
            or candidate._read_current_target(current_link, release_root) != release_root / SOURCE_SHA):
        raise M15UpgradeError("Gate A M15 requires current and live to be the finalized G/M9 source")
    final, digest = _load(candidate._final_record_path(record_dir, SOURCE_SHA), "M9 finalization")
    image_id = gatea.validate_app_image(values)
    if (final.get("record_type") != "gatea-current-finalization"
            or final.get("candidate_sha") != SOURCE_SHA or final.get("image_id") != image_id
            or final.get("passed") is not True or final.get("phase") != "runtime-restored"
            or final.get("runtime_services") != list(SERVICES)
            or final.get("target_link") != str(release_root / SOURCE_SHA)
            or not candidate._is_utc_timestamp(final.get("completed_at"))):
        raise M15UpgradeError("Gate A source finalization does not bind the live M9 release")
    source = gatea._require_upgrade_record(record_dir=record_dir, candidate_sha=SOURCE_SHA, image_id=image_id)
    gatea._require_m9_upgrade_replay_record(record_dir=record_dir, candidate_sha=SOURCE_SHA,
                                          image_id=image_id, upgrade_record=source)
    for field, path in (
        ("stage_record_sha256", candidate._stage_record_path(record_dir, SOURCE_SHA)),
        ("activation_record_sha256", candidate._activation_record_path(record_dir, SOURCE_SHA)),
        ("upgrade_record_sha256", gatea._upgrade_marker(record_dir, SOURCE_SHA)),
        ("upgrade_plan_replay_record_sha256", gatea._upgrade_replay_marker(record_dir, SOURCE_SHA)),
    ):
        if _load(path, "M9 finalized dependency")[1] != final.get(field):
            raise M15UpgradeError("Gate A finalized M9 dependency changed")
    return final, digest


def _validate_steps(source: dict[str, Any], steps: Any) -> dict[str, Any]:
    if not isinstance(steps, list) or len(steps) != 6:
        raise M15UpgradeError("Gate A M15 requires six verified steps")
    for version, item in enumerate(steps, 10):
        if (not isinstance(item, dict) or set(item) != {"phase", "version", "migration", "state"}
                or type(item.get("version")) is not int or item["version"] != version
                or item.get("phase") != "migration-verified"):
            raise M15UpgradeError("Gate A M15 migration journal is invalid")
        expected = {"target_version": version, "migration": snapshots.APPROVED_MIGRATIONS[version],
                    "applied": True, "aerich_versions": list(snapshots.APPROVED_MIGRATIONS[:version + 1])}
        if not isinstance(item["migration"], dict) or _digest(item["migration"]) != _digest(expected):
            raise M15UpgradeError("Gate A M15 migration journal has an invalid step")
        snapshots.require_preserved(source, item["state"], target=version)
    return steps[-1]["state"]


def require_upgrade_record(payload: dict[str, Any], *, record_dir: Path,
                           candidate_sha: str, image_id: str) -> dict[str, Any]:
    """运行入口验证升级提交和依赖摘要；业务增加后不再比较停写时的行数。"""
    try:
        if (type(payload.get("schema_version")) is not int or payload["schema_version"] != 3
                or payload.get("record_type") != "existing-database-upgrade"
                or payload.get("transition_kind") != TRANSITION_KIND
                or payload.get("candidate_sha") != candidate_sha or payload.get("image_id") != image_id
                or gatea.GIT_SHA_PATTERN.fullmatch(candidate_sha) is None or candidate_sha == SOURCE_SHA
                or payload.get("source_candidate_sha") != SOURCE_SHA
                or not isinstance(payload.get("source_image_id"), str)
                or not payload["source_image_id"].startswith("sha256:")
                or gatea.BACKUP_ID_PATTERN.fullmatch(str(payload.get("backup_id", ""))) is None
                or any(gatea.SHA256_PATTERN.fullmatch(str(payload.get(field, ""))) is None
                       for field in ("backup_record_sha256", "restore_record_sha256"))
                or type(payload.get("source_version")) is not int or payload["source_version"] != 9
                or type(payload.get("target_version")) is not int or payload["target_version"] != 15
                or payload.get("source_aerich_versions") != list(gatea.APPROVED_TARGET_M9_CHAIN)
                or payload.get("target_aerich_versions") != list(gatea.APPROVED_TARGET_M15_CHAIN)
                or payload.get("passed") is not True or payload.get("secret_values_recorded") is not False
                or not candidate._is_utc_timestamp(payload.get("completed_at"))):
            raise M15UpgradeError("Gate A M15 upgrade record contract is invalid")
        if _validate_steps(payload["source_state"], payload["steps"]) != payload["target_state"]:
            raise M15UpgradeError("Gate A M15 final state differs from its verified steps")
        for field, path in (
            ("stage_record_sha256", candidate._stage_record_path(record_dir, candidate_sha)),
            ("source_finalization_sha256", candidate._final_record_path(record_dir, SOURCE_SHA)),
            ("activation_record_sha256", candidate._activation_record_path(record_dir, candidate_sha)),
            ("backup_record_sha256", record_dir.parent / "backups" / f"{payload['backup_id']}.json"),
            ("restore_record_sha256", record_dir.parent / "restores" / f"{payload['backup_id']}.json"),
        ):
            if _load(path, "M15 bound dependency")[1] != payload.get(field):
                raise M15UpgradeError("Gate A M15 upgrade dependency changed")
        if (payload["source_image_manifest"] != payload["target_image_manifest"]
                or not isinstance(payload["source_image_manifest"], list)):
            raise M15UpgradeError("Gate A M15 upgrade changed image content")
    except (KeyError, TypeError, snapshots.M15SnapshotError) as error:
        raise M15UpgradeError("Gate A M15 upgrade record is invalid") from error
    return payload


def require_replay(*, record_dir: Path, candidate_sha: str, image_id: str,
                   upgrade_record: dict[str, Any]) -> dict[str, Any]:
    replay, _ = _load(gatea._upgrade_replay_marker(record_dir, candidate_sha), "M15 replay")
    if (type(replay.get("schema_version")) is not int or replay["schema_version"] != 3
            or replay.get("record_type") != "existing-database-upgrade-plan-replay"
            or replay.get("transition_kind") != TRANSITION_KIND
            or replay.get("candidate_sha") != candidate_sha or replay.get("image_id") != image_id
            or replay.get("upgrade_record_sha256") != _load(gatea._upgrade_marker(record_dir, candidate_sha), "M15 upgrade")[1]
            or replay.get("target_state") != upgrade_record["target_state"]
            or replay.get("passed") is not True or replay.get("already_current") is not True
            or replay.get("read_only") is not True or not candidate._is_utc_timestamp(replay.get("completed_at"))):
        raise M15UpgradeError("Gate A M15 read-only replay is invalid")
    return replay


def upgrade(*, config_file: Path, secret_dir: Path, release_root: Path,
            record_dir: Path, current_link: Path, config_history_dir: Path,
            backup_root: Path, backup_record_dir: Path, restore_record_dir: Path,
            target_sha: str, backup_id: str, apply: bool = False,
            confirm_source_sha: str | None = None, confirm_target_sha: str | None = None,
            confirm_backup_id: str | None = None) -> dict[str, Any]:
    """默认只读计划；完整迁移后保留停写，由受控 app-up 单独启动五服务。"""
    if gatea.GIT_SHA_PATTERN.fullmatch(target_sha) is None or target_sha == SOURCE_SHA:
        raise M15UpgradeError("Gate A M15 target must be a distinct immutable candidate")
    backup_id = backup._backup_id(backup_id)
    if (backup_record_dir != record_dir.parent / "backups"
            or restore_record_dir != record_dir.parent / "restores"):
        raise M15UpgradeError("Gate A M15 backup records must use the release's bound record layout")
    candidate._require_execution_release(release_root, target_sha)
    gatea._validate_root_directory(record_dir, 0o755, "Gate A release record directory")
    gatea.reject_unresolved_candidate_transition_journals(record_dir=record_dir)
    gatea.reject_unresolved_m9_acceptance_sidecars(record_dir=gatea.DEFAULT_M9_ACCEPTANCE_RECORD_DIR)
    stage = candidate._load_stage(release_root=release_root, release_record_dir=record_dir, target_sha=target_sha)
    if stage.get("schema_version") != 4 or stage.get("target_version") != 15:
        raise M15UpgradeError("Gate A M15 requires its own reviewed stage")
    values = gatea._validated_inputs(config_file=config_file, secret_dir=secret_dir,
                                    mode="loopback", require_available_port=False)
    final, final_digest = _require_source(release_root=release_root, current_link=current_link,
                                         record_dir=record_dir, values=values)
    bound = legacy._load_verified_backup(values=values, backup_id=backup_id,
        source_candidate_sha=SOURCE_SHA, backup_root=backup_root,
        backup_record_dir=backup_record_dir, restore_record_dir=restore_record_dir,
        require_m8_swatch_content_snapshot=True)
    source_backup = bound.backup_record
    if (source_backup["image_id"] != final["image_id"]
            or source_backup["database_snapshot"].get("aerich_versions") != ",".join(gatea.APPROVED_TARGET_M9_CHAIN)):
        raise M15UpgradeError("Gate A M15 source backup is not finalized G/M9")
    target_values = {**values, "GATEA_APP_IMAGE": f"pinkdoohub-gatea:{target_sha}"}
    if gatea.validate_app_image(target_values) != stage["image_id"]:
        raise M15UpgradeError("Gate A M15 image differs from stage")
    pinned = {**target_values, "GATEA_APP_IMAGE": stage["image_id"]}
    legacy._run_runtime_preflight(values=pinned, config_file=config_file,
                                  secret_dir=secret_dir, mode="loopback")
    read_state(pinned, config_file, secret_dir, 9)
    # 原配置只存入 root-only 回滚副本；所有可发布记录只保留摘要。
    candidate._require_root_file(config_file, 0o640, "Gate A config")
    original = config_file.read_bytes()
    updated, changed = candidate._rewrite_config(original, target_sha)
    if changed != ["GATEA_APP_IMAGE"]:
        raise M15UpgradeError("Gate A M15 activation may only change the image")
    pending, success, replay_path = _paths(record_dir, target_sha)
    activation_path = candidate._activation_record_path(record_dir, target_sha)
    if any(p.exists() or p.is_symlink() for p in (pending, success, replay_path, activation_path)):
        raise M15UpgradeError("Gate A M15 prior operation requires inspection; automatic retry is forbidden")
    plan = {"candidate_sha": target_sha, "source_candidate_sha": SOURCE_SHA,
            "source_version": 9, "target_version": 15, "backup_id": backup_id,
            "source_finalization_sha256": final_digest, "steps": list(range(10, 16)),
            "mode": "plan", "writes_performed": False}
    if not apply:
        return plan
    if (confirm_source_sha != SOURCE_SHA or confirm_target_sha != target_sha or confirm_backup_id != backup_id):
        raise M15UpgradeError("Gate A M15 apply confirmations must match source, target and backup")
    candidate._require_root_directory(config_history_dir, 0o700, "Gate A config history")
    history = config_history_dir / f"{target_sha}.m15-source.env"
    candidate._write_bytes_exclusive(history, original, 0o600)
    journal: dict[str, Any] = {"schema_version": 1, "record_type": "gatea-m15-upgrade-pending",
        "candidate_sha": target_sha, "source_candidate_sha": SOURCE_SHA,
        "backup_id": backup_id, "phase": "prepared", "started_at": legacy._iso_now(),
        "source_config_sha256": hashlib.sha256(original).hexdigest(),
        "target_config_sha256": hashlib.sha256(updated).hexdigest(),
        "steps": [], "secret_values_recorded": False}
    candidate._write_json_exclusive(pending, journal)
    def save(item: dict[str, Any]) -> None:
        journal["phase"] = item["phase"]
        journal["current_version"] = item["version"]
        if item["phase"] == "migration-verified":
            journal["steps"].append(item)
        candidate._atomic_replace_json(pending, journal, 0o644)
    try:
        gatea._run_compose(values=values, config_file=config_file, secret_dir=secret_dir,
                           mode="loopback", arguments=("stop", *WRITERS))
        _require_stopped(values, config_file, secret_dir)
        if (backup._source_snapshot(values, config_file, secret_dir, "loopback") != source_backup["database_snapshot"]
                or backup._source_image_manifest(values, config_file, secret_dir, "loopback") != source_backup["image_manifest"]):
            raise M15UpgradeError("Gate A stopped source differs from the verified backup")
        for key, reader in (("m7_content_snapshot", backup._source_m7_content_snapshot),
                            ("m8_swatch_content_snapshot", backup._source_m8_swatch_content_snapshot),
                            ("m9_table_content_snapshot", backup._source_m9_table_content_snapshot)):
            if reader(values, config_file, secret_dir, "loopback") != source_backup.get(key):
                raise M15UpgradeError("Gate A stopped source content differs from the verified backup")
        source_state = read_state(pinned, config_file, secret_dir, 9)
        journal["source_state"] = source_state
        steps = execute_steps(values=pinned, config_file=config_file, secret_dir=secret_dir,
                              source_state=source_state, checkpoint=save)
        target_state = steps[-1]["state"]
        images = backup._source_image_manifest(values, config_file, secret_dir, "loopback")
        if images != source_backup["image_manifest"]:
            raise M15UpgradeError("Gate A migration changed image volume content")
        _require_stopped(values, config_file, secret_dir)
        if gatea.validate_app_image(target_values) != stage["image_id"]:
            raise M15UpgradeError("Gate A target image tag changed during migration")
        if config_file.read_bytes() != original:
            raise M15UpgradeError("Gate A source config changed during migration")
        journal["phase"] = "activating"
        candidate._atomic_replace_json(pending, journal, 0o644)
        candidate._atomic_replace_bytes(config_file, updated, 0o640)
        activation = {"schema_version": 4, "record_type": "gatea-config-activation",
            "transition_kind": TRANSITION_KIND, "candidate_sha": target_sha,
            "source_candidate_sha": SOURCE_SHA, "image_id": stage["image_id"],
            "source_config_sha256": journal["source_config_sha256"],
            "target_config_sha256": journal["target_config_sha256"],
            "stage_record_sha256": _load(candidate._stage_record_path(record_dir, target_sha), "M15 stage")[1],
            "changed_keys": changed, "completed_at": legacy._iso_now(), "passed": True,
            "config_values_recorded": False, "secret_values_recorded": False}
        candidate._write_json_exclusive(activation_path, activation)
        record = {"schema_version": 3, "record_type": "existing-database-upgrade",
            "transition_kind": TRANSITION_KIND, "candidate_sha": target_sha, "image_id": stage["image_id"],
            "source_candidate_sha": SOURCE_SHA, "source_image_id": source_backup["image_id"],
            "source_version": 9, "target_version": 15, "source_state": source_state,
            "target_state": target_state, "steps": steps, "backup_id": backup_id,
            "backup_record_sha256": bound.backup_record_sha256, "restore_record_sha256": bound.restore_record_sha256,
            "source_finalization_sha256": final_digest,
            "stage_record_sha256": activation["stage_record_sha256"],
            "activation_record_sha256": _load(activation_path, "M15 activation")[1],
            "source_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
            "target_aerich_versions": list(gatea.APPROVED_TARGET_M15_CHAIN),
            "source_image_manifest": source_backup["image_manifest"], "target_image_manifest": images,
            "started_at": journal["started_at"], "completed_at": legacy._iso_now(),
            "passed": True, "secret_values_recorded": False}
        require_upgrade_record(record, record_dir=record_dir, candidate_sha=target_sha, image_id=stage["image_id"])
        candidate._write_json_exclusive(success, record)
        # 再次只读捕获，不重放任何 DDL；新业务仍被停止。
        if read_state(pinned, config_file, secret_dir, 15) != target_state:
            raise M15UpgradeError("Gate A M15 replay changed after upgrade commit")
        replay = {"schema_version": 3, "record_type": "existing-database-upgrade-plan-replay",
            "transition_kind": TRANSITION_KIND, "candidate_sha": target_sha, "image_id": stage["image_id"],
            "upgrade_record_sha256": _load(success, "M15 upgrade")[1], "target_state": target_state,
            "passed": True, "already_current": True, "read_only": True, "completed_at": legacy._iso_now()}
        candidate._write_json_exclusive(replay_path, replay)
        require_replay(record_dir=record_dir, candidate_sha=target_sha, image_id=stage["image_id"], upgrade_record=record)
        pending.unlink()
        candidate._fsync_directory(record_dir)
    except BaseException as error:
        # 不覆盖不可变 success；pending 明确阻止其他入口启动半完成的升级。
        if pending.exists():
            journal["phase"] = "failed"
            journal["error_type"] = type(error).__name__
            candidate._atomic_replace_json(pending, journal, 0o644)
        raise
    return {**plan, "mode": "apply", "writes_performed": True, "passed": True,
            "application_stopped": True, "record": str(success)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--apply", action="store_true")
    for name in ("source-sha", "target-sha", "backup-id"):
        parser.add_argument(f"--confirm-{name}")
    for name, default in (("config-file", gatea.DEFAULT_CONFIG_FILE), ("secret-dir", gatea.DEFAULT_SECRET_DIR),
        ("release-root", Path("/srv/pinkdoohub/gatea/releases")), ("record-dir", gatea.DEFAULT_RECORD_DIR),
        ("current-link", Path("/srv/pinkdoohub/gatea/current")),
        ("config-history-dir", candidate.DEFAULT_CONFIG_HISTORY_DIR),
        ("backup-root", backup.DEFAULT_BACKUP_ROOT), ("backup-record-dir", backup.DEFAULT_BACKUP_RECORD_DIR),
        ("restore-record-dir", backup.DEFAULT_RESTORE_RECORD_DIR)):
        parser.add_argument(f"--{name}", type=Path, default=default)
    args = parser.parse_args(argv)
    try:
        with gatea.operation_lock(), gatea.operation_termination_guard():
            result = upgrade(**vars(args))
    except (gatea.GateAError, snapshots.M15SnapshotError, subprocess.SubprocessError, OSError) as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
