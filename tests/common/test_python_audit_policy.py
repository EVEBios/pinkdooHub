"""Phase 9.2.5 Python 依赖审计策略契约。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPOSITORY_ROOT / "scripts" / "ci" / "check_python_audit.py"
POLICY = REPOSITORY_ROOT / "security" / "dependency_audit" / "python-policy.json"


def _report(*, version: str = "0.19.2", advisory: str = "PYSEC-2026-1325") -> dict:
    return {
        "dependencies": [
            {
                "name": "ecdsa",
                "version": version,
                "vulns": [
                    {
                        "id": advisory,
                        "fix_versions": [],
                        "aliases": ["GHSA-wj6h-64fc-37mp", "CVE-2024-23342"],
                    }
                ],
            }
        ],
        "fixes": [],
    }


def _run(tmp_path: Path, report: dict, policy_path: Path = POLICY) -> subprocess.CompletedProcess[str]:
    report_path = tmp_path / "audit.json"
    summary_path = tmp_path / "summary.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return subprocess.run(
        [
            str(REPOSITORY_ROOT / ".venv" / "bin" / "python"),
            str(CHECKER),
            "--report",
            str(report_path),
            "--policy",
            str(policy_path),
            "--summary",
            str(summary_path),
            "--today",
            "2026-08-31",
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_current_python_exception_is_exact_and_accepted(tmp_path: Path) -> None:
    result = _run(tmp_path, _report())

    assert result.returncode == 0, result.stderr
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["passed"] is True
    assert summary["vulnerability_count"] == 1
    assert summary["canonical_advisories"] == ["GHSA-wj6h-64fc-37mp"]


def test_new_advisory_fails_closed(tmp_path: Path) -> None:
    report = _report()
    report["dependencies"].append(
        {
            "name": "new-package",
            "version": "1.0.0",
            "vulns": [{"id": "PYSEC-2099-1", "fix_versions": ["1.0.1"], "aliases": []}],
        }
    )

    result = _run(tmp_path, report)

    assert result.returncode == 1
    assert "unexpected vulnerability" in result.stderr.lower()


def test_changed_version_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path, _report(version="0.19.3"))

    assert result.returncode == 1
    assert "unexpected vulnerability" in result.stderr.lower()


def test_expired_exception_fails_closed(tmp_path: Path) -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    policy["expires_on"] = "2026-08-30"
    policy_path = tmp_path / "expired-policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    result = _run(tmp_path, _report(), policy_path)

    assert result.returncode == 1
    assert "expired" in result.stderr.lower()
