"""Gate A 持久部署预检与生命周期命令边界。"""

import json
from pathlib import Path
import subprocess

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
        lambda **kwargs: _healthy_rows("mysql"),
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
        False,
    )


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
        lambda **kwargs: _healthy_rows("mysql", "redis"),
    )

    def fake_run_compose(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        profiles = tuple(kwargs.get("profiles", ()))
        commands.append((arguments, profiles))
        stdout = "0\n" if arguments[:3] == ("exec", "--no-tty", "mysql") else ""
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
        lambda **kwargs: _healthy_rows("mysql", "redis"),
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
            "nginx",
        )
    ]


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
