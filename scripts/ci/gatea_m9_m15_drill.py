"""在 GitHub 临时 runner 或专属本地 Docker daemon 中演练 M9→M15。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.tasks import gatea_m15_snapshot as snapshots
from scripts.ci import gatea_m7_m8_drill as shared
from scripts.release import gatea_backup as backup
from scripts.release import gatea_candidate as candidate
from scripts.release import gatea_m15_upgrade as upgrade
from scripts.release import gatea_operations as gatea


SOURCE_SHA = upgrade.SOURCE_SHA
SENTINEL = "PINKDOOHUB_GATEA_M9_M15_DRILL"
SCOPES = {"ci": "github-hosted-disposable-linux", "local": "local-private-docker-daemon"}


def checked(*args: str, timeout: int = 300) -> str:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise shared.DrillError(f"M15 drill command failed: {Path(args[0]).name}")
    return result.stdout.strip()


def validate_host(profile: str, *, clean: bool) -> None:
    if profile not in SCOPES or os.environ.get(SENTINEL) != "disposable-only-v1":
        raise shared.DrillError("M15 drill requires its disposable sentinel and explicit profile")
    if os.geteuid() != 0 or platform.system() != "Linux":
        raise shared.DrillError("M15 drill requires a disposable root Linux environment")
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        raise shared.DrillError("M15 drill refuses Docker endpoint overrides")
    if checked("docker", "context", "show") != "default":
        raise shared.DrillError("M15 drill requires the local default Docker context")
    if checked("docker", "context", "inspect", "default", "--format", "{{.Endpoints.docker.Host}}") != "unix:///var/run/docker.sock":
        raise shared.DrillError("M15 drill requires a local Unix socket")
    info = json.loads(checked("docker", "info", "--format", "{{json .}}"))
    if info["OSType"] != "linux":
        raise shared.DrillError("M15 drill requires a Linux daemon")
    if profile == "ci":
        if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
            raise shared.DrillError("M15 CI refuses self-hosted or unknown runners")
    else:
        marker = Path("/run/pinkdoo-m15-private-daemon.json")
        candidate._require_root_file(marker, 0o400, "M15 private daemon identity")
        identity = json.loads(marker.read_text())
        if (identity != {"daemon_id": info["ID"], "name": info["Name"]}
                or not info["Name"].startswith("pinkdoo-m15-private-")
                or "com.pinkdoohub.disposable=m15" not in info.get("Labels", [])):
            raise shared.DrillError("M15 local drill is not attached to its private daemon")
    if clean and (any(shared.docker_inventory(shared.CommandRunner()).values())
                  or not shared._port_available(shared.LOOPBACK_PORT)):
        raise shared.DrillError("M15 drill refuses existing Gate A resources")


def paths() -> shared.DrillPaths:
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve()
    if workspace != ROOT or temporary == workspace or temporary.is_relative_to(workspace):
        raise shared.DrillError("M15 drill temporary root must be outside the checkout")
    run_id, attempt = os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"]
    if any(not value.isdigit() or int(value) < 1 for value in (run_id, attempt)):
        raise shared.DrillError("M15 drill run identity is invalid")
    root = temporary / f"pinkdoohub-gatea-m9-m15-{run_id}-{attempt}"
    return shared.DrillPaths(artifact_dir=ROOT / "artifacts/gatea-m9-m15-updater", work_root=root,
        source_tree=root / "source-m9", config_file=root / "config.env", secret_dir=root / "secrets",
        backup_root=root / "backups", backup_record_dir=root / "records/backups",
        restore_record_dir=root / "records/restores", release_record_dir=root / "records/releases",
        bootstrap_record_dir=root / "records/bootstrap", representative_record_dir=root / "records/representative-data",
        bootstrap_secret_file=root / "bootstrap-runtime/bootstrap_password.pending")


def ownership_path() -> Path:
    return ROOT / "artifacts/gatea-m9-m15-ownership.json"


def save_owner(state: shared.DrillState, profile: str) -> None:
    candidate._atomic_replace_json(ownership_path(), {
        "schema_version": 1, "record_type": "gatea-m9-m15-drill-ownership", "profile": profile,
        "target_sha": state.target_sha, "work_root": str(state.paths.work_root),
        "source_sha": SOURCE_SHA, "source_backup_id": state.source_backup_id,
        "target_backup_id": state.target_backup_id, "ownership_acquired": state.ownership_acquired,
    }, 0o600)


def cleanup(state: shared.DrillState, profile: str) -> dict[str, Any]:
    validate_host(profile, clean=False)
    owner = candidate._load_json(ownership_path(), "M15 drill ownership", mode=0o600)
    if (owner.get("work_root") != str(paths().work_root) or owner.get("target_sha") != state.target_sha
            or owner.get("source_sha") != SOURCE_SHA or owner.get("profile") != profile
            or owner.get("ownership_acquired") is not True
            or owner.get("source_backup_id") != state.source_backup_id
            or owner.get("target_backup_id") != state.target_backup_id):
        raise shared.DrillError("M15 cleanup ownership does not match this run")
    # 本演练直接使用冻结数据夹具，没有 bootstrap 服务或其用户名配置。
    errors = shared._remove_exact_resources(state, include_bootstrap=False)
    if state.paths.work_root.exists():
        if state.paths.work_root != paths().work_root or state.paths.work_root.is_symlink():
            raise shared.DrillError("M15 cleanup root is unsafe")
        shutil.rmtree(state.paths.work_root)
    inventory = shared.docker_inventory(state.command_runner)
    residual = {
        "containers": inventory["main_containers"] + inventory["restore_containers"],
        "volumes": inventory["main_volumes"] + inventory["restore_volumes"],
        "networks": inventory["main_networks"] + inventory["restore_networks"],
        "images": [i for i in (state.source_image, state.target_image) if shared._docker_image_ids(state.command_runner, i)],
        "temporary_paths": [str(state.paths.work_root)] if state.paths.work_root.exists() else [],
    }
    passed = not errors and not any(residual.values()) and shared._port_available(shared.LOOPBACK_PORT)
    result = {"schema_version": 1, "record_type": "gatea-m9-m15-cleanup", "passed": passed,
              "owned_resources_removed": passed, **residual}
    if not passed:
        failure_path = ROOT / "artifacts/gatea-m9-m15-cleanup-failure.json"
        if not failure_path.exists():
            candidate._write_json_exclusive(failure_path, {"errors": errors, "first_result": result})
    shared._write_json(state.paths.artifact_dir / "cleanup-report.json", result)
    return result


def compose(state: shared.DrillState, *arguments: str, operations: bool = False,
            input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    values = gatea.parse_env_file(state.paths.config_file)
    return gatea._run_compose(values=values, config_file=state.paths.config_file,
        secret_dir=state.paths.secret_dir, mode="loopback", profiles=("operations",) if operations else (),
        arguments=arguments, capture_output=True, input_text=input_text)


def start_runtime(state: shared.DrillState) -> None:
    compose(state, "up", "--detach", "--no-build", "--wait", "--wait-timeout", "180", "app", "table-sweeper", "nginx")
    values = gatea.parse_env_file(state.paths.config_file)
    rows = gatea._compose_ps(values=values, config_file=state.paths.config_file,
        secret_dir=state.paths.secret_dir, mode="loopback", services=upgrade.SERVICES)
    gatea._ensure_services_healthy(rows, *upgrade.SERVICES)
    gatea._validate_loopback_publishers(rows, shared.LOOPBACK_PORT)


def build_images(state: shared.DrillState) -> None:
    archive = state.paths.work_root / "source.tar"
    checked("git", "archive", "--format=tar", "--output", str(archive), SOURCE_SHA)
    state.paths.source_tree.mkdir()
    checked("tar", "-xf", str(archive), "-C", str(state.paths.source_tree))
    archive.unlink()
    for tag, sha, context in ((state.source_image, SOURCE_SHA, state.paths.source_tree),
                              (state.target_image, state.target_sha, ROOT)):
        checked("docker", "build", "--file", str(context / "deploy/runtime/Dockerfile"),
                "--tag", tag, "--label", f"org.opencontainers.image.revision={sha}", str(context), timeout=1200)
        shared._safe_image_metadata(tag, state.command_runner)


def seed_source(state: shared.DrillState) -> None:
    """仅在空的临时 M9 库上，加载冻结源码的现成已付款/已关闭会话夹具。"""
    # tests 不进入发布镜像；只把两个冻结的测试模块通过 stdin 放入一次性容器内存。
    fixture = state.paths.source_tree / "tests/release/test_gatea_m9_failed_acceptance_verify.py"
    services = state.paths.source_tree / "tests/table_sessions/test_table_session_service.py"
    modules = {"tests.table_sessions.test_table_session_service": services.read_text(),
               "tests.release.test_gatea_m9_failed_acceptance_verify": fixture.read_text()}
    code = '''import asyncio,json,sys,types
from tortoise import Tortoise
from app.db.database import TORTOISE_ORM
from app.core.config import settings
from app.models.user import User
modules = json.loads(sys.stdin.readline())
for name in ("tests", "tests.table_sessions", "tests.release"):
 m=types.ModuleType(name);m.__path__=[];sys.modules[name]=m
for name,code in modules.items():
 m=types.ModuleType(name);sys.modules[name]=m;exec(compile(code,name,"exec"),m.__dict__)
async def run():
 if settings.db_name != "pinkdoohub_gatea_drill": raise RuntimeError("disposable database required")
 await Tortoise.init(config=TORTOISE_ORM)
 try:
  if await User.all().count(): raise RuntimeError("empty source required")
  await sys.modules["tests.release.test_gatea_m9_failed_acceptance_verify"]._seed_paid_failure()
 finally: await Tortoise.close_connections()
asyncio.run(run())
print(json.dumps({"paid_fixture_created":True}))
'''
    result = compose(state, "run", "--rm", "--no-deps", "-T", "migrate", "python", "-B", "-c", code,
                     operations=True, input_text=json.dumps(modules, separators=(",", ":")) + "\n")
    if shared._parse_task_json(result.stdout) != {"paid_fixture_created": True}:
        raise shared.DrillError("M15 source paid fixture failed")
    # 221 色与色图由实际发布任务生成；不创建任何门店盘点。
    result = compose(state, "run", "--rm", "--no-deps", "-T", "app", "python", "-B", "-m",
        "app.tasks.gatea_mard_publish", "--apply", "--confirm-manifest-sha256", shared.MARD_MANIFEST_SHA256)
    if shared._parse_task_json(result.stdout).get("colors") != 221:
        raise shared.DrillError("M15 source MARD publication failed")


def capture_target_backup(state: shared.DrillState) -> dict[str, Any]:
    """使用实际备份原语捕获临时数据库；不伪造持久部署或 finalized 记录。"""
    p = state.paths
    values = gatea.parse_env_file(p.config_file)
    backup_id = state.target_backup_id
    if backup_id is None:
        raise shared.DrillError("M15 backup ID is missing")
    image_id = gatea.validate_app_image(values)
    started = shared._utc_now()
    compose(state, "stop", *upgrade.WRITERS)
    upgrade._require_stopped(values, p.config_file, p.secret_dir)
    database = backup._source_snapshot(values, p.config_file, p.secret_dir, "loopback")
    content = backup._source_m15_content_snapshot(values, p.config_file, p.secret_dir, "loopback")
    images = backup._source_image_manifest(values, p.config_file, p.secret_dir, "loopback")
    db_path, images_path = backup._backup_paths(p.backup_root, backup_id)
    for arguments, path in (
        (("exec", "--no-TTY", "mysql", "sh", "-ec", backup.MYSQL_DUMP_COMMAND), db_path),
        (("run", "--rm", "--no-deps", "--entrypoint", "tar", "image-init", "-C", "/data/images", "-cf", "-", "."), images_path),
    ):
        backup._stream_source_artifact(values=values, config_file=p.config_file,
            secret_dir=p.secret_dir, mode="loopback", arguments=arguments, path=path)
    start_runtime(state)
    payload = {"schema_version": 1, "backup_id": backup_id, "candidate_sha": state.target_sha,
        "image_id": image_id, "started_at": started, "completed_at": shared._utc_now(),
        "scope": SCOPES[state.environment["M15_DRILL_PROFILE"]],
        "consistency": "nginx-and-app-stopped", "database_snapshot": database,
        "m15_content_snapshot": content, "image_manifest": images,
        "artifacts": {name: {"path": str(path), "bytes": path.stat().st_size, "sha256": backup._sha256(path)}
                      for name, path in (("mysql", db_path), ("images", images_path))},
        "redis_recovery_policy": "start-empty-and-invalidate-refresh-sessions",
        "application_restarted": True, "table_sweeper_restarted": True, "passed": True}
    backup._validate_loaded_backup_record(payload=payload, backup_id=backup_id, backup_root=p.backup_root)
    candidate._write_json_exclusive(p.backup_record_dir / f"{backup_id}.json", payload)
    return payload


def execute(state: shared.DrillState, profile: str) -> None:
    p = state.paths
    build_images(state)
    gatea.infra_up(config_file=p.config_file, secret_dir=p.secret_dir, mode="loopback", wait_timeout=180)
    gatea.initial_migrate(config_file=p.config_file, secret_dir=p.secret_dir,
                          record_dir=p.release_record_dir, mode="loopback")
    seed_source(state)
    values = gatea.parse_env_file(p.config_file)
    target_values = {**values, "GATEA_APP_IMAGE": state.target_image}
    target_image = gatea.validate_app_image(target_values)
    pinned = {**target_values, "GATEA_APP_IMAGE": target_image}
    source = upgrade.read_state(pinned, p.config_file, p.secret_dir, 9)
    if source["m9_preserved"]["payments"]["rows"] < 1:
        raise shared.DrillError("M15 drill requires preserved paid business")
    shared._write_json(p.artifact_dir / "state-9.json", source)
    def checkpoint(item: dict[str, Any]) -> None:
        candidate._atomic_replace_json(p.work_root / "step-checkpoint.json", item, 0o600)
        if item["phase"] == "migration-verified":
            shared._write_json(p.artifact_dir / f"state-{item['version']}.json", item["state"])
    upgrade.execute_steps(values=pinned, config_file=p.config_file, secret_dir=p.secret_dir,
                           source_state=source, checkpoint=checkpoint)
    shared._replace_config(state, state.target_image)
    start_runtime(state)
    # 无需管理员凭据的真实 HTTP /ready 和数据库/图片恢复，业务功能另由 MySQL/API 测试覆盖。
    client = shared.representative.LoopbackClient(shared.LOOPBACK_PORT)
    client.json_request("m15-runtime-ready", "GET", "/api/v1/health/ready", expected_status=200)
    shared._write_json(p.artifact_dir / "runtime-verification.json", {
        "passed": True, "candidate_sha": state.target_sha, "target_version": 15,
        "loopback_only": True, "five_services_healthy": True, "ready": True})
    state.target_backup_id = shared._next_backup_id(state)
    save_owner(state, profile)
    payload = capture_target_backup(state)
    shared._write_json(p.artifact_dir / "target-backup.json", payload)
    backup.verify_restore(backup_id=state.target_backup_id, confirm_project=backup.restore_project(state.target_backup_id), config_file=p.config_file,
        secret_dir=p.secret_dir, mode="loopback", backup_root=p.backup_root,
        backup_record_dir=p.backup_record_dir, restore_record_dir=p.restore_record_dir,
        release_record_dir=p.release_record_dir, wait_timeout=180)
    restored = shared._read_json(p.restore_record_dir / f"{state.target_backup_id}.json")
    shared._write_json(p.artifact_dir / "target-restore.json", restored)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "cleanup"))
    parser.add_argument("--profile", choices=SCOPES, required=True)
    args = parser.parse_args(argv)
    state = None
    try:
        validate_host(args.profile, clean=args.command == "run")
        p = paths()
        if args.command == "cleanup":
            if not ownership_path().exists():
                print(json.dumps({"owned_resources": False})); return 0
            owner = candidate._load_json(ownership_path(), "M15 ownership", mode=0o600)
            target = owner["target_sha"]
        else:
            target = checked("git", "rev-parse", "HEAD")
            if (target != os.environ.get("GITHUB_SHA") or checked("git", "status", "--porcelain")
                    or candidate.SHA_PATTERN.fullmatch(target) is None):
                raise shared.DrillError("M15 drill requires a clean exact target checkout")
            checked("git", "merge-base", "--is-ancestor", SOURCE_SHA, target)
            pr_head = shared._reported_pr_head(os.environ) if args.profile == "ci" else os.environ.get("PR_HEAD_SHA")
            if not isinstance(pr_head, str) or candidate.SHA_PATTERN.fullmatch(pr_head) is None:
                raise shared.DrillError("M15 drill requires a valid PR head identity")
            for sha, chain in ((SOURCE_SHA, gatea.APPROVED_TARGET_M9_CHAIN), (target, gatea.APPROVED_TARGET_M15_CHAIN)):
                actual = checked("git", "ls-tree", "-r", "--name-only", sha, "--", "migrations/models").splitlines()
                if actual != sorted(f"migrations/models/{v}" for v in chain):
                    raise shared.DrillError("M15 drill source or target migration tree differs")
            if p.work_root.exists() or ownership_path().exists() or p.artifact_dir.exists():
                raise shared.DrillError("M15 drill workspace is already owned")
        state = shared.DrillState(paths=p, target_sha=target, source_image=f"pinkdoohub-gatea:{SOURCE_SHA}",
            target_image=f"pinkdoohub-gatea:{target}", environment={**os.environ, "M15_DRILL_PROFILE": args.profile},
            command_runner=shared.CommandRunner(), ownership_acquired=True)
        if args.command == "cleanup":
            state.source_backup_id, state.target_backup_id = owner["source_backup_id"], owner["target_backup_id"]
            result = cleanup(state, args.profile)
            print(json.dumps(result)); return 0 if result["passed"] else 1
        for tag in (state.source_image, state.target_image):
            if shared._docker_image_ids(state.command_runner, tag):
                raise shared.DrillError("M15 drill image tag already exists")
        p.artifact_dir.mkdir(parents=True, mode=0o755)
        save_owner(state, args.profile)
        shared.prepare_workspace(state)
        execute(state, args.profile)
        result = cleanup(state, args.profile)
        if not result["passed"]:
            raise shared.DrillError("M15 drill cleanup failed")
        files = {name: (p.artifact_dir / name).read_bytes() for name in candidate.M15_CI_FILES - {"summary.json"}}
        secrets = state.secrets.values() if state.secrets else ()
        if any(pattern.search(data) for data in files.values() for pattern in shared.SENSITIVE_TEXT_PATTERNS):
            raise shared.DrillError("M15 artifact contains sensitive patterns")
        if any(secret.encode() in data for secret in secrets if secret for data in files.values()):
            raise shared.DrillError("M15 artifact contains an exact generated secret")
        summary = {"schema_version": 1, "record_type": "gatea-m9-m15-drill", "passed": True,
            "source_sha": SOURCE_SHA, "target_sha": target, "source_version": 9, "target_version": 15,
            "reported_pr_head_sha": pr_head, "ci_run_id": os.environ["GITHUB_RUN_ID"],
            "ci_run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]), "scope": SCOPES[args.profile],
            "production_secrets_used": False, "persistent_gatea_authorized": False,
            "migration_steps": list(range(10, 16)), "cleanup_passed": True,
            "artifact_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        shared._write_json(p.artifact_dir / "summary.json", summary)
        print(json.dumps({"passed": True, "profile": args.profile, "target_sha": target})); return 0
    except BaseException as error:
        generated_secrets = state.secrets.values() if state is not None and state.secrets else ()
        print(json.dumps({"passed": False, "failure": shared._safe_failure_evidence(error, secret_values=generated_secrets)}), file=sys.stderr)
        if state is not None and ownership_path().exists():
            try: cleanup(state, args.profile)
            except BaseException as cleanup_error:
                print(json.dumps({"cleanup_passed": False, "error_type": type(cleanup_error).__name__}), file=sys.stderr)
        return 1
    finally:
        if state is not None and state.secrets is not None:
            state.secrets.clear()


def main(argv: list[str] | None = None) -> int:
    with gatea.operation_lock(), gatea.operation_termination_guard():
        return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
