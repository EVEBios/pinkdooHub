#!/usr/bin/env python3
"""Gate A 权威数据备份与隔离恢复验证。

MySQL 与商品图片是备份资产；Redis 只保存 refresh-token 会话，灾难恢复时使用
空实例使既有会话失效，避免恢复旧快照重新激活已撤销 Token。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, BinaryIO, Mapping, Sequence

from scripts.release import gatea_operations as gatea


RESTORE_COMPOSE = gatea.GATEA_ROOT / "compose.restore.yml"
DEFAULT_BACKUP_ROOT = Path("/srv/pinkdoohub/gatea/backups")
DEFAULT_BACKUP_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/backups")
DEFAULT_RESTORE_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/restores")
BACKUP_ID_PATTERN = re.compile(r"^[0-9]{8}t[0-9]{6}z$")
RESTORE_PROJECT_PREFIX = "pinkdoohub-gatea-restore-"
MYSQL_DUMP_COMMAND = (
    'MYSQL_PWD="$(cat /run/secrets/mysql_root_password)" '
    "exec mysqldump --host=127.0.0.1 --user=root "
    "--single-transaction --routines --triggers --hex-blob "
    "--set-gtid-purged=OFF --no-tablespaces --default-character-set=utf8mb4 "
    '"$MYSQL_DATABASE"'
)
MYSQL_RESTORE_COMMAND = (
    'MYSQL_PWD="$(cat /run/secrets/mysql_root_password)" '
    'exec mysql --host=127.0.0.1 --user=root "$MYSQL_DATABASE"'
)
MYSQL_SNAPSHOT_COMMAND = """MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"
export MYSQL_PWD
mysql --batch --skip-column-names --host=127.0.0.1 --user=root "$MYSQL_DATABASE" <<'SQL'
SELECT JSON_OBJECT(
  'aerich_versions', COALESCE((SELECT GROUP_CONCAT(version ORDER BY id SEPARATOR ',') FROM aerich), ''),
  'tables', (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()),
  'columns', (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()),
  'statistics', (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE()),
  'constraints', (SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema = DATABASE()),
  'users', (SELECT COUNT(*) FROM users),
  'products', (SELECT COUNT(*) FROM products),
  'experience_options', (SELECT COUNT(*) FROM experience_options),
  'product_images', (SELECT COUNT(*) FROM product_images),
  'product_kits', (SELECT COUNT(*) FROM product_kits),
  'kit_stock', (SELECT COALESCE(SUM(stock), 0) FROM product_kits),
  'orders', (SELECT COUNT(*) FROM orders),
  'order_items', (SELECT COUNT(*) FROM order_items),
  'order_total', (SELECT CAST(COALESCE(SUM(total_amount), 0) AS CHAR) FROM orders),
  'inventory_transactions', (SELECT COUNT(*) FROM inventory_transactions),
  'inventory_change', (SELECT COALESCE(SUM(change_quantity), 0) FROM inventory_transactions),
  'audit_logs', (SELECT COUNT(*) FROM audit_logs)
);
SQL"""
IMAGE_MANIFEST_COMMAND = (
    "find /data/images -type f -exec sha256sum {} + | "
    "sed 's# /data/images/# #' | sort"
)
RESTORED_IMAGE_MANIFEST_COMMAND = (
    "find /restore -type f -exec sha256sum {} + | "
    "sed 's# /restore/# #' | sort"
)


def _backup_id(value: str) -> str:
    if BACKUP_ID_PATTERN.fullmatch(value) is None:
        raise gatea.GateAError("Gate A backup ID must use YYYYMMDDtHHMMSSz")
    return value


def restore_project(backup_id: str) -> str:
    return RESTORE_PROJECT_PREFIX + _backup_id(backup_id)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any], mode: int) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            mode,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _exclusive_binary(path: Path) -> BinaryIO:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "wb")


def _source_command(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    arguments: Sequence[str],
) -> tuple[list[str], dict[str, str]]:
    return (
        gatea.compose_command(
            config_file=config_file,
            mode=mode,
            arguments=arguments,
        ),
        gatea._operation_environment(values, config_file, secret_dir),
    )


def restore_command(
    *,
    project: str,
    config_file: Path,
    arguments: Sequence[str],
    operations_profile: bool = False,
) -> list[str]:
    command = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(config_file),
        "--file",
        str(RESTORE_COMPOSE),
    ]
    if operations_profile:
        command.extend(("--profile", "operations"))
    command.extend(arguments)
    return command


def _restore_environment(
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    project: str,
) -> dict[str, str]:
    return gatea._operation_environment(values, config_file, secret_dir) | {
        "GATEA_RESTORE_PROJECT": project,
    }


def _run_restore(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    project: str,
    arguments: Sequence[str],
    operations_profile: bool = False,
    capture_output: bool = False,
    check: bool = True,
    stdin: BinaryIO | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        restore_command(
            project=project,
            config_file=config_file,
            arguments=arguments,
            operations_profile=operations_profile,
        ),
        check=check,
        cwd=gatea.REPOSITORY_ROOT,
        env=_restore_environment(values, config_file, secret_dir, project),
        text=stdin is None,
        capture_output=capture_output,
        stdin=stdin,
    )


def _parse_snapshot(output: str) -> dict[str, Any]:
    try:
        payload = json.loads(output.strip())
    except json.JSONDecodeError as error:
        raise gatea.GateAError("Gate A database snapshot output is invalid") from error
    if not isinstance(payload, dict) or not payload:
        raise gatea.GateAError("Gate A database snapshot output has an invalid shape")
    return payload


def _source_snapshot(
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
) -> dict[str, Any]:
    result = gatea._run_compose(
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
            MYSQL_SNAPSHOT_COMMAND,
        ),
        capture_output=True,
    )
    return _parse_snapshot(result.stdout)


def _source_image_manifest(
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
) -> list[str]:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=(
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "/bin/sh",
            "image-init",
            "-ec",
            IMAGE_MANIFEST_COMMAND,
        ),
        capture_output=True,
    )
    return result.stdout.splitlines()


def _stream_source_artifact(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    arguments: Sequence[str],
    path: Path,
) -> None:
    command, environment = _source_command(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=arguments,
    )
    with _exclusive_binary(path) as stream:
        subprocess.run(
            command,
            check=True,
            cwd=gatea.REPOSITORY_ROOT,
            env=environment,
            stdout=stream,
        )
    if path.stat().st_size == 0:
        raise gatea.GateAError("Gate A backup artifact is empty")


def _backup_paths(backup_root: Path, backup_id: str) -> tuple[Path, Path]:
    return (
        backup_root / "mysql" / f"{backup_id}.sql",
        backup_root / "images" / f"{backup_id}.tar",
    )


def _validate_backup_directories(
    *,
    values: Mapping[str, str],
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path | None = None,
) -> None:
    if values.get("GATEA_BACKUP_ROOT") != str(backup_root):
        raise gatea.GateAError("Gate A backup root does not match protected config")
    gatea._validate_root_directory(backup_root, 0o755, "Gate A backup root")
    gatea._validate_root_directory(
        backup_root / "mysql", 0o755, "Gate A MySQL backup directory"
    )
    gatea._validate_root_directory(
        backup_root / "images", 0o755, "Gate A image backup directory"
    )
    gatea._validate_root_directory(
        backup_record_dir, 0o755, "Gate A backup record directory"
    )
    if restore_record_dir is not None:
        gatea._validate_root_directory(
            restore_record_dir, 0o755, "Gate A restore record directory"
        )


def create_backup(
    *,
    backup_id: str,
    config_file: Path,
    secret_dir: Path,
    mode: str,
    backup_root: Path,
    backup_record_dir: Path,
    release_record_dir: Path,
    wait_timeout: int,
) -> None:
    """短暂停止 edge/App，生成一致 MySQL/图片备份后恢复服务。"""

    backup_id = _backup_id(backup_id)
    gatea._require_loopback_write_mode(mode)
    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=False,
    )
    _validate_backup_directories(
        values=values,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
    )
    image_id = gatea.validate_app_image(values)
    gatea._require_migration_record(
        record_dir=release_record_dir,
        candidate_sha=gatea._candidate_sha(values),
        image_id=image_id,
    )
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("mysql", "redis", "app", "nginx"),
    )
    gatea._ensure_services_healthy(rows, "mysql", "redis", "app", "nginx")

    database_path, image_path = _backup_paths(backup_root, backup_id)
    record_path = backup_record_dir / f"{backup_id}.json"
    for path in (database_path, image_path, record_path):
        if path.exists():
            raise gatea.GateAError("Gate A backup ID already exists")

    started_at = datetime.now(timezone.utc).isoformat()
    backup_error: BaseException | None = None
    snapshot: dict[str, Any] = {}
    image_manifest: list[str] = []
    try:
        gatea._run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=("stop", "--timeout", "30", "nginx", "app"),
        )
        snapshot = _source_snapshot(values, config_file, secret_dir, mode)
        image_manifest = _source_image_manifest(
            values, config_file, secret_dir, mode
        )
        _stream_source_artifact(
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
                MYSQL_DUMP_COMMAND,
            ),
            path=database_path,
        )
        _stream_source_artifact(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "tar",
                "image-init",
                "-C",
                "/data/images",
                "-cf",
                "-",
                ".",
            ),
            path=image_path,
        )
    except BaseException as error:
        backup_error = error

    restart_error: BaseException | None = None
    try:
        gatea.app_up(
            config_file=config_file,
            secret_dir=secret_dir,
            record_dir=release_record_dir,
            mode=mode,
            wait_timeout=wait_timeout,
        )
    except BaseException as error:
        restart_error = error

    if backup_error is not None or restart_error is not None:
        database_path.unlink(missing_ok=True)
        image_path.unlink(missing_ok=True)
        if restart_error is not None:
            raise gatea.GateAError(
                "Gate A backup did not restore application availability"
            ) from restart_error
        raise gatea.GateAError("Gate A backup creation failed") from backup_error

    payload = {
        "schema_version": 1,
        "backup_id": backup_id,
        "candidate_sha": gatea._candidate_sha(values),
        "image_id": image_id,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "consistency": "nginx-and-app-stopped",
        "database_snapshot": snapshot,
        "image_manifest": image_manifest,
        "artifacts": {
            "mysql": {
                "path": str(database_path),
                "bytes": database_path.stat().st_size,
                "sha256": _sha256(database_path),
            },
            "images": {
                "path": str(image_path),
                "bytes": image_path.stat().st_size,
                "sha256": _sha256(image_path),
            },
        },
        "redis_recovery_policy": "start-empty-and-invalidate-refresh-sessions",
        "application_restarted": True,
        "passed": True,
    }
    try:
        _write_json_atomic(record_path, payload, 0o644)
    except BaseException:
        database_path.unlink(missing_ok=True)
        image_path.unlink(missing_ok=True)
        raise
    print(f"Gate A backup {backup_id} completed and application health was restored")


def _load_backup_record(
    *,
    backup_id: str,
    backup_root: Path,
    backup_record_dir: Path,
) -> tuple[dict[str, Any], Path, Path]:
    record_path = backup_record_dir / f"{backup_id}.json"
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        artifacts = payload["artifacts"]
        database_path, image_path = _backup_paths(backup_root, backup_id)
        expected = {
            "mysql": database_path,
            "images": image_path,
        }
        if (
            payload.get("schema_version") != 1
            or payload.get("backup_id") != backup_id
            or payload.get("passed") is not True
        ):
            raise ValueError
        for name, path in expected.items():
            metadata = artifacts[name]
            if metadata.get("path") != str(path):
                raise ValueError
            if path.stat().st_size != int(metadata["bytes"]):
                raise ValueError
            if _sha256(path) != metadata["sha256"]:
                raise ValueError
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise gatea.GateAError("Gate A verified backup record is invalid") from error
    return payload, database_path, image_path


def _restore_project_absent(project: str) -> None:
    result = subprocess.run(
        (
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ),
        check=True,
        text=True,
        capture_output=True,
    )
    if result.stdout.strip():
        raise gatea.GateAError("Gate A restore project already exists")
    for suffix in ("mysql-data", "product-images"):
        volume = subprocess.run(
            ("docker", "volume", "inspect", f"{project}-{suffix}"),
            check=False,
            text=True,
            capture_output=True,
        )
        if volume.returncode == 0:
            raise gatea.GateAError("Gate A restore volume already exists")
    network = subprocess.run(
        ("docker", "network", "inspect", f"{project}-internal"),
        check=False,
        text=True,
        capture_output=True,
    )
    if network.returncode == 0:
        raise gatea.GateAError("Gate A restore network already exists")


def _restore_snapshot(
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    project: str,
) -> dict[str, Any]:
    result = _run_restore(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        project=project,
        arguments=(
            "exec",
            "--no-tty",
            "mysql-restore",
            "sh",
            "-ec",
            MYSQL_SNAPSHOT_COMMAND,
        ),
        capture_output=True,
    )
    return _parse_snapshot(result.stdout)


def _restored_image_manifest(
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    project: str,
) -> list[str]:
    result = _run_restore(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        project=project,
        operations_profile=True,
        arguments=(
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "/bin/sh",
            "image-restore",
            "-ec",
            RESTORED_IMAGE_MANIFEST_COMMAND,
        ),
        capture_output=True,
    )
    return result.stdout.splitlines()


def _restore_cleanup_verified(project: str) -> None:
    _restore_project_absent(project)


def verify_restore(
    *,
    backup_id: str,
    confirm_project: str,
    config_file: Path,
    secret_dir: Path,
    mode: str,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
    wait_timeout: int,
) -> None:
    """恢复到隔离 project，比较快照并在所有退出路径删除临时资源。"""

    backup_id = _backup_id(backup_id)
    project = restore_project(backup_id)
    if confirm_project != project:
        raise gatea.GateAError("Gate A restore project confirmation does not match")
    gatea._require_loopback_write_mode(mode)
    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=False,
    )
    _validate_backup_directories(
        values=values,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
    )
    payload, database_path, image_path = _load_backup_record(
        backup_id=backup_id,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
    )
    if payload.get("candidate_sha") != gatea._candidate_sha(values):
        raise gatea.GateAError("Gate A backup candidate does not match runtime")
    record_path = restore_record_dir / f"{backup_id}.json"
    if record_path.exists():
        raise gatea.GateAError("Gate A restore record already exists")

    _restore_project_absent(project)
    _run_restore(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        project=project,
        arguments=("config", "--quiet"),
    )
    started_at = datetime.now(timezone.utc).isoformat()
    restored_snapshot: dict[str, Any] = {}
    restored_images: list[str] = []
    redis_size = "unknown"
    passed = False
    operation_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    try:
        _run_restore(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            project=project,
            arguments=(
                "up",
                "--detach",
                "--wait",
                "--wait-timeout",
                str(wait_timeout),
                "mysql-restore",
                "redis",
            ),
        )
        with database_path.open("rb") as stream:
            _run_restore(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                project=project,
                arguments=(
                    "exec",
                    "--no-tty",
                    "mysql-restore",
                    "sh",
                    "-ec",
                    MYSQL_RESTORE_COMMAND,
                ),
                stdin=stream,
            )
        with image_path.open("rb") as stream:
            _run_restore(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                project=project,
                operations_profile=True,
                arguments=(
                    "run",
                    "--rm",
                    "--no-deps",
                    "--entrypoint",
                    "tar",
                    "image-restore",
                    "-C",
                    "/restore",
                    "-xf",
                    "-",
                ),
                stdin=stream,
            )
        _run_restore(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            project=project,
            arguments=(
                "up",
                "--detach",
                "--wait",
                "--wait-timeout",
                str(wait_timeout),
                "image-init",
                "restore-app",
            ),
        )
        restored_snapshot = _restore_snapshot(
            values, config_file, secret_dir, project
        )
        restored_images = _restored_image_manifest(
            values, config_file, secret_dir, project
        )
        redis_result = _run_restore(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            project=project,
            arguments=(
                "exec",
                "--no-tty",
                "redis",
                "/bin/sh",
                "-ec",
                'REDISCLI_AUTH="$(cat /run/secrets/redis_password)" redis-cli DBSIZE',
            ),
            capture_output=True,
        )
        redis_size = redis_result.stdout.strip()
        _run_restore(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            project=project,
            arguments=(
                "exec",
                "--no-tty",
                "restore-app",
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen(" 
                "'http://127.0.0.1:8000/api/v1/health/ready', timeout=3)",
            ),
        )
        if restored_snapshot != payload["database_snapshot"]:
            raise gatea.GateAError("Gate A restored database snapshot does not match")
        if restored_images != payload["image_manifest"]:
            raise gatea.GateAError("Gate A restored image manifest does not match")
        if redis_size != "0":
            raise gatea.GateAError("Gate A restore Redis must start empty")
        rows_result = _run_restore(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            project=project,
            arguments=("ps", "--all", "--format", "json"),
            capture_output=True,
        )
        for row in gatea._parse_compose_ps_output(rows_result.stdout):
            for publisher in row.get("Publishers") or []:
                if int(publisher.get("PublishedPort") or 0) != 0:
                    raise gatea.GateAError(
                        "Gate A restore project must not publish host ports"
                    )
        passed = True
    except BaseException as error:
        operation_error = error
    finally:
        try:
            _run_restore(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                project=project,
                operations_profile=True,
                arguments=("down", "--volumes", "--remove-orphans"),
                check=False,
            )
            _restore_cleanup_verified(project)
        except BaseException as error:
            cleanup_error = error

    if operation_error is not None or cleanup_error is not None or not passed:
        if cleanup_error is not None:
            raise gatea.GateAError(
                "Gate A isolated restore cleanup could not be verified"
            ) from cleanup_error
        raise gatea.GateAError("Gate A isolated restore verification failed") from operation_error

    _write_json_atomic(
        record_path,
        {
            "schema_version": 1,
            "backup_id": backup_id,
            "restore_project": project,
            "candidate_sha": payload["candidate_sha"],
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "database_matches": True,
            "images_match": True,
            "restore_app_ready": True,
            "redis_started_empty": True,
            "refresh_sessions_invalidated": True,
            "host_ports_published": False,
            "temporary_resources_removed": True,
            "passed": True,
        },
        0o644,
    )
    print(f"Gate A backup {backup_id} independent restore verification passed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run guarded Gate A backup and isolated restore verification",
    )
    parser.add_argument("command", choices=("backup", "restore-verify"))
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--confirm-project")
    parser.add_argument("--mode", choices=tuple(gatea.MODE_COMPOSE), required=True)
    parser.add_argument("--config-file", type=Path, default=gatea.DEFAULT_CONFIG_FILE)
    parser.add_argument("--secret-dir", type=Path, default=gatea.DEFAULT_SECRET_DIR)
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    parser.add_argument(
        "--backup-record-dir", type=Path, default=DEFAULT_BACKUP_RECORD_DIR
    )
    parser.add_argument(
        "--restore-record-dir", type=Path, default=DEFAULT_RESTORE_RECORD_DIR
    )
    parser.add_argument(
        "--release-record-dir", type=Path, default=gatea.DEFAULT_RECORD_DIR
    )
    parser.add_argument("--wait-timeout", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 30 <= args.wait_timeout <= 600:
        print(
            "Gate A backup operation failed: --wait-timeout must be between 30 and 600",
            file=sys.stderr,
        )
        return 1
    try:
        if args.command == "backup":
            if args.confirm_project is not None:
                raise gatea.GateAError("Gate A backup does not accept restore confirmation")
            create_backup(
                backup_id=args.backup_id,
                config_file=args.config_file,
                secret_dir=args.secret_dir,
                mode=args.mode,
                backup_root=args.backup_root,
                backup_record_dir=args.backup_record_dir,
                release_record_dir=args.release_record_dir,
                wait_timeout=args.wait_timeout,
            )
        else:
            if args.confirm_project is None:
                raise gatea.GateAError("Gate A restore requires exact project confirmation")
            verify_restore(
                backup_id=args.backup_id,
                confirm_project=args.confirm_project,
                config_file=args.config_file,
                secret_dir=args.secret_dir,
                mode=args.mode,
                backup_root=args.backup_root,
                backup_record_dir=args.backup_record_dir,
                restore_record_dir=args.restore_record_dir,
                wait_timeout=args.wait_timeout,
            )
    except (gatea.GateAError, subprocess.CalledProcessError) as error:
        print(f"Gate A {args.command} failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
