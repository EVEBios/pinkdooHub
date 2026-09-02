"""Gate A 持久 SUPER_ADMIN Bootstrap 的交互、Secret 与证据边界。"""

import json
from pathlib import Path
import subprocess

import pytest

from scripts.release import gatea_bootstrap as bootstrap
from scripts.release import gatea_operations as gatea


def _values() -> dict[str, str]:
    return {
        "GATEA_APP_IMAGE": "pinkdoohub-gatea:" + "a" * 40,
        "GATEA_LOOPBACK_PORT": "18080",
    }


def test_parser_rejects_password_argument_without_echoing_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "must-not-appear"

    with pytest.raises(SystemExit) as captured:
        bootstrap._parser().parse_args(
            [
                "--username",
                "owner",
                "--nickname",
                "Owner",
                "--phone",
                "13800000101",
                "--confirm-username",
                "owner",
                "--initial-password",
                secret,
                "--apply",
            ]
        )

    assert captured.value.code == 2
    assert secret not in capsys.readouterr().err


def test_identity_and_password_validation_fail_before_any_operation() -> None:
    bootstrap._validate_identity(
        username="owner",
        nickname="Owner",
        phone="13800000101",
        confirm_username="owner",
    )
    bootstrap._validate_passwords("initial-password", "final-password")

    with pytest.raises(gatea.GateAError, match="confirmation"):
        bootstrap._validate_identity(
            username="owner",
            nickname="Owner",
            phone="13800000101",
            confirm_username="other",
        )
    with pytest.raises(gatea.GateAError, match="phone"):
        bootstrap._validate_identity(
            username="owner",
            nickname="Owner",
            phone="123",
            confirm_username="owner",
        )
    with pytest.raises(gatea.GateAError, match="must differ"):
        bootstrap._validate_passwords("same-password", "same-password")


def test_password_input_requires_tty_and_matching_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap.sys.stdin, "isatty", lambda: False)
    with pytest.raises(gatea.GateAError, match="interactive TTY"):
        bootstrap.read_passwords()

    monkeypatch.setattr(bootstrap.sys.stdin, "isatty", lambda: True)
    answers = iter(("initial-password", "different"))
    monkeypatch.setattr(bootstrap.getpass, "getpass", lambda prompt: next(answers))
    with pytest.raises(gatea.GateAError, match="confirmation"):
        bootstrap.read_passwords()


def test_secret_file_is_exclusive_group_readable_and_removed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime" / "bootstrap_password.pending"
    ownership: list[tuple[int, int]] = []
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        bootstrap.os,
        "fchown",
        lambda descriptor, uid, gid: ownership.append((uid, gid)),
    )

    parent_created = bootstrap._create_secret_file(path, "initial-password")

    assert parent_created is True
    assert path.read_text(encoding="utf-8") == "initial-password\n"
    assert path.stat().st_mode & 0o777 == 0o440
    assert ownership == [(0, gatea.APP_RUNTIME_SECRET_GID)]
    with pytest.raises(gatea.GateAError, match="already exists"):
        bootstrap._create_secret_file(path, "other-password")

    bootstrap._remove_secret_file(path, parent_created=parent_created)
    assert not path.exists()
    assert not path.parent.exists()


def _prepare_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    first_created: bool = True,
) -> tuple[Path, Path, list[str]]:
    values = _values()
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    secret_file = tmp_path / "runtime" / "bootstrap_password.pending"
    calls: list[str] = []

    monkeypatch.setattr(bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda value: "sha256:image")
    monkeypatch.setattr(gatea, "_require_migration_record", lambda **kwargs: None)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {
                "Service": name,
                "State": "running",
                "Health": "healthy",
                "Publishers": (
                    [
                        {
                            "URL": "127.0.0.1",
                            "TargetPort": 8080,
                            "PublishedPort": 18080,
                            "Protocol": "tcp",
                        }
                    ]
                    if name == "nginx"
                    else []
                ),
            }
            for name in ("mysql", "redis", "app", "nginx")
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)

    def fake_create_secret(path: Path, password: str) -> bool:
        assert password == "initial-password"
        path.parent.mkdir()
        path.write_text(password, encoding="utf-8")
        return True

    monkeypatch.setattr(bootstrap, "_create_secret_file", fake_create_secret)
    monkeypatch.setattr(
        bootstrap,
        "_run_bootstrap_compose",
        lambda **kwargs: subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    )
    results = iter((first_created, False))
    monkeypatch.setattr(
        bootstrap,
        "_run_bootstrap_once",
        lambda **kwargs: next(results),
    )
    snapshot = {
        "super_admins": 1,
        "normal_super_admins": 1,
        "bootstrap_audits": 1,
        "self_target_audits": 1,
        "user_id": 7,
        "updated_at": "2026-09-02T00:00:00.000000Z",
    }
    monkeypatch.setattr(bootstrap, "_bootstrap_snapshot", lambda **kwargs: snapshot)
    monkeypatch.setattr(bootstrap, "_bootstrap_container_absent", lambda: None)

    def fake_login(*, base_url: str, username: str, password: str) -> dict:
        calls.append(f"login:{password}")
        suffix = "initial" if password == "initial-password" else "final"
        return {
            "access_token": f"access-{suffix}",
            "refresh_token": f"refresh-{suffix}",
            "user": {"id": 7, "role": "super_admin", "status": "normal"},
        }

    monkeypatch.setattr(bootstrap, "_login", fake_login)
    monkeypatch.setattr(
        bootstrap,
        "_change_password",
        lambda **kwargs: calls.append("password-changed"),
    )
    monkeypatch.setattr(
        bootstrap,
        "_expect_login_rejected",
        lambda **kwargs: calls.append("old-password-rejected"),
    )
    monkeypatch.setattr(
        bootstrap,
        "_logout_and_verify_refresh_revoked",
        lambda **kwargs: calls.append("session-revoked"),
    )
    return record_dir, secret_file, calls


@pytest.mark.parametrize("first_created", (True, False))
def test_execute_bootstrap_records_only_sanitized_evidence_and_cleans_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    first_created: bool,
) -> None:
    record_dir, secret_file, calls = _prepare_success(
        monkeypatch,
        tmp_path,
        first_created=first_created,
    )

    bootstrap.execute_bootstrap(
        username="owner",
        nickname="Owner",
        phone="13800000101",
        confirm_username="owner",
        initial_password="initial-password",
        final_password="final-password",
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        release_record_dir=tmp_path / "release-records",
        bootstrap_record_dir=record_dir,
        secret_file=secret_file,
    )

    assert not secret_file.exists()
    assert not secret_file.parent.exists()
    record_path = record_dir / bootstrap.BOOTSTRAP_RECORD_NAME
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["created_on_this_run"] is first_created
    assert payload["strict_replay_verified"] is True
    assert payload["password_rotated"] is True
    assert payload["refresh_sessions_revoked"] is True
    assert payload["initial_secret_file_removed"] is True
    assert payload["pii_recorded"] is False
    assert payload["secret_values_recorded"] is False
    raw_record = record_path.read_text(encoding="utf-8")
    for forbidden in (
        "owner",
        "Owner",
        "13800000101",
        "initial-password",
        "final-password",
        "access-initial",
        "refresh-final",
    ):
        assert forbidden not in raw_record
    assert calls == [
        "login:initial-password",
        "session-revoked",
        "password-changed",
        "old-password-rejected",
        "login:final-password",
        "session-revoked",
    ]


def test_execute_bootstrap_cleans_secret_and_writes_no_record_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record_dir, secret_file, _ = _prepare_success(monkeypatch, tmp_path)
    monkeypatch.setattr(
        bootstrap,
        "_run_bootstrap_once",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("sensitive detail")),
    )

    with pytest.raises(gatea.GateAError, match="SUPER_ADMIN bootstrap failed"):
        bootstrap.execute_bootstrap(
            username="owner",
            nickname="Owner",
            phone="13800000101",
            confirm_username="owner",
            initial_password="initial-password",
            final_password="final-password",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            release_record_dir=tmp_path / "release-records",
            bootstrap_record_dir=record_dir,
            secret_file=secret_file,
        )

    assert not secret_file.exists()
    assert not secret_file.parent.exists()
    assert not (record_dir / bootstrap.BOOTSTRAP_RECORD_NAME).exists()


def test_existing_record_refuses_before_creating_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record_dir, secret_file, _ = _prepare_success(monkeypatch, tmp_path)
    (record_dir / bootstrap.BOOTSTRAP_RECORD_NAME).write_text(
        "{}\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        bootstrap,
        "_create_secret_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not create Secret")
        ),
    )

    with pytest.raises(gatea.GateAError, match="already recorded"):
        bootstrap.execute_bootstrap(
            username="owner",
            nickname="Owner",
            phone="13800000101",
            confirm_username="owner",
            initial_password="initial-password",
            final_password="final-password",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            release_record_dir=tmp_path / "release-records",
            bootstrap_record_dir=record_dir,
            secret_file=secret_file,
        )


def test_bootstrap_result_and_database_evidence_are_strict() -> None:
    assert bootstrap._parse_bootstrap_result(
        subprocess.CompletedProcess(
            [], 0, stdout="created=True replay=False", stderr=""
        )
    ) is True
    assert bootstrap._parse_bootstrap_result(
        subprocess.CompletedProcess(
            [], 0, stdout="created=False replay=True", stderr=""
        )
    ) is False
    with pytest.raises(gatea.GateAError, match="result marker"):
        bootstrap._parse_bootstrap_result(
            subprocess.CompletedProcess([], 0, stdout="", stderr="")
        )
    with pytest.raises(gatea.GateAError, match="database evidence"):
        bootstrap._validate_bootstrap_snapshot(
            {
                "super_admins": 2,
                "normal_super_admins": 2,
                "bootstrap_audits": 1,
                "self_target_audits": 1,
                "user_id": 7,
                "updated_at": "now",
            }
        )
