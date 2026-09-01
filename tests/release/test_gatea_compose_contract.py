"""Gate A 持久部署 Compose 与 Nginx 的静态安全契约。"""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
GATEA_ROOT = ROOT / "deploy" / "gatea"
BASE_COMPOSE = GATEA_ROOT / "compose.yml"
LOOPBACK_COMPOSE = GATEA_ROOT / "compose.loopback.yml"
TLS_COMPOSE = GATEA_ROOT / "compose.tls.yml"
BOOTSTRAP_COMPOSE = GATEA_ROOT / "compose.bootstrap.yml"
RUNTIME_DOCKERFILE = ROOT / "deploy" / "runtime" / "Dockerfile"


def _render(*overrides: Path, profiles: tuple[str, ...] = ()) -> dict:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required to validate Gate A topology")

    with tempfile.TemporaryDirectory(prefix="gatea-compose-contract-") as raw:
        temp = Path(raw)
        secret_dir = temp / "secrets"
        letsencrypt_dir = temp / "letsencrypt"
        acme_dir = temp / "acme"
        secret_dir.mkdir()
        letsencrypt_dir.mkdir()
        acme_dir.mkdir()
        for name in (
            "mysql_app_password",
            "mysql_root_password",
            "redis_password",
            "jwt_secret",
            "bootstrap_password.pending",
        ):
            (secret_dir / name).write_text(
                "contract-test-only\n",
                encoding="utf-8",
            )

        config = temp / "config.env"
        config.write_text(
            "\n".join(
                (
                    "GATEA_APP_IMAGE=pinkdoohub-gatea:contract-sha",
                    f"GATEA_CONFIG_FILE={config}",
                    f"GATEA_SECRET_DIR={secret_dir}",
                    "GATEA_LOOPBACK_PORT=18080",
                    "GATEA_API_HOST=api-test.pinkdoohub.cn",
                    f"GATEA_LETSENCRYPT_DIR={letsencrypt_dir}",
                    f"GATEA_ACME_CHALLENGE_DIR={acme_dir}",
                    "APP_NAME=pinkdooHub",
                    "APP_VERSION=0.6.0",
                    "APP_ENV=production",
                    "APP_DEBUG=false",
                    "DB_ENGINE=mysql",
                    "DB_HOST=mysql",
                    "DB_PORT=3306",
                    "DB_NAME=pinkdoohub_gatea",
                    "DB_USER=pinkdoo_app",
                    "PRODUCT_IMAGE_UPLOAD_DIR=/data/images",
                    "PRODUCT_IMAGE_BASE_URL=https://api-test.pinkdoohub.cn/uploads/products",
                    "JWT_ALGORITHM=HS256",
                    "JWT_ACCESS_TOKEN_EXPIRE=7200",
                    "JWT_REFRESH_TOKEN_EXPIRE=604800",
                    "GATEA_BOOTSTRAP_USERNAME=gatea_owner",
                    "GATEA_BOOTSTRAP_NICKNAME=Gate A Owner",
                    "GATEA_BOOTSTRAP_PHONE=13800000000",
                )
            )
            + "\n",
            encoding="utf-8",
        )

        command = [
            "docker",
            "compose",
            "--env-file",
            str(config),
            "--file",
            str(BASE_COMPOSE),
        ]
        for override in overrides:
            command.extend(("--file", str(override)))
        for profile in profiles:
            command.extend(("--profile", profile))
        command.extend(("config", "--format", "json"))
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            encoding="utf-8",
        )

    return json.loads(result.stdout)


def test_gatea_uses_frozen_images_and_shared_non_root_runtime() -> None:
    compose = _render(LOOPBACK_COMPOSE, profiles=("operations",))
    services = compose["services"]
    dockerfile = RUNTIME_DOCKERFILE.read_text(encoding="utf-8")

    assert services["mysql"]["image"] == "mysql:8.0.46"
    assert services["redis"]["image"] == "redis:8.0.1-alpine"
    assert services["nginx"]["image"] == "nginx:1.27.5-alpine"
    assert dockerfile.splitlines()[0] == "FROM python:3.10.9-slim-bullseye"
    assert "USER 10001:10001" in dockerfile
    assert "COPY deploy/runtime/app-entrypoint.sh" in dockerfile
    assert services["app"]["image"] == "pinkdoohub-gatea:contract-sha"
    assert services["app"]["read_only"] is True
    assert services["app"]["security_opt"] == ["no-new-privileges:true"]


def test_only_nginx_joins_edge_and_only_loopback_nginx_publishes_a_port() -> None:
    compose = _render(LOOPBACK_COMPOSE, profiles=("operations",))
    services = compose["services"]

    assert compose["networks"]["backend"]["internal"] is True
    assert compose["networks"]["edge"].get("internal", False) is False
    assert set(services["nginx"]["networks"]) == {"backend", "edge"}
    assert all(
        "edge" not in service.get("networks", {})
        for name, service in services.items()
        if name != "nginx"
    )
    assert services["image-init"]["network_mode"] == "none"
    assert {
        name: service["ports"]
        for name, service in services.items()
        if "ports" in service
    } == {
        "nginx": [
            {
                "mode": "ingress",
                "host_ip": "127.0.0.1",
                "target": 8080,
                "published": "18080",
                "protocol": "tcp",
            }
        ]
    }


def test_tls_override_publishes_only_http_and_https_through_nginx() -> None:
    compose = _render(TLS_COMPOSE)
    published = {
        name: service["ports"]
        for name, service in compose["services"].items()
        if "ports" in service
    }

    assert published == {
        "nginx": [
            {
                "mode": "ingress",
                "target": 8080,
                "published": "80",
                "protocol": "tcp",
            },
            {
                "mode": "ingress",
                "target": 8443,
                "published": "443",
                "protocol": "tcp",
            },
        ]
    }


def test_named_volumes_are_stable_and_not_attached_to_release_source() -> None:
    compose = _render(LOOPBACK_COMPOSE)
    services = compose["services"]

    assert compose["volumes"] == {
        "mysql_data": {"name": "pinkdoohub-gatea-mysql-data"},
        "product_images": {"name": "pinkdoohub-gatea-product-images"},
        "redis_data": {"name": "pinkdoohub-gatea-redis-data"},
    }
    assert services["mysql"]["volumes"][0]["target"] == "/var/lib/mysql"
    assert services["redis"]["volumes"][0]["target"] == "/data"
    assert {
        volume["target"] for volume in services["app"]["volumes"]
    } == {"/data/images"}
    assert all(
        volume.get("type") != "bind"
        for service in (services["mysql"], services["redis"], services["app"])
        for volume in service.get("volumes", [])
    )


def test_runtime_secrets_are_files_and_root_password_is_not_given_to_app() -> None:
    compose = _render(LOOPBACK_COMPOSE, profiles=("operations",))
    text = BASE_COMPOSE.read_text(encoding="utf-8")
    app_secrets = {
        secret["source"] for secret in compose["services"]["app"]["secrets"]
    }

    assert set(compose["secrets"]) == {
        "jwt_secret",
        "mysql_app_password",
        "mysql_root_password",
        "redis_password",
    }
    assert app_secrets == {
        "jwt_secret",
        "mysql_app_password",
        "redis_password",
    }
    assert "mysql_root_password" not in app_secrets
    assert "DB_PASSWORD:" not in text
    assert "JWT_SECRET_KEY:" not in text
    assert "redis://:" not in text


def test_migration_is_explicit_and_application_does_not_auto_migrate() -> None:
    compose = _render(LOOPBACK_COMPOSE, profiles=("operations",))
    services = compose["services"]
    dockerfile = RUNTIME_DOCKERFILE.read_text(encoding="utf-8")

    assert services["migrate"]["profiles"] == ["operations"]
    assert services["migrate"]["command"] == [
        "aerich",
        "--app",
        "models",
        "upgrade",
    ]
    assert services["app"]["command"] is None
    assert (
        'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", '
        '"--port", "8000", "--no-server-header"]'
    ) in dockerfile
    assert "aerich" not in dockerfile


def test_bootstrap_is_an_explicit_profile_with_a_pending_secret_file() -> None:
    compose = _render(
        LOOPBACK_COMPOSE,
        BOOTSTRAP_COMPOSE,
        profiles=("bootstrap",),
    )
    bootstrap = compose["services"]["bootstrap"]

    assert bootstrap["profiles"] == ["bootstrap"]
    assert "--apply" in bootstrap["command"]
    assert "--password" not in bootstrap["command"]
    assert "bootstrap_password" in {
        secret["source"] for secret in bootstrap["secrets"]
    }
    assert compose["secrets"]["bootstrap_password"]["file"].endswith(
        "/bootstrap_password.pending"
    )


def test_nginx_overwrites_untrusted_forwarding_headers_and_omits_query_log() -> None:
    for path in (
        GATEA_ROOT / "nginx" / "loopback.conf",
        GATEA_ROOT / "nginx" / "tls.conf.template",
    ):
        text = path.read_text(encoding="utf-8")
        assert "proxy_set_header X-Forwarded-For $remote_addr;" in text
        assert "proxy_set_header X-Real-IP $remote_addr;" in text
        assert "$proxy_add_x_forwarded_for" not in text
        assert '"$request_method $uri $server_protocol"' in text
        assert "$args" not in text


def test_example_config_contains_no_runtime_secret_values() -> None:
    text = (GATEA_ROOT / "config.env.example").read_text(encoding="utf-8")

    assert "DB_PASSWORD=" not in text
    assert "JWT_SECRET_KEY=" not in text
    assert "REDIS_URL=" not in text
    assert "MYSQL_ROOT_PASSWORD=" not in text
    assert "REPLACE_WITH_GIT_SHA" in text
