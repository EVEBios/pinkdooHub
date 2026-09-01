#!/usr/bin/env python3
"""Gate A 持久部署的受控预检与生命周期操作。

本模块不生成、读取或输出 Secret 值。写操作固定到经过验证的 Compose
文件、完整 Git SHA 镜像与受保护配置；当前只允许 loopback 首次部署，
不提供删卷、恢复、Bootstrap、TLS 切换或公开发布操作。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GATEA_ROOT = REPOSITORY_ROOT / "deploy" / "gatea"
BASE_COMPOSE = GATEA_ROOT / "compose.yml"
MODE_COMPOSE = {
    "loopback": GATEA_ROOT / "compose.loopback.yml",
    "tls": GATEA_ROOT / "compose.tls.yml",
}
BOOTSTRAP_COMPOSE = GATEA_ROOT / "compose.bootstrap.yml"
DEFAULT_CONFIG_FILE = Path("/etc/pinkdoohub/gatea/config.env")
DEFAULT_SECRET_DIR = Path("/etc/pinkdoohub/gatea/secrets")
DEFAULT_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/releases")
EXPECTED_SECRET_FILES = (
    "mysql_app_password",
    "mysql_root_password",
    "redis_password",
    "jwt_secret",
)
REQUIRED_CONFIG_KEYS = (
    "GATEA_APP_IMAGE",
    "GATEA_API_HOST",
    "APP_VERSION",
    "APP_ENV",
    "APP_DEBUG",
    "DB_ENGINE",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "PRODUCT_IMAGE_UPLOAD_DIR",
    "PRODUCT_IMAGE_BASE_URL",
    "JWT_ALGORITHM",
)
FORBIDDEN_CONFIG_KEYS = (
    "DB_PASSWORD",
    "JWT_SECRET_KEY",
    "REDIS_URL",
    "MYSQL_ROOT_PASSWORD",
    "PINKDOOHUB_BOOTSTRAP_PASSWORD",
)
APP_IMAGE_PATTERN = re.compile(r"^pinkdoohub-gatea:[0-9a-f]{40}$")
HOST_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
EXPECTED_APP_USER = "10001:10001"
EXPECTED_APP_ENTRYPOINT = ["/usr/local/bin/pinkdoo-entrypoint"]
EXPECTED_APP_COMMAND = [
    "uvicorn",
    "app.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--no-server-header",
]
INITIAL_SCHEMA_COUNT_COMMAND = (
    'MYSQL_PWD="$(cat /run/secrets/mysql_root_password)" '
    "mysql --batch --skip-column-names --host=127.0.0.1 --user=root "
    '--execute="SELECT COUNT(*) FROM information_schema.tables '
    'WHERE table_schema = DATABASE();" "$MYSQL_DATABASE"'
)
LIFECYCLE_COMMANDS = (
    "preflight",
    "infra-up",
    "initial-migrate",
    "app-up",
    "status",
    "safe-stop",
)


class GateAError(RuntimeError):
    """不包含 Secret、Token、密码或连接串的 Gate A 操作错误。"""


def parse_env_file(path: Path) -> dict[str, str]:
    """读取只允许简单 KEY=VALUE 的非 Secret 配置文件。"""

    if not path.is_file():
        raise GateAError("Gate A config file is unavailable")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or "=" not in line:
            raise GateAError(
                f"Gate A config line {line_number} must use plain KEY=VALUE"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise GateAError(f"Gate A config line {line_number} has an invalid key")
        if key in values:
            raise GateAError(f"Gate A config contains duplicate key {key}")
        values[key] = value.strip()
    return values


def validate_config_values(values: Mapping[str, str], *, mode: str) -> None:
    """验证非 Secret 配置的生产语义，不在错误中回显值。"""

    if mode not in MODE_COMPOSE:
        raise GateAError("Gate A mode must be loopback or tls")

    missing = [key for key in REQUIRED_CONFIG_KEYS if not values.get(key)]
    if missing:
        raise GateAError(f"Gate A config is missing required keys: {', '.join(missing)}")

    forbidden = [key for key in FORBIDDEN_CONFIG_KEYS if key in values]
    if forbidden:
        raise GateAError(
            f"Gate A config must not contain Secret keys: {', '.join(forbidden)}"
        )

    if APP_IMAGE_PATTERN.fullmatch(values["GATEA_APP_IMAGE"]) is None:
        raise GateAError("GATEA_APP_IMAGE must use an immutable full Git SHA tag")
    if HOST_PATTERN.fullmatch(values["GATEA_API_HOST"]) is None:
        raise GateAError("GATEA_API_HOST must be a DNS hostname without scheme or path")
    if values["APP_ENV"] != "production" or values["APP_DEBUG"].lower() != "false":
        raise GateAError("Gate A must use production semantics with APP_DEBUG=false")
    if values["DB_ENGINE"] != "mysql":
        raise GateAError("Gate A DB_ENGINE must be mysql")
    if values["DB_HOST"] != "mysql" or values["DB_PORT"] != "3306":
        raise GateAError("Gate A database must use the internal mysql service")
    if values["PRODUCT_IMAGE_UPLOAD_DIR"] != "/data/images":
        raise GateAError("Gate A product images must use the persistent image volume")
    if values["JWT_ALGORITHM"] != "HS256":
        raise GateAError("Gate A JWT_ALGORITHM must be HS256")

    image_url = urlsplit(values["PRODUCT_IMAGE_BASE_URL"])
    if (
        image_url.scheme != "https"
        or image_url.hostname != values["GATEA_API_HOST"]
        or image_url.username is not None
        or image_url.password is not None
        or image_url.query
        or image_url.fragment
        or image_url.path != "/uploads/products"
    ):
        raise GateAError(
            "PRODUCT_IMAGE_BASE_URL must use the approved HTTPS Gate A image path"
        )

    if mode == "loopback":
        raw_port = values.get("GATEA_LOOPBACK_PORT", "18080")
        try:
            port = int(raw_port)
        except ValueError as error:
            raise GateAError("GATEA_LOOPBACK_PORT must be an integer") from error
        if not 1024 <= port <= 65535:
            raise GateAError("GATEA_LOOPBACK_PORT must be an unprivileged TCP port")
    else:
        for key in ("GATEA_LETSENCRYPT_DIR", "GATEA_ACME_CHALLENGE_DIR"):
            if not values.get(key):
                raise GateAError(f"TLS mode requires {key}")


def _validate_root_file(path: Path, expected_mode: int, description: str) -> None:
    """验证 Root 所有普通文件及其精确权限，不读取内容。"""

    try:
        metadata = path.stat()
    except FileNotFoundError as error:
        raise GateAError(f"{description} is unavailable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise GateAError(f"{description} must be a regular file")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise GateAError(f"{description} must be owned by root:root")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise GateAError(f"{description} has unsafe permissions")


def _validate_root_directory(
    path: Path,
    expected_mode: int,
    description: str,
) -> None:
    """验证 Root 所有目录及其精确权限。"""

    try:
        metadata = path.stat()
    except FileNotFoundError as error:
        raise GateAError(f"{description} is unavailable") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise GateAError(f"{description} must be a directory")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise GateAError(f"{description} must be owned by root:root")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise GateAError(f"{description} has unsafe permissions")


def validate_secret_metadata(secret_dir: Path) -> None:
    """只检查 Secret 文件元数据和非空大小，不读取 Secret。"""

    _validate_root_directory(secret_dir, 0o700, "Gate A Secret directory")
    for name in EXPECTED_SECRET_FILES:
        path = secret_dir / name
        _validate_root_file(path, 0o400, f"Gate A Secret file {name}")
        if path.stat().st_size == 0:
            raise GateAError(f"Gate A Secret file {name} is empty")


def compose_command(
    *,
    config_file: Path,
    mode: str,
    arguments: Sequence[str],
    include_bootstrap: bool = False,
    profiles: Sequence[str] = (),
) -> list[str]:
    """构造绑定精确配置与 mode override 的 Compose 命令。"""

    if mode not in MODE_COMPOSE:
        raise GateAError("Gate A mode must be loopback or tls")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(config_file),
        "--file",
        str(BASE_COMPOSE),
        "--file",
        str(MODE_COMPOSE[mode]),
    ]
    if include_bootstrap:
        command.extend(("--file", str(BOOTSTRAP_COMPOSE)))
    for profile in profiles:
        command.extend(("--profile", profile))
    command.extend(arguments)
    return command


def _operation_environment(
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> dict[str, str]:
    return os.environ | dict(values) | {
        "GATEA_CONFIG_FILE": str(config_file),
        "GATEA_SECRET_DIR": str(secret_dir),
    }


def _run_compose(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    arguments: Sequence[str],
    profiles: Sequence[str] = (),
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        compose_command(
            config_file=config_file,
            mode=mode,
            arguments=arguments,
            profiles=profiles,
        ),
        check=check,
        cwd=REPOSITORY_ROOT,
        env=_operation_environment(values, config_file, secret_dir),
        text=True,
        capture_output=capture_output,
    )


def _assert_loopback_port_available(port: int) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", port))
    except OSError as error:
        raise GateAError("Gate A loopback port is already in use") from error
    finally:
        listener.close()


def _validated_inputs(
    *,
    config_file: Path,
    secret_dir: Path,
    mode: str,
    require_available_port: bool,
    require_secrets: bool = True,
) -> dict[str, str]:
    _validate_root_file(config_file, 0o640, "Gate A config file")
    values = parse_env_file(config_file)
    validate_config_values(values, mode=mode)
    if require_secrets:
        validate_secret_metadata(secret_dir)
    if shutil.which("docker") is None:
        raise GateAError("Docker CLI is unavailable")

    if mode == "loopback" and require_available_port:
        _assert_loopback_port_available(
            int(values.get("GATEA_LOOPBACK_PORT", "18080"))
        )
    elif mode == "tls":
        cert_dir = (
            Path(values["GATEA_LETSENCRYPT_DIR"])
            / "live"
            / values["GATEA_API_HOST"]
        )
        _validate_root_file(cert_dir / "fullchain.pem", 0o644, "TLS certificate")
        _validate_root_file(cert_dir / "privkey.pem", 0o600, "TLS private key")
        acme_dir = Path(values["GATEA_ACME_CHALLENGE_DIR"])
        if not acme_dir.is_dir():
            raise GateAError("ACME challenge directory is unavailable")

    _run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=("config", "--quiet"),
    )
    return values


def _require_loopback_write_mode(mode: str) -> None:
    if mode != "loopback":
        raise GateAError(
            "Gate A lifecycle writes are currently restricted to loopback mode"
        )


def _candidate_sha(values: Mapping[str, str]) -> str:
    return values["GATEA_APP_IMAGE"].rsplit(":", 1)[1]


def validate_app_image(values: Mapping[str, str]) -> str:
    """验证本地镜像身份、运行用户、入口和候选 SHA，返回 Image ID。"""

    image = values["GATEA_APP_IMAGE"]
    result = subprocess.run(
        ("docker", "image", "inspect", image, "--format", "{{json .}}"),
        check=True,
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
    )
    try:
        payload = json.loads(result.stdout)
        config = payload["Config"]
        labels = config.get("Labels") or {}
        image_id = payload["Id"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise GateAError("Gate A app image metadata is invalid") from error

    if config.get("User") != EXPECTED_APP_USER:
        raise GateAError("Gate A app image must run as UID/GID 10001")
    if config.get("Entrypoint") != EXPECTED_APP_ENTRYPOINT:
        raise GateAError("Gate A app image entrypoint does not match the contract")
    if config.get("Cmd") != EXPECTED_APP_COMMAND:
        raise GateAError("Gate A app image command does not match the contract")
    if labels.get("org.opencontainers.image.revision") != _candidate_sha(values):
        raise GateAError("Gate A app image revision does not match its Git SHA tag")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise GateAError("Gate A app image ID is invalid")
    return image_id


def _compose_ps(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    services: Sequence[str] = (),
) -> list[dict[str, Any]]:
    result = _run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=("ps", "--all", "--format", "json", *services),
        capture_output=True,
    )
    payload = _parse_compose_ps_output(result.stdout)
    return payload


def _parse_compose_ps_output(output: str) -> list[dict[str, Any]]:
    """兼容 Compose v2 JSON 数组与 v5 newline-delimited JSON。"""

    stripped = output.strip()
    if not stripped:
        payload: Any = []
    else:
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            try:
                payload = [
                    json.loads(line)
                    for line in stripped.splitlines()
                    if line.strip()
                ]
            except json.JSONDecodeError as error:
                raise GateAError("Docker Compose status output is invalid") from error
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise GateAError("Docker Compose status output has an invalid shape")
    return payload


def _ensure_services_healthy(rows: Sequence[Mapping[str, Any]], *services: str) -> None:
    by_service = {str(row.get("Service")): row for row in rows}
    for service in services:
        row = by_service.get(service)
        if row is None:
            raise GateAError(f"Gate A service {service} is unavailable")
        if str(row.get("State", "")).lower() != "running":
            raise GateAError(f"Gate A service {service} is not running")
        if str(row.get("Health", "")).lower() != "healthy":
            raise GateAError(f"Gate A service {service} is not healthy")


def _validate_loopback_publishers(
    rows: Sequence[Mapping[str, Any]],
    expected_port: int,
) -> None:
    """运行时确认只有 Nginx 发布精确的宿主环回端口。"""

    publishers: list[tuple[str, int, int, str]] = []
    for row in rows:
        service = str(row.get("Service") or "")
        raw_publishers = row.get("Publishers") or []
        if not isinstance(raw_publishers, list):
            raise GateAError("Gate A runtime publisher metadata is invalid")
        if service != "nginx" and raw_publishers:
            raise GateAError(f"Gate A service {service} must not publish host ports")
        for publisher in raw_publishers:
            if not isinstance(publisher, dict):
                raise GateAError("Gate A runtime publisher metadata is invalid")
            try:
                publishers.append(
                    (
                        str(publisher.get("URL") or ""),
                        int(publisher["TargetPort"]),
                        int(publisher["PublishedPort"]),
                        str(publisher.get("Protocol") or ""),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise GateAError(
                    "Gate A runtime publisher metadata is invalid"
                ) from error
    if publishers != [("127.0.0.1", 8080, expected_port, "tcp")]:
        raise GateAError("Gate A loopback publisher does not match the port contract")


def _best_effort_stop(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    services: Sequence[str],
) -> None:
    _run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=("stop", "--timeout", "30", *services),
        check=False,
    )


def _migration_marker(record_dir: Path, candidate_sha: str) -> Path:
    return record_dir / f"{candidate_sha}.initial-migration.json"


def _write_migration_record(
    *,
    record_dir: Path,
    candidate_sha: str,
    image_id: str,
) -> None:
    marker = _migration_marker(record_dir, candidate_sha)
    temporary = record_dir / f".{marker.name}.tmp-{os.getpid()}"
    payload = {
        "candidate_sha": candidate_sha,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "image_id": image_id,
        "schema_version": 1,
    }
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, marker)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _require_migration_record(
    *,
    record_dir: Path,
    candidate_sha: str,
    image_id: str,
) -> None:
    marker = _migration_marker(record_dir, candidate_sha)
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise GateAError("Gate A initial migration record is unavailable") from error
    if (
        payload.get("schema_version") != 1
        or payload.get("candidate_sha") != candidate_sha
        or payload.get("image_id") != image_id
        or not payload.get("completed_at")
    ):
        raise GateAError("Gate A initial migration record does not match the candidate")


def preflight(*, config_file: Path, secret_dir: Path, mode: str) -> None:
    """在创建任何 Docker 资源前完成只读 Gate A 预检。"""

    _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=True,
    )
    print(f"Gate A {mode} preflight passed")


def infra_up(
    *,
    config_file: Path,
    secret_dir: Path,
    mode: str,
    wait_timeout: int,
) -> None:
    """仅启动 MySQL/Redis 并等待健康；失败时停止已启动的基础设施。"""

    _require_loopback_write_mode(mode)
    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=True,
    )
    validate_app_image(values)
    try:
        _run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=(
                "up",
                "--detach",
                "--no-build",
                "--wait",
                "--wait-timeout",
                str(wait_timeout),
                "mysql",
                "redis",
            ),
        )
        rows = _compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("mysql", "redis"),
        )
        _ensure_services_healthy(rows, "mysql", "redis")
    except (GateAError, subprocess.CalledProcessError):
        _best_effort_stop(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("redis", "mysql"),
        )
        raise
    print("Gate A infrastructure is healthy")


def initial_migrate(
    *,
    config_file: Path,
    secret_dir: Path,
    record_dir: Path,
    mode: str,
) -> None:
    """只对首次空库执行 Aerich upgrade，并原子记录候选和镜像身份。"""

    _require_loopback_write_mode(mode)
    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=True,
    )
    _validate_root_directory(record_dir, 0o755, "Gate A release record directory")
    image_id = validate_app_image(values)
    candidate_sha = _candidate_sha(values)
    marker = _migration_marker(record_dir, candidate_sha)
    if marker.exists():
        _require_migration_record(
            record_dir=record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
        print("Gate A initial migration was already recorded for this candidate")
        return

    try:
        rows = _compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("mysql", "redis"),
        )
        _ensure_services_healthy(rows, "mysql", "redis")
        count_result = _run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=(
                "exec",
                "--no-tty",
                "mysql",
                "sh",
                "-ec",
                INITIAL_SCHEMA_COUNT_COMMAND,
            ),
            capture_output=True,
        )
        table_count = count_result.stdout.strip()
        if table_count != "0":
            raise GateAError(
                "Gate A initial migration requires an empty application database"
            )

        _run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            profiles=("operations",),
            arguments=("run", "--rm", "--no-deps", "migrate"),
        )
        _write_migration_record(
            record_dir=record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
    except (GateAError, subprocess.CalledProcessError):
        _best_effort_stop(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("redis", "mysql"),
        )
        raise
    print("Gate A initial migration completed and was recorded")


def app_up(
    *,
    config_file: Path,
    secret_dir: Path,
    record_dir: Path,
    mode: str,
    wait_timeout: int,
) -> None:
    """迁移记录匹配后启动 App/Nginx，并等待两者健康。"""

    _require_loopback_write_mode(mode)
    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=True,
    )
    _validate_root_directory(record_dir, 0o755, "Gate A release record directory")
    image_id = validate_app_image(values)
    _require_migration_record(
        record_dir=record_dir,
        candidate_sha=_candidate_sha(values),
        image_id=image_id,
    )
    rows = _compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("mysql", "redis"),
    )
    _ensure_services_healthy(rows, "mysql", "redis")

    try:
        _run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=(
                "up",
                "--detach",
                "--no-build",
                "--wait",
                "--wait-timeout",
                str(wait_timeout),
                "app",
                "nginx",
            ),
        )
        rows = _compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("app", "nginx"),
        )
        _ensure_services_healthy(rows, "app", "nginx")
        _validate_loopback_publishers(
            rows,
            int(values.get("GATEA_LOOPBACK_PORT", "18080")),
        )
    except (GateAError, subprocess.CalledProcessError):
        _best_effort_stop(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("nginx", "app", "image-init"),
        )
        raise
    print("Gate A application and loopback edge are healthy")


def status(
    *,
    config_file: Path,
    secret_dir: Path,
    record_dir: Path,
    mode: str,
) -> None:
    """输出不含 Secret、环境值和挂载详情的运行状态。"""

    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=False,
    )
    rows = _compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
    )
    summary = [
        {
            "health": str(row.get("Health") or ""),
            "service": str(row.get("Service") or ""),
            "state": str(row.get("State") or ""),
        }
        for row in rows
    ]
    marker = _migration_marker(record_dir, _candidate_sha(values))
    print(
        json.dumps(
            {
                "candidate_sha": _candidate_sha(values),
                "initial_migration_recorded": marker.is_file(),
                "mode": mode,
                "services": sorted(summary, key=lambda item: item["service"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def safe_stop(*, config_file: Path, secret_dir: Path, mode: str) -> None:
    """停止 Gate A 服务但保留容器、命名卷、迁移记录和 Secret。"""

    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=False,
        require_secrets=False,
    )
    _run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=(
            "stop",
            "--timeout",
            "30",
            "nginx",
            "app",
            "image-init",
            "redis",
            "mysql",
        ),
    )
    print("Gate A services stopped; named volumes were preserved")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run guarded pinkdooHub Gate A deployment operations",
    )
    parser.add_argument("command", choices=LIFECYCLE_COMMANDS)
    parser.add_argument("--mode", choices=tuple(MODE_COMPOSE), required=True)
    parser.add_argument(
        "--config-file",
        type=Path,
        default=DEFAULT_CONFIG_FILE,
    )
    parser.add_argument(
        "--secret-dir",
        type=Path,
        default=DEFAULT_SECRET_DIR,
    )
    parser.add_argument(
        "--record-dir",
        type=Path,
        default=DEFAULT_RECORD_DIR,
    )
    parser.add_argument("--wait-timeout", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 30 <= args.wait_timeout <= 600:
        print(
            "Gate A operation failed: --wait-timeout must be between 30 and 600",
            file=sys.stderr,
        )
        return 1
    common = {
        "config_file": args.config_file,
        "secret_dir": args.secret_dir,
        "mode": args.mode,
    }
    try:
        if args.command == "preflight":
            preflight(**common)
        elif args.command == "infra-up":
            infra_up(**common, wait_timeout=args.wait_timeout)
        elif args.command == "initial-migrate":
            initial_migrate(**common, record_dir=args.record_dir)
        elif args.command == "app-up":
            app_up(
                **common,
                record_dir=args.record_dir,
                wait_timeout=args.wait_timeout,
            )
        elif args.command == "status":
            status(**common, record_dir=args.record_dir)
        else:
            safe_stop(**common)
    except (GateAError, subprocess.CalledProcessError) as error:
        print(f"Gate A {args.command} failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
