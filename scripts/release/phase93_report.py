#!/usr/bin/env python3
"""把 Phase 9.3 私有原始证据收敛为不含 Secret 的交付摘要。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.phase93_operations import Phase93Operations
from scripts.release.phase93_rehearsal import RehearsalError, config_for_run


REQUIRED_PASSED_REPORTS = (
    "dr01-migrate-current.json",
    "dr01-result.json",
    "dr02-result.json",
    "dr03-result.json",
    "dr04-backup-database.json",
    "dr04-restore-database.json",
    "dr04-restore-verification.json",
    "dr05-result.json",
    "dr06-start-application.json",
    "dr06-dr07-dr09-live-smoke.json",
    "dr06-backup-images.json",
    "dr06-restore-images.json",
    "dr06-dependency-failure-result.json",
    "dr06-restart-image-persistence.json",
    "dr07-bootstrap-first.json",
    "dr07-bootstrap-replay.json",
    "dr07-bootstrap-verification.json",
    "dr09-seed-runtime-roles.json",
)


def _load_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise RehearsalError(f"required evidence is missing: {path.name}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RehearsalError(f"required evidence is invalid: {path.name}") from error
    if not isinstance(document, dict):
        raise RehearsalError(f"required evidence is not an object: {path.name}")
    return document


def _duration_seconds(document: Mapping[str, object]) -> float:
    started = datetime.fromisoformat(str(document["started_at"]))
    finished = datetime.fromisoformat(str(document["finished_at"]))
    return round((finished - started).total_seconds(), 3)


def summarize_evidence(evidence_dir: Path) -> dict[str, object]:
    """验证全部服务端场景通过，并只选择脱敏字段。"""

    reports = {
        name: _load_json(evidence_dir / name)
        for name in REQUIRED_PASSED_REPORTS
    }
    failed = [
        name for name, report in reports.items() if report.get("passed") is not True
    ]
    if failed:
        raise RehearsalError("one or more required rehearsal reports did not pass")

    manifest = _load_json(evidence_dir / "manifest.json")
    images = _load_json(evidence_dir / "image-digests.json")
    app_image = _load_json(evidence_dir / "app-image.json")
    live = reports["dr06-dr07-dr09-live-smoke.json"]
    restore = reports["dr04-restore-verification.json"]
    failure = reports["dr05-result.json"]
    backup = reports["dr04-backup-database.json"]
    restore_step = reports["dr04-restore-database.json"]

    return {
        "schema_version": 1,
        "run_id": manifest["run_id"],
        "project": manifest["project"],
        "git_sha": manifest["git_sha"],
        "compose_file_sha256": manifest["compose_file_sha256"],
        "ca_fingerprint": manifest["ca_fingerprint"],
        "versions": manifest["versions"],
        "base_images": images["images"],
        "app_image": app_image,
        "scenarios": {
            "DR-01": reports["dr01-result.json"],
            "DR-02": reports["dr02-result.json"],
            "DR-03": reports["dr03-result.json"],
            "DR-04": {
                "database_matches": restore["database_matches"],
                "images_match": restore["images_match"],
                "restore_app_ready": restore["restore_app_ready"],
                "restore_login_verified": restore["restore_login_verified"],
                "backup_sha256": backup["backup_sha256"],
                "backup_bytes": backup["backup_bytes"],
                "restore_seconds": _duration_seconds(restore_step),
                "passed": True,
            },
            "DR-05": {
                "partial_commit_proven": failure["partial_commit_proven"],
                "restored_matches": failure["restored_matches"],
                "upgraded_valid": failure["upgraded_valid"],
                "backup_seconds": failure["backup_seconds"],
                "restore_seconds": failure["restore_seconds"],
                "passed": True,
            },
            "DR-06": {
                "live_request_count": live["request_count"],
                "dependency_failure_recovery": True,
                "graceful_restart": True,
                "image_persistence": True,
                "passed": True,
            },
            "DR-07": {
                "bootstrap_first": True,
                "bootstrap_replay": True,
                "unique_user_and_audit": True,
                "login": True,
                "credential_rotated": live["bootstrap_credential_rotated"],
                "passed": True,
            },
            "DR-08": {
                "passed": False,
                "deferred_to": "Phase 9.4 iOS/Android real-device validation",
            },
            "DR-09": {
                "server_side_https_smoke_requests": live["request_count"],
                "passed": True,
                "real_device_extension": "Phase 9.4",
            },
        },
        "required_reports": list(REQUIRED_PASSED_REPORTS),
        "secret_values_recorded": False,
        "cleanup_pending": True,
        "passed": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        config = config_for_run(arguments.run_id)
        Phase93Operations(config).validate_workspace()
        summary = summarize_evidence(config.evidence_dir)
        output = Path(f"/tmp/pinkdoohub-phase93-summary-{config.run_id}.json")
        descriptor = os.open(
            output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(summary, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        print(f"Phase 9.3 sanitized summary prepared: {output}")
        return 0
    except RehearsalError as error:
        print(f"Phase 9.3 summary refused: {error}", file=sys.stderr)
    except Exception as error:
        print(
            f"Phase 9.3 summary failed safely: {type(error).__name__}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
