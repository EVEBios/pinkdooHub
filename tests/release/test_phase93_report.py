"""Phase 9.3 脱敏摘要只接受完整通过证据。"""

import json
from pathlib import Path

import pytest

from scripts.release.phase93_rehearsal import RehearsalError
from scripts.release.phase93_report import REQUIRED_PASSED_REPORTS, summarize_evidence


def test_summary_refuses_missing_required_evidence(tmp_path: Path) -> None:
    with pytest.raises(RehearsalError, match="missing"):
        summarize_evidence(tmp_path)


def test_summary_refuses_a_failed_required_report(tmp_path: Path) -> None:
    for name in REQUIRED_PASSED_REPORTS:
        (tmp_path / name).write_text(
            json.dumps({"passed": name != "dr01-result.json"}),
            encoding="utf-8",
        )

    with pytest.raises(RehearsalError, match="did not pass"):
        summarize_evidence(tmp_path)
