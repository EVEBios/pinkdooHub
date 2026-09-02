#!/usr/bin/env python3
"""检查 Git 跟踪文件、敏感内容与工作树卫生状态。"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Iterable


ALLOWED_ENV_FILES = {
    ".env.example",
    "miniapp/.env.development",
    "miniapp/.env.production",
    "miniapp/.env.test",
}
FORBIDDEN_DIRECTORY_NAMES = {
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "backups",
    "build",
    "dist",
    "logs",
    "node_modules",
    "uploads",
    "venv",
}
FORBIDDEN_SUFFIXES = {
    ".bak",
    ".db",
    ".db-shm",
    ".db-wal",
    ".key",
    ".log",
    ".manifest",
    ".orig",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".sqlite",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
    ".tmp",
}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:EC |OPENSSH |RSA )?PRIVATE KEY-----"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,255}"),
    "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "openai_key": re.compile(r"sk-[A-Za-z0-9_-]{32,}"),
}
SENSITIVE_ENV_KEYS = {
    "DB_PASSWORD",
    "JWT_SECRET_KEY",
    "REDIS_URL",
    "TARO_APP_APPSECRET",
    "WECHAT_APPSECRET",
}


@dataclass(frozen=True)
class SecretFinding:
    """不包含命中原文的 Secret 发现。"""

    path: str
    rule: str


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _is_env_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def find_path_violations(paths: Iterable[str]) -> list[str]:
    """返回不允许进入 Git 的本地数据或生成物路径。"""

    violations: list[str] = []
    for raw_path in paths:
        path = _normalize_path(raw_path)
        pure_path = PurePosixPath(path)
        if path in ALLOWED_ENV_FILES:
            continue
        suffixes = {suffix.lower() for suffix in pure_path.suffixes}
        if (
            any(part in FORBIDDEN_DIRECTORY_NAMES for part in pure_path.parts)
            or any(part.lower().endswith("venv") for part in pure_path.parts[:-1])
            or bool(suffixes & FORBIDDEN_SUFFIXES)
            or _is_env_file(path)
        ):
            violations.append(path)
    return sorted(set(violations))


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().strip('"\'').lower()
    return (
        not normalized
        or normalized in {"change-me", "changeme"}
        or "example" in normalized
        or "placeholder" in normalized
        or normalized.startswith("<")
    )


def _env_secret_rule(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        key = key.strip()
        if key not in SENSITIVE_ENV_KEYS or _looks_like_placeholder(value):
            continue
        if key == "REDIS_URL":
            if re.search(r"redis(?:s)?://[^/@\s]+:[^/@\s]+@", value):
                return "sensitive_env_value"
            continue
        return "sensitive_env_value"
    return None


def find_secret_findings(root: Path, paths: Iterable[str]) -> list[SecretFinding]:
    """扫描高置信 Secret 格式；只返回路径和规则名。"""

    findings: list[SecretFinding] = []
    for raw_path in paths:
        path = _normalize_path(raw_path)
        absolute_path = root / path
        if not absolute_path.is_file():
            continue
        content = absolute_path.read_bytes()
        if b"\x00" in content:
            continue
        text = content.decode("utf-8", errors="replace")
        for rule, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(SecretFinding(path=path, rule=rule))
        if _is_env_file(path):
            rule = _env_secret_rule(text)
            if rule:
                findings.append(SecretFinding(path=path, rule=rule))
    return sorted(set(findings), key=lambda finding: (finding.path, finding.rule))


def _run_git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _tracked_paths(root: Path) -> list[str]:
    result = _run_git(root, "ls-files", "-z")
    if result.returncode != 0:
        raise RuntimeError("git ls-files failed")
    return [
        path.decode("utf-8")
        for path in result.stdout.split(b"\0")
        if path
    ]


def _clean_tree_findings(root: Path) -> list[str]:
    result = _run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if result.returncode != 0:
        raise RuntimeError("git status failed")
    return [line[3:] for line in result.stdout.decode("utf-8").splitlines() if line]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Git 仓库根目录",
    )
    parser.add_argument("--report", type=Path, help="可选 JSON 报告路径")
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="同时要求工作树没有 tracked/untracked 变化",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    root = arguments.root.resolve()
    tracked_paths = _tracked_paths(root)
    path_violations = find_path_violations(tracked_paths)
    secret_findings = find_secret_findings(root, tracked_paths)
    dirty_paths = _clean_tree_findings(root) if arguments.require_clean else []
    report = {
        "schema_version": 1,
        "tracked_file_count": len(tracked_paths),
        "path_violations": path_violations,
        "secret_findings": [asdict(finding) for finding in secret_findings],
        "dirty_paths": dirty_paths,
        "passed": not path_violations and not secret_findings and not dirty_paths,
    }
    if arguments.report:
        report_path = arguments.report.resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if path_violations:
        print("Repository hygiene failed: forbidden tracked paths:")
        for path in path_violations:
            print(f"- {path}")
    if secret_findings:
        print("Repository hygiene failed: high-confidence Secret markers:")
        for finding in secret_findings:
            print(f"- {finding.path}: {finding.rule}")
    if dirty_paths:
        print("Repository hygiene failed: working tree is not clean:")
        for path in dirty_paths:
            print(f"- {path}")
    if report["passed"]:
        print(f"Repository hygiene passed: tracked_files={len(tracked_paths)}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
