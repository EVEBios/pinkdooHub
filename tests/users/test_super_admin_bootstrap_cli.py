"""SUPER_ADMIN Bootstrap CLI 的 Secret 和确认边界。"""

import logging
import sys

import pytest
from pydantic import ValidationError

from app.common.constants.bootstrap import SUPER_ADMIN_BOOTSTRAP_PASSWORD_ENV
from app.services.super_admin_bootstrap_service import SuperAdminBootstrapResult
from app.tasks import super_admin_bootstrap as command


def test_parser_rejects_password_argument_without_echoing_value(capsys) -> None:
    secret = "must-not-appear-in-parser-error"

    with pytest.raises(SystemExit) as error:
        command.build_parser().parse_args(
            [
                "--username",
                "owner",
                "--nickname",
                "Owner",
                "--phone",
                "13800000101",
                "--password",
                secret,
                "--apply",
            ]
        )

    assert error.value.code == 2
    captured = capsys.readouterr()
    assert secret not in captured.err
    assert "invalid arguments" in captured.err


def test_main_requires_apply_before_reading_password(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "super-admin-bootstrap",
            "--username",
            "owner",
            "--nickname",
            "Owner",
            "--phone",
            "13800000101",
        ],
    )
    monkeypatch.setattr(
        command,
        "read_password",
        lambda: (_ for _ in ()).throw(AssertionError("must not read password")),
    )

    with caplog.at_level(logging.ERROR):
        exit_code = command.main()

    assert exit_code == 2
    assert "--apply is required" in caplog.text


def test_non_interactive_password_requires_secret_environment(
    monkeypatch,
) -> None:
    monkeypatch.delenv(SUPER_ADMIN_BOOTSTRAP_PASSWORD_ENV, raising=False)
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: False)

    with pytest.raises(RuntimeError, match=SUPER_ADMIN_BOOTSTRAP_PASSWORD_ENV):
        command.read_password()


def test_validation_summary_does_not_echo_password() -> None:
    secret = "xyZ$7!"

    with pytest.raises(ValidationError) as error:
        command.validate_input(
            username="owner",
            password=secret,
            nickname="Owner",
            phone="13800000101",
        )

    summary = command._safe_validation_summary(error.value)
    assert secret not in summary
    assert "password:string_too_short" in summary


def test_main_uses_environment_secret_without_logging_it(
    monkeypatch,
    caplog,
) -> None:
    secret = "bootstrap-secret-123"
    monkeypatch.setenv(SUPER_ADMIN_BOOTSTRAP_PASSWORD_ENV, secret)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "super-admin-bootstrap",
            "--username",
            "owner",
            "--nickname",
            "Owner",
            "--phone",
            "13800000101",
            "--apply",
        ],
    )

    async def successful_run(data) -> SuperAdminBootstrapResult:
        assert data.password == secret
        return SuperAdminBootstrapResult(user_id=7, created=True)

    monkeypatch.setattr(command, "run", successful_run)

    with caplog.at_level(logging.INFO):
        exit_code = command.main()

    assert exit_code == 0
    assert "user_id=7 created=True replay=False" in caplog.text
    assert secret not in caplog.text
