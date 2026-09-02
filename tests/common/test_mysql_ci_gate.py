"""Phase 9.2.4 MySQL CI 门槛脚本的安全契约。"""

import json
import os
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPOSITORY_ROOT / "scripts" / "ci" / "check_mysql_gate.py"
PHASE95_MIGRATION = "3_20260902125032_phase95_external_identity.py"
SAFE_ENVIRONMENT = {
    "APP_ENV": "testing",
    "DB_ENGINE": "mysql",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "13306",
    "DB_NAME": "pinkdoohub_inventory_4311_ci",
    "DB_USER": "root",
    "DB_PASSWORD": "test-only-password",
    "INVENTORY_MYSQL_TEST_ENABLED": "1",
    "INVENTORY_MYSQL_TEST_HOST": "127.0.0.1",
    "INVENTORY_MYSQL_TEST_PORT": "13306",
    "INVENTORY_MYSQL_TEST_DB": "pinkdoohub_inventory_4311_ci",
    "INVENTORY_MYSQL_TEST_USER": "root",
    "INVENTORY_MYSQL_TEST_PASSWORD": "test-only-password",
}


def _run_preflight(tmp_path: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(SAFE_ENVIRONMENT)
    environment.update(overrides)
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "preflight",
            "--report",
            str(tmp_path / "preflight.json"),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_preflight_accepts_only_the_frozen_disposable_target(tmp_path: Path) -> None:
    result = _run_preflight(tmp_path)

    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "preflight.json").read_text(encoding="utf-8"))
    assert report == {
        "database": "pinkdoohub_inventory_4311_ci",
        "host": "127.0.0.1",
        "port": 13306,
        "schema_version": 1,
        "status": "preflight-passed",
    }
    assert SAFE_ENVIRONMENT["INVENTORY_MYSQL_TEST_PASSWORD"] not in result.stdout
    assert SAFE_ENVIRONMENT["INVENTORY_MYSQL_TEST_PASSWORD"] not in result.stderr
    assert SAFE_ENVIRONMENT["INVENTORY_MYSQL_TEST_PASSWORD"] not in report.values()


def test_snapshot_contract_includes_phase95_migration() -> None:
    checker_source = CHECKER.read_text(encoding="utf-8")

    assert PHASE95_MIGRATION in checker_source


def test_preflight_rejects_disabled_default_port_remote_and_wrong_schema(
    tmp_path: Path,
) -> None:
    cases = [
        {"INVENTORY_MYSQL_TEST_ENABLED": "0"},
        {"INVENTORY_MYSQL_TEST_HOST": "mysql"},
        {"INVENTORY_MYSQL_TEST_PORT": "3306"},
        {"INVENTORY_MYSQL_TEST_DB": "pinkdoohub"},
        {"DB_NAME": "a_different_schema"},
        {"DB_PASSWORD": "a-different-password"},
    ]

    for overrides in cases:
        result = _run_preflight(tmp_path, **overrides)
        assert result.returncode != 0
        assert SAFE_ENVIRONMENT["INVENTORY_MYSQL_TEST_PASSWORD"] not in result.stderr


def test_preflight_rejects_invalid_port_without_a_traceback_or_secret(
    tmp_path: Path,
) -> None:
    result = _run_preflight(
        tmp_path,
        INVENTORY_MYSQL_TEST_PORT="not-a-port",
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert SAFE_ENVIRONMENT["INVENTORY_MYSQL_TEST_PASSWORD"] not in result.stderr
