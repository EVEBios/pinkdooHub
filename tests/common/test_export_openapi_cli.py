"""OpenAPI 导出脚本的跨平台 CLI 契约。"""

import os
from pathlib import Path
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = REPOSITORY_ROOT / "scripts" / "export_openapi.py"
COMMITTED_OPENAPI = REPOSITORY_ROOT / "miniapp" / "openapi" / "openapi.json"


def _run_export_cli(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.update({"PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"})
    return subprocess.run(
        [sys.executable, str(EXPORT_SCRIPT), *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_help_is_utf8_safe_when_parent_environment_uses_cp1252() -> None:
    result = _run_export_cli("--help")

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert "输出文件" in result.stdout.decode("utf-8")


def test_cli_export_matches_the_committed_openapi_contract(tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"

    result = _run_export_cli("--output", str(output))

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert output.read_bytes() == COMMITTED_OPENAPI.read_bytes()
