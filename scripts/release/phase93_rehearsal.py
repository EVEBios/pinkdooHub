#!/usr/bin/env python3
"""准备并校验 Phase 9.3 专属隔离演练工作区。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
from typing import Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = Path("/tmp/pinkdoohub-phase93")
COMPOSE_FILE = REPOSITORY_ROOT / "deploy" / "rehearsal" / "compose.yml"
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}t[0-9]{6}$")
PROJECT_PREFIX = "pinkdoohub-phase93-"
HTTPS_HOST = "pinkdoohub-phase93.test"
PORTS = {
    "source_mysql": 14306,
    "restore_mysql": 14307,
    "redis": 16379,
    "https": 18443,
}
SECRET_NAMES = (
    "mysql_app_password",
    "mysql_root_password",
    "redis_password",
    "jwt_secret",
    "bootstrap_password",
    "bootstrap_rotated_password",
)
IMAGE_TAGS = (
    "mysql:8.0.46",
    "redis:8.0.1-alpine",
    "python:3.10.9-slim-bookworm",
    "nginx:1.27.5-alpine",
)


class RehearsalError(RuntimeError):
    """不携带 Secret、Token 或连接串的演练准备错误。"""


@dataclass(frozen=True)
class RehearsalConfig:
    """Phase 9.3 冻结目标；所有路径均属于一次运行。"""

    run_id: str
    project: str
    root: Path
    secret_dir: Path
    cert_dir: Path
    evidence_dir: Path
    app_image: str

    def compose_environment(self) -> dict[str, str]:
        """返回不含 Secret 值的 Compose 环境。"""

        return {
            "PHASE93_COMPOSE_PROJECT": self.project,
            "PHASE93_APP_IMAGE": self.app_image,
            "PHASE93_SOURCE_MYSQL_PORT": str(PORTS["source_mysql"]),
            "PHASE93_RESTORE_MYSQL_PORT": str(PORTS["restore_mysql"]),
            "PHASE93_REDIS_PORT": str(PORTS["redis"]),
            "PHASE93_HTTPS_HOST": HTTPS_HOST,
            "PHASE93_HTTPS_PORT": str(PORTS["https"]),
            "PHASE93_SECRET_DIR": str(self.secret_dir),
            "PHASE93_CERT_DIR": str(self.cert_dir),
        }

    def safe_summary(self) -> dict[str, object]:
        """返回适合进入脱敏证据的目标摘要。"""

        return {
            "run_id": self.run_id,
            "project": self.project,
            "root": str(self.root),
            "app_image": self.app_image,
            "https_host": HTTPS_HOST,
            "ports": PORTS,
            "secret_categories": list(SECRET_NAMES),
        }


def config_for_run(run_id: str) -> RehearsalConfig:
    """从严格 run ID 构造唯一、可精确回收的资源名。"""

    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise RehearsalError("run ID must use YYYYMMDDtHHMMSS lowercase format")
    try:
        datetime.strptime(run_id, "%Y%m%dt%H%M%S")
    except ValueError as error:
        raise RehearsalError("run ID is not a valid timestamp") from error

    root = WORKSPACE_ROOT / run_id
    if not root.resolve().is_relative_to(WORKSPACE_ROOT.resolve()):
        raise RehearsalError("run workspace escaped the frozen temporary root")
    project = f"{PROJECT_PREFIX}{run_id}"
    return RehearsalConfig(
        run_id=run_id,
        project=project,
        root=root,
        secret_dir=root / "secrets",
        cert_dir=root / "certs",
        evidence_dir=root / "evidence",
        app_image=f"pinkdoohub-phase93:{run_id}",
    )


def _run(
    command: Sequence[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )


def _successful_output(command: Sequence[str]) -> str:
    result = _run(command)
    if result.returncode != 0:
        raise RehearsalError(f"required command failed: {command[0]}")
    return result.stdout.strip()


def git_snapshot() -> tuple[str, list[str]]:
    """读取候选 SHA，并返回不包含文件内容的工作树状态。"""

    sha = _successful_output(("git", "rev-parse", "HEAD"))
    status = _successful_output(
        ("git", "status", "--porcelain=v1", "--untracked-files=all")
    )
    return sha, status.splitlines() if status else []


def _port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _docker_resource_ids(project: str) -> dict[str, list[str]]:
    docker = shutil.which("docker")
    if docker is None:
        raise RehearsalError("docker CLI is required")

    queries = {
        "containers": (
            docker,
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ),
        "networks": (
            docker,
            "network",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ),
        "volumes": (
            docker,
            "volume",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ),
    }
    resources: dict[str, list[str]] = {}
    for kind, command in queries.items():
        result = _run(command)
        if result.returncode != 0:
            raise RehearsalError(f"Docker {kind} ownership query failed")
        resources[kind] = result.stdout.splitlines()
    return resources


def validate_preflight(config: RehearsalConfig) -> dict[str, object]:
    """拒绝脏候选、端口冲突、同名资源和工具链缺失。"""

    if not COMPOSE_FILE.is_file():
        raise RehearsalError("the frozen Compose file is missing")
    if config.root.exists():
        raise RehearsalError("run workspace already exists")
    sha, dirty_paths = git_snapshot()
    if dirty_paths:
        raise RehearsalError("candidate working tree is not clean")

    unavailable_ports = [
        port for port in PORTS.values() if not _port_is_available(port)
    ]
    if unavailable_ports:
        raise RehearsalError("one or more frozen loopback ports are unavailable")
    if 3306 in PORTS.values():
        raise RehearsalError("the frozen topology must never publish port 3306")

    resources = _docker_resource_ids(config.project)
    if any(resources.values()):
        raise RehearsalError("the Compose project already owns Docker resources")

    versions = {
        "docker": _successful_output(
            (
                "docker",
                "version",
                "--format",
                "{{.Client.Version}}/{{.Server.Version}}",
            )
        ),
        "compose": _successful_output(("docker", "compose", "version", "--short")),
        "python": _successful_output((sys.executable, "--version")),
        "openssl": _successful_output(("openssl", "version")),
    }
    return {
        "schema_version": 1,
        "status": "preflight-passed",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": sha,
        "working_tree_clean": True,
        "ports_available": True,
        "docker_project_resources": resources,
        "versions": versions,
        **config.safe_summary(),
    }


def _write_private(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)
        stream.write("\n")


def _generate_secrets(config: RehearsalConfig) -> None:
    values = {
        "mysql_app_password": secrets.token_hex(32),
        "mysql_root_password": secrets.token_hex(32),
        "redis_password": secrets.token_hex(32),
        "jwt_secret": secrets.token_hex(64),
        "bootstrap_password": f"P9a!{secrets.token_hex(20)}",
        "bootstrap_rotated_password": f"P9r!{secrets.token_hex(20)}",
    }
    for name in SECRET_NAMES:
        _write_private(config.secret_dir / name, values[name])


def _generate_certificates(config: RehearsalConfig) -> str:
    ca_key = config.cert_dir / "ca.key"
    ca_cert = config.cert_dir / "ca.crt"
    server_key = config.cert_dir / "server.key"
    server_request = config.cert_dir / "server.csr"
    server_cert = config.cert_dir / "server.crt"
    extension = config.cert_dir / "server.ext"
    extension.write_text(
        "subjectAltName=DNS:pinkdoohub-phase93.test,IP:127.0.0.1\n"
        "extendedKeyUsage=serverAuth\n",
        encoding="utf-8",
    )
    commands = (
        (
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "7", "-subj", "/CN=pinkdoohub-phase93-ca",
            "-keyout", str(ca_key), "-out", str(ca_cert),
        ),
        (
            "openssl", "req", "-newkey", "rsa:2048", "-nodes",
            "-subj", f"/CN={HTTPS_HOST}", "-keyout", str(server_key),
            "-out", str(server_request),
        ),
        (
            "openssl", "x509", "-req", "-days", "7",
            "-in", str(server_request), "-CA", str(ca_cert),
            "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(server_cert),
            "-extfile", str(extension),
        ),
    )
    for command in commands:
        result = _run(command)
        if result.returncode != 0:
            raise RehearsalError("short-lived TLS certificate generation failed")

    os.chmod(ca_key, 0o600)
    os.chmod(server_key, 0o600)
    os.chmod(ca_cert, 0o644)
    os.chmod(server_cert, 0o644)
    fingerprint = _successful_output(
        ("openssl", "x509", "-in", str(ca_cert), "-noout", "-fingerprint", "-sha256")
    )
    server_request.unlink()
    extension.unlink()
    serial = config.cert_dir / "ca.srl"
    if serial.exists():
        serial.unlink()
    return fingerprint


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_compose_environment(config: RehearsalConfig) -> Path:
    path = config.root / "compose.env"
    content = "".join(
        f"{key}={value}\n"
        for key, value in sorted(config.compose_environment().items())
    )
    _write_private(path, content.rstrip("\n"))
    return path


def _verify_permissions(config: RehearsalConfig) -> None:
    for directory in (config.root, config.secret_dir, config.cert_dir):
        mode = stat.S_IMODE(directory.stat().st_mode)
        if mode != 0o700:
            raise RehearsalError("a private rehearsal directory has unsafe permissions")
    for name in SECRET_NAMES:
        if stat.S_IMODE((config.secret_dir / name).stat().st_mode) != 0o600:
            raise RehearsalError("a runtime Secret file has unsafe permissions")


def prepare(config: RehearsalConfig) -> Path:
    """通过预检后生成短期 Secret、TLS 和脱敏 manifest。"""

    preflight = validate_preflight(config)
    WORKSPACE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(WORKSPACE_ROOT, 0o700)
    config.root.mkdir(mode=0o700)
    config.secret_dir.mkdir(mode=0o700)
    config.cert_dir.mkdir(mode=0o700)
    config.evidence_dir.mkdir(mode=0o700)
    _generate_secrets(config)
    ca_fingerprint = _generate_certificates(config)
    compose_env = _write_compose_environment(config)
    _verify_permissions(config)

    manifest = {
        **preflight,
        "status": "prepared",
        "ca_fingerprint": ca_fingerprint,
        "compose_file_sha256": _file_sha256(COMPOSE_FILE),
        "compose_env_sha256": _file_sha256(compose_env),
        "image_tags": list(IMAGE_TAGS),
        "secrets_present": list(SECRET_NAMES),
        "secret_values_recorded": False,
    }
    manifest_path = config.evidence_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "Phase 9.3 workspace prepared: "
        f"run_id={config.run_id} project={config.project} "
        f"evidence={config.evidence_dir}"
    )
    return manifest_path


def cleanup_plan(config: RehearsalConfig) -> dict[str, object]:
    """只输出精确清理目标；本命令不会停止或删除任何资源。"""

    resources = _docker_resource_ids(config.project)
    return {
        "project": config.project,
        "workspace": str(config.root),
        "ports": list(PORTS.values()),
        "owned_resources": resources,
        "compose_command": [
            "docker", "compose", "--file", str(COMPOSE_FILE),
            "--env-file", str(config.root / "compose.env"),
            "down", "--volumes", "--remove-orphans",
        ],
        "destructive": True,
        "executed": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "cleanup-plan"))
    parser.add_argument("--run-id", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        config = config_for_run(arguments.run_id)
        if arguments.command == "prepare":
            prepare(config)
        else:
            print(json.dumps(cleanup_plan(config), ensure_ascii=False, indent=2))
        return 0
    except RehearsalError as error:
        print(f"Phase 9.3 preparation refused: {error}", file=sys.stderr)
    except Exception as error:
        print(
            f"Phase 9.3 preparation failed safely: {type(error).__name__}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
