"""Gate A M7 综合代表数据的前置门槛、API 流程和凭据边界。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts.release import gatea_m7_representative_data as representative
from scripts.release import gatea_operations as gatea


def _values() -> dict[str, str]:
    return {
        "GATEA_APP_IMAGE": "pinkdoohub-gatea:" + "a" * 40,
        "GATEA_LOOPBACK_PORT": "18080",
        "WALLET_ADMIN_WRITE_ENABLED": "true",
        "WALLET_ORDER_PAYMENT_ENABLED": "true",
        "WALLET_REFUND_ENABLED": "true",
        "WALLET_TOPUP_ENABLED": "false",
        "PAYMENT_PROVIDER": "disabled",
        "PASSWORD_REGISTRATION_ENABLED": "true",
    }


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
                "--backup-id",
                "20260908t010000z",
                "--confirm-backup-id",
                "20260908t010000z",
                "--password",
                secret,
                "--apply",
            ]
        )

    assert captured.value.code == 2
    assert secret not in capsys.readouterr().err


def test_feature_flags_fail_closed() -> None:
    representative._require_feature_flags(_values())

    for name in (
        "WALLET_ADMIN_WRITE_ENABLED",
        "WALLET_ORDER_PAYMENT_ENABLED",
        "WALLET_REFUND_ENABLED",
    ):
        values = _values() | {name: "false"}
        with pytest.raises(
            representative.M7RepresentativeDataError,
            match=name,
        ):
            representative._require_feature_flags(values)

    with pytest.raises(
        representative.M7RepresentativeDataError,
        match="top-up",
    ):
        representative._require_feature_flags(
            _values() | {"WALLET_TOPUP_ENABLED": "true"}
        )


def test_runtime_feature_flags_must_match_running_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    outputs = iter(
        (
            representative.EXPECTED_RUNTIME_FEATURE_FLAGS + "\n",
            "false,false,false,false,disabled,false\n",
        )
    )

    def fake_run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=next(outputs), stderr=""
        )

    monkeypatch.setattr(
        gatea,
        "_run_compose",
        fake_run_compose,
    )

    representative._require_runtime_feature_flags(
        values=_values(),
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
    )
    with pytest.raises(
        representative.M7RepresentativeDataError,
        match="running App feature flags",
    ):
        representative._require_runtime_feature_flags(
            values=_values(),
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
        )

    assert len(calls) == 2
    for call in calls:
        arguments = call["arguments"]
        assert isinstance(arguments, tuple)
        command = arguments[-1]
        assert isinstance(command, str)
        compile(command, "<runtime-feature-flags>", "exec")
        assert "/proc/1/environ" in command
        assert "PASSWORD_REGISTRATION_ENABLED" in command
        assert "app.core.config" not in command


def test_prepare_binds_upgrade_base_data_current_backup_and_empty_m7_baseline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    base_record = tmp_path / "base.json"
    base_record.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "candidate_sha": "b" * 40,
                "image_id": "sha256:source",
                "passed": True,
                "synthetic_user_disabled": True,
                "synthetic_session_revoked": True,
                "super_admin_session_revoked": True,
                "product_ids": [10, 20],
            }
        ),
        encoding="utf-8",
    )
    before_snapshot = {"audit_logs": 21, "users": 2}
    before_images = ["hash first.png"]
    publishers: list[int] = []

    monkeypatch.setattr(representative.os, "geteuid", lambda: 0)
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: _values())
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:image")
    monkeypatch.setattr(representative, "_operations_sha", lambda path: "c" * 40)
    monkeypatch.setattr(
        gatea,
        "_require_upgrade_record",
        lambda **kwargs: {
            "source_candidate_sha": "b" * 40,
            "source_image_id": "sha256:source",
        },
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": service, "State": "running", "Health": "healthy"}
            for service in ("mysql", "redis", "app", "nginx")
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_validate_loopback_publishers",
        lambda rows, port: publishers.append(port),
    )
    monkeypatch.setattr(
        representative,
        "_require_runtime_feature_flags",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        representative.upgrade,
        "_load_verified_backup",
        lambda **kwargs: {
            "image_id": "sha256:image",
            "database_snapshot": before_snapshot,
            "image_manifest": before_images,
            "completed_at": (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat(),
        },
    )
    monkeypatch.setattr(
        representative.backup,
        "_source_snapshot",
        lambda *args: before_snapshot.copy(),
    )
    monkeypatch.setattr(
        representative.backup,
        "_source_image_manifest",
        lambda *args: before_images.copy(),
    )
    monkeypatch.setattr(
        representative,
        "_database_details",
        lambda **kwargs: representative.EXPECTED_BASELINE_DETAILS.copy(),
    )

    context = representative.prepare(
        username="owner",
        confirm_username="owner",
        backup_id="20260908t010000z",
        confirm_backup_id="20260908t010000z",
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        backup_root=tmp_path / "backups",
        backup_record_dir=tmp_path / "backup-records",
        restore_record_dir=tmp_path / "restore-records",
        release_record_dir=tmp_path / "release-records",
        base_record=base_record,
        record_dir=record_dir,
        credentials_file=record_dir / "credentials.json",
    )

    assert context.candidate_sha == "a" * 40
    assert context.operations_sha == "c" * 40
    assert context.experience_product_id == 10
    assert context.fixed_product_id == 20
    assert context.before_snapshot == before_snapshot
    assert publishers == [18080]


def test_prepare_rejects_drift_after_verified_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    base_record = tmp_path / "base.json"
    base_record.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "candidate_sha": "b" * 40,
                "image_id": "sha256:source",
                "passed": True,
                "synthetic_user_disabled": True,
                "synthetic_session_revoked": True,
                "super_admin_session_revoked": True,
                "product_ids": [10, 20],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(representative.os, "geteuid", lambda: 0)
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: _values())
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda values: "sha256:image")
    monkeypatch.setattr(representative, "_operations_sha", lambda path: "c" * 40)
    monkeypatch.setattr(
        gatea,
        "_require_upgrade_record",
        lambda **kwargs: {
            "source_candidate_sha": "b" * 40,
            "source_image_id": "sha256:source",
        },
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": service, "State": "running", "Health": "healthy"}
            for service in ("mysql", "redis", "app", "nginx")
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(gatea, "_validate_loopback_publishers", lambda *args: None)
    monkeypatch.setattr(
        representative,
        "_require_runtime_feature_flags",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        representative.upgrade,
        "_load_verified_backup",
        lambda **kwargs: {
            "image_id": "sha256:image",
            "database_snapshot": {"users": 2},
            "image_manifest": [],
        },
    )
    monkeypatch.setattr(
        representative.backup,
        "_source_snapshot",
        lambda *args: {"users": 3},
    )
    monkeypatch.setattr(
        representative.backup,
        "_source_image_manifest",
        lambda *args: [],
    )

    with pytest.raises(
        representative.M7RepresentativeDataError,
        match="changed after the verified backup",
    ):
        representative.prepare(
            username="owner",
            confirm_username="owner",
            backup_id="20260908t010000z",
            confirm_backup_id="20260908t010000z",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            release_record_dir=tmp_path / "release-records",
            base_record=base_record,
            record_dir=record_dir,
            credentials_file=record_dir / "credentials.json",
        )


class _FakeClient:
    def __init__(self) -> None:
        self.results: list[dict[str, object]] = []
        self.calls: list[str] = []
        self.order_ids = iter(range(101, 107))
        self.reservation_ids = iter(range(201, 207))

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
        if step.startswith("register-"):
            offset = {
                "register-orders-and-wallet-user": 0,
                "register-reservations-user": 1,
                "register-empty-baseline-user": 2,
            }[step]
            return {"code": 0, "data": {"id": 10 + offset}}
        if step.startswith("login-") and step.endswith("-user"):
            purpose = step.removeprefix("login-").removesuffix("-user")
            return {
                "code": 0,
                "data": {
                    "access_token": f"{purpose}-access-secret",
                    "refresh_token": f"{purpose}-refresh-secret",
                    "user": {"id": 10, "role": "user", "status": "normal"},
                },
            }
        if step == "read-base-experience":
            return {"code": 0, "data": {"id": 1, "options": [{"id": 5}]}}
        if step == "read-base-fixed-kit":
            return {
                "code": 0,
                "data": {
                    "id": 2,
                    "kit_kind": {"value": "fixed"},
                    "stock": 10,
                },
            }
        if step == "create-color-kit":
            return {"code": 0, "data": {"id": 30}}
        if step == "read-color-kit-draft":
            return {
                "code": 0,
                "data": {
                    "id": 30,
                    "colors": [
                        {
                            "id": 300 + index,
                            "is_active": True,
                            "is_configured": True,
                        }
                        for index in range(221)
                    ],
                },
            }
        if step.startswith("supply-color-"):
            return {
                "code": 0,
                "data": {"stock_units": representative.COLOR_OPENING_STOCK},
            }
        if step == "read-public-color-kit":
            return {
                "code": 0,
                "data": {
                    "id": 30,
                    "colors": [
                        {
                            "id": 300 + index,
                            "swatch_image_url": (
                                "https://api-test.pinkdoohub.cn/"
                                f"uploads/products/colors/{index}.png"
                            ),
                        }
                        for index in range(3)
                    ],
                },
            }
        if step == "create-assisted-wallet-order":
            return {"code": 0, "data": {"order": {"id": next(self.order_ids)}}}
        if step.startswith("create-") and step.endswith("-order"):
            return {"code": 0, "data": {"id": next(self.order_ids)}}
        if step in {
            "complete-wallet-experience-order",
            "complete-manual-fixed-order",
        }:
            return {"code": 0, "data": {"status": {"value": "completed"}}}
        if step == "read-reservation-booking-options":
            dates = [
                "2026-09-10",
                "2026-09-11",
                "2026-09-15",
                "2026-09-17",
                "2026-09-18",
                "2026-09-16",
            ]
            return {
                "code": 0,
                "data": {
                    "dates": [
                        {"date": value, "start_times": ["11:00"]}
                        for value in dates
                    ]
                },
            }
        if step.startswith("create-") and step.endswith("-reservation"):
            reservation_id = next(self.reservation_ids)
            payload = kwargs["payload"]
            assert isinstance(payload, dict)
            return {
                "code": 0,
                "data": {
                    "id": reservation_id,
                    "reservation_date": payload["reservation_date"],
                    "status": {"value": "pending"},
                },
            }
        if step == "confirm-reservation":
            return {"code": 0, "data": {"status": {"value": "confirmed"}}}
        if step == "reject-reservation":
            return {"code": 0, "data": {"status": {"value": "rejected"}}}
        if step == "cancel-reservation":
            return {"code": 0, "data": {"status": {"value": "cancelled"}}}
        if step.startswith("verify-"):
            expected = "pending" if step == "verify-pending-reservation" else "cancelled"
            return {"code": 0, "data": {"status": {"value": expected}}}
        if step == "rotate-baseline-refresh-family":
            return {
                "code": 0,
                "data": {
                    "access_token": "rotated-access-secret",
                    "refresh_token": "rotated-refresh-secret",
                },
            }
        return {"code": int(kwargs.get("expected_code", 0)), "data": {}}

    def request(
        self,
        step: str,
        method: str,
        path: str,
        **kwargs: object,
    ) -> tuple[bytes, dict[str, str]]:
        self._record(step)
        if step == "upload-color-kit-cover":
            document = {
                "code": 0,
                "data": {
                    "image_url": (
                        "https://api-test.pinkdoohub.cn/"
                        "uploads/products/color-cover.png"
                    )
                },
            }
            return json.dumps(document).encode(), {"Content-Type": "application/json"}
        return representative.base_data.PNG_CONTENT, {"Content-Type": "image/png"}


def _context(tmp_path: Path) -> representative.PreparedContext:
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    return representative.PreparedContext(
        values=_values(),
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=record_dir,
        credentials_file=record_dir / "credentials.json",
        candidate_sha="a" * 40,
        image_id="sha256:image",
        operations_sha="c" * 40,
        backup_id="20260908t010000z",
        fixed_product_id=2,
        experience_product_id=1,
        before_snapshot={"audit_logs": 21},
        before_image_manifest=("old image",),
        started_at="2026-09-08T01:00:00+00:00",
    )


def test_execute_creates_all_m7_scenarios_and_sanitized_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = _FakeClient()
    context = _context(tmp_path)
    monkeypatch.setattr(representative, "LoopbackClient", lambda port: fake)
    passwords = iter(("secret-orders", "secret-reservations", "secret-baseline"))
    monkeypatch.setattr(
        representative.secrets,
        "token_urlsafe",
        lambda length: next(passwords),
    )
    monkeypatch.setattr(
        representative.backup,
        "_source_snapshot",
        lambda *args: representative.EXPECTED_AFTER_SNAPSHOT | {"audit_logs": 70},
    )
    monkeypatch.setattr(
        representative,
        "_database_details",
        lambda **kwargs: representative.EXPECTED_AFTER_DETAILS.copy(),
    )
    monkeypatch.setattr(
        representative.backup,
        "_source_image_manifest",
        lambda *args: ["old image", "new image"],
    )

    record = representative.execute(
        context,
        username="owner",
        password="current-super-admin-password",
    )

    assert record["passed"] is True
    assert record["synthetic_sessions_revoked"] is True
    assert record["super_admin_session_revoked"] is True
    assert record["operations_sha"] == "c" * 40
    assert record["synthetic_user_ids"] == [10, 11, 12]
    assert record["color_product_id"] == 30
    assert len(record["order_ids"]) == 6
    assert len(record["reservation_ids"]) == 6
    assert "replay-color-supply-1" in fake.calls
    assert "wechat-recharge-disabled" in fake.calls
    assert "wechat-order-payment-disabled" in fake.calls
    assert "set-temporary-weekly-closure" in fake.calls
    assert "restore-default-weekly-closure" in fake.calls

    credentials = context.credentials_file
    assert credentials.exists()
    assert os.stat(credentials).st_mode & 0o777 == 0o600
    credential_payload = json.loads(credentials.read_text(encoding="utf-8"))
    assert [item["password"] for item in credential_payload["accounts"]] == [
        "secret-orders",
        "secret-reservations",
        "secret-baseline",
    ]
    record_path = (
        context.record_dir
        / f"{representative.RECORD_PREFIX}-{context.candidate_sha}.json"
    )
    raw_record = record_path.read_text(encoding="utf-8")
    for forbidden in (
        "owner",
        "gatea_m7_orders_user",
        "13900009701",
        "current-super-admin-password",
        "secret-orders",
        "admin-access-secret",
        "rotated-refresh-secret",
    ):
        assert forbidden not in raw_record


def test_execute_failure_revokes_sessions_and_retains_pending_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = _FakeClient()
    original = fake.json_request

    def fail_color_create(
        step: str, method: str, path: str, **kwargs: object
    ) -> dict[str, object]:
        if step == "create-color-kit":
            raise representative.M7RepresentativeDataError("controlled failure")
        return original(step, method, path, **kwargs)

    fake.json_request = fail_color_create  # type: ignore[method-assign]
    context = _context(tmp_path)
    monkeypatch.setattr(representative, "LoopbackClient", lambda port: fake)

    with pytest.raises(
        representative.M7RepresentativeDataError,
        match="controlled failure",
    ):
        representative.execute(
            context,
            username="owner",
            password="current-super-admin-password",
        )

    assert "cleanup-orders-and-wallet-logout" in fake.calls
    assert "cleanup-reservations-logout" in fake.calls
    assert "cleanup-empty-baseline-logout" in fake.calls
    assert "cleanup-super-admin-logout" in fake.calls
    assert not context.credentials_file.exists()
    assert context.credentials_file.with_suffix(".json.pending").exists()
    assert not (
        context.record_dir
        / f"{representative.RECORD_PREFIX}-{context.candidate_sha}.json"
    ).exists()
