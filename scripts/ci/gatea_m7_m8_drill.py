#!/usr/bin/env python3
"""在 GitHub-hosted disposable Linux runner 上演练完整 Gate A M7→M9。

本工具只接受 root、GitHub-hosted Linux、本地 Docker daemon 和精确 sentinel。
``run`` 从冻结 M7 source 构建临时环境，执行真实 Backup/Restore、升级、重放、
app-up 和 M9 数据后恢复，并在所有退出路径精确清理。``cleanup`` 供 workflow 的
``if: always()`` 步骤幂等复核；没有本工具写出的 ownership Record 时绝不删除资源。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.tasks.mard_catalog import build_swatch_png, load_manifest
from scripts.release import gatea_backup as backup
from scripts.release import gatea_bootstrap as bootstrap
from scripts.release import gatea_operations as gatea
from scripts.release import gatea_representative_data as representative
from scripts.release import gatea_upgrade as upgrade


SOURCE_SHA = "73dca350505d43775fb1ff1158ccf6aabc221998"
MARD_MANIFEST = REPOSITORY_ROOT / "app" / "tasks" / "manifests" / "mard_221.json"
MARD_MANIFEST_SHA256 = (
    "45e37342ff77907556974bc78c501a3931fda9100afae4506a709ab8a11ad238"
)
SENTINEL_ENV = "PINKDOOHUB_GATEA_M7_M9_DRILL"
SENTINEL_VALUE = "github-hosted-disposable-linux-v1"
LOOPBACK_PORT = 18080
MAIN_PROJECT = "pinkdoohub-gatea"
FIXED_VOLUMES = (
    "pinkdoohub-gatea-mysql-data",
    "pinkdoohub-gatea-redis-data",
    "pinkdoohub-gatea-product-images",
)
FIXED_NETWORKS = (
    "pinkdoohub-gatea-backend",
    "pinkdoohub-gatea-edge",
)
RESTORE_PROJECT_PREFIX = "pinkdoohub-gatea-restore-"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
RUN_COMPONENT_PATTERN = re.compile(r"^[0-9]+$")
IMAGE_PATTERN = re.compile(r"^pinkdoohub-gatea:[0-9a-f]{40}$")
BACKUP_ID_PATTERN = re.compile(r"^[0-9]{8}t[0-9]{6}z$")
ARTIFACT_SCAN_MARKER = "artifact-scan-passed.json"

ARTIFACT_ALLOWLIST = frozenset(
    {
        "bootstrap-record.json",
        ARTIFACT_SCAN_MARKER,
        "cleanup-report.json",
        "color-fixture.json",
        "drill-state.json",
        "images.json",
        "representative-data.json",
        "runtime-verification.json",
        "source-backup-record.json",
        "source-mard.json",
        "source-m7-verification.json",
        "source-restore-record.json",
        "summary.json",
        "target-backup-record.json",
        "target-restore-record.json",
        "upgrade-apply.json",
        "upgrade-evidence.json",
        "upgrade-plan-replay.json",
        "upgrade-plan.json",
        "upgrade-record.json",
    }
)
SENSITIVE_TEXT_PATTERNS = (
    re.compile(rb"Authorization\s*:\s*Bearer\s+", re.IGNORECASE),
    re.compile(rb'"(?:access_token|refresh_token|password|jwt_secret|db_password)"\s*:', re.IGNORECASE),
    re.compile(rb"redis://:[^@\s]+@", re.IGNORECASE),
    re.compile(rb"mysql(?:\+[^:]+)?://[^\s]+", re.IGNORECASE),
)

PIPELINE: tuple[tuple[str, str], ...] = (
    ("build-images", "build_images"),
    ("start-source", "start_source"),
    ("bootstrap-source", "bootstrap_source"),
    ("seed-representative", "seed_representative"),
    ("publish-source-mard", "publish_source_mard"),
    ("seed-color-kit", "seed_color_kit"),
    ("verify-source-m7", "verify_source_m7"),
    ("backup-restore-source", "backup_restore_source"),
    ("plan-target", "plan_target"),
    ("apply-target", "apply_target"),
    ("plan-replay", "plan_replay"),
    ("app-up", "app_up"),
    ("verify-m9-runtime", "verify_m9_runtime"),
    ("backup-restore-target", "backup_restore_target"),
)


class DrillError(RuntimeError):
    """不包含 Secret、Token、凭据或响应正文的演练错误。"""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner:
    """可在单元测试中替换的宿主命令边界。"""

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path = REPOSITORY_ROOT,
        environment: Mapping[str, str] | None = None,
        timeout: int = 120,
    ) -> CommandResult:
        result = subprocess.run(
            tuple(command),
            cwd=cwd,
            env=None if environment is None else dict(environment),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(result.returncode, result.stdout, result.stderr)


@dataclass(slots=True)
class SecretBundle:
    mysql_app_password: str = field(repr=False)
    mysql_root_password: str = field(repr=False)
    redis_password: str = field(repr=False)
    jwt_secret: str = field(repr=False)
    bootstrap_initial_password: str = field(repr=False)
    bootstrap_final_password: str = field(repr=False)

    def values(self) -> tuple[str, ...]:
        return (
            self.mysql_app_password,
            self.mysql_root_password,
            self.redis_password,
            self.jwt_secret,
            self.bootstrap_initial_password,
            self.bootstrap_final_password,
        )

    def clear(self) -> None:
        self.mysql_app_password = ""
        self.mysql_root_password = ""
        self.redis_password = ""
        self.jwt_secret = ""
        self.bootstrap_initial_password = ""
        self.bootstrap_final_password = ""


def _safe_failure_evidence(
    error: BaseException | None,
    *,
    secret_values: Sequence[str] = (),
) -> dict[str, Any] | None:
    """生成可上传的最小失败证据，不回显凭据或不受控异常正文。"""

    if error is None:
        return None

    def safe_text(value: object, *, limit: int = 4096) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        rendered = value
        for secret_value in secret_values:
            if secret_value:
                rendered = rendered.replace(secret_value, "[REDACTED]")
        rendered = rendered[-limit:]
        encoded = rendered.encode("utf-8", errors="replace")
        if any(pattern.search(encoded) for pattern in SENSITIVE_TEXT_PATTERNS):
            return None
        return rendered

    evidence: dict[str, Any] = {"error_type": type(error).__name__}
    if isinstance(error, subprocess.CalledProcessError):
        evidence["returncode"] = error.returncode
        raw_command = error.cmd
        command = (
            [str(part) for part in raw_command]
            if isinstance(raw_command, (list, tuple))
            else [str(raw_command)]
        )
        safe_command = [safe_text(part, limit=1024) for part in command]
        if all(part is not None for part in safe_command):
            evidence["command"] = safe_command
        elif command:
            evidence["command"] = [Path(command[0]).name]
            evidence["command_details_omitted"] = True
        stdout_tail = safe_text(error.stdout)
        stderr_tail = safe_text(error.stderr)
        if stdout_tail is not None:
            evidence["stdout_tail"] = stdout_tail
        if stderr_tail is not None:
            evidence["stderr_tail"] = stderr_tail
    elif isinstance(error, (DrillError, gatea.GateAError)):
        message = safe_text(str(error), limit=1024)
        if message is not None:
            evidence["message"] = message
    return evidence


@dataclass(slots=True)
class DrillPaths:
    artifact_dir: Path
    work_root: Path
    source_tree: Path
    config_file: Path
    secret_dir: Path
    backup_root: Path
    backup_record_dir: Path
    restore_record_dir: Path
    release_record_dir: Path
    bootstrap_record_dir: Path
    representative_record_dir: Path
    bootstrap_secret_file: Path


@dataclass(slots=True)
class DrillState:
    paths: DrillPaths
    target_sha: str
    source_image: str
    target_image: str
    environment: Mapping[str, str]
    command_runner: CommandRunner
    pr_head_sha: str | None = None
    secrets: SecretBundle | None = None
    ownership_acquired: bool = False
    source_backup_id: str | None = None
    target_backup_id: str | None = None
    color_fixture: dict[str, Any] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def state_path(self) -> Path:
        return self.paths.artifact_dir / "drill-state.json"

    def safe_state(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-state",
            "ownership_acquired": self.ownership_acquired,
            "work_root": str(self.paths.work_root),
            "config_file": str(self.paths.config_file),
            "secret_dir": str(self.paths.secret_dir),
            "source_sha": SOURCE_SHA,
            "target_sha": self.target_sha,
            "source_image": self.source_image,
            "target_image": self.target_image,
            "source_backup_id": self.source_backup_id,
            "target_backup_id": self.target_backup_id,
            "restore_projects": [
                backup.restore_project(value)
                for value in (self.source_backup_id, self.target_backup_id)
                if value is not None
            ],
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
        if os.geteuid() == 0:
            os.fchown(descriptor, 0, 0)
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DrillError("required JSON evidence is unavailable") from error
    if not isinstance(payload, dict):
        raise DrillError("required JSON evidence has an invalid shape")
    return payload


def _copy_json(source: Path, destination: Path) -> dict[str, Any]:
    payload = _read_json(source)
    _write_json(destination, payload)
    return payload


def _checked(
    runner: CommandRunner,
    command: Sequence[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    environment: Mapping[str, str] | None = None,
    timeout: int = 120,
) -> str:
    result = runner.run(command, cwd=cwd, environment=environment, timeout=timeout)
    if result.returncode != 0:
        raise DrillError(f"required host command failed: {command[0]}")
    return result.stdout.strip()


def _git_command(*arguments: str) -> tuple[str, ...]:
    return (
        "git",
        "-c",
        f"safe.directory={REPOSITORY_ROOT}",
        *arguments,
    )


def _git_output(runner: CommandRunner, *arguments: str) -> str:
    return _checked(runner, _git_command(*arguments))


def _git_raw_output(runner: CommandRunner, *arguments: str) -> str:
    result = runner.run(_git_command(*arguments))
    if result.returncode != 0:
        raise DrillError("required host command failed: git")
    return result.stdout


def _artifact_directory(
    path: Path,
    *,
    require_empty: bool,
    allow_unexpected_entries: bool = False,
) -> Path:
    untrusted = path.expanduser().absolute()
    if untrusted.exists() and untrusted.is_symlink():
        raise DrillError("artifact directory must not be a symlink")
    candidate = untrusted.resolve()
    candidate.mkdir(mode=0o755, parents=True, exist_ok=True)
    if not candidate.is_dir():
        raise DrillError("artifact path must be a directory")
    if stat.S_IMODE(candidate.stat().st_mode) & 0o022:
        raise DrillError("artifact directory must not be group/world writable")
    unexpected = sorted(
        item.name for item in candidate.iterdir() if item.name not in ARTIFACT_ALLOWLIST
    )
    if unexpected and not allow_unexpected_entries:
        raise DrillError("artifact directory contains a non-allowlisted entry")
    if require_empty and any(candidate.iterdir()):
        raise DrillError("run requires an empty artifact directory")
    return candidate


def paths_from_environment(
    artifact_dir: Path,
    environment: Mapping[str, str],
    *,
    require_empty_artifacts: bool,
    allow_unexpected_artifacts: bool = False,
) -> DrillPaths:
    run_id = environment.get("GITHUB_RUN_ID", "")
    attempt = environment.get("GITHUB_RUN_ATTEMPT", "")
    if (
        RUN_COMPONENT_PATTERN.fullmatch(run_id) is None
        or RUN_COMPONENT_PATTERN.fullmatch(attempt) is None
    ):
        raise DrillError("GitHub run identity is unavailable")
    runner_temp = Path(environment.get("RUNNER_TEMP", ""))
    if not runner_temp.is_absolute() or runner_temp == Path("/"):
        raise DrillError("RUNNER_TEMP must be an absolute disposable path")
    workspace = Path(environment.get("GITHUB_WORKSPACE", ""))
    if not workspace.is_absolute() or workspace == Path("/"):
        raise DrillError("GITHUB_WORKSPACE must be an absolute path")
    workspace = workspace.resolve()
    if runner_temp.resolve().is_relative_to(workspace):
        raise DrillError("RUNNER_TEMP must be outside GITHUB_WORKSPACE")
    work_root = runner_temp / f"pinkdoohub-gatea-m7-m9-{run_id}-{attempt}"
    if work_root.parent.resolve() != runner_temp.resolve():
        raise DrillError("drill workspace escaped RUNNER_TEMP")
    expected_artifacts = (workspace / "artifacts" / "gatea-m7-m9-updater").resolve()
    requested_artifacts = artifact_dir.expanduser().absolute().resolve()
    if requested_artifacts != expected_artifacts:
        raise DrillError("artifact directory must use the frozen workspace path")
    artifacts = _artifact_directory(
        artifact_dir,
        require_empty=require_empty_artifacts,
        allow_unexpected_entries=allow_unexpected_artifacts,
    )
    if artifacts == work_root or artifacts.is_relative_to(work_root):
        raise DrillError("artifact directory must survive workspace cleanup")
    return DrillPaths(
        artifact_dir=artifacts,
        work_root=work_root,
        source_tree=work_root / "source-m7",
        config_file=work_root / "config.env",
        secret_dir=work_root / "secrets",
        backup_root=work_root / "backups",
        backup_record_dir=work_root / "records" / "backups",
        restore_record_dir=work_root / "records" / "restores",
        release_record_dir=work_root / "records" / "releases",
        bootstrap_record_dir=work_root / "records" / "bootstrap",
        representative_record_dir=work_root / "records" / "representative-data",
        bootstrap_secret_file=work_root
        / "bootstrap-runtime"
        / "bootstrap_password.pending",
    )


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _docker_names(
    runner: CommandRunner,
    kind: str,
    *,
    project: str | None = None,
) -> list[str]:
    if kind == "containers":
        command: tuple[str, ...] = (
            "docker",
            "ps",
            "--all",
            "--format",
            '{{.ID}}|{{.Names}}|{{.Label "com.docker.compose.project"}}',
        )
    elif kind == "volumes":
        command = ("docker", "volume", "ls", "--format", "{{.Name}}")
    elif kind == "networks":
        command = ("docker", "network", "ls", "--format", "{{.Name}}")
    else:
        raise DrillError("unsupported Docker resource kind")
    output = _checked(runner, command)
    lines = output.splitlines() if output else []
    if kind != "containers":
        return lines
    if project is None:
        return lines
    return [line for line in lines if line.rpartition("|")[2] == project]


def _docker_image_ids(runner: CommandRunner, image: str) -> list[str]:
    if IMAGE_PATTERN.fullmatch(image) is None:
        raise DrillError("invalid drill image tag")
    output = _checked(
        runner,
        (
            "docker",
            "image",
            "ls",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"reference={image}",
        ),
    )
    image_ids = output.splitlines() if output else []
    if any(re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None for value in image_ids):
        raise DrillError("Docker returned an invalid drill image ID")
    return image_ids


def docker_inventory(runner: CommandRunner) -> dict[str, list[str]]:
    container_lines = _docker_names(runner, "containers")
    volumes = _docker_names(runner, "volumes")
    networks = _docker_names(runner, "networks")
    return {
        "main_containers": [
            line for line in container_lines if line.rpartition("|")[2] == MAIN_PROJECT
        ],
        "restore_containers": [
            line
            for line in container_lines
            if line.rpartition("|")[2].startswith(RESTORE_PROJECT_PREFIX)
        ],
        "main_volumes": [name for name in volumes if name in FIXED_VOLUMES],
        "restore_volumes": [
            name for name in volumes if name.startswith(RESTORE_PROJECT_PREFIX)
        ],
        "main_networks": [name for name in networks if name in FIXED_NETWORKS],
        "restore_networks": [
            name for name in networks if name.startswith(RESTORE_PROJECT_PREFIX)
        ],
    }


def validate_host_environment(
    environment: Mapping[str, str],
    runner: CommandRunner,
    *,
    require_clean_start: bool,
    geteuid: Callable[[], int] = os.geteuid,
    system: Callable[[], str] = platform.system,
) -> dict[str, Any]:
    """在任何资源写入或删除前锁定 disposable runner 边界。"""

    if environment.get("GITHUB_ACTIONS") != "true":
        raise DrillError("drill requires GitHub Actions")
    if environment.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise DrillError("drill refuses a self-hosted or unknown runner")
    if environment.get(SENTINEL_ENV) != SENTINEL_VALUE:
        raise DrillError("drill sentinel does not match")
    if geteuid() != 0:
        raise DrillError("drill must run as root")
    if system() != "Linux":
        raise DrillError("drill requires Linux")
    if environment.get("DOCKER_HOST") or environment.get("DOCKER_CONTEXT"):
        raise DrillError("drill refuses an overridden Docker daemon/context")
    if shutil.which("docker") is None:
        raise DrillError("docker CLI is unavailable")

    context = _checked(runner, ("docker", "context", "show"))
    if context != "default":
        raise DrillError("drill requires the default Docker context")
    daemon_host = _checked(
        runner,
        (
            "docker",
            "context",
            "inspect",
            "default",
            "--format",
            "{{.Endpoints.docker.Host}}",
        ),
    )
    if daemon_host != "unix:///var/run/docker.sock":
        raise DrillError("drill requires the local Docker Unix socket")
    daemon_os = _checked(runner, ("docker", "info", "--format", "{{.OSType}}"))
    if daemon_os != "linux":
        raise DrillError("drill requires a Linux Docker daemon")
    compose_version = _checked(runner, ("docker", "compose", "version", "--short"))
    docker_version = _checked(
        runner,
        ("docker", "version", "--format", "{{.Client.Version}}/{{.Server.Version}}"),
    )
    inventory = docker_inventory(runner)
    if require_clean_start:
        if any(inventory.values()):
            raise DrillError("fixed Gate A Docker resources already exist")
        if not _port_available(LOOPBACK_PORT):
            raise DrillError("Gate A loopback port is already in use")
    return {
        "schema_version": 1,
        "checked_at": _utc_now(),
        "github_hosted": True,
        "root": True,
        "host_os": system(),
        "host_architecture": platform.machine(),
        "docker_context": context,
        "docker_daemon_host": daemon_host,
        "docker_daemon_os": daemon_os,
        "docker_version": docker_version,
        "compose_version": compose_version,
        "loopback_port_available": _port_available(LOOPBACK_PORT),
        "resources": inventory,
        "clean_start": require_clean_start,
    }


def _reported_pr_head(environment: Mapping[str, str]) -> str | None:
    event_path = environment.get("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        value = event["pull_request"]["head"]["sha"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, str) and SHA_PATTERN.fullmatch(value) else None


def validate_git_target(
    environment: Mapping[str, str],
    runner: CommandRunner,
) -> tuple[str, str | None, dict[str, Any]]:
    target_sha = _git_output(runner, "rev-parse", "HEAD")
    github_sha = environment.get("GITHUB_SHA", "")
    if (
        SHA_PATTERN.fullmatch(target_sha) is None
        or SHA_PATTERN.fullmatch(github_sha) is None
        or github_sha != target_sha
    ):
        raise DrillError("checkout HEAD must exactly match GITHUB_SHA")
    status = _git_output(
        runner,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if status:
        raise DrillError("target checkout must be clean")
    ancestor = runner.run(_git_command("merge-base", "--is-ancestor", SOURCE_SHA, target_sha))
    if ancestor.returncode != 0:
        raise DrillError("frozen M7 source is not an ancestor of target HEAD")

    source_migrations = _git_output(
        runner,
        "ls-tree",
        "-r",
        "--name-only",
        SOURCE_SHA,
        "--",
        "migrations/models",
    ).splitlines()
    target_migrations = _git_output(
        runner,
        "ls-tree",
        "-r",
        "--name-only",
        target_sha,
        "--",
        "migrations/models",
    ).splitlines()
    expected_source = [f"migrations/models/{name}" for name in gatea.APPROVED_SOURCE_M7_CHAIN]
    expected_target = [f"migrations/models/{name}" for name in gatea.APPROVED_TARGET_M9_CHAIN]
    if source_migrations != expected_source:
        raise DrillError("frozen source is not the exact M0-M7 migration tree")
    if target_migrations != expected_target:
        raise DrillError("target HEAD is not the exact M0-M9 migration tree")

    manifest_path = "app/tasks/manifests/mard_221.json"
    source_manifest = _git_raw_output(
        runner, "show", f"{SOURCE_SHA}:{manifest_path}"
    ).encode()
    target_manifest = _git_raw_output(
        runner, "show", f"{target_sha}:{manifest_path}"
    ).encode()
    source_manifest_sha = _sha256_bytes(source_manifest)
    target_manifest_sha = _sha256_bytes(target_manifest)
    if (
        source_manifest_sha != MARD_MANIFEST_SHA256
        or target_manifest_sha != MARD_MANIFEST_SHA256
        or source_manifest != target_manifest
        or _sha256_file(MARD_MANIFEST) != MARD_MANIFEST_SHA256
    ):
        raise DrillError("source and target MARD manifests do not match the freeze")

    pr_head = _reported_pr_head(environment)
    return target_sha, pr_head, {
        "target_sha": target_sha,
        "github_sha": github_sha,
        "reported_pr_head_sha": pr_head,
        "source_sha": SOURCE_SHA,
        "source_is_ancestor": True,
        "source_migrations": source_migrations,
        "target_migrations": target_migrations,
        "manifest_sha256": MARD_MANIFEST_SHA256,
        "checkout_clean": True,
    }


def _private_directory(path: Path, mode: int) -> None:
    path.mkdir(mode=mode, parents=True, exist_ok=False)
    os.chown(path, 0, 0)
    os.chmod(path, mode)


def _public_root_directory(path: Path) -> None:
    path.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chown(path, 0, 0)
    os.chmod(path, 0o755)


def _write_root_file(path: Path, value: str, *, mode: int, gid: int = 0) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, mode)
        os.fchown(descriptor, 0, gid)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            stream.write(value)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _config_text(state: DrillState, image: str) -> str:
    values = {
        "GATEA_APP_IMAGE": image,
        "GATEA_CONFIG_FILE": str(state.paths.config_file),
        "GATEA_SECRET_DIR": str(state.paths.secret_dir),
        "GATEA_LOOPBACK_PORT": str(LOOPBACK_PORT),
        "GATEA_API_HOST": "gatea-drill.invalid",
        "GATEA_BACKUP_ROOT": str(state.paths.backup_root),
        "APP_NAME": "pinkdooHub",
        "APP_VERSION": "0.6.0",
        "APP_ENV": "production",
        "APP_DEBUG": "false",
        "DB_ENGINE": "mysql",
        "DB_HOST": "mysql",
        "DB_PORT": "3306",
        "DB_NAME": "pinkdoohub_gatea_drill",
        "DB_USER": "pinkdoo_app",
        "PRODUCT_IMAGE_UPLOAD_DIR": "/data/images",
        "PRODUCT_IMAGE_BASE_URL": "https://gatea-drill.invalid/uploads/products",
        "PASSWORD_REGISTRATION_ENABLED": "true",
        "WECHAT_LOGIN_ENABLED": "false",
        "WALLET_ADMIN_WRITE_ENABLED": "true",
        "WALLET_ORDER_PAYMENT_ENABLED": "true",
        "WALLET_REFUND_ENABLED": "true",
        "WALLET_TOPUP_ENABLED": "false",
        "PAYMENT_PROVIDER": "disabled",
        "TABLE_SESSION_CLAIMS_ENABLED": "true",
        "JWT_ALGORITHM": "HS256",
        "JWT_ACCESS_TOKEN_EXPIRE": "7200",
        "JWT_REFRESH_TOKEN_EXPIRE": "604800",
    }
    return "\n".join(f"{key}={value}" for key, value in values.items())


def _replace_config(state: DrillState, image: str) -> None:
    temporary = state.paths.config_file.with_name(".config.env.pending")
    temporary.unlink(missing_ok=True)
    _write_root_file(temporary, _config_text(state, image), mode=0o640)
    os.replace(temporary, state.paths.config_file)


def prepare_workspace(state: DrillState) -> None:
    paths = state.paths
    if paths.work_root.exists():
        raise DrillError("drill workspace already exists")
    _private_directory(paths.work_root, 0o700)
    _private_directory(paths.secret_dir, 0o700)
    _public_root_directory(paths.backup_root)
    _public_root_directory(paths.backup_root / "mysql")
    _public_root_directory(paths.backup_root / "images")
    for directory in (
        paths.backup_record_dir,
        paths.restore_record_dir,
        paths.release_record_dir,
        paths.bootstrap_record_dir,
        paths.representative_record_dir,
    ):
        _public_root_directory(directory)
    _private_directory(paths.bootstrap_secret_file.parent, 0o700)

    secret_values = SecretBundle(
        mysql_app_password=secrets.token_urlsafe(48),
        mysql_root_password=secrets.token_urlsafe(48),
        redis_password=secrets.token_urlsafe(48),
        jwt_secret=secrets.token_urlsafe(64),
        bootstrap_initial_password=f"Drill-I1!{secrets.token_hex(20)}",
        bootstrap_final_password=f"Drill-F2!{secrets.token_hex(20)}",
    )
    state.secrets = secret_values
    metadata = gatea.EXPECTED_SECRET_METADATA
    for name, value in (
        ("mysql_app_password", secret_values.mysql_app_password),
        ("mysql_root_password", secret_values.mysql_root_password),
        ("redis_password", secret_values.redis_password),
        ("jwt_secret", secret_values.jwt_secret),
    ):
        mode, gid = metadata[name]
        _write_root_file(paths.secret_dir / name, value, mode=mode, gid=gid)
    _write_root_file(
        paths.config_file,
        _config_text(state, state.source_image),
        mode=0o640,
    )
    gatea._validated_inputs(
        config_file=paths.config_file,
        secret_dir=paths.secret_dir,
        mode="loopback",
        require_available_port=True,
    )


def _safe_image_metadata(image: str, runner: CommandRunner) -> dict[str, Any]:
    raw = _checked(
        runner,
        ("docker", "image", "inspect", image, "--format", "{{json .}}"),
    )
    try:
        payload = json.loads(raw)
        config = payload["Config"]
        labels = config.get("Labels") or {}
        result = {
            "tag": image,
            "id": payload["Id"],
            "architecture": payload["Architecture"],
            "os": payload["Os"],
            "user": config["User"],
            "entrypoint": config["Entrypoint"],
            "cmd": config["Cmd"],
            "revision": labels["org.opencontainers.image.revision"],
        }
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise DrillError("app image metadata is invalid") from error
    expected_sha = image.rpartition(":")[2]
    if (
        result["revision"] != expected_sha
        or result["user"] != gatea.EXPECTED_APP_USER
        or result["entrypoint"] != gatea.EXPECTED_APP_ENTRYPOINT
        or result["cmd"] != gatea.EXPECTED_APP_COMMAND
        or not str(result["id"]).startswith("sha256:")
        or result["os"] != "linux"
    ):
        raise DrillError("app image does not satisfy the Gate A identity contract")
    return result


def _json_data(document: Mapping[str, Any], step: str) -> dict[str, Any]:
    data = document.get("data")
    if document.get("code") != 0 or not isinstance(data, dict):
        raise DrillError(f"loopback step returned an invalid envelope: {step}")
    return data


def _header(headers: Mapping[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""


def _header_contains_token(
    headers: Mapping[str, str],
    name: str,
    expected_token: str,
) -> bool:
    return expected_token.lower() in {
        token.strip().lower()
        for token in _header(headers, name).split(",")
        if token.strip()
    }


def _parse_task_json(output: str) -> dict[str, Any]:
    lines = [line for line in output.splitlines() if line.strip()]
    try:
        payload = json.loads(lines[-1])
    except (IndexError, TypeError, json.JSONDecodeError) as error:
        raise DrillError("container task returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise DrillError("container task returned an invalid result")
    return payload


def _next_backup_id(state: DrillState) -> str:
    used = {value for value in (state.source_backup_id, state.target_backup_id) if value}
    for _ in range(20):
        value = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz").lower()
        if value not in used:
            return value
        time.sleep(0.1)
    raise DrillError("could not allocate a distinct backup ID")


def _assert_result_fields(
    result: Mapping[str, Any],
    expected: Mapping[str, Any],
    label: str,
) -> None:
    if any(result.get(key) != value for key, value in expected.items()):
        raise DrillError(f"{label} result does not match the drill contract")


class GateAM7M9Drill:
    """完整演练阶段编排；每个阶段只将脱敏摘要写入 allowlist。"""

    def __init__(self, state: DrillState) -> None:
        self.state = state

    def _artifact(self, name: str, payload: Mapping[str, Any]) -> None:
        if name not in ARTIFACT_ALLOWLIST:
            raise DrillError("attempted to write a non-allowlisted artifact")
        _write_json(self.state.paths.artifact_dir / name, payload)

    def _persist_state(self) -> None:
        self._artifact("drill-state.json", self.state.safe_state())

    def _stage(self, name: str, method: Callable[[], Mapping[str, Any]]) -> None:
        started_at = _utc_now()
        started = time.monotonic()
        result = method()
        self.state.stages.append(
            {
                "name": name,
                "started_at": started_at,
                "completed_at": _utc_now(),
                "duration_seconds": round(time.monotonic() - started, 3),
                "passed": True,
                "result": dict(result),
            }
        )

    def build_images(self) -> Mapping[str, Any]:
        state = self.state
        source_tar = state.paths.work_root / "source-m7.tar"
        state.paths.source_tree.mkdir(mode=0o755)
        os.chown(state.paths.source_tree, 0, 0)
        _checked(
            state.command_runner,
            _git_command(
                "archive",
                "--format=tar",
                "--output",
                str(source_tar),
                SOURCE_SHA,
            ),
            timeout=300,
        )
        _checked(
            state.command_runner,
            (
                "tar",
                "--extract",
                "--file",
                str(source_tar),
                "--directory",
                str(state.paths.source_tree),
            ),
            timeout=300,
        )
        source_tar.unlink()

        for image in (state.source_image, state.target_image):
            if _docker_image_ids(state.command_runner, image):
                raise DrillError("drill app image tag already exists")
        builds = (
            (state.source_image, SOURCE_SHA, state.paths.source_tree),
            (state.target_image, state.target_sha, REPOSITORY_ROOT),
        )
        for image, revision, context in builds:
            _checked(
                state.command_runner,
                (
                    "docker",
                    "build",
                    "--file",
                    str(context / "deploy" / "runtime" / "Dockerfile"),
                    "--tag",
                    image,
                    "--label",
                    f"org.opencontainers.image.revision={revision}",
                    str(context),
                ),
                timeout=1200,
            )
        source_metadata = _safe_image_metadata(state.source_image, state.command_runner)
        target_metadata = _safe_image_metadata(state.target_image, state.command_runner)
        source_values = gatea.parse_env_file(state.paths.config_file)
        if gatea.validate_app_image(source_values) != source_metadata["id"]:
            raise DrillError("source image identity changed during validation")
        payload = {"source": source_metadata, "target": target_metadata}
        self._artifact("images.json", payload)
        return {
            "source_image_id": source_metadata["id"],
            "target_image_id": target_metadata["id"],
        }

    def start_source(self) -> Mapping[str, Any]:
        paths = self.state.paths
        gatea.preflight(
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
        )
        gatea.infra_up(
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
            wait_timeout=300,
        )
        gatea.initial_migrate(
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            record_dir=paths.release_record_dir,
            mode="loopback",
        )
        # The frozen M7 image predates the M9 sweeper module. Start only the
        # services available at the source point; the target app-up path below
        # must start and verify the sweeper as part of the M9 contract.
        values = gatea._validated_inputs(
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
            require_available_port=True,
        )
        gatea._run_compose(
            values=values,
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
            arguments=(
                "up",
                "--detach",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "300",
                "app",
                "nginx",
            ),
        )
        rows = gatea._compose_ps(
            values=values,
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
            services=("app", "nginx"),
        )
        gatea._ensure_services_healthy(rows, "app", "nginx")
        gatea._validate_loopback_publishers(rows, LOOPBACK_PORT)
        values = gatea._validated_inputs(
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
            require_available_port=False,
        )
        snapshot = gatea.read_database_snapshot(
            values=values,
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
        )
        if snapshot.get("aerich_versions") != list(gatea.APPROVED_SOURCE_M7_CHAIN):
            raise DrillError("source initial migration did not produce exact M0-M7")
        return {"aerich_versions": snapshot["aerich_versions"]}

    def bootstrap_source(self) -> Mapping[str, Any]:
        state = self.state
        if state.secrets is None:
            raise DrillError("drill Secret bundle is unavailable")
        bootstrap.execute_bootstrap(
            username="gatea_drill_admin",
            nickname="Gate A Drill Admin",
            phone="13900009881",
            confirm_username="gatea_drill_admin",
            initial_password=state.secrets.bootstrap_initial_password,
            final_password=state.secrets.bootstrap_final_password,
            config_file=state.paths.config_file,
            secret_dir=state.paths.secret_dir,
            release_record_dir=state.paths.release_record_dir,
            bootstrap_record_dir=state.paths.bootstrap_record_dir,
            secret_file=state.paths.bootstrap_secret_file,
        )
        payload = _copy_json(
            state.paths.bootstrap_record_dir / bootstrap.BOOTSTRAP_RECORD_NAME,
            state.paths.artifact_dir / "bootstrap-record.json",
        )
        return {"passed": payload.get("passed", True), "recorded": True}

    def seed_representative(self) -> Mapping[str, Any]:
        state = self.state
        if state.secrets is None:
            raise DrillError("drill Secret bundle is unavailable")
        context = representative.prepare(
            username="gatea_drill_admin",
            confirm_username="gatea_drill_admin",
            config_file=state.paths.config_file,
            secret_dir=state.paths.secret_dir,
            release_record_dir=state.paths.release_record_dir,
            bootstrap_record=state.paths.bootstrap_record_dir
            / bootstrap.BOOTSTRAP_RECORD_NAME,
            record_dir=state.paths.representative_record_dir,
        )
        payload = representative.execute(
            context,
            username="gatea_drill_admin",
            password=state.secrets.bootstrap_final_password,
        )
        self._artifact("representative-data.json", payload)
        return {
            "products": len(payload.get("product_ids", [])),
            "images": payload.get("image_file_count"),
            "requests": payload.get("request_count"),
        }

    def _mard_task(self, *arguments: str) -> dict[str, Any]:
        state = self.state
        values = gatea._validated_inputs(
            config_file=state.paths.config_file,
            secret_dir=state.paths.secret_dir,
            mode="loopback",
            require_available_port=False,
        )
        result = gatea._run_compose(
            values=values,
            config_file=state.paths.config_file,
            secret_dir=state.paths.secret_dir,
            mode="loopback",
            arguments=(
                "run",
                "--rm",
                "--no-deps",
                "app",
                "python",
                "-m",
                "app.tasks.gatea_mard_publish",
                *arguments,
            ),
            capture_output=True,
        )
        return _parse_task_json(result.stdout)

    def publish_source_mard(self) -> Mapping[str, Any]:
        preview = self._mard_task()
        _assert_result_fields(
            preview,
            {
                "mode": "preview",
                "colors": 221,
                "manifest_sha256": MARD_MANIFEST_SHA256,
            },
            "source MARD preview",
        )
        applied = self._mard_task(
            "--apply",
            "--confirm-manifest-sha256",
            MARD_MANIFEST_SHA256,
        )
        _assert_result_fields(
            applied,
            {
                "mode": "apply",
                "colors": 221,
                "manifest_sha256": MARD_MANIFEST_SHA256,
            },
            "source MARD apply",
        )
        replay = self._mard_task()
        _assert_result_fields(
            replay,
            {
                "mode": "preview",
                "colors": 221,
                "manifest_sha256": MARD_MANIFEST_SHA256,
                "already_current": True,
                "database_changes": 0,
                "images_to_create": 0,
                "images_reused": 221,
            },
            "source MARD replay",
        )
        payload = {"preview": preview, "apply": applied, "replay": replay}
        self._artifact("source-mard.json", payload)
        return {
            "colors": 221,
            "created_images": applied.get("created_images"),
            "replay_noop": True,
        }

    def seed_color_kit(self) -> Mapping[str, Any]:
        state = self.state
        if state.secrets is None:
            raise DrillError("drill Secret bundle is unavailable")
        client = representative.LoopbackClient(LOOPBACK_PORT)
        admin: dict[str, Any] | None = None
        logout_error: BaseException | None = None
        operation_error: BaseException | None = None
        result: dict[str, Any] = {}
        try:
            admin = representative._login(
                client,
                step="drill-color-login",
                username="gatea_drill_admin",
                password=state.secrets.bootstrap_final_password,
                expected_role="super_admin",
            )
            token = str(admin["access_token"])
            created = _json_data(
                client.json_request(
                    "drill-create-color-kit",
                    "POST",
                    "/api/v1/admin/products/kit",
                    token=token,
                    payload={
                        "name": "[DRILL-M7] Three-color online Kit",
                        "description": "Disposable M7 to M9 updater fixture",
                        "price": "3.00",
                        "kit_kind": "color_selectable",
                    },
                    expected_status=201,
                ),
                "create-color-kit",
            )
            product_id = int(created["id"])
            cover = representative._upload_image(
                client,
                step="drill-upload-color-cover",
                path=f"/api/v1/admin/products/{product_id}/images",
                token=token,
                fields={"is_cover": "true", "sort": "0"},
            )
            representative._verify_image_read(
                client,
                step="drill-read-color-cover",
                image=cover,
            )
            detail = _json_data(
                client.json_request(
                    "drill-read-color-draft",
                    "GET",
                    f"/api/v1/admin/products/kit/{product_id}",
                    token=token,
                ),
                "read-color-draft",
            )
            colors = detail.get("colors")
            if not isinstance(colors, list) or len(colors) != 221:
                raise DrillError("new color Kit does not contain 221 slots")
            selected = [
                item
                for item in colors
                if isinstance(item, dict)
                and item.get("is_active") is True
                and item.get("is_configured") is True
            ][:3]
            if len(selected) != 3:
                raise DrillError("M7 catalog has fewer than three sale-ready colors")
            color_ids: list[int] = []
            slots: list[int] = []
            swatch_paths: list[str] = []
            for index, color in enumerate(selected, start=1):
                color_id = int(color["id"])
                color_ids.append(color_id)
                slots.append(int(color["slot_no"]))
                swatch_url = str(color["swatch_image_url"])
                parsed = urlparse(swatch_url)
                if parsed.scheme != "https" or not parsed.path.startswith(
                    "/uploads/products/"
                ):
                    raise DrillError("M7 swatch URL is invalid")
                swatch_paths.append(parsed.path)
                client.json_request(
                    f"drill-enable-color-{index}",
                    "PATCH",
                    f"/api/v1/admin/product-kit-colors/{color_id}",
                    token=token,
                    payload={"is_enabled": True},
                )
                adjusted = _json_data(
                    client.json_request(
                        f"drill-stock-color-{index}",
                        "POST",
                        f"/api/v1/admin/products/kit/{product_id}/colors/"
                        f"{color_id}/inventory-adjustments",
                        token=token,
                        payload={
                            "change": 10,
                            "reason": "Disposable M7 to M9 drill opening stock",
                        },
                        headers={
                            "Idempotency-Key": f"gatea-m7-m9-drill-color-{index}-v1"
                        },
                        expected_status=201,
                    ),
                    f"stock-color-{index}",
                )
                if adjusted.get("stock_units") != 10:
                    raise DrillError("color opening stock did not converge")
            client.json_request(
                "drill-online-color-kit",
                "PATCH",
                f"/api/v1/admin/products/{product_id}/online",
                token=token,
            )
            public = _json_data(
                client.json_request(
                    "drill-read-public-color-kit-m7",
                    "GET",
                    f"/api/v1/products/kit/{product_id}",
                ),
                "read-public-color-kit-m7",
            )
            public_colors = public.get("colors")
            if (
                not isinstance(public_colors, list)
                or len(public_colors) != 3
                or any(not isinstance(item, dict) for item in public_colors)
                or {int(item["slot_no"]) for item in public_colors} != set(slots)
            ):
                raise DrillError("M7 public color Kit does not expose three colors")
            result = {
                "schema_version": 1,
                "product_id": product_id,
                "product_kit_color_ids": color_ids,
                "slot_numbers": slots,
                "swatch_paths": swatch_paths,
                "enabled_colors": 3,
                "opening_stock_units_each": 10,
                "online": True,
                "request_count": len(client.results),
            }
        except BaseException as error:
            operation_error = error
        finally:
            if admin is not None:
                try:
                    representative._logout_and_verify(
                        client,
                        step_prefix="drill-color-admin",
                        access_token=str(admin["access_token"]),
                        refresh_token=str(admin["refresh_token"]),
                    )
                except BaseException as error:
                    logout_error = error
        if logout_error is not None:
            raise DrillError("color fixture session cleanup failed") from logout_error
        if operation_error is not None:
            if isinstance(operation_error, DrillError):
                raise operation_error
            raise DrillError("color fixture failed safely") from operation_error
        state.color_fixture = result
        self._artifact("color-fixture.json", result)
        return {
            "product_id": result["product_id"],
            "enabled_colors": 3,
            "online": True,
        }

    def verify_source_m7(self) -> Mapping[str, Any]:
        state = self.state
        paths = state.paths
        values = gatea._validated_inputs(
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
            require_available_port=False,
        )
        snapshot = gatea.read_database_snapshot(
            values=values,
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
        )
        if snapshot.get("aerich_versions") != list(gatea.APPROVED_SOURCE_M7_CHAIN):
            raise DrillError("prepared source is not exact M0-M7")
        image_manifest = backup._source_image_manifest(
            values,
            paths.config_file,
            paths.secret_dir,
            "loopback",
        )
        if len(image_manifest) != 225:
            raise DrillError("prepared M7 source must contain exactly 225 images")
        source_preflight = upgrade._run_m7_source_preflight(
            values=values,
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
            stopped_image_manifest=image_manifest,
            manifest_sha256=MARD_MANIFEST_SHA256,
        )
        payload = {
            "database_snapshot": snapshot,
            "mard_preflight": source_preflight,
            "image_files": len(image_manifest),
            "color_fixture": {
                "product_id": state.color_fixture.get("product_id"),
                "enabled_colors": state.color_fixture.get("enabled_colors"),
                "online": state.color_fixture.get("online"),
            },
        }
        self._artifact("source-m7-verification.json", payload)
        return {
            "aerich_versions": snapshot["aerich_versions"],
            "mard_colors": source_preflight["catalog_rows"],
            "images": len(image_manifest),
        }

    def _backup_and_restore(self, backup_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        paths = self.state.paths
        backup.create_backup(
            backup_id=backup_id,
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
            backup_root=paths.backup_root,
            backup_record_dir=paths.backup_record_dir,
            release_record_dir=paths.release_record_dir,
            wait_timeout=300,
        )
        backup.verify_restore(
            backup_id=backup_id,
            confirm_project=backup.restore_project(backup_id),
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
            backup_root=paths.backup_root,
            backup_record_dir=paths.backup_record_dir,
            restore_record_dir=paths.restore_record_dir,
            wait_timeout=300,
        )
        return (
            _read_json(paths.backup_record_dir / f"{backup_id}.json"),
            _read_json(paths.restore_record_dir / f"{backup_id}.json"),
        )

    def backup_restore_source(self) -> Mapping[str, Any]:
        state = self.state
        state.source_backup_id = _next_backup_id(state)
        self._persist_state()
        backup_payload, restore_payload = self._backup_and_restore(
            state.source_backup_id
        )
        self._artifact("source-backup-record.json", backup_payload)
        self._artifact("source-restore-record.json", restore_payload)
        if (
            backup_payload.get("candidate_sha") != SOURCE_SHA
            or backup_payload.get("m7_content_snapshot", {}).get("profile")
            != backup.M7_CONTENT_SNAPSHOT_PROFILE
            or restore_payload.get("backup_id") != state.source_backup_id
            or restore_payload.get("passed") is not True
        ):
            raise DrillError("source Backup/Restore records are invalid")
        return {
            "backup_id": state.source_backup_id,
            "same_id_restore": True,
            "m7_content_profile": backup.M7_CONTENT_SNAPSHOT_PROFILE,
        }

    def plan_target(self) -> Mapping[str, Any]:
        state = self.state
        if state.source_backup_id is None:
            raise DrillError("source Backup ID is unavailable")
        _replace_config(state, state.target_image)
        result = upgrade.upgrade_existing_database(
            config_file=state.paths.config_file,
            secret_dir=state.paths.secret_dir,
            mode="loopback",
            source_candidate_sha=SOURCE_SHA,
            backup_id=state.source_backup_id,
            backup_root=state.paths.backup_root,
            backup_record_dir=state.paths.backup_record_dir,
            restore_record_dir=state.paths.restore_record_dir,
            release_record_dir=state.paths.release_record_dir,
            apply=False,
            confirm_target_sha=None,
            confirm_source_sha=None,
            confirm_backup_id=None,
            confirm_manifest_sha256=None,
            source_version=7,
        )
        _assert_result_fields(
            result,
            {
                "mode": "plan",
                "already_current": False,
                "restore_verified": True,
                "source_candidate_sha": SOURCE_SHA,
                "candidate_sha": state.target_sha,
                "backup_id": state.source_backup_id,
                "manifest_sha256": MARD_MANIFEST_SHA256,
                "source_version": 7,
                "target_version": 9,
            },
            "target upgrade plan",
        )
        self._artifact("upgrade-plan.json", result)
        return {"mode": "plan", "backup_id": state.source_backup_id}

    def apply_target(self) -> Mapping[str, Any]:
        state = self.state
        if state.source_backup_id is None:
            raise DrillError("source Backup ID is unavailable")
        result = upgrade.upgrade_existing_database(
            config_file=state.paths.config_file,
            secret_dir=state.paths.secret_dir,
            mode="loopback",
            source_candidate_sha=SOURCE_SHA,
            backup_id=state.source_backup_id,
            backup_root=state.paths.backup_root,
            backup_record_dir=state.paths.backup_record_dir,
            restore_record_dir=state.paths.restore_record_dir,
            release_record_dir=state.paths.release_record_dir,
            apply=True,
            confirm_target_sha=state.target_sha,
            confirm_source_sha=SOURCE_SHA,
            confirm_backup_id=state.source_backup_id,
            confirm_manifest_sha256=MARD_MANIFEST_SHA256,
            source_version=7,
        )
        _assert_result_fields(
            result,
            {
                "mode": "apply",
                "already_current": False,
                "application_stopped": True,
                "candidate_sha": state.target_sha,
                "source_candidate_sha": SOURCE_SHA,
                "backup_id": state.source_backup_id,
            },
            "target upgrade apply",
        )
        self._artifact("upgrade-apply.json", result)
        record_path = gatea._upgrade_marker(state.paths.release_record_dir, state.target_sha)
        evidence_path = state.paths.release_record_dir / (
            f"{state.target_sha}.existing-database-upgrade.evidence.json"
        )
        self._artifact("upgrade-record.json", _read_json(record_path))
        self._artifact("upgrade-evidence.json", _read_json(evidence_path))
        return {"mode": "apply", "application_stopped": True}

    def plan_replay(self) -> Mapping[str, Any]:
        state = self.state
        if state.source_backup_id is None:
            raise DrillError("source Backup ID is unavailable")
        result = upgrade.upgrade_existing_database(
            config_file=state.paths.config_file,
            secret_dir=state.paths.secret_dir,
            mode="loopback",
            source_candidate_sha=SOURCE_SHA,
            backup_id=state.source_backup_id,
            backup_root=state.paths.backup_root,
            backup_record_dir=state.paths.backup_record_dir,
            restore_record_dir=state.paths.restore_record_dir,
            release_record_dir=state.paths.release_record_dir,
            apply=False,
            confirm_target_sha=None,
            confirm_source_sha=None,
            confirm_backup_id=None,
            confirm_manifest_sha256=None,
            source_version=7,
        )
        _assert_result_fields(
            result,
            {
                "mode": "plan-replay",
                "already_current": True,
                "candidate_sha": state.target_sha,
                "backup_id": state.source_backup_id,
                "source_version": 7,
                "target_version": 9,
            },
            "target plan replay",
        )
        self._artifact("upgrade-plan-replay.json", result)
        return {"mode": "plan-replay", "already_current": True}

    def app_up(self) -> Mapping[str, Any]:
        state = self.state
        gatea.app_up(
            config_file=state.paths.config_file,
            secret_dir=state.paths.secret_dir,
            record_dir=state.paths.release_record_dir,
            mode="loopback",
            wait_timeout=300,
        )
        values = gatea._validated_inputs(
            config_file=state.paths.config_file,
            secret_dir=state.paths.secret_dir,
            mode="loopback",
            require_available_port=False,
        )
        rows = gatea._compose_ps(
            values=values,
            config_file=state.paths.config_file,
            secret_dir=state.paths.secret_dir,
            mode="loopback",
            services=("mysql", "redis", "app", "table-sweeper", "nginx"),
        )
        gatea._ensure_services_healthy(
            rows, "mysql", "redis", "app", "table-sweeper", "nginx"
        )
        gatea._validate_loopback_publishers(rows, LOOPBACK_PORT)
        return {"services_healthy": 5, "loopback_only": True}

    def verify_m9_runtime(self) -> Mapping[str, Any]:
        state = self.state
        if state.secrets is None:
            raise DrillError("drill Secret bundle is unavailable")
        paths = state.paths
        values = gatea._validated_inputs(
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
            require_available_port=False,
        )
        snapshot = gatea.read_database_snapshot(
            values=values,
            config_file=paths.config_file,
            secret_dir=paths.secret_dir,
            mode="loopback",
        )
        if snapshot.get("aerich_versions") != list(gatea.APPROVED_TARGET_M9_CHAIN):
            raise DrillError("M9 runtime does not expose exact M0-M9")
        expected_table_values = {
            "store_tables": 30,
            "enabled_store_tables": 30,
            "invalid_store_tables": 0,
            "distinct_table_qr_tokens": 30,
            "table_sessions": 0,
            "table_session_timers": 0,
            "table_occupancies": 0,
        }
        if any(snapshot.get(key) != value for key, value in expected_table_values.items()):
            raise DrillError("M9 runtime table bootstrap invariants are invalid")
        task_results: dict[str, dict[str, Any]] = {}
        for label, module in (
            ("reconcile", "app.tasks.table_reconcile"),
            ("sweep", "app.tasks.table_sweep"),
        ):
            result = gatea._run_compose(
                values=values,
                config_file=paths.config_file,
                secret_dir=paths.secret_dir,
                mode="loopback",
                arguments=(
                    "run",
                    "--rm",
                    "--no-deps",
                    "app",
                    "python",
                    "-m",
                    module,
                ),
                capture_output=True,
            )
            task_results[label] = _parse_task_json(result.stdout)
        if task_results["reconcile"].get("violations") != 0:
            raise DrillError("M9 table reconciliation reported a violation")
        if task_results["sweep"] != {"status": "ok", "closed": 0}:
            raise DrillError("M9 empty table sweep result is invalid")

        client = representative.LoopbackClient(LOOPBACK_PORT)
        admin: dict[str, Any] | None = None
        operation_error: BaseException | None = None
        logout_error: BaseException | None = None
        payload: dict[str, Any] = {}
        try:
            admin = representative._login(
                client,
                step="drill-m8-login",
                username="gatea_drill_admin",
                password=state.secrets.bootstrap_final_password,
                expected_role="super_admin",
            )
            token = str(admin["access_token"])
            table_list = _json_data(
                client.json_request(
                    "drill-m9-admin-tables",
                    "GET",
                    "/api/v1/admin/tables",
                    token=token,
                ),
                "m9-admin-tables",
            )
            table_items = table_list.get("items")
            if (
                not isinstance(table_items, list)
                or len(table_items) != 30
                or [item.get("table_no") for item in table_items]
                != [f"T{index:02d}" for index in range(1, 31)]
                or any(
                    item.get("state") != "available"
                    or item.get("is_enabled") is not True
                    for item in table_items
                    if isinstance(item, dict)
                )
            ):
                raise DrillError("M9 admin table inventory is invalid")
            product_id = int(state.color_fixture["product_id"])
            path = f"/api/v1/admin/products/kit/{product_id}"
            identity_body, identity_headers = client.request(
                "drill-m8-color-identity",
                "GET",
                path,
                token=token,
                headers={"Accept-Encoding": "identity"},
            )
            gzip_body, gzip_headers = client.request(
                "drill-m8-color-gzip",
                "GET",
                path,
                token=token,
                headers={"Accept-Encoding": "gzip"},
            )
            if _header(identity_headers, "Content-Encoding"):
                raise DrillError("identity JSON response was unexpectedly encoded")
            if _header(gzip_headers, "Content-Encoding").lower() != "gzip":
                raise DrillError("M8 JSON response was not gzip encoded")
            if not _header_contains_token(
                gzip_headers,
                "Vary",
                "Accept-Encoding",
            ):
                raise DrillError("M8 gzip response is missing Vary")
            try:
                decoded = gzip.decompress(gzip_body)
                identity_document = json.loads(identity_body)
                gzip_document = json.loads(decoded)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise DrillError("M8 gzip response is invalid") from error
            if (
                gzip_document != identity_document
                or len(gzip_body) >= len(identity_body)
            ):
                raise DrillError("M8 gzip body is not an equivalent reduction")
            health_body, health_headers = client.request(
                "drill-m8-small-health-gzip",
                "GET",
                "/api/v1/health/live",
                headers={"Accept-Encoding": "gzip"},
            )
            if (
                _header(health_headers, "Content-Encoding")
                or len(health_body) >= 1024
            ):
                raise DrillError("M8 small health response compression is invalid")
            _json_data(json.loads(health_body), "m8-small-health")
            detail = _json_data(identity_document, "m8-color-detail")
            colors = detail.get("colors")
            if not isinstance(colors, list) or len(colors) != 221:
                raise DrillError("M8 admin color Kit does not contain 221 slots")
            manifest = load_manifest(MARD_MANIFEST)
            by_slot = {int(item["slot_no"]): item for item in colors if isinstance(item, dict)}
            if len(by_slot) != 221:
                raise DrillError("M8 admin color Kit contains duplicate slots")
            for expected in manifest:
                actual = by_slot.get(expected.slot_no)
                if (
                    actual is None
                    or actual.get("color_code") != expected.color_code
                    or actual.get("name") != expected.name
                    or actual.get("swatch_hex") != expected.hex
                    or Path(
                        urlparse(str(actual.get("swatch_image_url"))).path
                    ).name
                    != expected.image_filename
                    or actual.get("is_active") is not True
                    or actual.get("is_configured") is not True
                ):
                    raise DrillError("M8 HEX catalog differs from the manifest")
            if len({str(item.get("swatch_hex")) for item in colors}) != 221:
                raise DrillError("M8 HEX catalog contains duplicate values")

            public = _json_data(
                client.json_request(
                    "drill-m8-public-color-kit",
                    "GET",
                    f"/api/v1/products/kit/{product_id}",
                ),
                "m8-public-color-kit",
            )
            public_colors = public.get("colors")
            if (
                not isinstance(public_colors, list)
                or len(public_colors) != 3
                or any(not isinstance(item, dict) for item in public_colors)
            ):
                raise DrillError("M8 public color Kit does not expose three colors")
            public_by_slot = {int(item["slot_no"]): item for item in public_colors}
            expected_public_slots = {
                int(value) for value in state.color_fixture["slot_numbers"]
            }
            if set(public_by_slot) != expected_public_slots:
                raise DrillError("M8 public color Kit changed its enabled colors")
            if any(
                re.fullmatch(r"#[0-9A-F]{6}", str(item.get("swatch_hex"))) is None
                or item.get("color_code") != manifest[slot - 1].color_code
                or item.get("name") != manifest[slot - 1].name
                or item.get("swatch_hex") != manifest[slot - 1].hex
                or Path(urlparse(str(item.get("swatch_image_url"))).path).name
                != manifest[slot - 1].image_filename
                for slot, item in public_by_slot.items()
            ):
                raise DrillError("M8 public colors do not expose canonical HEX")

            first_slot = int(public_colors[0]["slot_no"])
            expected = manifest[first_slot - 1]
            swatch_path = urlparse(str(public_colors[0]["swatch_image_url"])).path
            png_body, png_headers = client.request(
                "drill-m8-public-png",
                "GET",
                swatch_path,
                headers={"Accept-Encoding": "gzip"},
            )
            expected_png = build_swatch_png(expected.rgb)
            if (
                png_body != expected_png
                or _header(png_headers, "Content-Encoding")
                or not _header(png_headers, "Content-Type").lower().startswith("image/png")
            ):
                raise DrillError("M8 PNG compatibility response is invalid")
            payload = {
                "schema_version": 1,
                "candidate_sha": state.target_sha,
                "aerich_versions": snapshot["aerich_versions"],
                "store_tables": len(table_items),
                "table_reconcile_violations": 0,
                "table_sweep_closed": 0,
                "admin_color_slots": len(colors),
                "manifest_hex_matches": True,
                "public_enabled_colors": len(public_colors),
                "public_hex_canonical": True,
                "identity_json_bytes": len(identity_body),
                "gzip_json_bytes": len(gzip_body),
                "gzip_decoded_equal": True,
                "gzip_vary": True,
                "small_response_bytes": len(health_body),
                "small_response_content_encoding": None,
                "png_bytes": len(png_body),
                "png_sha256": _sha256_bytes(png_body),
                "png_content_type": _header(png_headers, "Content-Type"),
                "png_content_encoding": None,
                "request_count": len(client.results),
                "passed": True,
            }
        except BaseException as error:
            operation_error = error
        finally:
            if admin is not None:
                try:
                    representative._logout_and_verify(
                        client,
                        step_prefix="drill-m8-admin",
                        access_token=str(admin["access_token"]),
                        refresh_token=str(admin["refresh_token"]),
                    )
                except BaseException as error:
                    logout_error = error
        if logout_error is not None:
            raise DrillError("M9 runtime session cleanup failed") from logout_error
        if operation_error is not None:
            if isinstance(operation_error, DrillError):
                raise operation_error
            raise DrillError("M9 runtime verification failed safely") from operation_error
        self._artifact("runtime-verification.json", payload)
        return {
            "tables": 30,
            "table_reconcile_violations": 0,
            "hex_colors": 221,
            "gzip_reduction_bytes": payload["identity_json_bytes"]
            - payload["gzip_json_bytes"],
            "png_compatibility": True,
        }

    def backup_restore_target(self) -> Mapping[str, Any]:
        state = self.state
        state.target_backup_id = _next_backup_id(state)
        self._persist_state()
        backup_payload, restore_payload = self._backup_and_restore(
            state.target_backup_id
        )
        self._artifact("target-backup-record.json", backup_payload)
        self._artifact("target-restore-record.json", restore_payload)
        if (
            backup_payload.get("candidate_sha") != state.target_sha
            or restore_payload.get("backup_id") != state.target_backup_id
            or restore_payload.get("candidate_sha") != state.target_sha
            or restore_payload.get("passed") is not True
        ):
            raise DrillError("target Backup/Restore records are invalid")
        return {
            "backup_id": state.target_backup_id,
            "same_id_restore": True,
            "restore_app_ready": True,
        }

    def execute(self) -> None:
        for name, method_name in PIPELINE:
            self._stage(name, getattr(self, method_name))


def _state_from_record(
    paths: DrillPaths,
    environment: Mapping[str, str],
    runner: CommandRunner,
) -> DrillState | None:
    state_path = paths.artifact_dir / "drill-state.json"
    if not state_path.exists():
        return None
    payload = _read_json(state_path)
    target_sha = payload.get("target_sha")
    work_root = payload.get("work_root")
    source_image = payload.get("source_image")
    target_image = payload.get("target_image")
    if (
        payload.get("schema_version") != 1
        or payload.get("record_type") != "gatea-m7-m9-drill-state"
        or payload.get("source_sha") != SOURCE_SHA
        or not isinstance(target_sha, str)
        or SHA_PATTERN.fullmatch(target_sha) is None
        or source_image != f"pinkdoohub-gatea:{SOURCE_SHA}"
        or target_image != f"pinkdoohub-gatea:{target_sha}"
        or work_root != str(paths.work_root)
        or payload.get("config_file") != str(paths.config_file)
        or payload.get("secret_dir") != str(paths.secret_dir)
    ):
        raise DrillError("drill ownership state is invalid")
    state = DrillState(
        paths=paths,
        target_sha=target_sha,
        source_image=source_image,
        target_image=target_image,
        environment=environment,
        command_runner=runner,
        ownership_acquired=payload.get("ownership_acquired") is True,
    )
    for attribute in ("source_backup_id", "target_backup_id"):
        value = payload.get(attribute)
        if value is not None and (
            not isinstance(value, str) or BACKUP_ID_PATTERN.fullmatch(value) is None
        ):
            raise DrillError("drill ownership Backup ID is invalid")
        setattr(state, attribute, value)
    return state


def _container_ids_for_project(runner: CommandRunner, project: str) -> list[str]:
    return [
        line.partition("|")[0]
        for line in _docker_names(runner, "containers", project=project)
        if line.partition("|")[0]
    ]


def _remove_exact_resources(state: DrillState) -> list[str]:
    runner = state.command_runner
    errors: list[str] = []
    paths = state.paths
    projects = [MAIN_PROJECT]
    projects.extend(
        backup.restore_project(value)
        for value in (state.source_backup_id, state.target_backup_id)
        if value is not None
    )

    if paths.config_file.is_file():
        try:
            values = gatea.parse_env_file(paths.config_file)
            environment = gatea._operation_environment(
                values,
                paths.config_file,
                paths.secret_dir,
            )
            main_command = gatea.compose_command(
                config_file=paths.config_file,
                mode="loopback",
                include_bootstrap=True,
                profiles=("operations", "bootstrap"),
                arguments=("down", "--volumes", "--remove-orphans"),
            )
            result = runner.run(main_command, environment=environment, timeout=300)
            if result.returncode != 0:
                errors.append("main-compose-down")
            for project in projects[1:]:
                command = backup.restore_command(
                    project=project,
                    config_file=paths.config_file,
                    operations_profile=True,
                    arguments=("down", "--volumes", "--remove-orphans"),
                )
                restore_environment = environment | {"GATEA_RESTORE_PROJECT": project}
                result = runner.run(
                    command,
                    environment=restore_environment,
                    timeout=300,
                )
                if result.returncode != 0:
                    errors.append("restore-compose-down")
        except BaseException:
            errors.append("compose-cleanup-exception")

    for project in projects:
        container_ids = _container_ids_for_project(runner, project)
        if container_ids:
            result = runner.run(("docker", "rm", "--force", *container_ids), timeout=180)
            if result.returncode != 0:
                errors.append("container-remove")

    exact_volumes = list(FIXED_VOLUMES)
    exact_networks = list(FIXED_NETWORKS)
    for project in projects[1:]:
        exact_volumes.extend((f"{project}-mysql-data", f"{project}-product-images"))
        exact_networks.append(f"{project}-internal")
    for name in exact_volumes:
        if runner.run(("docker", "volume", "inspect", name)).returncode == 0:
            if runner.run(("docker", "volume", "rm", name), timeout=180).returncode != 0:
                errors.append("volume-remove")
    for name in exact_networks:
        if runner.run(("docker", "network", "inspect", name)).returncode == 0:
            if runner.run(("docker", "network", "rm", name), timeout=180).returncode != 0:
                errors.append("network-remove")
    for image in (state.target_image, state.source_image):
        try:
            image_ids = _docker_image_ids(runner, image)
        except DrillError:
            errors.append("image-inspection")
            continue
        if image_ids:
            if runner.run(("docker", "image", "rm", image), timeout=180).returncode != 0:
                errors.append("image-remove")
    return errors


def cleanup_owned_state(state: DrillState) -> dict[str, Any]:
    """只清理由可信 ownership Record 精确声明的资源，并复核结果。"""

    errors: list[str] = []
    performed = False
    if state.ownership_acquired:
        performed = True
        try:
            errors.extend(_remove_exact_resources(state))
        except BaseException:
            errors.append("resource-removal-exception")
        if state.paths.work_root.exists():
            try:
                if (
                    state.paths.work_root.parent.resolve()
                    != Path(state.environment["RUNNER_TEMP"]).resolve()
                    or not state.paths.work_root.name.startswith(
                        "pinkdoohub-gatea-m7-m9-"
                    )
                ):
                    raise DrillError("refused unsafe workspace cleanup target")
                shutil.rmtree(state.paths.work_root)
            except BaseException:
                errors.append("workspace-remove")

    inventory = docker_inventory(state.command_runner)
    owned_restore_projects = {
        backup.restore_project(value)
        for value in (state.source_backup_id, state.target_backup_id)
        if value is not None
    }
    residual_restore_containers = [
        line
        for line in inventory["restore_containers"]
        if line.rpartition("|")[2] in owned_restore_projects
    ]
    residual_restore_volumes = [
        name
        for name in inventory["restore_volumes"]
        if any(name.startswith(project + "-") for project in owned_restore_projects)
    ]
    residual_restore_networks = [
        name
        for name in inventory["restore_networks"]
        if any(name.startswith(project + "-") for project in owned_restore_projects)
    ]
    try:
        residual_images = [
            image
            for image in (state.source_image, state.target_image)
            if _docker_image_ids(state.command_runner, image)
        ]
    except DrillError:
        errors.append("image-residual-inspection")
        residual_images = [state.source_image, state.target_image]
    residual = {
        "main_containers": inventory["main_containers"],
        "main_volumes": inventory["main_volumes"],
        "main_networks": inventory["main_networks"],
        "restore_containers": residual_restore_containers,
        "restore_volumes": residual_restore_volumes,
        "restore_networks": residual_restore_networks,
        "images": residual_images,
        "workspace_exists": state.paths.work_root.exists(),
        "loopback_port_available": _port_available(LOOPBACK_PORT),
    }
    passed = (
        not errors
        and not residual["main_containers"]
        and not residual["main_volumes"]
        and not residual["main_networks"]
        and not residual["restore_containers"]
        and not residual["restore_volumes"]
        and not residual["restore_networks"]
        and not residual["images"]
        and residual["workspace_exists"] is False
        and residual["loopback_port_available"] is True
    )
    return {
        "schema_version": 1,
        "record_type": "gatea-m7-m9-drill-cleanup",
        "checked_at": _utc_now(),
        "ownership_acquired": state.ownership_acquired,
        "cleanup_performed": performed,
        "errors": sorted(set(errors)),
        "residual": residual,
        "passed": passed,
    }


def scan_artifacts(
    artifact_dir: Path,
    *,
    secret_values: Sequence[str] = (),
) -> dict[str, Any]:
    files = sorted(item.name for item in artifact_dir.iterdir())
    unexpected = [name for name in files if name not in ARTIFACT_ALLOWLIST]
    if unexpected:
        raise DrillError("artifact directory contains a non-allowlisted file")
    scanned_bytes = 0
    populated_secrets = [value.encode() for value in secret_values if value]
    for name in files:
        path = artifact_dir / name
        if not path.is_file() or path.is_symlink():
            raise DrillError("artifact allowlist contains a non-regular file")
        content = path.read_bytes()
        scanned_bytes += len(content)
        if any(value in content for value in populated_secrets):
            raise DrillError("artifact contains an ephemeral Secret value")
        if any(pattern.search(content) for pattern in SENSITIVE_TEXT_PATTERNS):
            raise DrillError("artifact contains a credential-shaped value")
    return {
        "files": files,
        "file_count": len(files),
        "bytes": scanned_bytes,
        "allowlist_passed": True,
        "secret_scan_passed": True,
    }


def _purge_artifact_directory(artifact_dir: Path) -> None:
    """扫描失败时删除全部候选上传内容，避免失败作业反向泄露 Secret。"""

    for item in artifact_dir.iterdir():
        if item.is_symlink() or item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink(missing_ok=True)


def _write_artifact_scan_failure(
    state: DrillState,
    cleanup_payload: Mapping[str, Any] | None,
    *,
    failure_stage: str = "artifact-scan",
) -> None:
    _purge_artifact_directory(state.paths.artifact_dir)
    cleanup_passed = cleanup_payload is not None and cleanup_payload.get("passed") is True
    _write_json(
        state.paths.artifact_dir / "drill-state.json",
        state.safe_state(),
    )
    _write_json(
        state.paths.artifact_dir / "cleanup-report.json",
        {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-cleanup",
            "checked_at": _utc_now(),
            "passed": cleanup_passed,
            "errors": [] if cleanup_passed else ["cleanup-not-verified"],
        },
    )
    _write_json(
        state.paths.artifact_dir / "summary.json",
        {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill",
            "completed_at": _utc_now(),
            "status": "failed",
            "failed_stage": failure_stage,
            "error_type": (
                "ArtifactSafetyError"
                if failure_stage == "artifact-scan"
                else "FinalizationSafetyError"
            ),
            "source_sha": SOURCE_SHA,
            "target_sha": state.target_sha,
            "cleanup_passed": cleanup_passed,
            "production_secrets_used": False,
            "persistent_gatea_authorized": False,
            "scope": "github-hosted-disposable-linux",
            "artifact_directory_purged": True,
        },
    )


def _write_artifact_scan_marker(artifact_dir: Path) -> None:
    _write_json(
        artifact_dir / ARTIFACT_SCAN_MARKER,
        {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-artifact-scan",
            "checked_at": _utc_now(),
            "allowlist_passed": True,
            "secret_scan_passed": True,
        },
    )


def _initial_state(
    artifact_dir: Path,
    environment: Mapping[str, str],
    runner: CommandRunner,
) -> tuple[DrillState, dict[str, Any], dict[str, Any]]:
    paths = paths_from_environment(
        artifact_dir,
        environment,
        require_empty_artifacts=True,
    )
    if paths.work_root.exists():
        raise DrillError("drill workspace already exists")
    host = validate_host_environment(
        environment,
        runner,
        require_clean_start=True,
    )
    target_sha, pr_head, git_evidence = validate_git_target(environment, runner)
    state = DrillState(
        paths=paths,
        target_sha=target_sha,
        source_image=f"pinkdoohub-gatea:{SOURCE_SHA}",
        target_image=f"pinkdoohub-gatea:{target_sha}",
        environment=environment,
        command_runner=runner,
        pr_head_sha=pr_head,
    )
    for image in (state.source_image, state.target_image):
        if _docker_image_ids(runner, image):
            raise DrillError("drill app image tag already exists")
    return state, host, git_evidence


def run_command(
    artifact_dir: Path,
    *,
    environment: Mapping[str, str] = os.environ,
    runner: CommandRunner | None = None,
    drill_factory: Callable[[DrillState], GateAM7M9Drill] = GateAM7M9Drill,
) -> int:
    command_runner = runner or CommandRunner()
    state: DrillState | None = None
    host_evidence: dict[str, Any] = {}
    git_evidence: dict[str, Any] = {}
    operation_error: BaseException | None = None
    cleanup_payload: dict[str, Any] | None = None
    cleanup_attempts: list[dict[str, Any]] = []
    scan_payload: dict[str, Any] | None = None
    failure_evidence: dict[str, Any] | None = None
    started_at = _utc_now()
    failed_stage = "preflight"
    try:
        state, host_evidence, git_evidence = _initial_state(
            artifact_dir,
            environment,
            command_runner,
        )
        state.ownership_acquired = True
        _write_json(state.state_path, state.safe_state())
        prepare_workspace(state)
        drill = drill_factory(state)
        for name, method_name in PIPELINE:
            failed_stage = name
            drill._stage(name, getattr(drill, method_name))
        failed_stage = "completed"
    except BaseException as error:
        operation_error = error
    finally:
        if state is None:
            try:
                paths = paths_from_environment(
                    artifact_dir,
                    environment,
                    require_empty_artifacts=False,
                )
                synthetic_state = DrillState(
                    paths=paths,
                    target_sha=environment.get("GITHUB_SHA", "0" * 40),
                    source_image=f"pinkdoohub-gatea:{SOURCE_SHA}",
                    target_image=f"pinkdoohub-gatea:{environment.get('GITHUB_SHA', '0' * 40)}",
                    environment=environment,
                    command_runner=command_runner,
                )
                cleanup_payload = cleanup_owned_state(synthetic_state)
                _write_json(paths.artifact_dir / "cleanup-report.json", cleanup_payload)
            except BaseException:
                cleanup_payload = {
                    "schema_version": 1,
                    "record_type": "gatea-m7-m9-drill-cleanup",
                    "ownership_acquired": False,
                    "cleanup_performed": False,
                    "passed": False,
                    "errors": ["cleanup-report-unavailable"],
                }
        else:
            secret_values = state.secrets.values() if state.secrets is not None else ()
            failure_evidence = _safe_failure_evidence(
                operation_error,
                secret_values=secret_values,
            )
            finalization_stage = "cleanup"
            try:
                for attempt in range(1, 3):
                    cleanup_payload = cleanup_owned_state(state)
                    cleanup_attempts.append(
                        {
                            "attempt": attempt,
                            "errors": cleanup_payload.get("errors", []),
                            "passed": cleanup_payload.get("passed") is True,
                            "residual": cleanup_payload.get("residual", {}),
                        }
                    )
                    if cleanup_payload.get("passed") is True:
                        break
                    if attempt == 1:
                        time.sleep(1)
                finalization_stage = "cleanup-report-write"
                _write_json(
                    state.paths.artifact_dir / "cleanup-report.json",
                    cleanup_payload,
                )
                finalization_stage = "summary-write"
                summary = {
                    "schema_version": 1,
                    "record_type": "gatea-m7-m9-drill",
                    "started_at": started_at,
                    "completed_at": _utc_now(),
                    "status": (
                        "passed"
                        if operation_error is None and cleanup_payload.get("passed") is True
                        else "failed"
                    ),
                    "failed_stage": None if operation_error is None else failed_stage,
                    "error_type": (
                        None if operation_error is None else type(operation_error).__name__
                    ),
                    "failure_evidence": failure_evidence,
                    "source_sha": SOURCE_SHA,
                    "target_sha": state.target_sha,
                    "reported_pr_head_sha": state.pr_head_sha,
                    "host_preflight": host_evidence,
                    "git_preflight": git_evidence,
                    "source_backup_id": state.source_backup_id,
                    "target_backup_id": state.target_backup_id,
                    "stages": state.stages,
                    "cleanup_attempts": cleanup_attempts,
                    "cleanup_passed": cleanup_payload.get("passed") is True,
                    "production_secrets_used": False,
                    "persistent_gatea_authorized": False,
                    "scope": "github-hosted-disposable-linux",
                }
                _write_json(state.paths.artifact_dir / "summary.json", summary)
                finalization_stage = "artifact-scan"
                scan_payload = scan_artifacts(
                    state.paths.artifact_dir,
                    secret_values=secret_values,
                )
                _write_artifact_scan_marker(state.paths.artifact_dir)
                scan_payload = scan_artifacts(
                    state.paths.artifact_dir,
                    secret_values=secret_values,
                )
                summary["artifact_scan"] = {
                    "allowlist_passed": True,
                    "file_count": scan_payload["file_count"],
                    "scope": "all-artifacts-before-final-summary-rewrite",
                    "secret_scan_passed": True,
                }
                _write_json(state.paths.artifact_dir / "summary.json", summary)
                scan_payload = scan_artifacts(
                    state.paths.artifact_dir,
                    secret_values=secret_values,
                )
            except BaseException as error:
                if operation_error is None:
                    operation_error = error
                if cleanup_payload is None:
                    cleanup_payload = {
                        "passed": False,
                        "errors": ["cleanup-exception"],
                    }
                try:
                    _write_artifact_scan_failure(
                        state,
                        cleanup_payload,
                        failure_stage=finalization_stage,
                    )
                    scan_artifacts(
                        state.paths.artifact_dir,
                        secret_values=secret_values,
                    )
                except BaseException:
                    try:
                        _purge_artifact_directory(state.paths.artifact_dir)
                    except BaseException:
                        pass
                scan_payload = None
            finally:
                if state.secrets is not None:
                    state.secrets.clear()

    if operation_error is not None:
        if failure_evidence is not None:
            print(
                "Gate A M7-to-M9 drill failure evidence: "
                + json.dumps(failure_evidence, ensure_ascii=True, sort_keys=True),
                file=sys.stderr,
            )
        return 1
    if cleanup_payload is None or cleanup_payload.get("passed") is not True:
        return 1
    if scan_payload is None or scan_payload.get("secret_scan_passed") is not True:
        return 1
    return 0


def cleanup_command(
    artifact_dir: Path,
    *,
    environment: Mapping[str, str] = os.environ,
    runner: CommandRunner | None = None,
) -> int:
    command_runner = runner or CommandRunner()
    paths: DrillPaths | None = None
    state: DrillState | None = None
    cleanup_payload: dict[str, Any] | None = None
    try:
        paths = paths_from_environment(
            artifact_dir,
            environment,
            require_empty_artifacts=False,
            allow_unexpected_artifacts=True,
        )
        marker = paths.artifact_dir / ARTIFACT_SCAN_MARKER
        marker.unlink(missing_ok=True)
        validate_host_environment(
            environment,
            command_runner,
            require_clean_start=False,
        )
        state = _state_from_record(paths, environment, command_runner)
        if state is None:
            target_sha = environment.get("GITHUB_SHA", "")
            if SHA_PATTERN.fullmatch(target_sha) is None:
                raise DrillError("cleanup target SHA is unavailable")
            state = DrillState(
                paths=paths,
                target_sha=target_sha,
                source_image=f"pinkdoohub-gatea:{SOURCE_SHA}",
                target_image=f"pinkdoohub-gatea:{target_sha}",
                environment=environment,
                command_runner=command_runner,
            )
        cleanup_payload = cleanup_owned_state(state)
        _write_json(paths.artifact_dir / "cleanup-report.json", cleanup_payload)
        try:
            scan_artifacts(paths.artifact_dir)
        except BaseException:
            _write_artifact_scan_failure(state, cleanup_payload)
            scan_artifacts(paths.artifact_dir)
            _write_artifact_scan_marker(paths.artifact_dir)
            scan_artifacts(paths.artifact_dir)
            return 1
        _write_artifact_scan_marker(paths.artifact_dir)
        scan_artifacts(paths.artifact_dir)
        return 0 if cleanup_payload.get("passed") is True else 1
    except BaseException as error:
        if paths is not None:
            try:
                (paths.artifact_dir / ARTIFACT_SCAN_MARKER).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            if paths is None:
                paths = paths_from_environment(
                    artifact_dir,
                    environment,
                    require_empty_artifacts=False,
                    allow_unexpected_artifacts=True,
                )
            _write_json(
                paths.artifact_dir / "cleanup-report.json",
                {
                    "schema_version": 1,
                    "record_type": "gatea-m7-m9-drill-cleanup",
                    "checked_at": _utc_now(),
                    "passed": False,
                    "error_type": type(error).__name__,
                    "errors": ["cleanup-command-failed-safely"],
                },
            )
        except BaseException:
            pass
        return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "cleanup"))
    parser.add_argument("--artifact-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    if arguments.command == "run":
        result = run_command(arguments.artifact_dir)
    else:
        result = cleanup_command(arguments.artifact_dir)
    if result == 0:
        print(f"Gate A M7-to-M9 drill {arguments.command} passed")
    else:
        print(
            f"Gate A M7-to-M9 drill {arguments.command} failed safely",
            file=sys.stderr,
        )
    return result


if __name__ == "__main__":
    raise SystemExit(main())
