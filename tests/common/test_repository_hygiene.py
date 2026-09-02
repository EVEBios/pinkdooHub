"""Repository hygiene 路径与高置信 Secret 检查契约。"""

import json
import subprocess
import sys
from pathlib import Path

from scripts.ci.check_repository_hygiene import (
    find_path_violations,
    find_secret_findings,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPOSITORY_ROOT / "scripts" / "ci" / "check_repository_hygiene.py"


def test_path_policy_allows_public_env_templates_and_rejects_local_data() -> None:
    paths = [
        ".env.example",
        "miniapp/.env.development",
        "miniapp/.env.production",
        "miniapp/.env.test",
        "app/api/uploads.py",
        "local.sqlite3",
        "local.sqlite3-wal",
        "uploads/private/image.png",
        "backups/release.sql",
        ".venv/bin/python",
        "miniapp/node_modules/pkg/index.js",
        "miniapp/dist/weapp/app.js",
        "miniapp/.env.production.local",
    ]

    violations = find_path_violations(paths)

    assert set(violations) == {
        "local.sqlite3",
        "local.sqlite3-wal",
        "uploads/private/image.png",
        "backups/release.sql",
        ".venv/bin/python",
        "miniapp/node_modules/pkg/index.js",
        "miniapp/dist/weapp/app.js",
        "miniapp/.env.production.local",
    }


def test_secret_policy_detects_high_confidence_credentials_without_echoing_them(
    tmp_path: Path,
) -> None:
    github_token = "ghp_" + ("A" * 36)
    private_key = "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key"
    (tmp_path / "token.txt").write_text(github_token, encoding="utf-8")
    (tmp_path / "key.txt").write_text(private_key, encoding="utf-8")

    findings = find_secret_findings(tmp_path, ["token.txt", "key.txt"])

    assert {(finding.path, finding.rule) for finding in findings} == {
        ("token.txt", "github_token"),
        ("key.txt", "private_key"),
    }
    assert github_token not in repr(findings)
    assert private_key not in repr(findings)


def test_secret_policy_ignores_binary_files(tmp_path: Path) -> None:
    (tmp_path / "image.bin").write_bytes(b"\x00ghp_" + (b"A" * 36))

    assert find_secret_findings(tmp_path, ["image.bin"]) == []


def test_cli_requires_a_clean_tree_and_writes_a_safe_report(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "ci-test@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "CI Test"],
        cwd=repository,
        check=True,
    )
    (repository / "README.md").write_text("safe\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test fixture"],
        cwd=repository,
        check=True,
    )
    report = tmp_path / "report.json"

    clean_result = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--root",
            str(repository),
            "--require-clean",
            "--report",
            str(report),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert clean_result.returncode == 0, clean_result.stderr.decode()
    assert json.loads(report.read_text(encoding="utf-8"))["passed"] is True

    (repository / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    dirty_result = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--root",
            str(repository),
            "--require-clean",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert dirty_result.returncode == 1
    assert b"untracked.txt" in dirty_result.stdout
