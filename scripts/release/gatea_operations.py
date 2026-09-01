#!/usr/bin/env python3
"""Gate A 持久部署的只读预检与 Compose 命令边界。

本模块不生成、读取或输出 Secret 值。当前只提供部署前预检；启动、迁移、
Bootstrap、备份和恢复仍需在对应步骤经过明确 Review 后执行。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
from typing import Mapping, Sequence
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


class GateAError(RuntimeError):
    """不包含 Secret、Token、密码或连接串的 Gate A 预检错误。"""


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


def validate_secret_metadata(secret_dir: Path) -> None:
    """只检查 Secret 文件元数据和非空大小，不读取 Secret。"""

    try:
        metadata = secret_dir.stat()
    except FileNotFoundError as error:
        raise GateAError("Gate A Secret directory is unavailable") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise GateAError("Gate A Secret path must be a directory")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise GateAError("Gate A Secret directory must be owned by root:root")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise GateAError("Gate A Secret directory must use mode 0700")

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


def _assert_loopback_port_available(port: int) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", port))
    except OSError as error:
        raise GateAError("Gate A loopback port is already in use") from error
    finally:
        listener.close()


def preflight(*, config_file: Path, secret_dir: Path, mode: str) -> None:
    """在创建任何 Docker 资源前完成只读 Gate A 预检。"""

    _validate_root_file(config_file, 0o640, "Gate A config file")
    values = parse_env_file(config_file)
    validate_config_values(values, mode=mode)
    validate_secret_metadata(secret_dir)
    if shutil.which("docker") is None:
        raise GateAError("Docker CLI is unavailable")

    if mode == "loopback":
        _assert_loopback_port_available(
            int(values.get("GATEA_LOOPBACK_PORT", "18080"))
        )
    else:
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

    environment = os.environ | values | {
        "GATEA_CONFIG_FILE": str(config_file),
        "GATEA_SECRET_DIR": str(secret_dir),
    }
    subprocess.run(
        compose_command(
            config_file=config_file,
            mode=mode,
            arguments=("config", "--quiet"),
        ),
        check=True,
        cwd=REPOSITORY_ROOT,
        env=environment,
    )
    print(f"Gate A {mode} preflight passed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run read-only pinkdooHub Gate A deployment checks",
    )
    parser.add_argument("command", choices=("preflight",))
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        preflight(
            config_file=args.config_file,
            secret_dir=args.secret_dir,
            mode=args.mode,
        )
    except (GateAError, subprocess.CalledProcessError) as error:
        print(f"Gate A preflight failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
