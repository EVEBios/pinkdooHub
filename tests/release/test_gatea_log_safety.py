"""真实扫描器回归；仅替换 Docker 日志读取这个外部边界。"""

from types import SimpleNamespace

import pytest

from scripts.release import gatea_m9_acceptance as acceptance
from scripts.release import gatea_resilience as resilience


@pytest.mark.parametrize("value,line", [
    ("fixture-user", "User logged in: user_id=1 username=fixture-user"),
    ("fixture-password", "password=fixture-password"),
    ("", "GET /api/v1/table-codes/AbCdEfGhIjKlMnOpQrStUvWxYz012345 HTTP/1.1"),
    ("", "Authorization: Bearer fixture-access-token"),
    ("", "mysql://fixture:fixture-password@mysql/db"),
])
def test_real_scanner_detects_sensitive_logs_without_returning_values(value, line):
    scan = resilience.inspect_log_text(line, (value,))
    assert scan["exact_secret_matches"] + scan["forbidden_pattern_matches"] > 0
    assert all(type(count) is int for count in scan.values())
    assert line not in str(scan)


def test_real_scanner_accepts_redacted_runtime_logs():
    scan = resilience.inspect_log_text(
        "User logged in: user_id=1\nGET /api/v1/table-codes/<redacted> HTTP/1.1",
        ("fixture-user", "fixture-password"),
    )
    assert scan == {"line_count": 2, "exact_secret_matches": 0, "forbidden_pattern_matches": 0}


@pytest.mark.parametrize("service,kind", [("app", "exact"), ("nginx", "pattern")])
def test_acceptance_scans_real_reader_output_and_reports_only_service_count(
    tmp_path, monkeypatch, service, kind,
):
    for name in acceptance.gatea.EXPECTED_SECRET_FILES:
        (tmp_path / name).write_text("fixture-deployment-" + name)
    context = SimpleNamespace(values={}, config_file=tmp_path / "config", secret_dir=tmp_path)
    token = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"
    bad = "User logged in: username=fixture-user" if kind == "exact" else "/api/v1/table-codes/" + token
    monkeypatch.setattr(
        resilience, "_compose_logs",
        lambda **kwargs: bad if kwargs["services"] == (service,) else "healthy",
    )
    with pytest.raises(acceptance.M9AcceptanceError) as caught:
        acceptance._verify_log_redaction(context, transient_secrets=("fixture-user",))
    assert f"{service}=1" in str(caught.value)
    assert "fixture-user" not in str(caught.value)
    assert token not in str(caught.value)


@pytest.mark.parametrize("logs,expected", [("", False), ("healthy", True)])
def test_acceptance_real_scanner_empty_and_safe_logs(tmp_path, monkeypatch, logs, expected):
    for name in acceptance.gatea.EXPECTED_SECRET_FILES:
        (tmp_path / name).write_text("fixture-deployment-" + name)
    context = SimpleNamespace(values={}, config_file=tmp_path / "config", secret_dir=tmp_path)
    monkeypatch.setattr(resilience, "_compose_logs", lambda **kwargs: logs)
    if expected:
        result = acceptance._verify_log_redaction(context, transient_secrets=())
        assert result["passed"] is True
        assert result["services_scanned"] == list(acceptance.M9_SERVICES)
        assert result["combined_line_count"] == 5
    else:
        with pytest.raises(acceptance.M9AcceptanceError, match="logs are empty"):
            acceptance._verify_log_redaction(context, transient_secrets=())
