"""在安装依赖、构建镜像前只读检查候选 Git 树与 M9 发布器契约。"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import subprocess


class SourceContractError(ValueError):
    """候选源码与发布工具的支持范围不一致。"""


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repository), *arguments), check=True,
        capture_output=True, text=True, timeout=30,
    ).stdout


def _constant(source: str, name: str) -> object:
    """只解释常量及元组拼接，绝不执行被检查的候选 Python。"""
    assignments = {
        node.targets[0].id: node.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    active: set[str] = set()

    def resolve(key: str) -> object:
        if key in active or key not in assignments:
            raise SourceContractError("missing or cyclic release constant")
        active.add(key)
        try:
            return evaluate(assignments[key])
        finally:
            active.remove(key)

    def evaluate(node: ast.AST) -> object:
        if isinstance(node, ast.Name):
            return resolve(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(left, tuple) and isinstance(right, tuple):
                return left + right
            raise SourceContractError("unsupported release constant expression")
        return ast.literal_eval(node)

    return resolve(name)


def check(repository: Path, ref: str = "HEAD") -> dict[str, object]:
    """检查不可变 Git ref；结果只用于前置反馈，不是 provenance 或部署证据。"""
    sha = _git(repository, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").strip()
    def source(path: str) -> str:
        return _git(repository, "show", f"{sha}:{path}")

    approved = _constant(source("app/tasks/gatea_migrate_step.py"), "APPROVED_MIGRATIONS")
    operations = _constant(
        source("scripts/release/gatea_operations.py"), "APPROVED_TARGET_M9_CHAIN",
    )
    target = _constant(source("scripts/release/gatea_upgrade.py"), "TARGET_VERSION")
    if (
        not isinstance(approved, tuple) or approved != operations
        or type(target) is not int or target != 9 or len(approved) != target + 1
        or not all(isinstance(name, str) for name in approved)
        or [int(name.split("_", 1)[0]) for name in approved] != list(range(target + 1))
    ):
        raise SourceContractError("migration step, operations and upgrade contracts disagree")
    actual = _git(
        repository, "ls-tree", "-r", "--name-only", sha, "--", "migrations/models",
    ).splitlines()
    expected = [f"migrations/models/{name}" for name in approved]
    if sorted(actual) != sorted(expected):
        raise SourceContractError("candidate Git tree is not the approved exact M0-M9 chain")
    mode_line = _git(
        repository, "ls-tree", sha, "--", "scripts/release/gatea_operations.py",
    ).strip()
    mode = mode_line.split(" ", 1)[0]
    if mode not in {"100644", "100755"}:
        raise SourceContractError("operations source is not a regular Git blob")
    return {
        "candidate_sha": sha, "migration_count": len(approved),
        "target_version": target, "operations_git_mode": mode,
        "operations_extracted_mode": "0755" if mode == "100755" else "0644",
        "deployment_evidence": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()
    try:
        report = check(args.repository, args.ref)
    except (ValueError, SyntaxError, OSError, subprocess.SubprocessError) as error:
        detail = str(error) if isinstance(error, SourceContractError) else type(error).__name__
        print(f"Gate A source contract failed: {detail}")
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
