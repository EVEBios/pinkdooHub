"""Gate A 代表性数据的交互、API、验收与脱敏 Record 边界。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release import gatea_operations as gatea
from scripts.release import gatea_representative_data as representative


def _values() -> dict[str, str]:
    return {
        "GATEA_APP_IMAGE": "pinkdoohub-gatea:" + "a" * 40,
        "GATEA_LOOPBACK_PORT": "18080",
    }


def _bootstrap_record(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "passed": True,
                "candidate_sha": "a" * 40,
                "image_id": "sha256:image",
                "super_admin_count": 1,
                "password_rotated": True,
                "initial_secret_file_removed": True,
                "pii_recorded": False,
                "secret_values_recorded": False,
            }
        ),
        encoding="utf-8",
    )


def test_parser_rejects_password_argument_without_echoing_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "must-not-appear"

    with pytest.raises(SystemExit) as captured:
        representative._parser().parse_args(
            [
                "--super-admin-username",
                "owner",
                "--confirm-super-admin-username",
                "owner",
                "--password",
                secret,
                "--apply",
            ]
        )

    assert captured.value.code == 2
    assert secret not in capsys.readouterr().err


def test_identity_password_and_snapshot_validation_are_strict() -> None:
    representative._validate_identity("owner", "owner")
    representative._validate_password("current-password", "current-password")
    representative._assert_snapshot(
        representative.BASELINE_SNAPSHOT,
        representative.BASELINE_SNAPSHOT,
        "test",
    )

    with pytest.raises(representative.RepresentativeDataError, match="username"):
        representative._validate_identity("owner", "other")
    with pytest.raises(representative.RepresentativeDataError, match="password"):
        representative._validate_password("current-password", "different")
    with pytest.raises(representative.RepresentativeDataError, match="users"):
        representative._assert_snapshot(
            representative.BASELINE_SNAPSHOT | {"users": 2},
            representative.BASELINE_SNAPSHOT,
            "test",
        )


def test_prepare_requires_bootstrap_empty_business_baseline_and_no_images(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record_dir = tmp_path / "representative"
    record_dir.mkdir()
    bootstrap_record = tmp_path / "bootstrap.json"
    _bootstrap_record(bootstrap_record)
    validated_publishers: list[int] = []

    monkeypatch.setattr(representative.os, "geteuid", lambda: 0)
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: _values())
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:image")
    monkeypatch.setattr(gatea, "_require_migration_record", lambda **kwargs: None)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in ("mysql", "redis", "app", "nginx")
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_validate_loopback_publishers",
        lambda rows, port: validated_publishers.append(port),
    )
    monkeypatch.setattr(
        representative.gatea_backup,
        "_source_snapshot",
        lambda *args: representative.BASELINE_SNAPSHOT.copy(),
    )
    monkeypatch.setattr(
        representative.gatea_backup,
        "_source_image_manifest",
        lambda *args: [],
    )

    context = representative.prepare(
        username="owner",
        confirm_username="owner",
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        release_record_dir=tmp_path / "release-records",
        bootstrap_record=bootstrap_record,
        record_dir=record_dir,
    )

    assert context.candidate_sha == "a" * 40
    assert context.image_id == "sha256:image"
    assert context.before_snapshot == representative.BASELINE_SNAPSHOT
    assert validated_publishers == [18080]


def test_prepare_rejects_nonempty_baseline_before_api_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record_dir = tmp_path / "representative"
    record_dir.mkdir()
    bootstrap_record = tmp_path / "bootstrap.json"
    _bootstrap_record(bootstrap_record)

    monkeypatch.setattr(representative.os, "geteuid", lambda: 0)
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: _values())
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:image")
    monkeypatch.setattr(gatea, "_require_migration_record", lambda **kwargs: None)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in ("mysql", "redis", "app", "nginx")
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(gatea, "_validate_loopback_publishers", lambda *args: None)
    monkeypatch.setattr(
        representative.gatea_backup,
        "_source_snapshot",
        lambda *args: representative.BASELINE_SNAPSHOT | {"products": 1},
    )

    with pytest.raises(
        representative.RepresentativeDataError,
        match="pre-write.*products",
    ):
        representative.prepare(
            username="owner",
            confirm_username="owner",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            release_record_dir=tmp_path / "release-records",
            bootstrap_record=bootstrap_record,
            record_dir=record_dir,
        )


def test_multipart_contains_only_fixed_png_and_declared_fields() -> None:
    body, content_type = representative._multipart_image(
        {"is_cover": "true", "sort": "0"}
    )

    assert content_type.startswith("multipart/form-data; boundary=gatea-")
    assert representative.PNG_CONTENT in body
    assert b'filename="gatea-representative.png"' in body
    assert b'name="is_cover"' in body
    assert b'name="sort"' in body


class _FakeClient:
    def __init__(self) -> None:
        self.results: list[dict[str, object]] = []
        self.calls: list[str] = []

    def _record(self, step: str) -> None:
        self.calls.append(step)
        self.results.append({"step": step, "passed": True})

    def json_request(
        self,
        step: str,
        method: str,
        path: str,
        **kwargs: object,
    ) -> dict[str, object]:
        self._record(step)
        if step == "login-super-admin":
            return {
                "code": 0,
                "data": {
                    "access_token": "admin-access-secret",
                    "refresh_token": "admin-refresh-secret",
                    "user": {"id": 1, "role": "super_admin", "status": "normal"},
                },
            }
        if step == "register-synthetic-user":
            return {"code": 0, "data": {"id": 2}}
        if step == "login-synthetic-user":
            return {
                "code": 0,
                "data": {
                    "access_token": "user-access-secret",
                    "refresh_token": "user-refresh-secret",
                    "user": {"id": 2, "role": "user", "status": "normal"},
                },
            }
        if step == "create-experience":
            return {"code": 0, "data": {"id": 10}}
        if step == "create-experience-option":
            return {"code": 0, "data": {"id": 11}}
        if step == "create-kit":
            return {"code": 0, "data": {"id": 20}}
        if step == "adjust-kit-stock":
            return {"code": 0, "data": {"stock": 10}}
        if step == "create-cancellable-mixed-order":
            return {"code": 0, "data": {"id": 30}}
        if step == "cancel-mixed-order":
            return {"code": 0, "data": {"status": {"value": "cancelled"}}}
        if step == "create-completable-order":
            return {"code": 0, "data": {"id": 31}}
        if step == "complete-order":
            return {"code": 0, "data": {"status": {"value": "completed"}}}
        return {"code": int(kwargs.get("expected_code", 0)), "data": {}}

    def request(
        self,
        step: str,
        method: str,
        path: str,
        **kwargs: object,
    ) -> tuple[bytes, dict[str, str]]:
        self._record(step)
        if step.startswith("upload-"):
            payload = {
                "code": 0,
                "data": {
                    "image_url": (
                        "https://api-test.pinkdoohub.cn/uploads/products/"
                        f"{step}.png"
                    )
                },
            }
            return json.dumps(payload).encode(), {"Content-Type": "application/json"}
        return representative.PNG_CONTENT, {"Content-Type": "image/png"}


def _context(tmp_path: Path) -> representative.PreparedContext:
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    return representative.PreparedContext(
        values=_values(),
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=record_dir,
        candidate_sha="a" * 40,
        image_id="sha256:image",
        before_snapshot=representative.BASELINE_SNAPSHOT.copy(),
        started_at="2026-09-02T00:00:00+00:00",
    )


def test_execute_uses_formal_api_disables_fixture_and_writes_sanitized_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_client = _FakeClient()
    context = _context(tmp_path)
    monkeypatch.setattr(
        representative,
        "LoopbackClient",
        lambda port: fake_client,
    )
    monkeypatch.setattr(
        representative.secrets,
        "token_urlsafe",
        lambda length: "synthetic-password-secret",
    )
    monkeypatch.setattr(
        representative.gatea_backup,
        "_source_snapshot",
        lambda *args: representative.EXPECTED_SNAPSHOT | {"audit_logs": 21},
    )
    monkeypatch.setattr(
        representative,
        "_representative_details",
        lambda context: representative.EXPECTED_DETAILS.copy(),
    )
    monkeypatch.setattr(
        representative.gatea_backup,
        "_source_image_manifest",
        lambda *args: ["a file-1.png", "b file-2.png", "c file-3.png"],
    )

    payload = representative.execute(
        context,
        username="owner",
        password="current-super-admin-password",
    )

    assert payload["passed"] is True
    assert payload["synthetic_user_disabled"] is True
    assert payload["synthetic_session_revoked"] is True
    assert payload["super_admin_session_revoked"] is True
    assert payload["image_file_count"] == 3
    assert payload["product_ids"] == [10, 20]
    assert payload["order_ids"] == [30, 31]
    assert "disable-synthetic-user" in fake_client.calls
    assert "synthetic-user-refresh-revoked" in fake_client.calls
    assert "super-admin-refresh-revoked" in fake_client.calls

    raw_record = (context.record_dir / representative.RECORD_NAME).read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "owner",
        representative.SYNTHETIC_USERNAME,
        representative.SYNTHETIC_PHONE,
        "current-super-admin-password",
        "synthetic-password-secret",
        "admin-access-secret",
        "user-refresh-secret",
    ):
        assert forbidden not in raw_record


def test_execute_failure_revokes_sessions_disables_fixture_and_writes_no_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_client = _FakeClient()
    original = fake_client.json_request

    def fail_after_user_login(
        step: str, method: str, path: str, **kwargs: object
    ) -> dict[str, object]:
        if step == "create-experience":
            raise representative.RepresentativeDataError("controlled failure")
        return original(step, method, path, **kwargs)

    fake_client.json_request = fail_after_user_login  # type: ignore[method-assign]
    context = _context(tmp_path)
    monkeypatch.setattr(representative, "LoopbackClient", lambda port: fake_client)

    with pytest.raises(representative.RepresentativeDataError, match="controlled"):
        representative.execute(
            context,
            username="owner",
            password="current-super-admin-password",
        )

    assert "cleanup-synthetic-user-logout" in fake_client.calls
    assert "cleanup-disable-synthetic-user" in fake_client.calls
    assert "cleanup-super-admin-logout" in fake_client.calls
    assert not (context.record_dir / representative.RECORD_NAME).exists()
