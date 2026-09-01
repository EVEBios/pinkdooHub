"""Gate A 持久部署预检的配置与命令边界。"""

from pathlib import Path

import pytest

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
