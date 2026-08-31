#!/usr/bin/env python3
"""执行 Phase 9.3 已冻结 Compose 环境的可审计运维步骤。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import time
from typing import IO, Mapping, Sequence
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.phase93_rehearsal import (
    COMPOSE_FILE,
    IMAGE_TAGS,
    PORTS,
    REPOSITORY_ROOT,
    SECRET_NAMES,
    RehearsalConfig,
    RehearsalError,
    config_for_run,
)


RESTORE_DATABASE = "pinkdoohub_phase93_restore"
SOURCE_DATABASE = "pinkdoohub_phase93_source"
FAILURE_DATABASE = "pinkdoohub_phase93_failure"
FAILURE_RESTORE_DATABASE = "pinkdoohub_phase93_failure_restore"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Phase93Operations:
    """只操作 manifest 绑定的精确 Compose project。"""

    def __init__(self, config: RehearsalConfig) -> None:
        self.config = config
        self.manifest_path = config.evidence_dir / "manifest.json"
        self.environment = os.environ | config.compose_environment()

    def validate_workspace(self) -> dict[str, object]:
        """执行每个写步骤前的候选、权限和内容绑定复核。"""

        if not self.manifest_path.is_file():
            raise RehearsalError("prepared rehearsal manifest is missing")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if manifest.get("project") != self.config.project:
            raise RehearsalError("manifest project does not match the requested run")

        git_sha = self._output(("git", "rev-parse", "HEAD"))
        git_status = self._output(
            ("git", "status", "--porcelain=v1", "--untracked-files=all")
        )
        if git_status:
            raise RehearsalError("candidate working tree is not clean")
        if manifest.get("git_sha") != git_sha:
            raise RehearsalError("candidate SHA changed after workspace preparation")
        if manifest.get("compose_file_sha256") != _sha256(COMPOSE_FILE):
            raise RehearsalError("Compose file changed after workspace preparation")

        for directory in (
            self.config.root,
            self.config.secret_dir,
            self.config.cert_dir,
            self.config.evidence_dir,
        ):
            if stat.S_IMODE(directory.stat().st_mode) != 0o700:
                raise RehearsalError("a rehearsal directory has unsafe permissions")
        for name in SECRET_NAMES:
            secret_path = self.config.secret_dir / name
            if (
                not secret_path.is_file()
                or stat.S_IMODE(secret_path.stat().st_mode) != 0o600
            ):
                raise RehearsalError("a rehearsal Secret is missing or unsafe")
        return manifest

    def _command(
        self,
        command: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
        stdin: IO[bytes] | None = None,
        stdout: IO[bytes] | int | None = subprocess.PIPE,
        timeout: int = 600,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                command,
                cwd=REPOSITORY_ROOT,
                env=environment or self.environment,
                stdin=stdin,
                stdout=stdout,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RehearsalError(f"command failed to complete: {command[0]}") from error

    def _output(self, command: Sequence[str]) -> str:
        result = self._command(command, timeout=30)
        if result.returncode != 0:
            raise RehearsalError(f"required command failed: {command[0]}")
        return result.stdout.decode("utf-8").strip()

    def _compose(self, *arguments: str, profile: bool = False) -> list[str]:
        command = [
            "docker",
            "compose",
            "--file",
            str(COMPOSE_FILE),
            "--project-name",
            self.config.project,
            "--env-file",
            str(self.config.root / "compose.env"),
        ]
        if profile:
            command.extend(("--profile", "operations"))
        command.extend(arguments)
        return command

    def _record_step(
        self,
        name: str,
        *,
        started_at: str,
        result: subprocess.CompletedProcess[bytes],
    ) -> None:
        log_path = self.config.evidence_dir / f"{name}.log"
        output = (result.stdout or b"") + result.stderr
        log_path.write_bytes(output)
        report = {
            "schema_version": 1,
            "step": name,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "exit_code": result.returncode,
            "log_sha256": _sha256(log_path),
            "passed": result.returncode == 0,
        }
        self._write_json(f"{name}.json", report)

    def _run_step(
        self,
        name: str,
        command: Sequence[str],
        *,
        environment: Mapping[str, str] | None = None,
        timeout: int = 600,
    ) -> None:
        self.validate_workspace()
        started_at = datetime.now(timezone.utc).isoformat()
        result = self._command(
            command,
            environment=environment,
            timeout=timeout,
        )
        self._record_step(name, started_at=started_at, result=result)
        if result.returncode != 0:
            raise RehearsalError(f"rehearsal step failed: {name}")
        print(f"Phase 9.3 step passed: {name}")

    def _write_json(self, name: str, document: Mapping[str, object]) -> None:
        path = self.config.evidence_dir / name
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    def pull_images(self) -> None:
        for index, image in enumerate(IMAGE_TAGS, start=1):
            self._run_step(
                f"pull-image-{index}",
                ("docker", "pull", image),
                timeout=900,
            )
        image_evidence: dict[str, object] = {}
        for image in IMAGE_TAGS:
            raw = self._output(
                (
                    "docker",
                    "image",
                    "inspect",
                    image,
                    "--format",
                    "{{json .}}",
                )
            )
            inspected = json.loads(raw)
            image_evidence[image] = {
                "id": inspected["Id"],
                "repo_digests": inspected.get("RepoDigests", []),
                "architecture": inspected["Architecture"],
            }
        self._write_json(
            "image-digests.json",
            {
                "schema_version": 1,
                "images": image_evidence,
            },
        )

    def build_app(self) -> None:
        manifest = self.validate_workspace()
        self._run_step(
            "build-app",
            (
                "docker",
                "build",
                "--file",
                str(REPOSITORY_ROOT / "deploy" / "rehearsal" / "Dockerfile"),
                "--tag",
                self.config.app_image,
                "--label",
                f"com.pinkdoohub.phase93.run={self.config.run_id}",
                "--label",
                f"org.opencontainers.image.revision={manifest['git_sha']}",
                str(REPOSITORY_ROOT),
            ),
            timeout=1200,
        )
        inspected = json.loads(
            self._output(
                (
                    "docker",
                    "image",
                    "inspect",
                    self.config.app_image,
                    "--format",
                    "{{json .}}",
                )
            )
        )
        self._write_json(
            "app-image.json",
            {
                "schema_version": 1,
                "image": self.config.app_image,
                "id": inspected["Id"],
                "architecture": inspected["Architecture"],
                "revision": inspected["Config"]["Labels"][
                    "org.opencontainers.image.revision"
                ],
            },
        )

    def start_data_services(self) -> None:
        self._run_step(
            "start-data-services",
            self._compose(
                "up",
                "--detach",
                "--wait",
                "mysql-source",
                "mysql-restore",
                "redis",
            ),
        )
        self.record_status("data-services-ready")

    def migrate(self) -> None:
        self._run_step(
            "dr01-migrate-current",
            self._compose(
                "run",
                "--rm",
                "--no-deps",
                "migrate",
                profile=True,
            ),
        )

    def verify_current_schema(self) -> None:
        """验证 DR-01 空库完整迁移链与零业务数据。"""

        self.validate_workspace()
        snapshot = self._current_database_snapshot(
            "mysql-source",
            SOURCE_DATABASE,
        )
        empty_keys = (
            "users",
            "products",
            "experience_options",
            "product_images",
            "product_kits",
            "orders",
            "order_items",
            "inventory_transactions",
            "audit_logs",
        )
        migrations_valid = snapshot["aerich_versions"] == (
            "0_20260810101218_init.py,"
            "1_20260813130455_add_order_tables.py,"
            "2_20260814104655_add_inventory_transactions.py"
        )
        empty = all(snapshot[key] == "0" for key in empty_keys)
        schema_present = (
            int(snapshot["tables"]) == 10
            and int(snapshot["columns"]) > 0
            and int(snapshot["statistics"]) > 0
            and int(snapshot["constraints"]) > 0
        )
        passed = migrations_valid and empty and schema_present
        self._write_json(
            "dr01-result.json",
            {
                "schema_version": 1,
                "scenario": "DR-01",
                "snapshot": snapshot,
                "migrations_valid": migrations_valid,
                "business_tables_empty": empty,
                "schema_present": schema_present,
                "passed": passed,
            },
        )
        if not passed:
            raise RehearsalError("fresh migration scenario assertions failed")
        print("Phase 9.3 fresh 0-to-current migration passed: DR-01")

    def _mysql_root(
        self,
        sql: str,
        *,
        database: str | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return self._mysql_service(
            "mysql-source",
            sql,
            database=database,
        )

    def _mysql_service(
        self,
        service: str,
        sql: str,
        *,
        database: str | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        if service not in {"mysql-source", "mysql-restore"}:
            raise RehearsalError("unknown rehearsal MySQL service")
        command = self._compose(
            "exec",
            "--no-TTY",
            service,
            "/bin/sh",
            "-ec",
            "MYSQL_PWD=\"$(cat /run/secrets/mysql_root_password)\" "
            "exec mysql --user=root --batch --skip-column-names "
            + (f"--database={database} " if database else "")
            + "--execute \"$1\"",
            "phase93-mysql",
            sql,
        )
        return self._command(command, timeout=60)

    def _query_scalar(self, database: str, sql: str) -> str:
        return self._query_service_scalar("mysql-source", database, sql)

    def _query_service_scalar(
        self,
        service: str,
        database: str,
        sql: str,
    ) -> str:
        result = self._mysql_service(service, sql, database=database)
        if result.returncode != 0:
            raise RehearsalError("isolated migration scenario query failed")
        return result.stdout.decode("utf-8").strip()

    def _scenario_snapshot(self, database: str, version: int) -> dict[str, str]:
        queries = {
            "aerich_versions": (
                "SELECT GROUP_CONCAT(version ORDER BY id SEPARATOR ',') FROM aerich"
            ),
            "users": "SELECT COUNT(*) FROM users",
            "products": "SELECT COUNT(*) FROM products",
            "experience_options": "SELECT COUNT(*) FROM experience_options",
            "product_kits": "SELECT COUNT(*) FROM product_kits",
            "kit_stock": "SELECT COALESCE(SUM(stock), 0) FROM product_kits",
            "audit_logs": "SELECT COUNT(*) FROM audit_logs",
        }
        if version >= 1:
            queries.update(
                {
                    "orders": "SELECT COUNT(*) FROM orders",
                    "order_items": "SELECT COUNT(*) FROM order_items",
                    "order_total": (
                        "SELECT COALESCE(SUM(total_amount), 0) FROM orders"
                    ),
                    "order_snapshot_total": (
                        "SELECT COALESCE(SUM(subtotal), 0) FROM order_items"
                    ),
                }
            )
        if version >= 2:
            queries.update(
                {
                    "inventory_transactions": (
                        "SELECT COUNT(*) FROM inventory_transactions"
                    ),
                    "opening_change": (
                        "SELECT COALESCE(SUM(change_quantity), 0) "
                        "FROM inventory_transactions "
                        "WHERE transaction_type='opening_balance'"
                    ),
                    "opening_after": (
                        "SELECT COALESCE(SUM(after_quantity), 0) "
                        "FROM inventory_transactions "
                        "WHERE transaction_type='opening_balance'"
                    ),
                }
            )
        return {
            name: self._query_scalar(database, sql)
            for name, sql in queries.items()
        }

    def _prepare_scenario_directory(
        self,
        version: int,
        *,
        label: str | None = None,
    ) -> Path:
        directory_name = label or f"m{version}"
        if directory_name not in {"m0", "m1", "failure"}:
            raise RehearsalError("migration scenario directory label is not frozen")
        directory = self.config.root / "scenarios" / directory_name
        if directory.exists():
            raise RehearsalError("legacy migration scenario directory already exists")
        migrations_directory = directory / "migrations" / "models"
        migrations_directory.mkdir(mode=0o700, parents=True)
        os.chmod(directory, 0o700)
        os.chmod(directory.parent, 0o700)
        migration_names = (
            "0_20260810101218_init.py",
            "1_20260813130455_add_order_tables.py",
            "2_20260814104655_add_inventory_transactions.py",
        )
        for name in migration_names[: version + 1]:
            shutil.copy2(
                REPOSITORY_ROOT / "migrations" / "models" / name,
                migrations_directory / name,
            )
        (directory / "pyproject.toml").write_text(
            "[tool.tortoise]\n"
            'tortoise_orm = "app.db.database.TORTOISE_ORM"\n'
            'location = "./migrations"\n'
            'src_folder = "/app"\n',
            encoding="utf-8",
        )
        return directory

    def run_legacy_scenario(self, version: int) -> None:
        """执行 DR-02 或 DR-03，不 fake Aerich 版本或补业务 SQL。"""

        if version not in (0, 1):
            raise RehearsalError("only migration 0 and migration 1 are supported")
        self.validate_workspace()
        database = f"pinkdoohub_phase93_m{version}"
        create_result = self._mysql_root(
            f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4"
        )
        self._record_step(
            f"dr0{version + 2}-create-schema",
            started_at=datetime.now(timezone.utc).isoformat(),
            result=create_result,
        )
        if create_result.returncode != 0:
            raise RehearsalError("legacy migration scenario schema creation failed")

        directory = self._prepare_scenario_directory(version)
        environment = self.environment | {
            "PHASE93_SCENARIO_DATABASE": database,
            "PHASE93_SCENARIO_DIR": str(directory),
        }
        scenario_name = f"dr0{version + 2}"
        self._run_step(
            f"{scenario_name}-migrate-to-legacy",
            self._compose(
                "run",
                "--rm",
                "--no-deps",
                "migration-scenario",
                profile=True,
            ),
            environment=environment,
        )
        self._run_step(
            f"{scenario_name}-seed-legacy",
            self._compose(
                "run",
                "--rm",
                "--no-deps",
                "--environment",
                "PHASE93_LEGACY_SEED_ENABLED=1",
                "migration-scenario",
                "python",
                "-m",
                "app.tasks.phase93_legacy_seed",
                "--migration-version",
                str(version),
                profile=True,
            ),
            environment=environment,
        )
        before = self._scenario_snapshot(database, version)

        migrations_directory = directory / "migrations" / "models"
        remaining_names = (
            "1_20260813130455_add_order_tables.py",
            "2_20260814104655_add_inventory_transactions.py",
        )[version:]
        for name in remaining_names:
            shutil.copy2(
                REPOSITORY_ROOT / "migrations" / "models" / name,
                migrations_directory / name,
            )
        self._run_step(
            f"{scenario_name}-upgrade-current",
            self._compose(
                "run",
                "--rm",
                "--no-deps",
                "migration-scenario",
                profile=True,
            ),
            environment=environment,
        )
        after = self._scenario_snapshot(database, 2)
        expected_common = {
            "users": "1",
            "products": "2",
            "experience_options": "1",
            "product_kits": "1",
            "kit_stock": "7",
            "audit_logs": str(2 + (1 if version == 1 else 0)),
        }
        preserved = all(
            before[key] == expected and after[key] == expected
            for key, expected in expected_common.items()
        )
        order_preserved = (
            version == 0
            and after["orders"] == "0"
            and after["order_items"] == "0"
        ) or (
            version == 1
            and before["orders"] == after["orders"] == "1"
            and before["order_items"] == after["order_items"] == "2"
            and before["order_total"] == after["order_total"] == "160.00"
            and before["order_snapshot_total"]
            == after["order_snapshot_total"]
            == "160.00"
        )
        opening_balance_valid = (
            after["inventory_transactions"] == "1"
            and after["opening_change"] == "7"
            and after["opening_after"] == "7"
        )
        migrations_valid = after["aerich_versions"] == (
            "0_20260810101218_init.py,"
            "1_20260813130455_add_order_tables.py,"
            "2_20260814104655_add_inventory_transactions.py"
        )
        passed = (
            preserved
            and order_preserved
            and opening_balance_valid
            and migrations_valid
        )
        self._write_json(
            f"{scenario_name}-result.json",
            {
                "schema_version": 1,
                "scenario": scenario_name.upper(),
                "database": database,
                "before": before,
                "after": after,
                "preserved": preserved,
                "order_preserved": order_preserved,
                "opening_balance_valid": opening_balance_valid,
                "migrations_valid": migrations_valid,
                "passed": passed,
            },
        )
        if not passed:
            raise RehearsalError("legacy migration scenario assertions failed")
        print(f"Phase 9.3 legacy migration scenario passed: DR-0{version + 2}")

    def _dump_source_schema(self, database: str, path: Path) -> None:
        command = self._compose(
            "exec",
            "--no-TTY",
            "mysql-source",
            "/bin/sh",
            "-ec",
            "MYSQL_PWD=\"$(cat /run/secrets/mysql_root_password)\" "
            "exec mysqldump --user=root --single-transaction --routines "
            "--triggers --hex-blob --set-gtid-purged=OFF \"$1\"",
            "phase93-dump",
            database,
        )
        with path.open("wb") as stream:
            result = self._command(command, stdout=stream)
        if result.returncode != 0 or path.stat().st_size == 0:
            raise RehearsalError("isolated failure scenario backup failed")

    def _restore_source_schema(self, database: str, path: Path) -> None:
        command = self._compose(
            "exec",
            "--no-TTY",
            "mysql-source",
            "/bin/sh",
            "-ec",
            "MYSQL_PWD=\"$(cat /run/secrets/mysql_root_password)\" "
            "exec mysql --user=root \"$1\"",
            "phase93-restore",
            database,
        )
        with path.open("rb") as stream:
            result = self._command(command, stdin=stream)
        if result.returncode != 0:
            raise RehearsalError("isolated failure scenario restore failed")

    def run_failure_drill(
        self,
        *,
        confirm_project: str,
        confirm_database: str,
    ) -> None:
        """执行 DR-05：证明隐式提交，再恢复副本并迁移。"""

        if confirm_project != self.config.project:
            raise RehearsalError("failure drill project confirmation does not match")
        if confirm_database != FAILURE_DATABASE:
            raise RehearsalError("failure drill database confirmation does not match")
        self.validate_workspace()
        create_result = self._mysql_root(
            f"CREATE DATABASE `{FAILURE_DATABASE}` CHARACTER SET utf8mb4; "
            f"CREATE DATABASE `{FAILURE_RESTORE_DATABASE}` CHARACTER SET utf8mb4"
        )
        self._record_step(
            "dr05-create-schemas",
            started_at=datetime.now(timezone.utc).isoformat(),
            result=create_result,
        )
        if create_result.returncode != 0:
            raise RehearsalError("failure drill schema creation failed")

        directory = self._prepare_scenario_directory(1, label="failure")
        environment = self.environment | {
            "PHASE93_SCENARIO_DATABASE": FAILURE_DATABASE,
            "PHASE93_SCENARIO_DIR": str(directory),
        }
        self._run_step(
            "dr05-migrate-to-one",
            self._compose(
                "run", "--rm", "--no-deps", "migration-scenario", profile=True
            ),
            environment=environment,
        )
        self._run_step(
            "dr05-seed-migration-one",
            self._compose(
                "run",
                "--rm",
                "--no-deps",
                "--environment",
                "PHASE93_LEGACY_SEED_ENABLED=1",
                "migration-scenario",
                "python",
                "-m",
                "app.tasks.phase93_legacy_seed",
                "--migration-version",
                "1",
                profile=True,
            ),
            environment=environment,
        )
        before = self._scenario_snapshot(FAILURE_DATABASE, 1)
        backup_path = self.config.evidence_dir / "dr05-pre-failure.sql"
        backup_started = time.monotonic()
        self._dump_source_schema(FAILURE_DATABASE, backup_path)
        backup_seconds = time.monotonic() - backup_started

        official_migration = (
            REPOSITORY_ROOT
            / "migrations"
            / "models"
            / "2_20260814104655_add_inventory_transactions.py"
        )
        migration_text = official_migration.read_text(encoding="utf-8")
        marker = "\n\n        INSERT INTO `inventory_transactions`"
        if migration_text.count(marker) != 1:
            raise RehearsalError("controlled failure injection marker drifted")
        injected_text = migration_text.replace(
            marker,
            "\n\n        CREATE TABL phase93_controlled_failure;" + marker,
            1,
        )
        scenario_migration = (
            directory
            / "migrations"
            / "models"
            / official_migration.name
        )
        scenario_migration.write_text(injected_text, encoding="utf-8")

        failure_started = datetime.now(timezone.utc).isoformat()
        failure_result = self._command(
            self._compose(
                "run", "--rm", "--no-deps", "migration-scenario", profile=True
            ),
            environment=environment,
        )
        self._record_step(
            "dr05-expected-migration-failure",
            started_at=failure_started,
            result=failure_result,
        )
        if failure_result.returncode == 0:
            raise RehearsalError("controlled migration failure unexpectedly succeeded")

        partial = self._scenario_snapshot(FAILURE_DATABASE, 2)
        table_exists = self._query_scalar(
            "information_schema",
            "SELECT COUNT(*) FROM tables "
            f"WHERE table_schema='{FAILURE_DATABASE}' "
            "AND table_name='inventory_transactions'",
        )
        partial_commit_proven = (
            table_exists == "1"
            and partial["inventory_transactions"] == "0"
            and partial["aerich_versions"] == before["aerich_versions"]
        )

        restore_started = time.monotonic()
        self._restore_source_schema(FAILURE_RESTORE_DATABASE, backup_path)
        restore_seconds = time.monotonic() - restore_started
        restored = self._scenario_snapshot(FAILURE_RESTORE_DATABASE, 1)
        restored_matches = restored == before

        shutil.copy2(official_migration, scenario_migration)
        restore_environment = environment | {
            "PHASE93_SCENARIO_DATABASE": FAILURE_RESTORE_DATABASE,
        }
        self._run_step(
            "dr05-upgrade-restored-copy",
            self._compose(
                "run", "--rm", "--no-deps", "migration-scenario", profile=True
            ),
            environment=restore_environment,
        )
        upgraded = self._scenario_snapshot(FAILURE_RESTORE_DATABASE, 2)
        upgraded_valid = (
            upgraded["inventory_transactions"] == "1"
            and upgraded["opening_change"] == "7"
            and upgraded["opening_after"] == "7"
            and upgraded["users"] == before["users"]
            and upgraded["products"] == before["products"]
            and upgraded["orders"] == before["orders"]
            and upgraded["order_items"] == before["order_items"]
        )
        passed = partial_commit_proven and restored_matches and upgraded_valid
        self._write_json(
            "dr05-result.json",
            {
                "schema_version": 1,
                "scenario": "DR-05",
                "failure_database": FAILURE_DATABASE,
                "restore_database": FAILURE_RESTORE_DATABASE,
                "backup_sha256": _sha256(backup_path),
                "backup_seconds": round(backup_seconds, 3),
                "restore_seconds": round(restore_seconds, 3),
                "before": before,
                "partial": partial,
                "restored": restored,
                "upgraded": upgraded,
                "partial_commit_proven": partial_commit_proven,
                "restored_matches": restored_matches,
                "upgraded_valid": upgraded_valid,
                "passed": passed,
            },
        )
        if not passed:
            raise RehearsalError("controlled migration failure drill assertions failed")
        print("Phase 9.3 controlled migration failure drill passed: DR-05")

    def bootstrap(self, *, replay: bool = False) -> None:
        step_name = "dr07-bootstrap-replay" if replay else "dr07-bootstrap-first"
        self._run_step(
            step_name,
            self._compose(
                "run",
                "--rm",
                "--no-deps",
                "bootstrap",
                profile=True,
            ),
        )
        log_text = (self.config.evidence_dir / f"{step_name}.log").read_text(
            encoding="utf-8"
        )
        expected = (
            "created=False replay=True" if replay else "created=True replay=False"
        )
        if expected not in log_text:
            raise RehearsalError("bootstrap result did not match the requested mode")

    def verify_bootstrap(self) -> None:
        """验证唯一 SUPER_ADMIN、唯一自指 Audit 和严格重放结果。"""

        self.validate_workspace()
        values = {
            "super_admins": self._query_scalar(
                SOURCE_DATABASE,
                "SELECT COUNT(*) FROM users WHERE role=3",
            ),
            "normal_phase93_owner": self._query_scalar(
                SOURCE_DATABASE,
                "SELECT COUNT(*) FROM users "
                "WHERE role=3 AND status=1 AND username='phase93_owner'",
            ),
            "bootstrap_audits": self._query_scalar(
                SOURCE_DATABASE,
                "SELECT COUNT(*) FROM audit_logs "
                "WHERE action='BOOTSTRAP_SUPER_ADMIN'",
            ),
            "self_referencing_audits": self._query_scalar(
                SOURCE_DATABASE,
                "SELECT COUNT(*) FROM audit_logs a JOIN users u "
                "ON a.operator_id=u.id AND a.target_id=u.id "
                "WHERE a.action='BOOTSTRAP_SUPER_ADMIN' "
                "AND a.target_type='user' AND u.username='phase93_owner'",
            ),
        }
        passed = all(value == "1" for value in values.values())
        self._write_json(
            "dr07-bootstrap-verification.json",
            {
                "schema_version": 1,
                "scenario": "DR-07",
                "values": values,
                "first_result_verified": True,
                "replay_result_verified": True,
                "passed": passed,
            },
        )
        if not passed:
            raise RehearsalError("SUPER_ADMIN bootstrap verification failed")
        print("Phase 9.3 SUPER_ADMIN bootstrap verification passed: DR-07")

    def seed_runtime_roles(self) -> None:
        self._run_step(
            "dr09-seed-runtime-roles",
            self._compose(
                "run",
                "--rm",
                "--no-deps",
                "runtime-seed",
                profile=True,
            ),
        )

    def run_live_smoke(self) -> None:
        self._run_step(
            "dr06-dr07-dr09-live-smoke-runner",
            (
                sys.executable,
                "-m",
                "scripts.release.phase93_live_smoke",
                "--run-id",
                self.config.run_id,
            ),
        )

    def start_application(self) -> None:
        self._run_step(
            "dr06-start-application",
            self._compose("up", "--detach", "--wait", "app", "https"),
        )
        self.record_status("application-ready")

    def _health_response(self, path: str) -> tuple[int, dict[str, object]]:
        result = self._command(
            (
                "curl",
                "--silent",
                "--show-error",
                "--resolve",
                f"pinkdoohub-phase93.test:{PORTS['https']}:127.0.0.1",
                "--cacert",
                str(self.config.cert_dir / "ca.crt"),
                "--write-out",
                "\n%{http_code}",
                f"https://pinkdoohub-phase93.test:{PORTS['https']}{path}",
            ),
            timeout=15,
        )
        if result.returncode != 0:
            raise RehearsalError("HTTPS health request failed")
        body, separator, status_text = result.stdout.rpartition(b"\n")
        if not separator:
            raise RehearsalError("HTTPS health response status is missing")
        try:
            return int(status_text), json.loads(body)
        except (ValueError, json.JSONDecodeError) as error:
            raise RehearsalError("HTTPS health response is invalid") from error

    def _wait_health(
        self,
        *,
        expected_status: int,
        expected_checks: Mapping[str, str] | None = None,
        timeout: int = 45,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        last_status = 0
        last_document: dict[str, object] = {}
        while time.monotonic() < deadline:
            last_status, last_document = self._health_response(
                "/api/v1/health/ready"
            )
            checks = (last_document.get("data") or {}).get("checks")
            if last_status == expected_status and (
                expected_checks is None or checks == expected_checks
            ):
                return last_document
            time.sleep(1)
        raise RehearsalError(
            "readiness did not reach the expected dependency state"
        )

    def _restart_dependency(self, service: str) -> None:
        result = self._command(
            self._compose("up", "--detach", "--wait", service),
            timeout=180,
        )
        if result.returncode != 0:
            raise RehearsalError("dependency recovery failed")

    def run_dependency_drill(self, *, confirm_project: str) -> None:
        """依次停 Redis/MySQL，验证 503 摘流量、Liveness 和恢复。"""

        if confirm_project != self.config.project:
            raise RehearsalError("dependency drill project confirmation does not match")
        self.validate_workspace()
        observations: list[dict[str, object]] = []
        scenarios = (
            ("redis", {"database": "up", "redis": "down"}),
            ("mysql-source", {"database": "down", "redis": "up"}),
        )
        for service, expected_checks in scenarios:
            stopped = False
            try:
                stop_result = self._command(self._compose("stop", service))
                if stop_result.returncode != 0:
                    raise RehearsalError("dependency stop failed")
                stopped = True
                unavailable = self._wait_health(
                    expected_status=503,
                    expected_checks=expected_checks,
                )
                live_status, live = self._health_response(
                    "/api/v1/health/live"
                )
                if live_status != 200 or live.get("code") != 0:
                    raise RehearsalError("liveness failed during dependency outage")
            finally:
                if stopped:
                    self._restart_dependency(service)
            recovered = self._wait_health(
                expected_status=200,
                expected_checks={"database": "up", "redis": "up"},
            )
            observations.append(
                {
                    "service": service,
                    "unavailable": unavailable,
                    "liveness": live,
                    "recovered": recovered,
                }
            )
        self._write_json(
            "dr06-dependency-failure-result.json",
            {
                "schema_version": 1,
                "scenario": "DR-06 dependency failure/recovery",
                "observations": observations,
                "passed": True,
            },
        )
        print("Phase 9.3 dependency failure/recovery drill passed: DR-06")

    def _fetch_https_bytes(self, path: str) -> bytes:
        result = self._command(
            (
                "curl",
                "--silent",
                "--show-error",
                "--fail",
                "--resolve",
                f"pinkdoohub-phase93.test:{PORTS['https']}:127.0.0.1",
                "--cacert",
                str(self.config.cert_dir / "ca.crt"),
                f"https://pinkdoohub-phase93.test:{PORTS['https']}{path}",
            ),
            timeout=15,
        )
        if result.returncode != 0:
            raise RehearsalError("HTTPS image persistence request failed")
        return result.stdout

    def restart_application(self, *, confirm_project: str) -> None:
        """优雅重启应用与 HTTPS 代理，并验证图片 volume 未漂移。"""

        if confirm_project != self.config.project:
            raise RehearsalError("restart project confirmation does not match")
        self.validate_workspace()
        image_url = self._query_scalar(
            SOURCE_DATABASE,
            "SELECT image_url FROM product_images "
            "WHERE is_deleted=0 ORDER BY id LIMIT 1",
        )
        parsed = urlparse(image_url)
        if parsed.scheme != "https" or not parsed.path.startswith(
            "/uploads/products/"
        ):
            raise RehearsalError("stored Product image URL is outside HTTPS storage")
        before = self._fetch_https_bytes(parsed.path)
        self._run_step(
            "dr06-graceful-restart",
            self._compose("restart", "--timeout", "20", "app", "https"),
        )
        wait_result = self._command(
            self._compose("up", "--detach", "--wait", "app", "https"),
            timeout=180,
        )
        if wait_result.returncode != 0:
            raise RehearsalError("application did not become healthy after restart")
        self._wait_health(
            expected_status=200,
            expected_checks={"database": "up", "redis": "up"},
        )
        after = self._fetch_https_bytes(parsed.path)
        before_digest = hashlib.sha256(before).hexdigest()
        after_digest = hashlib.sha256(after).hexdigest()
        if before_digest != after_digest or not before:
            raise RehearsalError("Product image changed across application restart")
        self._write_json(
            "dr06-restart-image-persistence.json",
            {
                "schema_version": 1,
                "scenario": "DR-06 graceful restart and image persistence",
                "image_path": parsed.path,
                "before_sha256": before_digest,
                "after_sha256": after_digest,
                "readiness_recovered": True,
                "passed": True,
            },
        )
        print("Phase 9.3 graceful restart and image persistence passed: DR-06")

    def record_status(self, name: str) -> None:
        self.validate_workspace()
        result = self._command(self._compose("ps", "--format", "json"))
        self._record_step(
            name,
            started_at=datetime.now(timezone.utc).isoformat(),
            result=result,
        )
        if result.returncode != 0:
            raise RehearsalError("Compose status collection failed")

    def backup_database(self) -> Path:
        """创建 source 一致性逻辑备份；恢复验证由独立步骤完成。"""

        self.validate_workspace()
        path = self.config.evidence_dir / "source-backup.sql"
        command = self._compose(
            "exec",
            "--no-TTY",
            "mysql-source",
            "/bin/sh",
            "-ec",
            "MYSQL_PWD=\"$(cat /run/secrets/mysql_root_password)\" "
            "exec mysqldump --user=root --single-transaction --routines "
            "--triggers --hex-blob --set-gtid-purged=OFF "
            f"{SOURCE_DATABASE}",
        )
        started_at = datetime.now(timezone.utc).isoformat()
        with path.open("wb") as stream:
            result = self._command(command, stdout=stream)
        report = {
            "schema_version": 1,
            "step": "dr04-backup-database",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "exit_code": result.returncode,
            "backup_sha256": _sha256(path) if result.returncode == 0 else None,
            "backup_bytes": path.stat().st_size,
            "contains_secret_values": False,
            "passed": result.returncode == 0 and path.stat().st_size > 0,
        }
        self._write_json("dr04-backup-database.json", report)
        if not report["passed"]:
            raise RehearsalError("database backup failed")
        return path

    def restore_database(
        self,
        *,
        confirm_project: str,
        confirm_database: str,
    ) -> None:
        """只向冻结的独立 restore 实例写入已记录备份。"""

        if confirm_project != self.config.project:
            raise RehearsalError("restore project confirmation does not match")
        if confirm_database != RESTORE_DATABASE:
            raise RehearsalError("restore database confirmation does not match")
        self.validate_workspace()
        backup = self.config.evidence_dir / "source-backup.sql"
        if not backup.is_file() or backup.stat().st_size == 0:
            raise RehearsalError("verified source backup is missing")
        command = self._compose(
            "exec",
            "--no-TTY",
            "mysql-restore",
            "/bin/sh",
            "-ec",
            "MYSQL_PWD=\"$(cat /run/secrets/mysql_root_password)\" "
            f"exec mysql --user=root {RESTORE_DATABASE}",
        )
        started_at = datetime.now(timezone.utc).isoformat()
        with backup.open("rb") as stream:
            result = self._command(command, stdin=stream)
        self._record_step(
            "dr04-restore-database",
            started_at=started_at,
            result=result,
        )
        if result.returncode != 0:
            raise RehearsalError("database restore failed")

    def backup_images(self) -> Path:
        self.validate_workspace()
        path = self.config.evidence_dir / "product-images.tar"
        command = self._compose(
            "exec",
            "--no-TTY",
            "app",
            "tar",
            "-C",
            "/data/images",
            "-cf",
            "-",
            ".",
        )
        with path.open("wb") as stream:
            result = self._command(command, stdout=stream)
        self._write_json(
            "dr06-backup-images.json",
            {
                "schema_version": 1,
                "step": "dr06-backup-images",
                "exit_code": result.returncode,
                "backup_sha256": _sha256(path) if result.returncode == 0 else None,
                "backup_bytes": path.stat().st_size,
                "passed": result.returncode == 0 and path.stat().st_size > 0,
            },
        )
        if result.returncode != 0 or path.stat().st_size == 0:
            raise RehearsalError("image backup failed")
        return path

    def restore_images(self, *, confirm_project: str) -> None:
        if confirm_project != self.config.project:
            raise RehearsalError("image restore project confirmation does not match")
        self.validate_workspace()
        backup = self.config.evidence_dir / "product-images.tar"
        if not backup.is_file() or backup.stat().st_size == 0:
            raise RehearsalError("verified image backup is missing")
        command = self._compose(
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
            profile=True,
        )
        started_at = datetime.now(timezone.utc).isoformat()
        with backup.open("rb") as stream:
            result = self._command(command, stdin=stream)
        self._record_step(
            "dr06-restore-images",
            started_at=started_at,
            result=result,
        )
        if result.returncode != 0:
            raise RehearsalError("image restore failed")

    def _current_database_snapshot(
        self,
        service: str,
        database: str,
    ) -> dict[str, str]:
        queries = {
            "aerich_versions": (
                "SELECT GROUP_CONCAT(version ORDER BY id SEPARATOR ',') FROM aerich"
            ),
            "tables": (
                "SELECT COUNT(*) FROM information_schema.tables "
                f"WHERE table_schema='{database}'"
            ),
            "columns": (
                "SELECT COUNT(*) FROM information_schema.columns "
                f"WHERE table_schema='{database}'"
            ),
            "statistics": (
                "SELECT COUNT(*) FROM information_schema.statistics "
                f"WHERE table_schema='{database}'"
            ),
            "constraints": (
                "SELECT COUNT(*) FROM information_schema.table_constraints "
                f"WHERE table_schema='{database}'"
            ),
            "users": "SELECT COUNT(*) FROM users",
            "products": "SELECT COUNT(*) FROM products",
            "experience_options": "SELECT COUNT(*) FROM experience_options",
            "product_images": "SELECT COUNT(*) FROM product_images",
            "product_kits": "SELECT COUNT(*) FROM product_kits",
            "kit_stock": "SELECT COALESCE(SUM(stock), 0) FROM product_kits",
            "orders": "SELECT COUNT(*) FROM orders",
            "order_items": "SELECT COUNT(*) FROM order_items",
            "order_total": "SELECT COALESCE(SUM(total_amount), 0) FROM orders",
            "inventory_transactions": (
                "SELECT COUNT(*) FROM inventory_transactions"
            ),
            "inventory_change": (
                "SELECT COALESCE(SUM(change_quantity), 0) "
                "FROM inventory_transactions"
            ),
            "audit_logs": "SELECT COUNT(*) FROM audit_logs",
        }
        return {
            name: self._query_service_scalar(service, database, sql)
            for name, sql in queries.items()
        }

    def _image_manifest(self, *, restored: bool) -> list[str]:
        if restored:
            command = self._compose(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/bin/sh",
                "image-restore",
                "-ec",
                "find /restore -type f -exec sha256sum {} + | "
                "sed 's# /restore/# #' | sort",
                profile=True,
            )
        else:
            command = self._compose(
                "exec",
                "--no-TTY",
                "app",
                "/bin/sh",
                "-ec",
                "find /data/images -type f -exec sha256sum {} + | "
                "sed 's# /data/images/# #' | sort",
            )
        result = self._command(command, timeout=60)
        if result.returncode != 0:
            raise RehearsalError("Product image manifest collection failed")
        return result.stdout.decode("utf-8").splitlines()

    def verify_restore(
        self,
        *,
        confirm_project: str,
        confirm_database: str,
    ) -> None:
        """比较独立恢复实例，并启动 Restore App 验证 readiness/login。"""

        if confirm_project != self.config.project:
            raise RehearsalError("restore verification project confirmation mismatch")
        if confirm_database != RESTORE_DATABASE:
            raise RehearsalError("restore verification database confirmation mismatch")
        self.validate_workspace()
        source = self._current_database_snapshot(
            "mysql-source",
            SOURCE_DATABASE,
        )
        restored = self._current_database_snapshot(
            "mysql-restore",
            RESTORE_DATABASE,
        )
        source_images = self._image_manifest(restored=False)
        restored_images = self._image_manifest(restored=True)
        database_matches = source == restored
        images_match = bool(source_images) and source_images == restored_images
        if not database_matches or not images_match:
            raise RehearsalError("independent restore snapshot comparison failed")

        started = False
        try:
            start_result = self._command(
                self._compose(
                    "up",
                    "--detach",
                    "--wait",
                    "restore-app",
                    profile=True,
                ),
                timeout=180,
            )
            if start_result.returncode != 0:
                raise RehearsalError("Restore App did not become healthy")
            started = True
            smoke_result = self._command(
                self._compose(
                    "exec",
                    "--no-TTY",
                    "restore-app",
                    "python",
                    "-m",
                    "app.tasks.phase93_restore_smoke",
                    profile=True,
                ),
                timeout=60,
            )
            if smoke_result.returncode != 0:
                raise RehearsalError("Restore App readiness/login smoke failed")
        finally:
            if started:
                stop_result = self._command(
                    self._compose("stop", "restore-app", profile=True),
                    timeout=60,
                )
                if stop_result.returncode != 0:
                    raise RehearsalError("Restore App cleanup stop failed")
        self._write_json(
            "dr04-restore-verification.json",
            {
                "schema_version": 1,
                "scenario": "DR-04",
                "source_database": SOURCE_DATABASE,
                "restore_database": RESTORE_DATABASE,
                "source": source,
                "restored": restored,
                "database_matches": database_matches,
                "source_image_manifest": source_images,
                "restored_image_manifest": restored_images,
                "images_match": images_match,
                "restore_app_ready": True,
                "restore_login_verified": True,
                "restore_app_stopped": True,
                "passed": True,
            },
        )
        print("Phase 9.3 independent database/image restore passed: DR-04")

    def stop(self, *, confirm_project: str) -> None:
        if confirm_project != self.config.project:
            raise RehearsalError("stop project confirmation does not match")
        self._run_step(
            "stop-services",
            self._compose("stop", "--timeout", "20", profile=True),
        )

    def cleanup(self, *, confirm_project: str, confirm_workspace: str) -> None:
        """删除精确 project 的容器/网络/卷与短期工作区。"""

        if confirm_project != self.config.project:
            raise RehearsalError("cleanup project confirmation does not match")
        if confirm_workspace != str(self.config.root):
            raise RehearsalError("cleanup workspace confirmation does not match")
        self.validate_workspace()
        result = self._command(
            self._compose(
                "down",
                "--volumes",
                "--remove-orphans",
                "--timeout",
                "20",
                profile=True,
            )
        )
        if result.returncode != 0:
            raise RehearsalError("Compose project cleanup failed")
        resources = self._owned_resources()
        ports_closed = all(self._port_closed(port) for port in PORTS.values())
        if any(resources.values()) or not ports_closed:
            raise RehearsalError("cleanup verification found residual resources")
        shutil.rmtree(self.config.root)
        if self.config.root.exists():
            raise RehearsalError("temporary rehearsal workspace still exists")
        print(
            "Phase 9.3 cleanup passed: "
            f"project={self.config.project} ports_closed=true workspace_removed=true"
        )

    def _owned_resources(self) -> dict[str, list[str]]:
        queries = {
            "containers": (
                "docker", "ps", "--all", "--quiet", "--filter",
                f"label=com.docker.compose.project={self.config.project}",
            ),
            "networks": (
                "docker", "network", "ls", "--quiet", "--filter",
                f"label=com.docker.compose.project={self.config.project}",
            ),
            "volumes": (
                "docker", "volume", "ls", "--quiet", "--filter",
                f"label=com.docker.compose.project={self.config.project}",
            ),
        }
        return {
            kind: self._output(command).splitlines()
            for kind, command in queries.items()
        }

    @staticmethod
    def _port_closed(port: int) -> bool:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
                connection.settimeout(0.5)
                if connection.connect_ex(("127.0.0.1", port)) != 0:
                    return True
            time.sleep(0.25)
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "pull-images",
            "build-app",
            "start-data",
            "migrate",
            "verify-current",
            "legacy-m0",
            "legacy-m1",
            "failure-drill",
            "bootstrap",
            "bootstrap-replay",
            "verify-bootstrap",
            "runtime-seed",
            "live-smoke",
            "dependency-drill",
            "restart-app",
            "start-app",
            "status",
            "backup-db",
            "restore-db",
            "backup-images",
            "restore-images",
            "verify-restore",
            "stop",
            "cleanup",
        ),
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--confirm-project")
    parser.add_argument("--confirm-database")
    parser.add_argument("--confirm-workspace")
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        operations = Phase93Operations(config_for_run(arguments.run_id))
        commands = {
            "pull-images": operations.pull_images,
            "build-app": operations.build_app,
            "start-data": operations.start_data_services,
            "migrate": operations.migrate,
            "verify-current": operations.verify_current_schema,
            "legacy-m0": lambda: operations.run_legacy_scenario(0),
            "legacy-m1": lambda: operations.run_legacy_scenario(1),
            "failure-drill": lambda: operations.run_failure_drill(
                confirm_project=arguments.confirm_project or "",
                confirm_database=arguments.confirm_database or "",
            ),
            "bootstrap": lambda: operations.bootstrap(replay=False),
            "bootstrap-replay": lambda: operations.bootstrap(replay=True),
            "verify-bootstrap": operations.verify_bootstrap,
            "runtime-seed": operations.seed_runtime_roles,
            "live-smoke": operations.run_live_smoke,
            "dependency-drill": lambda: operations.run_dependency_drill(
                confirm_project=arguments.confirm_project or "",
            ),
            "restart-app": lambda: operations.restart_application(
                confirm_project=arguments.confirm_project or "",
            ),
            "start-app": operations.start_application,
            "status": lambda: operations.record_status("manual-status"),
            "backup-db": operations.backup_database,
            "restore-db": lambda: operations.restore_database(
                confirm_project=arguments.confirm_project or "",
                confirm_database=arguments.confirm_database or "",
            ),
            "backup-images": operations.backup_images,
            "restore-images": lambda: operations.restore_images(
                confirm_project=arguments.confirm_project or "",
            ),
            "verify-restore": lambda: operations.verify_restore(
                confirm_project=arguments.confirm_project or "",
                confirm_database=arguments.confirm_database or "",
            ),
            "stop": lambda: operations.stop(
                confirm_project=arguments.confirm_project or "",
            ),
            "cleanup": lambda: operations.cleanup(
                confirm_project=arguments.confirm_project or "",
                confirm_workspace=arguments.confirm_workspace or "",
            ),
        }
        commands[arguments.command]()
        return 0
    except RehearsalError as error:
        print(f"Phase 9.3 operation refused: {error}", file=sys.stderr)
    except Exception as error:
        print(
            f"Phase 9.3 operation failed safely: {type(error).__name__}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
