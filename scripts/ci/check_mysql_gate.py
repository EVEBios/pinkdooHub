#!/usr/bin/env python3
"""验证、记录并清理 Phase 9.2.4 隔离 MySQL 发布门槛。"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from typing import Mapping, Sequence


EXPECTED_DATABASE = "pinkdoohub_inventory_4311_ci"
EXPECTED_MIGRATIONS = [
    "0_20260810101218_init.py",
    "1_20260813130455_add_order_tables.py",
    "2_20260814104655_add_inventory_transactions.py",
    "3_20260902125032_phase95_external_identity.py",
]
MYSQL_VERSION_PREFIX = "8.0.46"
CONTAINER_ID_PATTERN = re.compile(r"^[0-9a-f]{12,64}$")


class GateError(RuntimeError):
    """不包含凭据或连接串的 CI 门槛错误。"""


@dataclass(frozen=True)
class GateConfig:
    """Aerich 与 pytest 共用的唯一隔离 MySQL 目标。"""

    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)

    def safe_target(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
        }


def _required(environment: Mapping[str, str], key: str) -> str:
    value = environment.get(key, "")
    if not value:
        raise GateError(f"{key} is required")
    return value


def load_config(environment: Mapping[str, str]) -> GateConfig:
    """拒绝默认端口、远端地址以及 Aerich/pytest 目标漂移。"""

    if environment.get("APP_ENV") != "testing":
        raise GateError("APP_ENV must be testing")
    if environment.get("DB_ENGINE") != "mysql":
        raise GateError("DB_ENGINE must be mysql")
    if environment.get("INVENTORY_MYSQL_TEST_ENABLED") != "1":
        raise GateError("the isolated MySQL gate must be explicitly enabled")

    host = _required(environment, "INVENTORY_MYSQL_TEST_HOST")
    try:
        port = int(_required(environment, "INVENTORY_MYSQL_TEST_PORT"))
    except ValueError as error:
        raise GateError("MySQL gate port must be an integer") from error
    database = _required(environment, "INVENTORY_MYSQL_TEST_DB")
    user = _required(environment, "INVENTORY_MYSQL_TEST_USER")
    password = _required(environment, "INVENTORY_MYSQL_TEST_PASSWORD")

    if host != "127.0.0.1":
        raise GateError("MySQL gate only permits 127.0.0.1")
    if port == 3306 or not 1024 <= port <= 65535:
        raise GateError("MySQL gate refuses the default or invalid port")
    if database != EXPECTED_DATABASE:
        raise GateError("MySQL gate requires the frozen disposable schema")
    if user != "root":
        raise GateError("MySQL gate requires its disposable container user")

    mirrored_values = {
        "DB_HOST": host,
        "DB_PORT": str(port),
        "DB_NAME": database,
        "DB_USER": user,
        "DB_PASSWORD": password,
    }
    for key, expected_value in mirrored_values.items():
        if environment.get(key) != expected_value:
            raise GateError(f"{key} must match the pytest MySQL target")

    return GateConfig(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
    )


def write_report(path: Path, document: Mapping[str, object]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def preflight(config: GateConfig, report_path: Path) -> None:
    write_report(
        report_path,
        {
            "schema_version": 1,
            "status": "preflight-passed",
            **config.safe_target(),
        },
    )
    print(
        "MySQL gate preflight passed: "
        f"host={config.host} port={config.port} database={config.database}"
    )


async def _read_snapshot(config: GateConfig) -> tuple[str, list[str]]:
    import asyncmy

    connection = await asyncmy.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        connect_timeout=5,
        autocommit=True,
    )
    try:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT VERSION()")
            version_row = await cursor.fetchone()
            await cursor.execute("SELECT version FROM aerich ORDER BY id")
            migration_rows = await cursor.fetchall()
    finally:
        await connection.ensure_closed()

    if not version_row:
        raise GateError("MySQL version query returned no rows")
    mysql_version = str(version_row[0])
    migrations = [str(row[0]) for row in migration_rows]
    return mysql_version, migrations


def snapshot(config: GateConfig, report_path: Path) -> None:
    mysql_version, migrations = asyncio.run(_read_snapshot(config))
    if not mysql_version.startswith(MYSQL_VERSION_PREFIX):
        raise GateError("MySQL server is not the frozen 8.0.46 release-gate version")
    if migrations != EXPECTED_MIGRATIONS:
        raise GateError("Aerich did not apply the complete reviewed migration chain")

    write_report(
        report_path,
        {
            "schema_version": 1,
            "status": "release-gate-ready",
            **config.safe_target(),
            "mysql_version": mysql_version,
            "aerich_versions": migrations,
            "git_sha": os.getenv("GITHUB_SHA", "local-uncommitted"),
            "workflow_run_id": os.getenv("GITHUB_RUN_ID", "local"),
        },
    )
    print(
        "MySQL release gate snapshot passed: "
        f"version={mysql_version} migrations={len(migrations)}"
    )


def _run_command(
    command: Sequence[str],
    *,
    environment: Mapping[str, str] | None = None,
) -> bool:
    try:
        result = subprocess.run(
            command,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _port_is_closed(host: str, port: int) -> bool:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.5)
            if connection.connect_ex((host, port)) != 0:
                return True
        time.sleep(0.25)
    return False


def cleanup(config: GateConfig, report_path: Path) -> bool:
    """删除专用 Schema、停止 service container，并复核端口已经释放。"""

    container_id = _required(os.environ, "MYSQL_SERVICE_CONTAINER_ID")
    if not CONTAINER_ID_PATTERN.fullmatch(container_id):
        raise GateError("MYSQL_SERVICE_CONTAINER_ID is invalid")
    docker = shutil.which("docker")
    if docker is None:
        raise GateError("docker CLI is required for MySQL service cleanup")

    docker_environment = os.environ.copy()
    docker_environment["MYSQL_PWD"] = config.password
    schema_dropped = _run_command(
        [
            docker,
            "exec",
            "--env",
            "MYSQL_PWD",
            container_id,
            "mysql",
            "--protocol=socket",
            f"--user={config.user}",
            "--execute",
            f"DROP DATABASE `{config.database}`",
        ],
        environment=docker_environment,
    )
    container_stopped = _run_command(
        [docker, "stop", "--time", "10", container_id],
    )

    try:
        inspect_result = subprocess.run(
            [docker, "inspect", "--format", "{{.State.Running}}", container_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=10,
        )
        container_inspected = inspect_result.returncode == 0
        container_running = (
            container_inspected
            and inspect_result.stdout.strip().lower() == "true"
        )
    except (OSError, subprocess.TimeoutExpired):
        container_inspected = False
        container_running = True
    port_closed = _port_is_closed(config.host, config.port)
    passed = (
        schema_dropped
        and container_stopped
        and container_inspected
        and not container_running
        and port_closed
    )
    write_report(
        report_path,
        {
            "schema_version": 1,
            "status": "cleanup-passed" if passed else "cleanup-failed",
            **config.safe_target(),
            "schema_dropped": schema_dropped,
            "container_stopped": container_stopped,
            "container_inspected": container_inspected,
            "container_running": container_running,
            "port_closed": port_closed,
        },
    )
    print(
        "MySQL release gate cleanup: "
        f"schema_dropped={schema_dropped} container_stopped={container_stopped} "
        f"container_inspected={container_inspected} "
        f"container_running={container_running} port_closed={port_closed}"
    )
    return passed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "snapshot", "cleanup"))
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        config = load_config(os.environ)
        if arguments.command == "preflight":
            preflight(config, arguments.report)
            return 0
        if arguments.command == "snapshot":
            snapshot(config, arguments.report)
            return 0
        return 0 if cleanup(config, arguments.report) else 1
    except GateError as error:
        print(f"MySQL release gate failed: {error}", file=sys.stderr)
    except Exception as error:
        print(
            f"MySQL release gate failed safely: {type(error).__name__}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
