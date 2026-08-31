"""Phase 9.3 Docker 演练拓扑的静态安全契约。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

from scripts.release.phase93_rehearsal import IMAGE_TAGS


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "deploy" / "rehearsal" / "compose.yml"
DOCKERFILE_PATH = ROOT / "deploy" / "rehearsal" / "Dockerfile"


def _compose() -> dict:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required to validate rehearsal topology")

    with tempfile.TemporaryDirectory(prefix="phase93-compose-contract-") as temp:
        temp_path = Path(temp)
        secret_dir = temp_path / "secrets"
        cert_dir = temp_path / "certs"
        secret_dir.mkdir()
        cert_dir.mkdir()
        for name in (
            "mysql_app_password",
            "mysql_root_password",
            "redis_password",
            "jwt_secret",
            "bootstrap_password",
        ):
            (secret_dir / name).write_text("contract-test-only", encoding="utf-8")

        environment = os.environ | {
            "PHASE93_COMPOSE_PROJECT": "pinkdoohub-phase93-contract",
            "PHASE93_APP_IMAGE": "pinkdoohub-phase93:contract",
            "PHASE93_SOURCE_MYSQL_PORT": "14306",
            "PHASE93_RESTORE_MYSQL_PORT": "14307",
            "PHASE93_REDIS_PORT": "16379",
            "PHASE93_HTTPS_HOST": "phase93.pinkdoo.test",
            "PHASE93_HTTPS_PORT": "18443",
            "PHASE93_SECRET_DIR": str(secret_dir),
            "PHASE93_CERT_DIR": str(cert_dir),
        }
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--file",
                str(COMPOSE_PATH),
                "--profile",
                "operations",
                "config",
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            encoding="utf-8",
            env=environment,
        )

    return json.loads(result.stdout)


def test_rehearsal_uses_frozen_images_and_internal_network() -> None:
    compose = _compose()
    services = compose["services"]
    dockerfile_base = DOCKERFILE_PATH.read_text(encoding="utf-8").splitlines()[0]

    assert services["mysql-source"]["image"] == "mysql:8.0.46"
    assert services["mysql-restore"]["image"] == "mysql:8.0.46"
    assert services["redis"]["image"] == "redis:8.0.1-alpine"
    assert services["https"]["image"] == "nginx:1.27.5-alpine"
    assert dockerfile_base == "FROM python:3.10.9-slim-bullseye"
    assert IMAGE_TAGS == (
        "mysql:8.0.46",
        "redis:8.0.1-alpine",
        "python:3.10.9-slim-bullseye",
        "nginx:1.27.5-alpine",
    )
    assert compose["networks"]["rehearsal"]["internal"] is True


def test_all_host_ports_are_loopback_and_non_default() -> None:
    compose = _compose()
    published = {
        service: config["ports"]
        for service, config in compose["services"].items()
        if "ports" in config
    }

    assert published == {
        "mysql-source": [
            {
                "mode": "ingress",
                "target": 3306,
                "published": "14306",
                "protocol": "tcp",
                "host_ip": "127.0.0.1",
            }
        ],
        "mysql-restore": [
            {
                "mode": "ingress",
                "target": 3306,
                "published": "14307",
                "protocol": "tcp",
                "host_ip": "127.0.0.1",
            }
        ],
        "redis": [
            {
                "mode": "ingress",
                "target": 6379,
                "published": "16379",
                "protocol": "tcp",
                "host_ip": "127.0.0.1",
            }
        ],
        "https": [
            {
                "mode": "ingress",
                "target": 8443,
                "published": "18443",
                "protocol": "tcp",
                "host_ip": "127.0.0.1",
            }
        ],
    }
    assert "3306:3306" not in COMPOSE_PATH.read_text(encoding="utf-8")


def test_source_restore_and_images_use_distinct_persistent_volumes() -> None:
    services = _compose()["services"]

    assert services["mysql-source"]["volumes"] == [
        {
            "type": "volume",
            "source": "mysql_source_data",
            "target": "/var/lib/mysql",
            "volume": {},
        }
    ]
    assert services["mysql-restore"]["volumes"] == [
        {
            "type": "volume",
            "source": "mysql_restore_data",
            "target": "/var/lib/mysql",
            "volume": {},
        }
    ]
    assert {
        "type": "volume",
        "source": "product_images",
        "target": "/data/images",
        "volume": {},
    } in services["app"]["volumes"]
    assert {
        "type": "volume",
        "source": "product_images",
        "target": "/data/uploads/products",
        "read_only": True,
        "volume": {},
    } in services["https"]["volumes"]
    assert services["image-restore"]["volumes"] == [
        {
            "type": "volume",
            "source": "product_images_restore",
            "target": "/restore",
            "volume": {},
        }
    ]


def test_runtime_secrets_are_files_not_literal_environment_values() -> None:
    compose = _compose()
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    secret_names = {
        "mysql_app_password",
        "mysql_root_password",
        "redis_password",
        "jwt_secret",
        "bootstrap_password",
        "bootstrap_rotated_password",
    }

    assert set(compose["secrets"]) == secret_names
    assert all("file" in compose["secrets"][name] for name in secret_names)
    assert "DB_PASSWORD:" not in text
    assert "JWT_SECRET_KEY:" not in text
    assert "PINKDOOHUB_BOOTSTRAP_PASSWORD:" not in text
    assert "redis://:" not in text


def test_app_runs_non_root_and_is_not_published_directly() -> None:
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    services = _compose()["services"]

    assert "USER 10001:10001" in dockerfile
    assert "ports" not in services["app"]
    assert services["app"]["environment"]["APP_ENV"] == "production"
    assert services["app"]["environment"]["APP_DEBUG"] == "false"
    assert services["app"]["environment"]["DB_ENGINE"] == "mysql"


def test_bootstrap_command_has_no_password_argument() -> None:
    bootstrap = _compose()["services"]["bootstrap"]
    command = bootstrap["command"]

    assert "--apply" in command
    assert "--password" not in command
    assert "bootstrap_password" in {
        secret["source"] for secret in bootstrap["secrets"]
    }


def test_migration_scenario_is_explicitly_isolated_and_uses_root_secret_file() -> None:
    scenario = _compose()["services"]["migration-scenario"]

    assert scenario["environment"]["APP_ENV"] == "testing"
    assert scenario["environment"]["DB_USER"] == "root"
    assert scenario["environment"]["DB_NAME"] == "pinkdoohub_phase93_m0"
    assert "ports" not in scenario
    assert {
        "source": "mysql_root_password",
        "target": "mysql_app_password",
    } in scenario["secrets"]


def test_runtime_seed_is_guarded_and_has_no_published_port() -> None:
    seed = _compose()["services"]["runtime-seed"]

    assert seed["environment"]["APP_ENV"] == "production"
    assert seed["environment"]["PHASE93_RUNTIME_SEED_ENABLED"] == "1"
    assert "ports" not in seed
    assert "bootstrap_password" in {
        secret["source"] for secret in seed["secrets"]
    }


def test_restore_app_uses_independent_database_images_and_rotated_credential() -> None:
    restore_app = _compose()["services"]["restore-app"]

    assert restore_app["environment"]["DB_HOST"] == "mysql-restore"
    assert restore_app["environment"]["DB_NAME"] == "pinkdoohub_phase93_restore"
    assert "ports" not in restore_app
    assert {
        "type": "volume",
        "source": "product_images_restore",
        "target": "/data/images",
        "read_only": True,
        "volume": {},
    } in restore_app["volumes"]
    assert "bootstrap_rotated_password" in {
        secret["source"] for secret in restore_app["secrets"]
    }


def test_docker_context_excludes_local_state_and_frontend_tree() -> None:
    ignored = set(
        (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    )

    assert {
        ".git",
        ".venv",
        "artifacts",
        "backups",
        "logs",
        "miniapp",
        "tests",
        "uploads",
    }.issubset(ignored)
