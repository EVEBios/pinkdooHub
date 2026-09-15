#!/usr/bin/env python3
"""严格比对 pip-audit 原始 JSON 与已审批、可到期的风险策略。"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any


REQUIRED_REVIEW_FIELDS = {
    "actual_usage",
    "decision",
    "dependency_paths",
    "fix_options",
    "rationale",
    "reachability",
    "regression_scope",
}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid {label} JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {label} JSON object: {path}")
    return value


def _canonical_advisory(vulnerability: dict[str, Any]) -> str:
    identifiers = [vulnerability.get("id"), *vulnerability.get("aliases", [])]
    for identifier in identifiers:
        if isinstance(identifier, str) and identifier.startswith("GHSA-"):
            return identifier
    identifier = vulnerability.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("Audit vulnerability is missing an advisory identifier")
    return identifier


def _audit_findings(report: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list) or "fixes" not in report:
        raise ValueError("Invalid pip-audit report: dependencies/fixes are required")
    findings: dict[tuple[str, str, str], dict[str, Any]] = {}
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise ValueError("Invalid pip-audit report dependency")
        name = dependency.get("name")
        version = dependency.get("version")
        vulnerabilities = dependency.get("vulns")
        if not isinstance(name, str) or not isinstance(version, str) or not isinstance(vulnerabilities, list):
            raise ValueError("Invalid pip-audit report dependency fields")
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise ValueError("Invalid pip-audit vulnerability")
            canonical = _canonical_advisory(vulnerability)
            aliases = {
                identifier
                for identifier in [vulnerability.get("id"), *vulnerability.get("aliases", [])]
                if isinstance(identifier, str) and identifier
            }
            key = (name, version, canonical)
            findings[key] = {
                "aliases": sorted(aliases),
                "fix_versions": sorted(vulnerability.get("fix_versions", [])),
            }
    return findings


def _parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"Policy {field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Policy {field} must be an ISO date") from exc


def _policy_findings(policy: dict[str, Any], today: date) -> dict[tuple[str, str, str], dict[str, Any]]:
    if policy.get("schema_version") != 1:
        raise ValueError("Unsupported Python audit policy schema_version")
    if policy.get("tool") != {"name": "pip-audit", "version": "2.10.1"}:
        raise ValueError("Python audit policy must pin pip-audit 2.10.1")
    if policy.get("audited_scope") != "requirements.txt exact pins":
        raise ValueError("Python audit policy audited_scope is invalid")
    for field in ("owner", "risk_accepted_by"):
        if not isinstance(policy.get(field), str) or not policy[field].strip():
            raise ValueError(f"Python audit policy {field} is required")
    reviewed_on = _parse_date(policy.get("reviewed_on"), "reviewed_on")
    expires_on = _parse_date(policy.get("expires_on"), "expires_on")
    if reviewed_on > today:
        raise ValueError("Python audit policy review date is in the future")
    if expires_on < today:
        raise ValueError("Python audit policy has expired")
    if (expires_on - reviewed_on).days > 92:
        raise ValueError("Python audit policy exception exceeds 92 days")

    expected = policy.get("expected_vulnerabilities")
    if not isinstance(expected, list):
        raise ValueError("Python audit policy expected_vulnerabilities is required")
    findings: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in expected:
        if not isinstance(item, dict):
            raise ValueError("Invalid Python audit policy vulnerability")
        missing = REQUIRED_REVIEW_FIELDS - item.keys()
        if missing:
            raise ValueError(f"Python audit policy review fields missing: {sorted(missing)}")
        if item["decision"] != "time-boxed-exception" or item["reachability"] == "unknown":
            raise ValueError("Python audit exception must be time-boxed with known reachability")
        for field in ("actual_usage", "fix_options", "rationale", "regression_scope"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise ValueError(f"Python audit policy {field} is required")
        if not isinstance(item["dependency_paths"], list) or not item["dependency_paths"]:
            raise ValueError("Python audit policy dependency_paths is required")
        key = (item.get("package"), item.get("installed_version"), item.get("canonical_advisory"))
        if not all(isinstance(value, str) and value for value in key):
            raise ValueError("Python audit policy package/version/advisory is invalid")
        if key in findings:
            raise ValueError(f"Duplicate Python audit policy finding: {key}")
        findings[key] = {
            "aliases": sorted(item.get("identifiers", [])),
            "fix_versions": sorted(item.get("fix_versions", [])),
        }
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    errors: list[str] = []
    try:
        report = _read_json(arguments.report, "pip-audit report")
        policy = _read_json(arguments.policy, "Python audit policy")
        actual = _audit_findings(report)
        expected = _policy_findings(policy, arguments.today)
        for key in sorted(actual.keys() - expected.keys()):
            errors.append(f"Unexpected vulnerability: {key[0]} {key[1]} {key[2]}")
        for key in sorted(expected.keys() - actual.keys()):
            errors.append(f"Policy finding is no longer present: {key[0]} {key[1]} {key[2]}")
        for key in sorted(actual.keys() & expected.keys()):
            if actual[key] != expected[key]:
                errors.append(f"Vulnerability metadata changed: {key[0]} {key[1]} {key[2]}")
    except ValueError as exc:
        actual = {}
        policy = {}
        errors.append(str(exc))

    summary = {
        "schema_version": 1,
        "passed": not errors,
        "audit_tool": "pip-audit 2.10.1",
        "audited_scope": "requirements.txt exact pins",
        "vulnerability_count": len(actual),
        "canonical_advisories": sorted({key[2] for key in actual}),
        "policy_expires_on": policy.get("expires_on"),
        "errors": errors,
    }
    arguments.summary.parent.mkdir(parents=True, exist_ok=True)
    arguments.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Python dependency audit policy passed: vulnerabilities={len(actual)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
