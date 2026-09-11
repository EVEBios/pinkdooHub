"""Gate A 持久部署预检与生命周期命令边界。"""

from contextlib import nullcontext
import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest

from scripts.release import gatea_operations as gatea
from scripts.release.gatea_operations import (
    GateAError,
    compose_command,
    parse_env_file,
    validate_config_values,
)


def _valid_values() -> dict[str, str]:
    return {
        "GATEA_APP_IMAGE": "pinkdoohub-gatea:" + "a" * 40,
        "GATEA_API_HOST": "api-test.pinkdoohub.cn",
        "GATEA_LOOPBACK_PORT": "18080",
        "GATEA_LETSENCRYPT_DIR": "/etc/letsencrypt",
        "GATEA_ACME_CHALLENGE_DIR": "/srv/pinkdoohub/gatea/acme",
        "APP_VERSION": "0.6.0",
        "APP_ENV": "production",
        "APP_DEBUG": "false",
        "DB_ENGINE": "mysql",
        "DB_HOST": "mysql",
        "DB_PORT": "3306",
        "DB_NAME": "pinkdoohub_gatea",
        "DB_USER": "pinkdoo_app",
        "PRODUCT_IMAGE_UPLOAD_DIR": "/data/images",
        "PRODUCT_IMAGE_BASE_URL": (
            "https://api-test.pinkdoohub.cn/uploads/products"
        ),
        "JWT_ALGORITHM": "HS256",
    }


def _mock_root_lock_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    real_fstat = os.fstat

    def root_fstat(descriptor: int) -> SimpleNamespace:
        metadata = real_fstat(descriptor)
        return SimpleNamespace(
            st_mode=metadata.st_mode,
            st_uid=0,
            st_gid=0,
        )

    monkeypatch.setattr(gatea.os, "fstat", root_fstat)


def test_operation_lock_uses_fixed_secure_nonblocking_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "gatea-operation.lock"
    real_open = os.open
    opened: list[tuple[Path, int, int]] = []

    def tracked_open(value: Path, flags: int, mode: int) -> int:
        opened.append((value, flags, mode))
        return real_open(value, flags, mode)

    monkeypatch.setattr(gatea.os, "open", tracked_open)
    _mock_root_lock_metadata(monkeypatch)

    with gatea.operation_lock(_path=path):
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        with pytest.raises(GateAError, match="Another Gate A operation is active"):
            with gatea.operation_lock(_path=path):
                pass

    assert path.is_file()
    assert gatea.DEFAULT_OPERATION_LOCK_FILE == Path(
        "/run/lock/pinkdoohub-gatea-operation.lock"
    )
    assert opened
    _, flags, mode = opened[0]
    assert flags & os.O_RDWR
    assert flags & os.O_CREAT
    assert flags & os.O_CLOEXEC
    assert flags & os.O_NOFOLLOW
    assert mode == 0o600


@pytest.mark.parametrize(
    ("file_type", "mode", "uid", "gid"),
    (
        (stat.S_IFDIR, 0o600, 0, 0),
        (stat.S_IFREG, 0o640, 0, 0),
        (stat.S_IFREG, 0o600, 1, 0),
        (stat.S_IFREG, 0o600, 0, 1),
    ),
)
def test_operation_lock_rejects_unsafe_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_type: int,
    mode: int,
    uid: int,
    gid: int,
) -> None:
    path = tmp_path / "gatea-operation.lock"
    path.touch(mode=0o600)
    monkeypatch.setattr(
        gatea.os,
        "fstat",
        lambda descriptor: SimpleNamespace(
            st_mode=file_type | mode,
            st_uid=uid,
            st_gid=gid,
        ),
    )

    with pytest.raises(GateAError, match="operation lock is unsafe"):
        with gatea.operation_lock(_path=path):
            pass


def test_operation_lock_rejects_symlink(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.lock"
    target.touch(mode=0o600)
    path = tmp_path / "gatea-operation.lock"
    path.symlink_to(target)

    with pytest.raises(GateAError, match="operation lock is unavailable"):
        with gatea.operation_lock(_path=path):
            pass


def test_operation_lock_releases_after_body_error_without_unlinking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "gatea-operation.lock"
    _mock_root_lock_metadata(monkeypatch)

    with pytest.raises(RuntimeError, match="operation failed"):
        with gatea.operation_lock(_path=path):
            raise RuntimeError("operation failed")

    assert path.is_file()
    with gatea.operation_lock(_path=path):
        assert path.is_file()


@pytest.mark.parametrize(
    ("work_signal", "work_error_type", "recovery_signal"),
    (
        (gatea.signal.SIGHUP, gatea.GateAOperationInterrupted, gatea.signal.SIGINT),
        (gatea.signal.SIGTERM, gatea.GateAOperationInterrupted, gatea.signal.SIGINT),
        (gatea.signal.SIGINT, KeyboardInterrupt, gatea.signal.SIGTERM),
    ),
)
def test_operation_termination_guard_covers_all_control_signals_and_restores(
    monkeypatch: pytest.MonkeyPatch,
    work_signal: int,
    work_error_type: type[BaseException],
    recovery_signal: int,
) -> None:
    previous = {
        gatea.signal.SIGHUP: object(),
        gatea.signal.SIGTERM: object(),
        gatea.signal.SIGINT: object(),
    }
    active_handlers: dict[int, object] = {}

    monkeypatch.setattr(
        gatea.signal,
        "getsignal",
        lambda signum: previous[signum],
    )
    monkeypatch.setattr(
        gatea.signal,
        "signal",
        lambda signum, handler: active_handlers.__setitem__(signum, handler),
    )

    first_interruption: BaseException | None = None
    with pytest.raises(work_error_type) as propagated:
        with gatea.operation_termination_guard() as controller:
            assert set(active_handlers) == set(previous)
            interrupt = active_handlers[work_signal]
            assert callable(interrupt)
            with pytest.raises(work_error_type) as caught:
                interrupt(work_signal, None)
            first_interruption = caught.value
            assert controller.work_interruption is first_interruption

            deferred = active_handlers[recovery_signal]
            assert callable(deferred)
            assert deferred(recovery_signal, None) is None
            remembered = controller.deferred_interruption
            assert remembered is not None
            assert deferred(recovery_signal, None) is None
            assert controller.deferred_interruption is remembered

    assert propagated.value is first_interruption
    assert active_handlers == previous


def test_operation_termination_guard_preserves_body_error_before_deferred_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = {
        gatea.signal.SIGHUP: object(),
        gatea.signal.SIGTERM: object(),
        gatea.signal.SIGINT: object(),
    }
    active_handlers: dict[int, object] = {}
    monkeypatch.setattr(
        gatea.signal,
        "getsignal",
        lambda signum: previous[signum],
    )
    monkeypatch.setattr(
        gatea.signal,
        "signal",
        lambda signum, handler: active_handlers.__setitem__(signum, handler),
    )

    original = GateAError("original work failure")
    with pytest.raises(GateAError, match="original work failure") as caught:
        with gatea.operation_termination_guard() as controller:
            controller.begin_recovery()
            handler = active_handlers[gatea.signal.SIGINT]
            assert callable(handler)
            assert handler(gatea.signal.SIGINT, None) is None
            raise original

    assert caught.value is original
    assert active_handlers == previous


def test_operation_termination_guard_propagates_late_deferred_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = {
        gatea.signal.SIGHUP: object(),
        gatea.signal.SIGTERM: object(),
        gatea.signal.SIGINT: object(),
    }
    active_handlers: dict[int, object] = {}
    monkeypatch.setattr(
        gatea.signal,
        "getsignal",
        lambda signum: previous[signum],
    )
    monkeypatch.setattr(
        gatea.signal,
        "signal",
        lambda signum, handler: active_handlers.__setitem__(signum, handler),
    )

    with pytest.raises(KeyboardInterrupt, match="received SIGINT"):
        with gatea.operation_termination_guard() as controller:
            controller.begin_recovery()
            handler = active_handlers[gatea.signal.SIGINT]
            assert callable(handler)
            assert handler(gatea.signal.SIGINT, None) is None

    assert active_handlers == previous


def test_best_effort_stop_is_strict_isolated_and_verifies_stopped_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[tuple[str, ...], bool, bool]] = []
    status_session_flags: list[bool] = []

    def run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(
            (
                tuple(kwargs["arguments"]),
                bool(kwargs.get("check", True)),
                bool(kwargs.get("start_new_session", False)),
            )
        )
        return subprocess.CompletedProcess([], 0, stdout="")

    monkeypatch.setattr(gatea, "_run_compose", run_compose)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: status_session_flags.append(
            bool(kwargs.get("start_new_session", False))
        )
        or [
            {"Service": "nginx", "State": "exited"},
            {"Service": "app", "State": "exited"},
        ],
    )

    gatea._best_effort_stop(
        values=_valid_values(),
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
        services=("nginx", "app"),
    )

    assert commands == [
        (("stop", "--timeout", "30", "nginx", "app"), True, True)
    ]
    assert status_session_flags == [True]


def test_best_effort_stop_rejects_a_service_that_is_still_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess([], 0, stdout=""),
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [{"Service": "app", "State": "running"}],
    )

    with pytest.raises(GateAError, match="service app did not stop"):
        gatea._best_effort_stop(
            values=_valid_values(),
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            services=("app",),
        )


def test_stop_on_failure_preserves_original_error_before_deferred_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = gatea._OperationTerminationController()
    original = GateAError("original work failure")
    completed: list[bool] = []

    def run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        assert controller.interrupt(gatea.signal.SIGINT, None) is None
        completed.append(True)
        return subprocess.CompletedProcess([], 0, stdout="")

    monkeypatch.setattr(gatea, "_run_compose", run_compose)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [{"Service": "app", "State": "exited"}],
    )

    with pytest.raises(GateAError, match="original work failure") as caught:
        with gatea._stop_services_on_failure(
            termination=controller,
            values=_valid_values(),
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            services=("app",),
        ):
            raise original

    assert caught.value is original
    assert isinstance(controller.deferred_interruption, KeyboardInterrupt)
    assert completed == [True]


def test_stop_on_failure_prioritizes_recovery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = gatea._OperationTerminationController()
    original = GateAError("original work failure")
    recovery = subprocess.CalledProcessError(130, ["docker", "compose", "stop"])

    def run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        assert controller.interrupt(gatea.signal.SIGINT, None) is None
        raise recovery

    monkeypatch.setattr(gatea, "_run_compose", run_compose)

    with pytest.raises(subprocess.CalledProcessError) as caught:
        with gatea._stop_services_on_failure(
            termination=controller,
            values=_valid_values(),
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            services=("app",),
        ):
            raise original

    assert caught.value is recovery
    assert isinstance(controller.deferred_interruption, KeyboardInterrupt)


def test_stop_on_failure_runs_stop_when_recovery_transition_is_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = gatea._OperationTerminationController()
    original = GateAError("original work failure")
    transition = KeyboardInterrupt("transition interrupt")
    completed: list[bool] = []

    def interrupt_transition() -> None:
        raise transition

    monkeypatch.setattr(controller, "begin_recovery", interrupt_transition)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: completed.append(True)
        or subprocess.CompletedProcess([], 0, stdout=""),
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [{"Service": "app", "State": "exited"}],
    )

    with pytest.raises(GateAError, match="original work failure") as caught:
        with gatea._stop_services_on_failure(
            termination=controller,
            values=_valid_values(),
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            services=("app",),
        ):
            raise original

    assert caught.value is original
    assert completed == [True]


def test_safe_stop_defers_sigint_until_stop_and_verification_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = gatea._OperationTerminationController()
    events: list[str] = []
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: _valid_values())

    def run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["start_new_session"] is True
        assert controller.interrupt(gatea.signal.SIGINT, None) is None
        events.append("stop")
        return subprocess.CompletedProcess([], 0, stdout="")

    def compose_ps(**kwargs: object) -> list[dict[str, str]]:
        assert kwargs["start_new_session"] is True
        events.append("verify")
        return [
            {"Service": service, "State": "exited"}
            for service in kwargs["services"]
        ]

    monkeypatch.setattr(gatea, "_run_compose", run_compose)
    monkeypatch.setattr(gatea, "_compose_ps", compose_ps)

    with pytest.raises(KeyboardInterrupt, match="received SIGINT"):
        gatea.safe_stop(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            _termination_controller=controller,
        )

    assert events == ["stop", "verify"]


def test_safe_stop_prioritizes_stop_failure_over_deferred_sigint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = gatea._OperationTerminationController()
    recovery = subprocess.CalledProcessError(1, ["docker", "compose", "stop"])
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: _valid_values())

    def run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        assert controller.interrupt(gatea.signal.SIGINT, None) is None
        raise recovery

    monkeypatch.setattr(gatea, "_run_compose", run_compose)

    with pytest.raises(subprocess.CalledProcessError) as caught:
        gatea.safe_stop(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            _termination_controller=controller,
        )

    assert caught.value is recovery


def test_parse_env_file_accepts_comments_and_rejects_duplicate_keys(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.env"
    path.write_text("# comment\nAPP_ENV=production\nAPP_DEBUG=false\n", encoding="utf-8")

    assert parse_env_file(path) == {
        "APP_ENV": "production",
        "APP_DEBUG": "false",
    }

    path.write_text("APP_ENV=production\nAPP_ENV=testing\n", encoding="utf-8")
    with pytest.raises(GateAError, match="duplicate key APP_ENV"):
        parse_env_file(path)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    (
        ("GATEA_APP_IMAGE", "pinkdoohub-gatea:latest", "full Git SHA"),
        ("APP_ENV", "testing", "production semantics"),
        ("APP_DEBUG", "true", "production semantics"),
        ("DB_ENGINE", "sqlite", "must be mysql"),
        ("DB_HOST", "127.0.0.1", "internal mysql service"),
        ("DB_PORT", "13306", "internal mysql service"),
        ("JWT_ALGORITHM", "RS256", "must be HS256"),
    ),
)
def test_validate_config_rejects_unsafe_runtime_values(
    key: str,
    value: str,
    message: str,
) -> None:
    values = _valid_values()
    values[key] = value

    with pytest.raises(GateAError, match=message):
        validate_config_values(values, mode="loopback")


def test_validate_config_rejects_secret_keys_without_echoing_values() -> None:
    values = _valid_values() | {"DB_PASSWORD": "must-not-appear"}

    with pytest.raises(GateAError) as captured:
        validate_config_values(values, mode="loopback")

    assert "DB_PASSWORD" in str(captured.value)
    assert "must-not-appear" not in str(captured.value)


def test_validate_config_requires_public_image_url_on_approved_host() -> None:
    values = _valid_values()
    values["PRODUCT_IMAGE_BASE_URL"] = "https://other.example/uploads/products"

    with pytest.raises(GateAError, match="approved HTTPS Gate A image path"):
        validate_config_values(values, mode="loopback")


def test_validate_config_accepts_loopback_and_tls_modes() -> None:
    values = _valid_values()

    validate_config_values(values, mode="loopback")
    validate_config_values(values, mode="tls")


def test_loopback_port_probe_reuses_recently_closed_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeSocket:
        reuse_address = False

        def setsockopt(self, *arguments: object) -> None:
            calls.append(("setsockopt", *arguments))
            self.reuse_address = arguments == (
                gatea.socket.SOL_SOCKET,
                gatea.socket.SO_REUSEADDR,
                1,
            )

        def bind(self, address: tuple[str, int]) -> None:
            calls.append(("bind", address))
            if not self.reuse_address:
                raise OSError("simulated TIME_WAIT conflict")

        def close(self) -> None:
            calls.append(("close",))

    monkeypatch.setattr(gatea.socket, "socket", lambda *args: FakeSocket())

    gatea._assert_loopback_port_available(18080)

    assert calls == [
        (
            "setsockopt",
            gatea.socket.SOL_SOCKET,
            gatea.socket.SO_REUSEADDR,
            1,
        ),
        ("bind", ("127.0.0.1", 18080)),
        ("close",),
    ]


def test_loopback_port_probe_still_rejects_active_listener() -> None:
    active = gatea.socket.socket(gatea.socket.AF_INET, gatea.socket.SOCK_STREAM)
    active.setsockopt(gatea.socket.SOL_SOCKET, gatea.socket.SO_REUSEADDR, 1)
    active.bind(("127.0.0.1", 0))
    active.listen()
    port = int(active.getsockname()[1])
    try:
        with pytest.raises(GateAError, match="already in use"):
            gatea._assert_loopback_port_available(port)
    finally:
        active.close()


def test_compose_command_binds_exact_mode_and_optional_bootstrap() -> None:
    command = compose_command(
        config_file=Path("/etc/pinkdoohub/gatea/config.env"),
        mode="loopback",
        arguments=("config", "--quiet"),
        include_bootstrap=True,
        profiles=("bootstrap",),
    )

    assert command[:4] == [
        "docker",
        "compose",
        "--env-file",
        "/etc/pinkdoohub/gatea/config.env",
    ]
    assert "compose.yml" in command[5]
    assert "compose.loopback.yml" in command[7]
    assert "compose.bootstrap.yml" in command[9]
    assert command[-4:] == ["--profile", "bootstrap", "config", "--quiet"]


def test_run_compose_start_new_session_creates_a_process_group_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gatea,
        "compose_command",
        lambda **kwargs: [
            gatea.sys.executable,
            "-c",
            "import os; print(os.getpgrp())",
        ],
    )

    result = gatea._run_compose(
        values=_valid_values(),
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
        arguments=("stop",),
        capture_output=True,
        start_new_session=True,
    )

    assert int(result.stdout.strip()) != os.getpgrp()


def test_run_compose_passes_frozen_identities_only_through_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    input_text = '{"order_id":9301,"option_id":9201}'

    def fake_run(command: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "{}\n", "")

    monkeypatch.setattr(gatea.subprocess, "run", fake_run)
    result = gatea._run_compose(
        values=_valid_values(),
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
        arguments=("run", "--rm", "app", "python3", "-B", "-m", "verifier"),
        capture_output=True,
        input_text=input_text,
    )

    assert result.returncode == 0
    assert observed["input"] == input_text
    assert not any(
        raw_id in str(argument)
        for raw_id in ("9301", "9201")
        for argument in observed["command"]  # type: ignore[union-attr]
    )
    assert not any(
        raw_id in str(value)
        for raw_id in ("9301", "9201")
        for value in observed["env"].values()  # type: ignore[union-attr]
    )


def _healthy_rows(*services: str) -> list[dict[str, str]]:
    return [
        {"Service": service, "State": "running", "Health": "healthy"}
        for service in services
    ]


def test_parse_compose_status_accepts_array_and_v5_ndjson() -> None:
    mysql = {"Service": "mysql", "State": "running", "Health": "healthy"}
    redis = {"Service": "redis", "State": "running", "Health": "healthy"}

    assert gatea._parse_compose_ps_output(json.dumps([mysql, redis])) == [
        mysql,
        redis,
    ]
    assert gatea._parse_compose_ps_output(
        f"{json.dumps(mysql)}\n{json.dumps(redis)}\n"
    ) == [mysql, redis]

    with pytest.raises(GateAError, match="status output is invalid"):
        gatea._parse_compose_ps_output('{"Service": "mysql"}\nnot-json')


def test_secret_metadata_keeps_root_secret_private_and_grants_app_group_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, int, int]] = []
    for name in gatea.EXPECTED_SECRET_FILES:
        (tmp_path / name).write_text("nonempty\n", encoding="utf-8")

    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    def fake_validate(
        path: Path,
        expected_mode: int,
        description: str,
        *,
        expected_gid: int = 0,
    ) -> None:
        calls.append((path.name, expected_mode, expected_gid))

    monkeypatch.setattr(gatea, "_validate_root_file", fake_validate)
    gatea.validate_secret_metadata(tmp_path)

    assert calls == [
        ("mysql_app_password", 0o440, 10001),
        ("mysql_root_password", 0o400, 0),
        ("redis_password", 0o440, 10001),
        ("jwt_secret", 0o440, 10001),
    ]


def test_validate_app_image_requires_matching_sha_and_non_root_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _valid_values()
    payload = {
        "Id": "sha256:image-id",
        "Config": {
            "User": "10001:10001",
            "Entrypoint": ["/usr/local/bin/pinkdoo-entrypoint"],
            "Cmd": [
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--no-server-header",
                "--no-access-log",
            ],
            "Labels": {
                "org.opencontainers.image.revision": "a" * 40,
            },
        },
    }

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(payload),
        ),
    )

    assert gatea.validate_app_image(values) == "sha256:image-id"

    payload["Config"]["Labels"]["org.opencontainers.image.revision"] = "b" * 40
    with pytest.raises(GateAError, match="revision"):
        gatea.validate_app_image(values)


def test_validate_app_image_allows_only_the_exact_legacy_m7_command_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _valid_values()
    payload = {
        "Id": "sha256:image-id",
        "Config": {
            "User": "10001:10001",
            "Entrypoint": ["/usr/local/bin/pinkdoo-entrypoint"],
            "Cmd": list(gatea.LEGACY_M7_APP_COMMAND),
            "Labels": {
                "org.opencontainers.image.revision": "a" * 40,
            },
        },
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(payload),
        ),
    )

    with pytest.raises(GateAError, match="command does not match"):
        gatea.validate_app_image(values)
    assert (
        gatea.validate_app_image(values, allow_legacy_m7_command=True)
        == "sha256:image-id"
    )

    payload["Config"]["Cmd"] = [*gatea.LEGACY_M7_APP_COMMAND, "--reload"]
    with pytest.raises(GateAError, match="command does not match"):
        gatea.validate_app_image(values, allow_legacy_m7_command=True)


def test_infra_up_uses_wait_and_stops_services_on_failed_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _valid_values()
    commands: list[tuple[tuple[str, ...], bool]] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "validate_app_image", lambda value: "sha256:image")
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(
            (tuple(kwargs["arguments"]), kwargs.get("check", True))
        )
        or subprocess.CompletedProcess(args=[], returncode=0),
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: (
            [
                {"Service": "redis", "State": "exited"},
                {"Service": "mysql", "State": "exited"},
            ]
            if kwargs.get("start_new_session")
            else _healthy_rows("mysql")
        ),
    )

    with pytest.raises(GateAError, match="redis is unavailable"):
        gatea.infra_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            wait_timeout=120,
        )

    assert commands[0][0] == (
        "up",
        "--detach",
        "--no-build",
        "--wait",
        "--wait-timeout",
        "120",
        "mysql",
        "redis",
    )
    assert commands[-1] == (
        ("stop", "--timeout", "30", "redis", "mysql"),
        True,
    )


def test_database_status_is_read_only_and_normalizes_aerich_versions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = _valid_values()
    commands: list[tuple[str, ...]] = []
    database_snapshot = {
        "aerich_versions": (
            "0_20260810101218_init.py,"
            "1_20260813130455_add_order_tables.py,"
            "2_20260814104655_add_inventory_transactions.py"
        ),
        "tables": 10,
        "columns_sha256": "a" * 64,
        "users": 2,
    }

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: _healthy_rows("mysql"),
    )

    def fake_run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        commands.append(arguments)
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(database_snapshot),
        )

    monkeypatch.setattr(gatea, "_run_compose", fake_run_compose)
    gatea.database_status(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "app_version": "0.6.0",
        "candidate_sha": "a" * 40,
        "database_snapshot": database_snapshot
        | {
            "aerich_versions": [
                "0_20260810101218_init.py",
                "1_20260813130455_add_order_tables.py",
                "2_20260814104655_add_inventory_transactions.py",
            ]
        },
        "mode": "loopback",
        "read_only": True,
    }
    assert commands == [
        (
            "exec",
            "--no-TTY",
            "mysql",
            "sh",
            "-ec",
            gatea.DATABASE_STATUS_COMMAND,
        )
    ]
    assert all("run" not in command and "up" not in command for command in commands)


def test_database_status_rejects_invalid_mysql_output_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _valid_values()
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: _healthy_rows("mysql"),
    )
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="not-json-without-secret-echo",
        ),
    )

    with pytest.raises(GateAError, match="status output is invalid") as captured:
        gatea.database_status(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
        )

    assert "not-json" not in str(captured.value)


def test_initial_migrate_requires_empty_schema_and_records_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _valid_values()
    commands: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda value: "sha256:image")
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: (
            [
                {"Service": "redis", "State": "exited"},
                {"Service": "mysql", "State": "exited"},
            ]
            if kwargs.get("start_new_session")
            else _healthy_rows("mysql", "redis")
        ),
    )

    def fake_run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        profiles = tuple(kwargs.get("profiles", ()))
        commands.append((arguments, profiles))
        stdout = "0\n" if arguments[:3] == ("exec", "--no-TTY", "mysql") else ""
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout)

    monkeypatch.setattr(gatea, "_run_compose", fake_run_compose)
    gatea.initial_migrate(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=tmp_path,
        mode="loopback",
    )

    assert commands[-1] == (
        ("run", "--rm", "--no-deps", "migrate"),
        ("operations",),
    )
    marker = tmp_path / f"{'a' * 40}.initial-migration.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["candidate_sha"] == "a" * 40
    assert payload["image_id"] == "sha256:image"
    assert payload["schema_version"] == 1


def test_initial_migrate_rejects_nonempty_database_before_aerich(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _valid_values()
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda value: "sha256:image")
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: (
            [
                {"Service": "redis", "State": "exited"},
                {"Service": "mysql", "State": "exited"},
            ]
            if kwargs.get("start_new_session")
            else _healthy_rows("mysql", "redis")
        ),
    )

    def fake_run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        commands.append(arguments)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="1\n")

    monkeypatch.setattr(gatea, "_run_compose", fake_run_compose)

    with pytest.raises(GateAError, match="requires an empty"):
        gatea.initial_migrate(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
        )

    assert not any(command[:1] == ("run",) for command in commands)
    assert commands[-1] == ("stop", "--timeout", "30", "redis", "mysql")
    assert not list(tmp_path.glob("*.initial-migration.json"))


@pytest.mark.parametrize(
    "pending_suffix",
    gatea.CANDIDATE_TRANSITION_PENDING_SUFFIXES,
)
def test_initial_migrate_rejects_any_candidate_pending_before_input_or_compose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pending_suffix: str,
) -> None:
    pending_path = tmp_path / f"{'b' * 40}.{pending_suffix}"
    pending_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    def unexpected_inputs(**kwargs: object) -> dict[str, str]:
        del kwargs
        raise AssertionError("pending must fail before input validation or compose")

    monkeypatch.setattr(gatea, "_validated_inputs", unexpected_inputs)

    with pytest.raises(GateAError, match="unresolved pending journal"):
        gatea.initial_migrate(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
        )


def test_initial_migrate_rejects_acceptance_sidecar_before_input_or_compose(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance_record_dir = tmp_path / "acceptance"
    acceptance_record_dir.mkdir()
    sidecar_path = acceptance_record_dir / (
        f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{'b' * 40}"
        f"{gatea.M9_ACCEPTANCE_PENDING_SUFFIX}"
    )
    sidecar_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    def unexpected_inputs(**kwargs: object) -> dict[str, str]:
        del kwargs
        raise AssertionError("acceptance sidecar must fail before compose")

    monkeypatch.setattr(gatea, "_validated_inputs", unexpected_inputs)

    with pytest.raises(GateAError, match="unresolved sidecar"):
        gatea.initial_migrate(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            acceptance_record_dir=acceptance_record_dir,
        )


def test_migration_record_never_publishes_partial_json_on_enospc(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate_sha = "a" * 40
    marker = gatea._migration_marker(tmp_path, candidate_sha)
    synced_directories: list[Path] = []

    def fail_after_partial_write(
        payload: object,
        stream: object,
        **kwargs: object,
    ) -> None:
        del payload, kwargs
        stream.write('{"candidate_sha":')
        raise OSError(28, "simulated ENOSPC")

    monkeypatch.setattr(gatea.json, "dump", fail_after_partial_write)
    monkeypatch.setattr(
        gatea,
        "_fsync_directory",
        lambda directory: synced_directories.append(directory),
    )

    with pytest.raises(OSError, match="ENOSPC"):
        gatea._write_migration_record(
            record_dir=tmp_path,
            candidate_sha=candidate_sha,
            image_id="sha256:image",
        )

    assert not marker.exists()
    assert not marker.is_symlink()
    assert list(tmp_path.glob(f".{marker.name}.tmp-*")) == []
    assert synced_directories == [tmp_path]


@pytest.mark.parametrize("target_kind", ("file", "dangling-symlink"))
def test_migration_record_never_overwrites_an_existing_path(
    tmp_path: Path,
    target_kind: str,
) -> None:
    candidate_sha = "a" * 40
    marker = gatea._migration_marker(tmp_path, candidate_sha)
    if target_kind == "file":
        original = '{"owner":"first"}\n'
        marker.write_text(original, encoding="utf-8")
    else:
        missing_target = tmp_path / "missing-record"
        marker.symlink_to(missing_target)

    with pytest.raises(GateAError, match="record path is already reserved"):
        gatea._write_migration_record(
            record_dir=tmp_path,
            candidate_sha=candidate_sha,
            image_id="sha256:replacement",
        )

    if target_kind == "file":
        assert marker.read_text(encoding="utf-8") == original
    else:
        assert marker.is_symlink()
        assert marker.readlink() == missing_target
    assert list(tmp_path.glob(f".{marker.name}.tmp-*")) == []


def test_migration_record_link_failure_does_not_publish_or_leave_a_tempfile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate_sha = "a" * 40
    marker = gatea._migration_marker(tmp_path, candidate_sha)
    synced_directories: list[Path] = []

    def fail_link(
        source: Path,
        target: Path,
        *,
        follow_symlinks: bool,
    ) -> None:
        assert source.parent == tmp_path
        assert target == marker
        assert follow_symlinks is False
        raise OSError("simulated link failure")

    monkeypatch.setattr(gatea.os, "link", fail_link)
    monkeypatch.setattr(
        gatea,
        "_fsync_directory",
        lambda directory: synced_directories.append(directory),
    )

    with pytest.raises(OSError, match="link failure"):
        gatea._write_migration_record(
            record_dir=tmp_path,
            candidate_sha=candidate_sha,
            image_id="sha256:image",
        )

    assert not marker.exists()
    assert list(tmp_path.glob(f".{marker.name}.tmp-*")) == []
    assert synced_directories == [tmp_path]


def test_migration_record_directory_sync_failure_keeps_only_complete_final_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate_sha = "a" * 40
    marker = gatea._migration_marker(tmp_path, candidate_sha)
    sync_calls = 0

    def interrupt_first_directory_sync(directory: Path) -> None:
        nonlocal sync_calls
        assert directory == tmp_path
        sync_calls += 1
        if sync_calls == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(gatea, "_fsync_directory", interrupt_first_directory_sync)

    with pytest.raises(KeyboardInterrupt):
        gatea._write_migration_record(
            record_dir=tmp_path,
            candidate_sha=candidate_sha,
            image_id="sha256:image",
        )

    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["candidate_sha"] == candidate_sha
    assert payload["image_id"] == "sha256:image"
    assert list(tmp_path.glob(f".{marker.name}.tmp-*")) == []
    assert sync_calls == 2


def test_app_up_requires_matching_migration_record_and_waits_for_health(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _valid_values()
    commands: list[tuple[str, ...]] = []
    gatea._write_migration_record(
        record_dir=tmp_path,
        candidate_sha="a" * 40,
        image_id="sha256:image",
    )

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda value: "sha256:image")

    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: {
            "aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN)
        },
    )
    monkeypatch.setattr(
        gatea,
        "_run_m9_table_reconcile",
        lambda **kwargs: {key: 0 for key in gatea.M9_RECONCILE_KEYS},
    )

    def fake_compose_ps(**kwargs: object) -> list[dict[str, object]]:
        services = tuple(kwargs["services"])
        rows: list[dict[str, object]] = _healthy_rows(*services)
        for row in rows:
            if row["Service"] == "nginx":
                row["Publishers"] = [
                    {
                        "URL": "127.0.0.1",
                        "TargetPort": 8080,
                        "PublishedPort": 18080,
                        "Protocol": "tcp",
                    }
                ]
        return rows

    monkeypatch.setattr(gatea, "_compose_ps", fake_compose_ps)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess(args=[], returncode=0),
    )

    gatea.app_up(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=tmp_path,
        mode="loopback",
        wait_timeout=180,
    )

    assert commands == [
        (
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "180",
            "app",
            "table-sweeper",
            "nginx",
        )
    ]


def test_app_up_recovery_session_is_forwarded_to_every_child_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _valid_values()
    gatea._write_migration_record(
        record_dir=tmp_path,
        candidate_sha="a" * 40,
        image_id="sha256:image",
    )
    session_flags: dict[str, list[bool]] = {
        "image": [],
        "snapshot": [],
        "reconcile": [],
        "ps": [],
        "compose": [],
    }

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    def validate_image(*args: object, **kwargs: object) -> str:
        session_flags["image"].append(bool(kwargs.get("start_new_session")))
        return "sha256:image"

    def read_snapshot(**kwargs: object) -> dict[str, object]:
        session_flags["snapshot"].append(
            bool(kwargs.get("start_new_session"))
        )
        return {"aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN)}

    def reconcile(**kwargs: object) -> dict[str, int]:
        session_flags["reconcile"].append(
            bool(kwargs.get("start_new_session"))
        )
        return {key: 0 for key in gatea.M9_RECONCILE_KEYS}

    def compose_ps(**kwargs: object) -> list[dict[str, object]]:
        session_flags["ps"].append(bool(kwargs.get("start_new_session")))
        rows: list[dict[str, object]] = _healthy_rows(*kwargs["services"])
        for row in rows:
            if row["Service"] == "nginx":
                row["Publishers"] = [
                    {
                        "URL": "127.0.0.1",
                        "TargetPort": 8080,
                        "PublishedPort": 18080,
                        "Protocol": "tcp",
                    }
                ]
        return rows

    monkeypatch.setattr(gatea, "validate_app_image", validate_image)
    monkeypatch.setattr(gatea, "read_database_snapshot", read_snapshot)
    monkeypatch.setattr(gatea, "_run_m9_table_reconcile", reconcile)
    monkeypatch.setattr(gatea, "_compose_ps", compose_ps)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: session_flags["compose"].append(
            bool(kwargs.get("start_new_session"))
        )
        or subprocess.CompletedProcess([], 0, stdout=""),
    )

    gatea.app_up(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=tmp_path,
        mode="loopback",
        wait_timeout=180,
        _start_new_session=True,
    )

    assert session_flags == {
        "image": [True, True],
        "snapshot": [True],
        "reconcile": [True],
        "ps": [True, True],
        "compose": [True],
    }


@pytest.mark.parametrize(
    "pending_suffix",
    gatea.CANDIDATE_TRANSITION_PENDING_SUFFIXES,
)
@pytest.mark.parametrize("pending_candidate_sha", ("a" * 40, "b" * 40))
def test_app_up_rejects_unresolved_candidate_transition_before_image_or_docker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pending_suffix: str,
    pending_candidate_sha: str,
) -> None:
    (tmp_path / f"{pending_candidate_sha}.{pending_suffix}").write_text(
        "{}\n", encoding="utf-8"
    )
    image_validated = False

    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: pytest.fail(
            "pending transition must fail before input validation"
        ),
    )

    def unexpected_image_validation(*args: object, **kwargs: object) -> str:
        nonlocal image_validated
        image_validated = True
        raise AssertionError("pending transition must fail before image validation")

    monkeypatch.setattr(gatea, "validate_app_image", unexpected_image_validation)

    with pytest.raises(GateAError, match="unresolved pending journal"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
        )

    assert image_validated is False


@pytest.mark.parametrize(
    "pending_suffix",
    (
        "config-activation.pending.json",
        gatea.CURRENT_FINALIZATION_PENDING_SUFFIX,
    ),
)
def test_candidate_transition_guard_rejects_dangling_pending_symlink(
    tmp_path: Path,
    pending_suffix: str,
) -> None:
    candidate_sha = "a" * 40
    pending_path = tmp_path / f"{candidate_sha}.{pending_suffix}"
    pending_path.symlink_to(tmp_path / "missing-journal")

    with pytest.raises(GateAError, match="unresolved pending journal"):
        gatea.reject_unresolved_candidate_transition_journals(
            record_dir=tmp_path,
            candidate_sha=candidate_sha,
        )


def test_candidate_transition_guard_rejects_malformed_candidate_name(
    tmp_path: Path,
) -> None:
    (tmp_path / "not-a-sha.config-activation.pending.json").write_text(
        "{}\n", encoding="utf-8"
    )

    with pytest.raises(GateAError, match="unresolved pending journal"):
        gatea.reject_unresolved_candidate_transition_journals(
            record_dir=tmp_path,
            candidate_sha="a" * 40,
        )


@pytest.mark.parametrize("entry_kind", ("directory", "fifo"))
def test_candidate_transition_guard_rejects_nonregular_pending(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    pending_path = tmp_path / f"{'a' * 40}.candidate-stage.pending.json"
    if entry_kind == "directory":
        pending_path.mkdir()
    else:
        os.mkfifo(pending_path)

    with pytest.raises(GateAError, match="unresolved pending journal"):
        gatea.reject_unresolved_candidate_transition_journals(
            record_dir=tmp_path,
            candidate_sha="a" * 40,
        )


def test_candidate_transition_guard_only_scans_direct_children(
    tmp_path: Path,
) -> None:
    nested_record_dir = tmp_path / "nested"
    nested_record_dir.mkdir()
    (nested_record_dir / f"{'a' * 40}.candidate-stage.pending.json").write_text(
        "{}\n", encoding="utf-8"
    )

    gatea.reject_unresolved_candidate_transition_journals(
        record_dir=tmp_path,
        candidate_sha="a" * 40,
    )


def test_candidate_transition_guard_allows_one_exact_validated_recovery(
    tmp_path: Path,
) -> None:
    candidate_sha = "a" * 40
    pending_path = tmp_path / (
        f"{candidate_sha}.{gatea.CURRENT_FINALIZATION_PENDING_SUFFIX}"
    )
    pending_path.write_text("{}\n", encoding="utf-8")
    allowance = gatea.CandidateTransitionRecoveryAllowance(
        path=pending_path,
        kind="current-finalization",
        candidate_sha=candidate_sha,
    )

    gatea.reject_unresolved_candidate_transition_journals(
        record_dir=tmp_path,
        candidate_sha=candidate_sha,
        recovery_allowance=allowance,
    )


@pytest.mark.parametrize("entry_kind", ("directory", "dangling-symlink", "fifo"))
def test_candidate_transition_guard_does_not_allow_unsafe_recovery_entry(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    candidate_sha = "a" * 40
    pending_path = tmp_path / (
        f"{candidate_sha}.{gatea.CURRENT_FINALIZATION_PENDING_SUFFIX}"
    )
    if entry_kind == "directory":
        pending_path.mkdir()
    elif entry_kind == "dangling-symlink":
        pending_path.symlink_to(tmp_path / "missing-journal")
    else:
        os.mkfifo(pending_path)

    allowance = gatea.CandidateTransitionRecoveryAllowance(
        path=pending_path,
        kind="current-finalization",
        candidate_sha=candidate_sha,
    )
    with pytest.raises(GateAError, match="recovery allowance is invalid"):
        gatea.reject_unresolved_candidate_transition_journals(
            record_dir=tmp_path,
            candidate_sha=candidate_sha,
            recovery_allowance=allowance,
        )


@pytest.mark.parametrize(
    "invalid_allowance",
    ("outside", "other-sha", "invalid-sha", "other-kind"),
)
def test_candidate_transition_guard_rejects_invalid_recovery_allowance(
    tmp_path: Path,
    invalid_allowance: str,
) -> None:
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    candidate_sha = "a" * 40
    pending_path = record_dir / (
        f"{candidate_sha}.{gatea.CURRENT_FINALIZATION_PENDING_SUFFIX}"
    )
    pending_path.write_text("{}\n", encoding="utf-8")
    allowance_path = pending_path
    allowance_sha = candidate_sha
    allowance_kind = "current-finalization"
    if invalid_allowance == "outside":
        allowance_path = tmp_path / pending_path.name
        allowance_path.write_text("{}\n", encoding="utf-8")
    elif invalid_allowance == "other-sha":
        allowance_sha = "b" * 40
    elif invalid_allowance == "invalid-sha":
        allowance_sha = "not-a-sha"
    else:
        allowance_kind = "config-rollback"

    with pytest.raises(GateAError, match="recovery allowance is invalid"):
        gatea.reject_unresolved_candidate_transition_journals(
            record_dir=record_dir,
            candidate_sha=candidate_sha,
            recovery_allowance=gatea.CandidateTransitionRecoveryAllowance(
                path=allowance_path,
                kind=allowance_kind,
                candidate_sha=allowance_sha,
            ),
        )


def test_m9_acceptance_inventory_allows_a_missing_directory(tmp_path: Path) -> None:
    gatea.reject_unresolved_m9_acceptance_sidecars(
        record_dir=tmp_path / "not-created-yet",
    )


@pytest.mark.parametrize(
    "candidate_part",
    ("a" * 40, "b" * 40, "not-a-candidate-sha"),
)
@pytest.mark.parametrize(
    "sidecar_suffix",
    gatea.M9_ACCEPTANCE_SIDECAR_SUFFIXES,
)
def test_m9_acceptance_inventory_rejects_every_matching_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    candidate_part: str,
    sidecar_suffix: str,
) -> None:
    sidecar_path = tmp_path / (
        f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{candidate_part}{sidecar_suffix}"
    )
    sidecar_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    with pytest.raises(GateAError, match="unresolved sidecar"):
        gatea.reject_unresolved_m9_acceptance_sidecars(record_dir=tmp_path)


def test_m9_acceptance_inventory_only_scans_direct_children(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (
        nested
        / (
            f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{'a' * 40}"
            f"{gatea.M9_ACCEPTANCE_PENDING_SUFFIX}"
        )
    ).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    gatea.reject_unresolved_m9_acceptance_sidecars(record_dir=tmp_path)


@pytest.mark.parametrize("entry_kind", ("directory", "dangling-symlink"))
def test_m9_acceptance_inventory_rejects_nonregular_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    entry_kind: str,
) -> None:
    sidecar_path = tmp_path / (
        f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{'a' * 40}"
        f"{gatea.M9_ACCEPTANCE_COMPLETE_SUFFIX}"
    )
    if entry_kind == "directory":
        sidecar_path.mkdir()
    else:
        sidecar_path.symlink_to(tmp_path / "missing-sidecar")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    with pytest.raises(GateAError, match="unresolved sidecar"):
        gatea.reject_unresolved_m9_acceptance_sidecars(record_dir=tmp_path)


def test_m9_acceptance_inventory_rejects_symlink_record_directory(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    record_dir = tmp_path / "acceptance"
    record_dir.symlink_to(target, target_is_directory=True)

    with pytest.raises(GateAError, match="must not be a symlink"):
        gatea.reject_unresolved_m9_acceptance_sidecars(record_dir=record_dir)


def test_m9_acceptance_inventory_rejects_unsafe_directory_metadata(
    tmp_path: Path,
) -> None:
    record_dir = tmp_path / "acceptance"
    record_dir.mkdir(mode=0o700)

    with pytest.raises(GateAError, match="owned by root|unsafe permissions"):
        gatea.reject_unresolved_m9_acceptance_sidecars(record_dir=record_dir)


def test_m9_acceptance_recovery_allows_exact_pending_and_complete_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate_sha = "a" * 40
    base_name = f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{candidate_sha}"
    pending_path = tmp_path / f"{base_name}{gatea.M9_ACCEPTANCE_PENDING_SUFFIX}"
    complete_path = tmp_path / f"{base_name}{gatea.M9_ACCEPTANCE_COMPLETE_SUFFIX}"
    pending_path.write_text("{}\n", encoding="utf-8")
    pending_path.chmod(0o600)
    complete_path.write_text("{}\n", encoding="utf-8")
    # final hard-link 发布后的 chmod 会同步改变同 inode 的 complete mode。
    complete_path.chmod(0o644)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_m9_acceptance_sidecar_lstat",
        lambda path: SimpleNamespace(
            st_mode=path.lstat().st_mode,
            st_uid=0,
            st_gid=0,
        ),
    )
    allowance = gatea.M9AcceptanceSidecarRecoveryAllowance(
        candidate_sha=candidate_sha,
        pending_path=pending_path,
        complete_path=complete_path,
    )

    gatea.reject_unresolved_m9_acceptance_sidecars(
        record_dir=tmp_path,
        recovery_allowance=allowance,
    )

    extra_path = tmp_path / (
        f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{'b' * 40}"
        f"{gatea.M9_ACCEPTANCE_PENDING_SUFFIX}"
    )
    extra_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(GateAError, match="unresolved sidecar"):
        gatea.reject_unresolved_m9_acceptance_sidecars(
            record_dir=tmp_path,
            recovery_allowance=allowance,
        )


@pytest.mark.parametrize(
    ("sidecar_kind", "mode", "uid", "gid", "allowed"),
    (
        ("pending", 0o600, 0, 0, True),
        ("pending", 0o644, 0, 0, False),
        ("complete", 0o600, 0, 0, True),
        ("complete", 0o644, 0, 0, True),
        ("complete", 0o640, 0, 0, False),
        ("complete", 0o600, 501, 0, False),
        ("complete", 0o600, 0, 501, False),
    ),
)
def test_m9_acceptance_recovery_enforces_owner_and_kind_specific_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sidecar_kind: str,
    mode: int,
    uid: int,
    gid: int,
    allowed: bool,
) -> None:
    candidate_sha = "a" * 40
    suffix = (
        gatea.M9_ACCEPTANCE_PENDING_SUFFIX
        if sidecar_kind == "pending"
        else gatea.M9_ACCEPTANCE_COMPLETE_SUFFIX
    )
    sidecar_path = tmp_path / (
        f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{candidate_sha}{suffix}"
    )
    sidecar_path.write_text("{}\n", encoding="utf-8")
    sidecar_path.chmod(mode)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_m9_acceptance_sidecar_lstat",
        lambda path: SimpleNamespace(
            st_mode=path.lstat().st_mode,
            st_uid=uid,
            st_gid=gid,
        ),
    )
    allowance = gatea.M9AcceptanceSidecarRecoveryAllowance(
        candidate_sha=candidate_sha,
        pending_path=sidecar_path if sidecar_kind == "pending" else None,
        complete_path=sidecar_path if sidecar_kind == "complete" else None,
    )

    expectation = (
        nullcontext()
        if allowed
        else pytest.raises(gatea.GateAError, match="recovery allowance is invalid")
    )
    with expectation:
        gatea.reject_unresolved_m9_acceptance_sidecars(
            record_dir=tmp_path,
            recovery_allowance=allowance,
        )


def test_app_up_finalization_recovery_allows_only_one_exact_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _valid_values()
    candidate_sha = "a" * 40
    finalization_path = tmp_path / (
        f"{candidate_sha}.{gatea.CURRENT_FINALIZATION_PENDING_SUFFIX}"
    )
    finalization_path.write_text("{}\n", encoding="utf-8")
    allowance = gatea.CandidateTransitionRecoveryAllowance(
        path=finalization_path,
        kind="current-finalization",
        candidate_sha=candidate_sha,
    )
    image_validations = 0

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    def stop_after_guard(*args: object, **kwargs: object) -> str:
        nonlocal image_validations
        del args, kwargs
        image_validations += 1
        raise AssertionError("finalization recovery passed the journal guard")

    monkeypatch.setattr(gatea, "validate_app_image", stop_after_guard)

    with pytest.raises(AssertionError, match="passed the journal guard"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_transition_recovery=allowance,
        )

    assert image_validations == 1

    (tmp_path / f"{candidate_sha}.config-rollback.pending.json").write_text(
        "{}\n", encoding="utf-8"
    )
    with pytest.raises(GateAError, match="unresolved pending journal"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_transition_recovery=allowance,
        )

    assert image_validations == 1


def test_app_up_failed_acceptance_retirement_allows_only_exact_b_journal_and_a_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_sha = "a" * 40
    target_sha = "b" * 40
    release_pending = tmp_path / (
        f"{target_sha}.acceptance-retirement.pending.json"
    )
    release_pending.write_text("{}\n", encoding="utf-8")
    acceptance_dir = tmp_path / "acceptance"
    acceptance_dir.mkdir()
    acceptance_pending = acceptance_dir / (
        f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{source_sha}"
        f"{gatea.M9_ACCEPTANCE_PENDING_SUFFIX}"
    )
    acceptance_pending.write_text("{}\n", encoding="utf-8")
    transition_allowance = gatea.CandidateTransitionRecoveryAllowance(
        path=release_pending,
        kind="failed-acceptance-retirement",
        candidate_sha=target_sha,
        runtime_candidate_sha=source_sha,
    )
    acceptance_allowance = gatea.M9AcceptanceSidecarRecoveryAllowance(
        candidate_sha=source_sha,
        pending_path=acceptance_pending,
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_m9_acceptance_sidecar_lstat",
        lambda path: SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600,
            st_uid=0,
            st_gid=0,
        ),
    )
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: _valid_values())
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("retirement recovery passed both exact guards")
        ),
    )

    with pytest.raises(AssertionError, match="passed both exact guards"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_transition_recovery=transition_allowance,
            acceptance_sidecar_recovery=acceptance_allowance,
            acceptance_record_dir=acceptance_dir,
        )

    with pytest.raises(GateAError, match="recovery allowance is invalid"):
        gatea.reject_unresolved_candidate_transition_journals(
            record_dir=tmp_path,
            candidate_sha=target_sha,
            recovery_allowance=gatea.CandidateTransitionRecoveryAllowance(
                path=release_pending,
                kind="failed-acceptance-retirement",
                candidate_sha=target_sha,
            ),
        )


def test_app_up_rejects_cross_candidate_retirement_sidecar_before_blocker_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_sha = "a" * 40
    target_sha = "b" * 40
    unrelated_sidecar_sha = "c" * 40
    blocker_inventory_calls: list[str] = []

    monkeypatch.setattr(
        gatea,
        "reject_unresolved_candidate_transition_journals",
        lambda **kwargs: blocker_inventory_calls.append("candidate-transition"),
    )
    monkeypatch.setattr(
        gatea,
        "reject_unresolved_m9_acceptance_sidecars",
        lambda **kwargs: blocker_inventory_calls.append("acceptance-sidecar"),
    )

    with pytest.raises(
        GateAError,
        match="acceptance allowance does not match the retirement runtime candidate",
    ):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_transition_recovery=(
                gatea.CandidateTransitionRecoveryAllowance(
                    path=(
                        tmp_path
                        / f"{target_sha}.acceptance-retirement.pending.json"
                    ),
                    kind="failed-acceptance-retirement",
                    candidate_sha=target_sha,
                    runtime_candidate_sha=runtime_sha,
                )
            ),
            acceptance_sidecar_recovery=(
                gatea.M9AcceptanceSidecarRecoveryAllowance(
                    candidate_sha=unrelated_sidecar_sha,
                    pending_path=(
                        tmp_path
                        / f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}"
                        f"{unrelated_sidecar_sha}"
                        f"{gatea.M9_ACCEPTANCE_PENDING_SUFFIX}"
                    ),
                )
            ),
            acceptance_record_dir=tmp_path,
        )

    assert blocker_inventory_calls == []


def test_app_up_never_accepts_retirement_sidecar_allowance_without_retirement_journal(
    tmp_path: Path,
) -> None:
    with pytest.raises(GateAError, match="restricted to failed-acceptance"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            acceptance_sidecar_recovery=gatea.M9AcceptanceSidecarRecoveryAllowance(
                candidate_sha="a" * 40,
                pending_path=tmp_path / "not-used",
            ),
        )


def _mock_m9_takeover_root_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """The production contract is root-only; tmp_path fixtures are not root-owned."""

    def root_owned(metadata: os.stat_result) -> SimpleNamespace:
        return SimpleNamespace(
            st_dev=metadata.st_dev,
            st_ino=metadata.st_ino,
            st_mode=metadata.st_mode,
            st_nlink=metadata.st_nlink,
            st_uid=0,
            st_gid=0,
            st_size=metadata.st_size,
            st_mtime_ns=metadata.st_mtime_ns,
            st_ctime_ns=metadata.st_ctime_ns,
        )

    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_m9_takeover_pending_lstat",
        lambda path: root_owned(path.lstat()),
    )
    monkeypatch.setattr(
        gatea,
        "_m9_takeover_pending_fstat",
        lambda descriptor: root_owned(os.fstat(descriptor)),
    )
    monkeypatch.setattr(
        gatea,
        "_m9_acceptance_sidecar_lstat",
        lambda path: SimpleNamespace(
            st_mode=path.lstat().st_mode,
            st_uid=0,
            st_gid=0,
        ),
    )


def _m9_takeover_allowance(
    *,
    record_dir: Path,
    acceptance_dir: Path,
    runtime_sha: str = "a" * 40,
    current_sha: str = "c" * 40,
    superseded_sha: str = "b" * 40,
    superseded_expected_exists: bool = True,
    current_digest: str | None = None,
    superseded_digest: str | None = None,
    include_acceptance_sidecar: bool = True,
) -> gatea.M9CandidateTakeoverRecoveryAllowance:
    current_path = record_dir / (
        f"{current_sha}.acceptance-retirement.pending.json"
    )
    superseded_path = record_dir / (
        f"{superseded_sha}.acceptance-retirement.pending.json"
    )
    acceptance_path = acceptance_dir / (
        f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{runtime_sha}"
        f"{gatea.M9_ACCEPTANCE_PENDING_SUFFIX}"
    )
    return gatea.M9CandidateTakeoverRecoveryAllowance(
        runtime_candidate_sha=runtime_sha,
        current_transition=gatea.CandidateTransitionRecoveryAllowance(
            path=current_path,
            kind="failed-acceptance-retirement",
            candidate_sha=current_sha,
            runtime_candidate_sha=runtime_sha,
        ),
        current_pending_sha256=current_digest or gatea._sha256(current_path),
        superseded_pending=gatea.SupersededCandidatePendingRecoveryAllowance(
            candidate_sha=superseded_sha,
            path=superseded_path,
            sha256=(
                superseded_digest
                if superseded_digest is not None
                else (
                    gatea._sha256(superseded_path)
                    if superseded_expected_exists
                    else None
                )
            ),
            expected_exists=superseded_expected_exists,
        ),
        acceptance_sidecar=(
            gatea.M9AcceptanceSidecarRecoveryAllowance(
                candidate_sha=runtime_sha,
                pending_path=acceptance_path,
            )
            if include_acceptance_sidecar
            else None
        ),
    )


def _write_m9_takeover_journals(
    *,
    record_dir: Path,
    acceptance_dir: Path,
    include_superseded: bool = True,
    include_acceptance_sidecar: bool = True,
) -> tuple[Path, Path]:
    current_path = record_dir / (
        f"{'c' * 40}.acceptance-retirement.pending.json"
    )
    superseded_path = record_dir / (
        f"{'b' * 40}.acceptance-retirement.pending.json"
    )
    current_path.write_text('{"candidate":"c"}\n', encoding="utf-8")
    current_path.chmod(0o600)
    if include_superseded:
        superseded_path.write_text('{"candidate":"b"}\n', encoding="utf-8")
        superseded_path.chmod(0o600)
    acceptance_dir.mkdir()
    if include_acceptance_sidecar:
        acceptance_path = acceptance_dir / (
            f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{'a' * 40}"
            f"{gatea.M9_ACCEPTANCE_PENDING_SUFFIX}"
        )
        acceptance_path.write_text("{}\n", encoding="utf-8")
        acceptance_path.chmod(0o600)
    return current_path, superseded_path


def test_app_up_m9_takeover_recovery_allows_exact_c_and_b_pending_before_runtime_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance_dir = tmp_path / "acceptance"
    _write_m9_takeover_journals(
        record_dir=tmp_path,
        acceptance_dir=acceptance_dir,
    )
    allowance = _m9_takeover_allowance(
        record_dir=tmp_path,
        acceptance_dir=acceptance_dir,
    )
    _mock_m9_takeover_root_metadata(monkeypatch)
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("takeover recovery passed exact pending guards")
        ),
    )

    with pytest.raises(AssertionError, match="passed exact pending guards"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_takeover_recovery=allowance,
            acceptance_record_dir=acceptance_dir,
        )


@pytest.mark.parametrize(
    ("superseded_expected_exists", "expect_runtime_boundary"),
    ((False, True), (True, False)),
)
def test_app_up_m9_takeover_recovery_allows_b_absence_only_when_explicitly_expected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    superseded_expected_exists: bool,
    expect_runtime_boundary: bool,
) -> None:
    acceptance_dir = tmp_path / "acceptance"
    _write_m9_takeover_journals(
        record_dir=tmp_path,
        acceptance_dir=acceptance_dir,
        include_superseded=False,
    )
    allowance = _m9_takeover_allowance(
        record_dir=tmp_path,
        acceptance_dir=acceptance_dir,
        superseded_expected_exists=superseded_expected_exists,
        superseded_digest=("d" * 64 if superseded_expected_exists else None),
    )
    _mock_m9_takeover_root_metadata(monkeypatch)
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("takeover recovery passed exact pending guards")
        ),
    )

    expectation = (
        pytest.raises(AssertionError, match="passed exact pending guards")
        if expect_runtime_boundary
        else pytest.raises(
            GateAError,
            match="candidate takeover recovery allowance is invalid",
        )
    )
    with expectation:
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_takeover_recovery=allowance,
            acceptance_record_dir=acceptance_dir,
        )


@pytest.mark.parametrize(
    ("include_acceptance_sidecar", "expect_runtime_boundary"),
    ((False, True), (True, False)),
)
def test_app_up_m9_takeover_recovery_allows_a_sidecar_absence_only_after_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    include_acceptance_sidecar: bool,
    expect_runtime_boundary: bool,
) -> None:
    acceptance_dir = tmp_path / "acceptance"
    _write_m9_takeover_journals(
        record_dir=tmp_path,
        acceptance_dir=acceptance_dir,
        include_superseded=False,
        include_acceptance_sidecar=include_acceptance_sidecar,
    )
    allowance = _m9_takeover_allowance(
        record_dir=tmp_path,
        acceptance_dir=acceptance_dir,
        superseded_expected_exists=False,
        include_acceptance_sidecar=False,
    )
    _mock_m9_takeover_root_metadata(monkeypatch)
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("takeover recovery passed exact pending guards")
        ),
    )

    expectation = (
        pytest.raises(AssertionError, match="passed exact pending guards")
        if expect_runtime_boundary
        else pytest.raises(
            GateAError,
            match="candidate takeover recovery allowance is invalid",
        )
    )
    with expectation:
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_takeover_recovery=allowance,
            acceptance_record_dir=acceptance_dir,
        )


@pytest.mark.parametrize(
    "failure",
    ("third", "malformed", "digest", "current-digest", "path", "sha"),
)
def test_app_up_m9_takeover_recovery_rejects_any_nonexact_pending_bundle_before_runtime_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
) -> None:
    acceptance_dir = tmp_path / "acceptance"
    _, superseded_path = _write_m9_takeover_journals(
        record_dir=tmp_path,
        acceptance_dir=acceptance_dir,
    )
    kwargs: dict[str, object] = {}
    if failure == "third":
        (tmp_path / f"{'d' * 40}.acceptance-retirement.pending.json").write_text(
            "{}\n", encoding="utf-8"
        )
    elif failure == "malformed":
        superseded_path.unlink()
        superseded_path.mkdir()
        kwargs["superseded_digest"] = "d" * 64
    elif failure == "digest":
        kwargs["superseded_digest"] = "d" * 64
    elif failure == "current-digest":
        kwargs["current_digest"] = "d" * 64
    elif failure == "path":
        kwargs["superseded_sha"] = "d" * 40
        kwargs["superseded_digest"] = "d" * 64
    else:
        kwargs["runtime_sha"] = "c" * 40
    allowance = _m9_takeover_allowance(
        record_dir=tmp_path,
        acceptance_dir=acceptance_dir,
        **kwargs,
    )
    _mock_m9_takeover_root_metadata(monkeypatch)
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: pytest.fail(
            "invalid M9 takeover recovery must fail before mutable runtime work"
        ),
    )

    with pytest.raises(
        GateAError,
        match="candidate takeover recovery allowance is invalid",
    ):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_takeover_recovery=allowance,
            acceptance_record_dir=acceptance_dir,
        )


def test_app_up_m9_takeover_recovery_rejects_current_journal_identity_drift_before_runtime_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance_dir = tmp_path / "acceptance"
    _write_m9_takeover_journals(
        record_dir=tmp_path,
        acceptance_dir=acceptance_dir,
    )
    allowance = _m9_takeover_allowance(
        record_dir=tmp_path,
        acceptance_dir=acceptance_dir,
    )
    _mock_m9_takeover_root_metadata(monkeypatch)
    stable_fstat = gatea._m9_takeover_pending_fstat
    calls = 0

    def drifting_fstat(descriptor: int) -> SimpleNamespace:
        nonlocal calls
        metadata = stable_fstat(descriptor)
        calls += 1
        if calls == 2:
            fields = {**vars(metadata), "st_ino": metadata.st_ino + 1}
            return SimpleNamespace(**fields)
        return metadata

    monkeypatch.setattr(gatea, "_m9_takeover_pending_fstat", drifting_fstat)
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: pytest.fail(
            "identity-drifting takeover pending must fail before mutable runtime work"
        ),
    )

    with pytest.raises(
        GateAError,
        match="candidate takeover recovery allowance is invalid",
    ):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_takeover_recovery=allowance,
            acceptance_record_dir=acceptance_dir,
        )


@pytest.mark.parametrize(
    ("kind", "pending_suffix"),
    (
        ("candidate-stage", "candidate-stage.pending.json"),
        ("config-activation", "config-activation.pending.json"),
        ("config-rollback", "config-rollback.pending.json"),
    ),
)
def test_app_up_rejects_matching_non_finalization_recovery_allowance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kind: str,
    pending_suffix: str,
) -> None:
    candidate_sha = "a" * 40
    pending_path = tmp_path / f"{candidate_sha}.{pending_suffix}"
    pending_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: pytest.fail(
            "non-finalization allowance must fail before input validation"
        ),
    )

    with pytest.raises(GateAError, match="restricted to finalization"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_transition_recovery=(
                gatea.CandidateTransitionRecoveryAllowance(
                    path=pending_path,
                    kind=kind,
                    candidate_sha=candidate_sha,
                )
            ),
        )


def test_app_up_rejects_acceptance_sidecar_before_image_or_docker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    acceptance_record_dir = tmp_path / "acceptance"
    acceptance_record_dir.mkdir()
    sidecar_path = acceptance_record_dir / (
        f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{'a' * 40}"
        f"{gatea.M9_ACCEPTANCE_COMPLETE_SUFFIX}"
    )
    sidecar_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: pytest.fail(
            "acceptance sidecar must fail before input validation"
        ),
    )
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda *args, **kwargs: pytest.fail(
            "acceptance sidecar must fail before image validation"
        ),
    )

    with pytest.raises(GateAError, match="unresolved sidecar"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            acceptance_record_dir=acceptance_record_dir,
        )


def test_app_up_recovery_allowance_must_match_live_config_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allowance_candidate_sha = "b" * 40
    pending_path = tmp_path / (
        f"{allowance_candidate_sha}.{gatea.CURRENT_FINALIZATION_PENDING_SUFFIX}"
    )
    pending_path.write_text("{}\n", encoding="utf-8")
    allowance = gatea.CandidateTransitionRecoveryAllowance(
        path=pending_path,
        kind="current-finalization",
        candidate_sha=allowance_candidate_sha,
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: _valid_values())
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda *args, **kwargs: pytest.fail(
            "candidate mismatch must fail before image validation"
        ),
    )

    with pytest.raises(GateAError, match="does not match the live candidate"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            candidate_transition_recovery=allowance,
        )


def test_cli_app_up_passes_controller_but_never_supplies_recovery_allowance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    controller = gatea._OperationTerminationController()
    monkeypatch.setattr(gatea, "operation_lock", lambda: nullcontext())
    monkeypatch.setattr(
        gatea,
        "operation_termination_guard",
        lambda: nullcontext(controller),
    )
    monkeypatch.setattr(gatea, "app_up", lambda **kwargs: calls.append(kwargs))

    assert (
        gatea.main(
            (
                "app-up",
                "--mode",
                "loopback",
                "--record-dir",
                str(tmp_path),
            )
        )
        == 0
    )
    assert len(calls) == 1
    assert calls[0].get("candidate_transition_recovery") is None
    assert calls[0]["acceptance_record_dir"] == gatea.DEFAULT_M9_ACCEPTANCE_RECORD_DIR
    assert calls[0]["_termination_controller"] is controller


@pytest.mark.parametrize(
    ("command", "function_name"),
    (
        ("infra-up", "infra_up"),
        ("initial-migrate", "initial_migrate"),
        ("app-up", "app_up"),
        ("safe-stop", "safe_stop"),
    ),
)
def test_cli_passes_the_shared_controller_to_every_mutating_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
    function_name: str,
) -> None:
    controller = gatea._OperationTerminationController()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(gatea, "operation_lock", lambda: nullcontext())
    monkeypatch.setattr(
        gatea,
        "operation_termination_guard",
        lambda: nullcontext(controller),
    )
    monkeypatch.setattr(
        gatea,
        function_name,
        lambda **kwargs: calls.append(kwargs),
    )

    assert (
        gatea.main(
            (
                command,
                "--mode",
                "loopback",
                "--record-dir",
                str(tmp_path),
            )
        )
        == 0
    )

    assert len(calls) == 1
    assert calls[0]["_termination_controller"] is controller


def test_app_up_can_restore_an_approved_pre_m9_runtime_without_sweeper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _valid_values()
    commands: list[tuple[str, ...]] = []
    requested_services: list[tuple[str, ...]] = []
    gatea._write_migration_record(
        record_dir=tmp_path,
        candidate_sha="a" * 40,
        image_id="sha256:image",
    )

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda value: "sha256:image")
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: {
            "aerich_versions": list(gatea.APPROVED_TARGET_M8_CHAIN)
        },
    )

    def fake_compose_ps(**kwargs: object) -> list[dict[str, object]]:
        services = tuple(kwargs["services"])
        requested_services.append(services)
        rows: list[dict[str, object]] = _healthy_rows(*services)
        for row in rows:
            if row["Service"] == "nginx":
                row["Publishers"] = [
                    {
                        "URL": "127.0.0.1",
                        "TargetPort": 8080,
                        "PublishedPort": 18080,
                        "Protocol": "tcp",
                    }
                ]
        return rows

    monkeypatch.setattr(gatea, "_compose_ps", fake_compose_ps)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess(args=[], returncode=0),
    )

    gatea.app_up(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=tmp_path,
        mode="loopback",
        wait_timeout=180,
        include_table_sweeper=False,
    )

    assert commands == [
        (
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "180",
            "app",
            "nginx",
        )
    ]
    assert requested_services == [("mysql", "redis"), ("app", "nginx")]


def test_m9_upgrade_replay_record_binds_success_evidence_and_candidate(
    tmp_path: Path,
) -> None:
    success = _write_m9_upgrade_evidence(tmp_path)

    replay = gatea._require_m9_upgrade_replay_record(
        record_dir=tmp_path,
        candidate_sha="b" * 40,
        image_id="sha256:target",
        upgrade_record=success,
    )

    assert replay["passed"] is True
    assert replay["table_reconcile"] == _empty_m9_reconcile()


@pytest.mark.parametrize("tamper_target", ("evidence", "replay", "success"))
def test_m9_upgrade_replay_record_rejects_digest_or_sidecar_tampering(
    tmp_path: Path,
    tamper_target: str,
) -> None:
    success = _write_m9_upgrade_evidence(tmp_path)
    if tamper_target == "evidence":
        path = tmp_path / (
            f"{'b' * 40}.existing-database-upgrade.evidence.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = "failed"
    elif tamper_target == "replay":
        path = gatea._upgrade_replay_marker(tmp_path, "b" * 40)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["evidence_sha256"] = "e" * 64
    else:
        path = gatea._upgrade_marker(tmp_path, "b" * 40)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["completed_at"] = "2026-09-08T12:11:00+00:00"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GateAError, match="replay evidence is invalid"):
        gatea._require_m9_upgrade_replay_record(
            record_dir=tmp_path,
            candidate_sha="b" * 40,
            image_id="sha256:target",
            upgrade_record=success,
        )


def test_m9_app_up_rejects_live_schema_drift_before_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_m9_upgrade_evidence(tmp_path)
    values = _valid_values() | {
        "GATEA_APP_IMAGE": "pinkdoohub-gatea:" + "b" * 40
    }
    drifted = _m9_database_snapshot() | {"columns_sha256": "e" * 64}
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda value: "sha256:target")
    monkeypatch.setattr(gatea, "read_database_snapshot", lambda **kwargs: drifted)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess(args=[], returncode=0),
    )

    with pytest.raises(GateAError, match="schema no longer matches"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
        )

    assert commands == []


def test_m9_app_up_allows_business_counts_to_change_after_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_m9_upgrade_evidence(tmp_path)
    values = _valid_values() | {
        "GATEA_APP_IMAGE": "pinkdoohub-gatea:" + "b" * 40
    }
    live_snapshot = _m9_database_snapshot() | {
        "orders": 3,
        "table_sessions": 1,
    }
    commands: list[tuple[str, ...]] = []
    compose_images: list[str] = []
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda value: "sha256:target")
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: live_snapshot,
    )
    monkeypatch.setattr(
        gatea,
        "_run_m9_table_reconcile",
        lambda **kwargs: _empty_m9_reconcile() | {"scanned": 1},
    )

    def fake_compose_ps(**kwargs: object) -> list[dict[str, object]]:
        services = tuple(kwargs["services"])
        rows: list[dict[str, object]] = _healthy_rows(*services)
        for row in rows:
            if row["Service"] == "nginx":
                row["Publishers"] = [
                    {
                        "URL": "127.0.0.1",
                        "TargetPort": 8080,
                        "PublishedPort": 18080,
                        "Protocol": "tcp",
                    }
                ]
        return rows

    def fake_run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(tuple(kwargs["arguments"]))
        compose_images.append(str(kwargs["values"]["GATEA_APP_IMAGE"]))
        return subprocess.CompletedProcess(args=[], returncode=0)

    monkeypatch.setattr(gatea, "_compose_ps", fake_compose_ps)
    monkeypatch.setattr(gatea, "_run_compose", fake_run_compose)

    gatea.app_up(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=tmp_path,
        mode="loopback",
        wait_timeout=180,
    )

    assert commands[0][:2] == ("up", "--detach")
    assert compose_images == ["sha256:target"]


def test_backup_recovery_reuses_only_the_existing_exact_gatea_publisher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _valid_values()
    gatea._write_migration_record(
        record_dir=tmp_path,
        candidate_sha="a" * 40,
        image_id="sha256:image",
    )
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda value: "sha256:image")
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: {
            "aerich_versions": list(gatea.APPROVED_TARGET_M8_CHAIN)
        },
    )
    monkeypatch.setattr(
        gatea,
        "_assert_loopback_port_available",
        lambda port: (_ for _ in ()).throw(AssertionError("unexpected port probe")),
    )

    def fake_compose_ps(**kwargs: object) -> list[dict[str, object]]:
        services = tuple(kwargs["services"])
        rows: list[dict[str, object]] = _healthy_rows(*services)
        for row in rows:
            if row["Service"] == "nginx":
                row["Publishers"] = [
                    {
                        "URL": "127.0.0.1",
                        "TargetPort": 8080,
                        "PublishedPort": 18080,
                        "Protocol": "tcp",
                    }
                ]
        return rows

    monkeypatch.setattr(gatea, "_compose_ps", fake_compose_ps)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess(args=[], returncode=0),
    )

    gatea.app_up(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=tmp_path,
        mode="loopback",
        wait_timeout=180,
        include_table_sweeper=False,
        allow_existing_gatea_publisher=True,
    )

    assert commands == [
        (
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "180",
            "app",
            "nginx",
        )
    ]


def test_app_up_legacy_command_compatibility_is_bound_to_exact_m7(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _valid_values()
    validation_flags: list[bool] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: {
            "aerich_versions": list(gatea.APPROVED_TARGET_M7_CHAIN)
        },
    )

    def fake_validate(
        value: object,
        *,
        allow_legacy_m7_command: bool = False,
    ) -> str:
        validation_flags.append(allow_legacy_m7_command)
        return "sha256:image"

    monkeypatch.setattr(gatea, "validate_app_image", fake_validate)
    monkeypatch.setattr(gatea, "_require_deployment_record", lambda **kwargs: None)

    def fake_compose_ps(**kwargs: object) -> list[dict[str, object]]:
        services = tuple(kwargs["services"])
        rows: list[dict[str, object]] = _healthy_rows(*services)
        for row in rows:
            if row["Service"] == "nginx":
                row["Publishers"] = [
                    {
                        "URL": "127.0.0.1",
                        "TargetPort": 8080,
                        "PublishedPort": 18080,
                        "Protocol": "tcp",
                    }
                ]
        return rows

    monkeypatch.setattr(gatea, "_compose_ps", fake_compose_ps)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess(args=[], returncode=0),
    )

    gatea.app_up(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=tmp_path,
        mode="loopback",
        wait_timeout=180,
        include_table_sweeper=False,
        allow_legacy_m7_command=True,
    )

    assert validation_flags == [True]


def test_app_up_legacy_m7_compatibility_cannot_start_the_table_sweeper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _valid_values()
    snapshot_read = False

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    def fake_snapshot(**kwargs: object) -> dict[str, object]:
        nonlocal snapshot_read
        snapshot_read = True
        return {"aerich_versions": list(gatea.APPROVED_TARGET_M7_CHAIN)}

    monkeypatch.setattr(gatea, "read_database_snapshot", fake_snapshot)

    with pytest.raises(GateAError, match="cannot start the table sweeper"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            allow_legacy_m7_command=True,
        )

    assert snapshot_read is False


def test_app_up_legacy_m7_compatibility_rejects_second_snapshot_chain_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = _valid_values()
    snapshots = iter(
        (
            {"aerich_versions": list(gatea.APPROVED_TARGET_M7_CHAIN)},
            {"aerich_versions": list(gatea.APPROVED_TARGET_M8_CHAIN)},
        )
    )
    snapshot_reads = 0

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    def fake_snapshot(**kwargs: object) -> dict[str, object]:
        nonlocal snapshot_reads
        snapshot_reads += 1
        return next(snapshots)

    monkeypatch.setattr(gatea, "read_database_snapshot", fake_snapshot)
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda values, **kwargs: "sha256:image",
    )
    monkeypatch.setattr(gatea, "_require_deployment_record", lambda **kwargs: None)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: pytest.fail("chain drift must fail before compose ps"),
    )
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: pytest.fail("chain drift must fail before compose up"),
    )

    with pytest.raises(GateAError, match="requires the exact M7 chain"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            include_table_sweeper=False,
            allow_legacy_m7_command=True,
        )

    assert snapshot_reads == 2


@pytest.mark.parametrize(
    "aerich_versions",
    (
        list(gatea.APPROVED_TARGET_M8_CHAIN),
        list(gatea.APPROVED_TARGET_M9_CHAIN),
        [*gatea.APPROVED_TARGET_M7_CHAIN, "unknown"],
    ),
)
def test_app_up_legacy_command_compatibility_rejects_non_m7_chains(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    aerich_versions: list[str],
) -> None:
    values = _valid_values()
    validation_called = False

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: {"aerich_versions": aerich_versions},
    )

    def fake_validate(*args: object, **kwargs: object) -> str:
        nonlocal validation_called
        validation_called = True
        return "sha256:image"

    monkeypatch.setattr(gatea, "validate_app_image", fake_validate)

    with pytest.raises(GateAError, match="requires the exact M7 chain"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
            include_table_sweeper=False,
            allow_legacy_m7_command=True,
        )

    assert validation_called is False


def test_lifecycle_writes_reject_tls_and_safe_stop_never_removes_volumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GateAError, match="restricted to loopback"):
        gatea.infra_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="tls",
            wait_timeout=180,
        )

    values = _valid_values()
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess(args=[], returncode=0),
    )
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": service, "State": "exited"}
            for service in kwargs["services"]
        ],
    )
    gatea.safe_stop(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
    )

    assert commands == [
        (
            "stop",
            "--timeout",
            "30",
            "nginx",
            "table-sweeper",
            "app",
            "image-init",
            "redis",
            "mysql",
        )
    ]
    assert "--volumes" not in commands[0]
    assert "down" not in commands[0]


def test_loopback_runtime_rejects_non_nginx_or_public_publishers() -> None:
    with pytest.raises(GateAError, match="app must not publish"):
        gatea._validate_loopback_publishers(
            [
                {
                    "Service": "app",
                    "Publishers": [
                        {
                            "URL": "127.0.0.1",
                            "TargetPort": 8000,
                            "PublishedPort": 8000,
                            "Protocol": "tcp",
                        }
                    ],
                }
            ],
            18080,
        )

    with pytest.raises(GateAError, match="does not match"):
        gatea._validate_loopback_publishers(
            [
                {
                    "Service": "nginx",
                    "Publishers": [
                        {
                            "URL": "0.0.0.0",
                            "TargetPort": 8080,
                            "PublishedPort": 18080,
                            "Protocol": "tcp",
                        }
                    ],
                }
            ],
            18080,
        )


def test_loopback_runtime_accepts_compose_v5_unpublished_exposed_port() -> None:
    gatea._validate_loopback_publishers(
        [
            {
                "Service": "mysql",
                "Publishers": [
                    {
                        "URL": "",
                        "TargetPort": 3306,
                        "PublishedPort": 0,
                        "Protocol": "tcp",
                    }
                ],
            },
            {
                "Service": "redis",
                "Publishers": [
                    {
                        "URL": "",
                        "TargetPort": 6379,
                        "PublishedPort": 0,
                        "Protocol": "tcp",
                    }
                ],
            },
            {
                "Service": "nginx",
                "Publishers": [
                    {
                        "URL": "",
                        "TargetPort": 80,
                        "PublishedPort": 0,
                        "Protocol": "tcp",
                    },
                    {
                        "URL": "127.0.0.1",
                        "TargetPort": 8080,
                        "PublishedPort": 18080,
                        "Protocol": "tcp",
                    },
                ],
            }
        ],
        18080,
    )


def test_status_outputs_only_sanitized_service_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = _valid_values()
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {
                "Service": "app",
                "State": "running",
                "Health": "healthy",
                "Mounts": "must-not-appear",
                "Publishers": [{"URL": "must-not-appear"}],
            }
        ],
    )

    gatea.status(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=tmp_path,
        mode="loopback",
    )
    output = capsys.readouterr().out

    assert '"service": "app"' in output
    assert '"health": "healthy"' in output
    assert "must-not-appear" not in output


def _upgrade_record_payload(
    *,
    source_versions: list[str],
    target_versions: list[str],
    source_version: int | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "record_type": "existing-database-upgrade",
        "candidate_sha": "b" * 40,
        "image_id": "sha256:target",
        "passed": True,
        "completed_at": "2026-09-08T12:00:00+00:00",
        "backup_id": "20260908t120000z",
        "manifest_sha256": "c" * 64,
        "source_candidate_sha": "a" * 40,
        "source_image_id": "sha256:source",
        "source_aerich_versions": source_versions,
        "target_aerich_versions": target_versions,
    }
    if source_version is not None:
        payload["source_version"] = source_version
    return payload


def _m9_database_snapshot() -> dict[str, object]:
    return {
        "aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
        "tables": 24,
        "columns": 180,
        "statistics": 72,
        "constraints": 40,
        "columns_sha256": "1" * 64,
        "statistics_sha256": "2" * 64,
        "constraints_sha256": "3" * 64,
        "orders": 0,
        "table_sessions": 0,
    }


def _empty_m9_reconcile() -> dict[str, int]:
    return {key: 0 for key in gatea.M9_RECONCILE_KEYS}


def _write_m9_upgrade_evidence(tmp_path: Path) -> dict[str, object]:
    candidate_sha = "b" * 40
    source_sha = "a" * 40
    image_id = "sha256:target"
    backup_id = "20260908t120000z"
    manifest_sha256 = "c" * 64
    final_snapshot = _m9_database_snapshot()
    final_images = {"count": 221, "sha256": "d" * 64}
    reconcile = _empty_m9_reconcile()
    sweep = {"status": "ok", "closed": 0}
    evidence_path = tmp_path / (
        f"{candidate_sha}.existing-database-upgrade.evidence.json"
    )
    evidence = {
        "schema_version": 1,
        "record_type": "existing-database-upgrade-evidence",
        "status": "succeeded",
        "candidate_sha": candidate_sha,
        "source_candidate_sha": source_sha,
        "backup_id": backup_id,
        "final_database_snapshot": final_snapshot,
        "final_image_manifest": final_images,
        "table_reconcile": reconcile,
        "table_sweep": sweep,
    }
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    success = {
        **_upgrade_record_payload(
            source_versions=list(gatea.APPROVED_SOURCE_M7_CHAIN),
            target_versions=list(gatea.APPROVED_TARGET_M9_CHAIN),
            source_version=7,
        ),
        "candidate_sha": candidate_sha,
        "image_id": image_id,
        "source_candidate_sha": source_sha,
        "backup_id": backup_id,
        "manifest_sha256": manifest_sha256,
        "evidence_path": str(evidence_path),
        "evidence_sha256": gatea._sha256(evidence_path),
        "final_database_snapshot": final_snapshot,
        "final_image_manifest": final_images,
        "table_reconcile": reconcile,
        "table_sweep": sweep,
    }
    success_path = gatea._upgrade_marker(tmp_path, candidate_sha)
    success_path.write_text(json.dumps(success), encoding="utf-8")
    replay_result = {
        "already_current": True,
        "backup_id": backup_id,
        "candidate_sha": candidate_sha,
        "manifest_sha256": manifest_sha256,
        "mode": "plan-replay",
        "source_aerich_versions": list(gatea.APPROVED_SOURCE_M7_CHAIN),
        "source_version": 7,
        "target_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
        "target_version": 9,
    }
    replay = {
        "schema_version": 1,
        "record_type": "gatea-m9-upgrade-plan-replay",
        "passed": True,
        "candidate_sha": candidate_sha,
        "source_candidate_sha": source_sha,
        "source_version": 7,
        "image_id": image_id,
        "backup_id": backup_id,
        "manifest_sha256": manifest_sha256,
        "database_snapshot": final_snapshot,
        "image_manifest": final_images,
        "table_reconcile": reconcile,
        "upgrade_record_sha256": gatea._sha256(success_path),
        "evidence_sha256": success["evidence_sha256"],
        "result": replay_result,
        "completed_at": "2026-09-08T12:10:00+00:00",
        "secret_values_recorded": False,
    }
    gatea._upgrade_replay_marker(tmp_path, candidate_sha).write_text(
        json.dumps(replay),
        encoding="utf-8",
    )
    return success


def _m9_content_snapshot(profile: str, digest: str) -> dict[str, object]:
    return {"schema_version": 1, "profile": profile, "content_sha256": digest}


def _allow_local_schema2_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产必须 root:root；单元测试仅绕过临时目录的宿主 owner。"""

    real_validator = gatea._require_schema2_record_metadata

    def local_metadata(metadata: os.stat_result, description: str) -> None:
        adjusted = SimpleNamespace(
            **{
                field: getattr(metadata, field)
                for field in (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_nlink",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
            },
            st_uid=0,
            st_gid=0,
        )
        real_validator(adjusted, description)

    monkeypatch.setattr(gatea, "_require_schema2_record_metadata", local_metadata)


def _write_m9_adoption_evidence(tmp_path: Path) -> dict[str, object]:
    candidate_sha = "b" * 40
    source_sha = "a" * 40
    lineage_sha = "c" * 40
    image_id = "sha256:" + "1" * 64
    source_image_id = "sha256:" + "2" * 64
    lineage_image_id = "sha256:" + "3" * 64
    backup_id = "20260911t120000z"
    manifest_sha256 = "4" * 64
    snapshot = _m9_database_snapshot()
    images = {"files": 221, "sha256": "5" * 64}
    m7_content = _m9_content_snapshot("m7-preserved-business-v1", "6" * 64)
    m8_swatch_content = _m9_content_snapshot("m8-swatch-content-v1", "8" * 64)
    m9_content = _m9_content_snapshot("m9-table-business-v1", "7" * 64)
    reconcile = _empty_m9_reconcile() | {"scanned": 4}
    common = {
        "schema_version": 2,
        "transition_kind": gatea.M9_ADOPTION_TRANSITION_KIND,
        "candidate_sha": candidate_sha,
        "image_id": image_id,
        "source_candidate_sha": source_sha,
        "source_image_id": source_image_id,
        "lineage_source_candidate_sha": lineage_sha,
        "lineage_source_image_id": lineage_image_id,
        "source_version": 9,
        "target_version": 9,
        "source_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
        "target_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
        "backup_id": backup_id,
        "manifest_sha256": manifest_sha256,
        "stage_record_sha256": "8" * 64,
        "activation_record_sha256": "9" * 64,
        "predecessor_stage_record_sha256": "a" * 64,
        "predecessor_activation_record_sha256": "b" * 64,
        "predecessor_upgrade_record_sha256": "c" * 64,
        "predecessor_upgrade_evidence_sha256": "d" * 64,
        "predecessor_upgrade_plan_replay_record_sha256": "e" * 64,
        "acceptance_retirement_record_sha256": "f" * 64,
        "backup_record_sha256": "0" * 64,
        "restore_record_sha256": "1" * 64,
        "runtime_preflight": {
            "app_env": "production",
            "db_engine": "mysql",
            "jwt_algorithm": "HS256",
            "table_session_claims_enabled": True,
            "validated": True,
        },
        "started_at": "2026-09-11T12:00:00+00:00",
        "completed_at": "2026-09-11T12:01:00+00:00",
        "source_database_snapshot": snapshot,
        "final_database_snapshot": snapshot,
        "source_image_manifest": images,
        "final_image_manifest": images,
        "source_m7_content_snapshot": m7_content,
        "final_m7_content_snapshot": m7_content,
        "source_m8_swatch_content_snapshot": m8_swatch_content,
        "final_m8_swatch_content_snapshot": m8_swatch_content,
        "source_m9_table_content_snapshot": m9_content,
        "final_m9_table_content_snapshot": m9_content,
        "database_changes_applied": False,
        "migrations_applied": [],
        "table_reconcile": reconcile,
    }
    evidence_path = tmp_path / (
        f"{candidate_sha}.existing-database-upgrade.evidence.json"
    )
    evidence = {
        **common,
        "record_type": "existing-database-upgrade-evidence",
        "status": "succeeded",
        "current_stage": "completed",
        "stopped_source_verified": True,
        "steps": [],
    }
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    success = {
        **common,
        "record_type": "existing-database-upgrade",
        "passed": True,
        "evidence_path": str(evidence_path),
        "evidence_sha256": gatea._sha256(evidence_path),
    }
    success_path = gatea._upgrade_marker(tmp_path, candidate_sha)
    success_path.write_text(json.dumps(success), encoding="utf-8")
    replay = {
        "schema_version": 2,
        "transition_kind": gatea.M9_ADOPTION_TRANSITION_KIND,
        "record_type": "gatea-m9-upgrade-plan-replay",
        "passed": True,
        "candidate_sha": candidate_sha,
        "source_candidate_sha": source_sha,
        "source_version": 9,
        "image_id": image_id,
        "backup_id": backup_id,
        "manifest_sha256": manifest_sha256,
        "lineage_source_candidate_sha": lineage_sha,
        "lineage_source_image_id": lineage_image_id,
        "acceptance_retirement_record_sha256": "f" * 64,
        "database_changes_applied": False,
        "migrations_applied": [],
        "database_snapshot": snapshot,
        "m8_swatch_content_snapshot": m8_swatch_content,
        "image_manifest": images,
        "table_reconcile": reconcile,
        "upgrade_record_sha256": gatea._sha256(success_path),
        "evidence_sha256": success["evidence_sha256"],
        "result": {
            "already_current": True,
            "backup_id": backup_id,
            "candidate_sha": candidate_sha,
            "database_changes_applied": False,
            "manifest_sha256": manifest_sha256,
            "migrations_applied": [],
            "mode": "plan-replay",
            "source_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
            "source_version": 9,
            "target_aerich_versions": list(gatea.APPROVED_TARGET_M9_CHAIN),
            "target_version": 9,
            "transition_kind": gatea.M9_ADOPTION_TRANSITION_KIND,
        },
        "completed_at": "2026-09-11T12:02:00+00:00",
        "secret_values_recorded": False,
    }
    gatea._upgrade_replay_marker(tmp_path, candidate_sha).write_text(
        json.dumps(replay), encoding="utf-8"
    )
    assert set(success) == gatea.M9_ADOPTION_UPGRADE_RECORD_KEYS
    assert set(evidence) == gatea.M9_ADOPTION_EVIDENCE_RECORD_KEYS
    assert set(replay) == gatea.M9_ADOPTION_REPLAY_RECORD_KEYS
    return success


def test_m9_adoption_upgrade_and_replay_accept_closed_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    success = _write_m9_adoption_evidence(tmp_path)

    assert gatea._require_upgrade_record(
        record_dir=tmp_path,
        candidate_sha="b" * 40,
        image_id="sha256:" + "1" * 64,
    ) == success
    replay = gatea._require_m9_upgrade_replay_record(
        record_dir=tmp_path,
        candidate_sha="b" * 40,
        image_id="sha256:" + "1" * 64,
        upgrade_record=success,
    )

    assert replay["transition_kind"] == gatea.M9_ADOPTION_TRANSITION_KIND
    assert replay["table_reconcile"]["scanned"] == 4
    assert replay["database_changes_applied"] is False
    assert replay["migrations_applied"] == []
    assert (
        replay["m8_swatch_content_snapshot"]
        == success["final_m8_swatch_content_snapshot"]
    )
    assert "m8_swatch_content_snapshot" not in replay["result"]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", 1),
        ("transition_kind", "m7-to-m9"),
        ("source_version", 7),
        ("target_version", 8),
        ("database_changes_applied", True),
        ("migrations_applied", ["9_20260910180000_add_table_sessions.py"]),
        ("final_database_snapshot", {"aerich_versions": []}),
        (
            "final_m7_content_snapshot",
            _m9_content_snapshot("m7-preserved-business-v1", "f" * 64),
        ),
        (
            "final_m8_swatch_content_snapshot",
            _m9_content_snapshot("m8-swatch-content-v1", "f" * 64),
        ),
        (
            "final_m9_table_content_snapshot",
            _m9_content_snapshot("m9-table-business-v1", "f" * 64),
        ),
        ("final_image_manifest", {"files": 220, "sha256": "5" * 64}),
        ("table_reconcile", _empty_m9_reconcile() | {"open_sessions": 1}),
    ),
)
def test_m9_adoption_upgrade_rejects_non_noop_or_unbound_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    _write_m9_adoption_evidence(tmp_path)
    path = gatea._upgrade_marker(tmp_path, "b" * 40)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GateAError, match="does not match"):
        gatea._require_upgrade_record(
            record_dir=tmp_path,
            candidate_sha="b" * 40,
            image_id="sha256:" + "1" * 64,
        )


def test_m9_adoption_content_snapshot_requires_string_digest() -> None:
    assert not gatea._validate_m9_adoption_content_snapshot(
        {
            "schema_version": 1,
            "profile": "m8-swatch-content-v1",
            "content_sha256": int("8" * 64),
        },
        profile="m8-swatch-content-v1",
    )


@pytest.mark.parametrize(
    ("target", "field", "value"),
    (
        ("replay", "transition_kind", "wrong"),
        ("replay", "database_changes_applied", True),
        ("replay", "migrations_applied", ["m9"]),
        ("replay", "table_reconcile", _empty_m9_reconcile() | {"occupancies": 1}),
        (
            "replay",
            "m8_swatch_content_snapshot",
            _m9_content_snapshot("m8-swatch-content-v1", "f" * 64),
        ),
        ("evidence", "status", "failed"),
        ("evidence", "database_changes_applied", True),
        (
            "evidence",
            "final_m8_swatch_content_snapshot",
            _m9_content_snapshot("m8-swatch-content-v1", "f" * 64),
        ),
    ),
)
def test_m9_adoption_replay_rejects_tampered_or_live_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
    field: str,
    value: object,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    success = _write_m9_adoption_evidence(tmp_path)
    path = (
        gatea._upgrade_replay_marker(tmp_path, "b" * 40)
        if target == "replay"
        else tmp_path / f"{'b' * 40}.existing-database-upgrade.evidence.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GateAError, match="replay evidence is invalid"):
        gatea._require_m9_upgrade_replay_record(
            record_dir=tmp_path,
            candidate_sha="b" * 40,
            image_id="sha256:" + "1" * 64,
            upgrade_record=success,
        )


def test_schema_v1_cannot_claim_an_m9_to_m9_transition(tmp_path: Path) -> None:
    payload = _upgrade_record_payload(
        source_versions=list(gatea.APPROVED_TARGET_M9_CHAIN),
        target_versions=list(gatea.APPROVED_TARGET_M9_CHAIN),
        source_version=9,
    )
    gatea._upgrade_marker(tmp_path, "b" * 40).write_text(
        json.dumps(payload), encoding="utf-8"
    )

    with pytest.raises(GateAError, match="does not match"):
        gatea._require_upgrade_record(
            record_dir=tmp_path,
            candidate_sha="b" * 40,
            image_id="sha256:target",
        )


def test_m9_adoption_record_supports_app_up_without_loosening_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    success = _write_m9_adoption_evidence(tmp_path)
    values = _valid_values() | {
        "GATEA_APP_IMAGE": "pinkdoohub-gatea:" + "b" * 40
    }
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda value, **kwargs: "sha256:" + "1" * 64,
    )
    monkeypatch.setattr(
        gatea,
        "read_database_snapshot",
        lambda **kwargs: success["final_database_snapshot"],
    )
    monkeypatch.setattr(
        gatea,
        "_run_m9_table_reconcile",
        lambda **kwargs: _empty_m9_reconcile() | {"scanned": 4},
    )

    def compose_ps(**kwargs: object) -> list[dict[str, object]]:
        rows = _healthy_rows(*tuple(kwargs["services"]))
        for row in rows:
            if row["Service"] == "nginx":
                row["Publishers"] = [
                    {
                        "URL": "127.0.0.1",
                        "TargetPort": 8080,
                        "PublishedPort": 18080,
                        "Protocol": "tcp",
                    }
                ]
        return rows

    monkeypatch.setattr(gatea, "_compose_ps", compose_ps)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess(args=[], returncode=0),
    )

    gatea.app_up(
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        record_dir=tmp_path,
        mode="loopback",
        wait_timeout=180,
    )

    assert commands[0][:2] == ("up", "--detach")
    assert "table-sweeper" in commands[0]


def _consume_m9_adoption_records(
    tmp_path: Path,
    success: dict[str, object],
    target: str,
) -> None:
    if target == "success":
        gatea._require_upgrade_record(
            record_dir=tmp_path,
            candidate_sha="b" * 40,
            image_id="sha256:" + "1" * 64,
        )
        return
    gatea._require_m9_upgrade_replay_record(
        record_dir=tmp_path,
        candidate_sha="b" * 40,
        image_id="sha256:" + "1" * 64,
        upgrade_record=success,
    )


def _m9_adoption_record_path(tmp_path: Path, target: str) -> Path:
    if target == "success":
        return gatea._upgrade_marker(tmp_path, "b" * 40)
    if target == "evidence":
        return tmp_path / f"{'b' * 40}.existing-database-upgrade.evidence.json"
    return gatea._upgrade_replay_marker(tmp_path, "b" * 40)


@pytest.mark.parametrize(
    ("target", "field"),
    (
        ("success", "source_m8_swatch_content_snapshot"),
        ("evidence", "final_m8_swatch_content_snapshot"),
        ("replay", "m8_swatch_content_snapshot"),
    ),
)
def test_m9_adoption_consumers_require_swatch_binding_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
    field: str,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    success = _write_m9_adoption_evidence(tmp_path)
    path = _m9_adoption_record_path(tmp_path, target)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop(field)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GateAError, match="does not match|replay evidence is invalid"):
        _consume_m9_adoption_records(tmp_path, success, target)


@pytest.mark.parametrize("target", ("success", "evidence", "replay"))
def test_m9_adoption_consumers_reject_symlink_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    success = _write_m9_adoption_evidence(tmp_path)
    path = _m9_adoption_record_path(tmp_path, target)
    real_path = tmp_path / f"real-{target}.json"
    path.rename(real_path)
    path.symlink_to(real_path)

    with pytest.raises(GateAError, match="unsafe|unavailable"):
        _consume_m9_adoption_records(tmp_path, success, target)


@pytest.mark.parametrize("target", ("success", "evidence", "replay"))
def test_m9_adoption_consumers_reject_hardlinked_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    success = _write_m9_adoption_evidence(tmp_path)
    path = _m9_adoption_record_path(tmp_path, target)
    (tmp_path / f"alias-{target}.json").hardlink_to(path)

    with pytest.raises(GateAError, match="unsafe|unavailable"):
        _consume_m9_adoption_records(tmp_path, success, target)


@pytest.mark.parametrize("target", ("success", "evidence", "replay"))
def test_m9_adoption_consumers_reject_duplicate_json_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    success = _write_m9_adoption_evidence(tmp_path)
    path = _m9_adoption_record_path(tmp_path, target)
    raw = path.read_text(encoding="utf-8").replace(
        '"schema_version": 2',
        '"schema_version": 2, "schema_version": 2',
        1,
    )
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(GateAError, match="unavailable"):
        _consume_m9_adoption_records(tmp_path, success, target)


def test_schema2_stable_reader_rejects_path_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    path = tmp_path / "record.json"
    replacement = tmp_path / "replacement.json"
    path.write_text('{"schema_version": 2}\n', encoding="utf-8")
    replacement.write_text('{"schema_version": 2}\n', encoding="utf-8")
    real_read = os.read
    replaced = False

    def replacing_read(descriptor: int, length: int) -> bytes:
        nonlocal replaced
        content = real_read(descriptor, length)
        if content and not replaced:
            replaced = True
            os.replace(replacement, path)
        return content

    monkeypatch.setattr(gatea.os, "read", replacing_read)

    with pytest.raises(GateAError, match="unsafe metadata|changed during validation"):
        gatea._load_schema2_record_with_sha256(path, "schema2 record")


def test_schema2_upgrade_classification_uses_one_stable_fd_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    success = _write_m9_adoption_evidence(tmp_path)

    def unexpected_read_text(*args: object, **kwargs: object) -> str:
        raise AssertionError("schema classification must not use Path.read_text")

    monkeypatch.setattr(Path, "read_text", unexpected_read_text)

    assert gatea._require_upgrade_record(
        record_dir=tmp_path,
        candidate_sha="b" * 40,
        image_id="sha256:" + "1" * 64,
    ) == success


def test_schema2_upgrade_classification_rejects_path_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    _write_m9_adoption_evidence(tmp_path)
    path = gatea._upgrade_marker(tmp_path, "b" * 40)
    replacement = tmp_path / "replacement-upgrade.json"
    replacement.write_bytes(path.read_bytes())
    real_read = os.read
    replaced = False

    def replacing_read(descriptor: int, length: int) -> bytes:
        nonlocal replaced
        content = real_read(descriptor, length)
        if content and not replaced:
            replaced = True
            os.replace(replacement, path)
        return content

    monkeypatch.setattr(gatea.os, "read", replacing_read)

    with pytest.raises(GateAError, match="changed during validation"):
        gatea._require_upgrade_record(
            record_dir=tmp_path,
            candidate_sha="b" * 40,
            image_id="sha256:" + "1" * 64,
        )


def test_m9_adoption_success_rejects_completion_before_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _allow_local_schema2_records(monkeypatch)
    _write_m9_adoption_evidence(tmp_path)
    path = gatea._upgrade_marker(tmp_path, "b" * 40)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["completed_at"] = "2026-09-11T11:59:59+00:00"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GateAError, match="does not match"):
        gatea._require_upgrade_record(
            record_dir=tmp_path,
            candidate_sha="b" * 40,
            image_id="sha256:" + "1" * 64,
        )


def test_app_up_rejects_ambiguous_initial_and_upgrade_markers_before_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gatea._write_migration_record(
        record_dir=tmp_path,
        candidate_sha="a" * 40,
        image_id="sha256:image",
    )
    gatea._upgrade_marker(tmp_path, "a" * 40).write_text(
        json.dumps(
            _upgrade_record_payload(
                source_versions=list(gatea.APPROVED_SOURCE_M2_CHAIN),
                target_versions=list(gatea.APPROVED_TARGET_M9_CHAIN),
                source_version=2,
            )
            | {"candidate_sha": "a" * 40, "image_id": "sha256:image"}
        ),
        encoding="utf-8",
    )
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: _valid_values())
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda *args, **kwargs: "sha256:image")
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: commands.append(tuple(kwargs["arguments"])),
    )

    with pytest.raises(GateAError, match="ambiguous"):
        gatea.app_up(
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            record_dir=tmp_path,
            mode="loopback",
            wait_timeout=180,
        )

    assert commands == []


@pytest.mark.parametrize("marker_kind", ("initial", "upgrade"))
def test_deployment_record_rejects_symlink_marker(
    tmp_path: Path,
    marker_kind: str,
) -> None:
    candidate_sha = "b" * 40
    target = tmp_path / "untrusted.json"
    target.write_text("{}", encoding="utf-8")
    marker = (
        gatea._migration_marker(tmp_path, candidate_sha)
        if marker_kind == "initial"
        else gatea._upgrade_marker(tmp_path, candidate_sha)
    )
    marker.symlink_to(target)

    with pytest.raises(GateAError, match="ambiguous or unsafe"):
        gatea._require_deployment_record(
            record_dir=tmp_path,
            candidate_sha=candidate_sha,
            image_id="sha256:image",
        )


@pytest.mark.parametrize(
    ("source_versions", "target_versions", "source_version"),
    (
        (
            list(gatea.APPROVED_SOURCE_M2_CHAIN),
            list(gatea.APPROVED_TARGET_M7_CHAIN),
            None,
        ),
        (
            list(gatea.APPROVED_SOURCE_M2_CHAIN),
            list(gatea.APPROVED_TARGET_M8_CHAIN),
            None,
        ),
        (
            list(gatea.APPROVED_SOURCE_M2_CHAIN),
            list(gatea.APPROVED_TARGET_M8_CHAIN),
            2,
        ),
        (
            list(gatea.APPROVED_SOURCE_M7_CHAIN),
            list(gatea.APPROVED_TARGET_M8_CHAIN),
            7,
        ),
    ),
)
def test_deployment_record_accepts_only_approved_upgrade_transitions(
    tmp_path: Path,
    source_versions: list[str],
    target_versions: list[str],
    source_version: int | None,
) -> None:
    payload = _upgrade_record_payload(
        source_versions=source_versions,
        target_versions=target_versions,
        source_version=source_version,
    )
    gatea._upgrade_marker(tmp_path, "b" * 40).write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    assert gatea._require_deployment_record(
        record_dir=tmp_path,
        candidate_sha="b" * 40,
        image_id="sha256:target",
    ) == payload


@pytest.mark.parametrize(
    ("source_versions", "target_versions", "source_version"),
    (
        (
            list(gatea.APPROVED_SOURCE_M7_CHAIN),
            list(gatea.APPROVED_TARGET_M8_CHAIN),
            None,
        ),
        (
            list(gatea.APPROVED_SOURCE_M7_CHAIN),
            list(gatea.APPROVED_TARGET_M8_CHAIN),
            2,
        ),
        (
            list(gatea.APPROVED_SOURCE_M7_CHAIN),
            list(gatea.APPROVED_TARGET_M7_CHAIN),
            7,
        ),
        (
            list(gatea.APPROVED_SOURCE_M2_CHAIN),
            list(gatea.APPROVED_TARGET_M7_CHAIN[:-1]),
            2,
        ),
        (
            list(gatea.APPROVED_TARGET_M7_CHAIN[:4]),
            list(gatea.APPROVED_TARGET_M8_CHAIN),
            3,
        ),
    ),
)
def test_deployment_record_rejects_unapproved_or_inconsistent_transition(
    tmp_path: Path,
    source_versions: list[str],
    target_versions: list[str],
    source_version: int | None,
) -> None:
    payload = _upgrade_record_payload(
        source_versions=source_versions,
        target_versions=target_versions,
        source_version=source_version,
    )
    gatea._upgrade_marker(tmp_path, "b" * 40).write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(GateAError, match="does not match"):
        gatea._require_deployment_record(
            record_dir=tmp_path,
            candidate_sha="b" * 40,
            image_id="sha256:target",
        )


@pytest.mark.parametrize(
    ("source_versions", "source_version"),
    (
        (list(gatea.APPROVED_SOURCE_M2_CHAIN), None),
        (list(gatea.APPROVED_SOURCE_M2_CHAIN), 2.0),
        (list(gatea.APPROVED_SOURCE_M2_CHAIN), True),
        (list(gatea.APPROVED_SOURCE_M2_CHAIN), "2"),
        (list(gatea.APPROVED_SOURCE_M7_CHAIN), 7.0),
        (list(gatea.APPROVED_SOURCE_M7_CHAIN), True),
        (list(gatea.APPROVED_SOURCE_M7_CHAIN), "7"),
    ),
)
def test_upgrade_record_rejects_present_non_exact_integer_source_version(
    tmp_path: Path,
    source_versions: list[str],
    source_version: object,
) -> None:
    payload = _upgrade_record_payload(
        source_versions=source_versions,
        target_versions=list(gatea.APPROVED_TARGET_M8_CHAIN),
        source_version=None,
    )
    payload["source_version"] = source_version
    gatea._upgrade_marker(tmp_path, "b" * 40).write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(GateAError, match="does not match"):
        gatea._require_upgrade_record(
            record_dir=tmp_path,
            candidate_sha="b" * 40,
            image_id="sha256:target",
        )
