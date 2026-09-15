"""可销毁压测 Compose、Nginx 与 tc helper 的静态安全契约。"""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_ROOT = ROOT / "deploy" / "performance"
COMPOSE = PERFORMANCE_ROOT / "compose.yml"
NGINX = PERFORMANCE_ROOT / "nginx.conf.template"
SHAPER_ENTRYPOINT = PERFORMANCE_ROOT / "shaper-entrypoint.sh"
SHAPER_DOCKERIGNORE = PERFORMANCE_ROOT / "Dockerfile.shaper.dockerignore"
APP_DOCKERFILE = PERFORMANCE_ROOT / "Dockerfile.app"
APP_DOCKERIGNORE = PERFORMANCE_ROOT / "Dockerfile.app.dockerignore"
RUNTIME_DOCKERFILE = ROOT / "deploy" / "runtime" / "Dockerfile"
STEADY_LIMITS_MIB = {
    "mysql": 2240,
    "redis": 384,
    "app": 1280,
    "edge": 128,
    "shaper": 64,
}


def _render() -> dict:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required to render the performance topology")
    with tempfile.TemporaryDirectory(prefix="pinkdoohub-performance-contract-") as raw:
        temporary = Path(raw)
        secrets = temporary / "secrets"
        secrets.mkdir()
        for name in (
            "mysql_app_password",
            "mysql_root_password",
            "redis_password",
            "jwt_secret",
            "persona_password",
        ):
            (secrets / name).write_text("contract-test-only\n", encoding="utf-8")
        environment = temporary / "compose.env"
        environment.write_text(
            "\n".join(
                (
                    "PERF_APP_IMAGE=pinkdoohub-performance-app:contract",
                    "PERF_BANDWIDTH=5mbit",
                    "PERF_BURST=128kbit",
                    "PERF_COMPOSE_PROJECT=pinkdoohub-performance-contract",
                    "PERF_CPUSET=0-1",
                    "PERF_DATABASE_NAME=pinkdoohub_performance",
                    "PERF_DATABASE_USER=pinkdoo_performance",
                    "PERF_HTTP_PORT=18083",
                    "PERF_LATENCY=400ms",
                    "PERF_RUN_ID=20260909t120000",
                    f"PERF_SECRET_DIR={secrets}",
                    "PERF_SHAPER_IMAGE=pinkdoohub-performance-shaper:contract",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "docker", "compose", "--env-file", str(environment),
                "--file", str(COMPOSE), "--profile", "operations",
                "config", "--format", "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    return json.loads(result.stdout)


def test_steady_runtime_is_one_shared_two_cpu_four_gib_envelope() -> None:
    services = _render()["services"]

    assert sum(STEADY_LIMITS_MIB.values()) == 4096
    for service, limit_mib in STEADY_LIMITS_MIB.items():
        assert services[service]["cpuset"] == "0-1"
        assert int(services[service]["mem_limit"]) == limit_mib * 1024**2
        assert int(services[service]["memswap_limit"]) == limit_mib * 1024**2


def test_one_off_operations_are_bounded_and_outside_steady_sum() -> None:
    services = _render()["services"]

    assert int(services["image-init"]["mem_limit"]) == 128 * 1024**2
    assert int(services["image-init"]["memswap_limit"]) == 128 * 1024**2
    for service in ("migrate", "mard", "seed"):
        assert int(services[service]["mem_limit"]) == 1280 * 1024**2
        assert int(services[service]["memswap_limit"]) == 1280 * 1024**2
        assert services[service]["profiles"] == ["operations"]


def test_only_edge_publishes_one_non_default_loopback_port() -> None:
    services = _render()["services"]
    published = {
        name: service["ports"]
        for name, service in services.items()
        if "ports" in service
    }

    assert published == {
        "edge": [
            {
                "mode": "ingress",
                "host_ip": "127.0.0.1",
                "target": 8080,
                "published": "18083",
                "protocol": "tcp",
            }
        ]
    }
    assert "ports" not in services["mysql"]
    assert "ports" not in services["redis"]
    assert "ports" not in services["app"]


def test_shaper_has_the_only_net_admin_and_shares_edge_namespace() -> None:
    services = _render()["services"]

    assert services["shaper"]["network_mode"] == "service:edge"
    assert services["shaper"]["cap_add"] == ["NET_ADMIN"]
    assert all(
        "NET_ADMIN" not in service.get("cap_add", [])
        for name, service in services.items()
        if name != "shaper"
    )
    assert services["shaper"]["command"] == ["5mbit", "128kbit", "400ms"]
    assert _render()["networks"]["backend"]["internal"] is True


def test_production_like_app_disables_external_money_and_extends_one_login_token() -> None:
    environment = _render()["services"]["app"]["environment"]

    assert environment["APP_ENV"] == "production"
    assert environment["DB_ENGINE"] == "mysql"
    assert environment["PAYMENT_PROVIDER"] == "disabled"
    assert environment["WALLET_TOPUP_ENABLED"] == "false"
    assert environment["WALLET_ORDER_PAYMENT_ENABLED"] == "true"
    assert environment["WALLET_ADMIN_WRITE_ENABLED"] == "true"
    assert environment["JWT_ACCESS_TOKEN_EXPIRE"] == "28800"


def test_secrets_are_files_and_never_literal_environment_values() -> None:
    compose = _render()
    text = COMPOSE.read_text(encoding="utf-8")

    assert set(compose["secrets"]) == {
        "mysql_app_password",
        "mysql_root_password",
        "redis_password",
        "jwt_secret",
        "persona_password",
    }
    assert "DB_PASSWORD:" not in text
    assert "JWT_SECRET_KEY:" not in text
    assert "redis://:" not in text
    assert "MYSQL_ROOT_PASSWORD:" not in text


def test_nginx_gzips_json_but_not_png_and_serves_the_isolated_volume() -> None:
    text = NGINX.read_text(encoding="utf-8")

    assert "gzip on;" in text
    assert "gzip_vary on;" in text
    assert "gzip_min_length 1024;" in text
    assert "gzip_comp_level 6;" in text
    assert "application/json" in text
    assert "image/png" not in text
    assert "try_files $uri =404;" in text
    assert "expires" not in text


def test_shaper_script_is_valid_and_restricts_the_exact_tbf_contract() -> None:
    checked = subprocess.run(
        ["sh", "-n", str(SHAPER_ENTRYPOINT)],
        check=False,
        capture_output=True,
        text=True,
    )
    text = SHAPER_ENTRYPOINT.read_text(encoding="utf-8")

    assert checked.returncode == 0, checked.stderr
    assert "5mbit)" in text
    assert "128kbit)" in text
    assert "400ms)" in text
    assert "ip -o route show default" in text
    assert 'tc qdisc replace dev "$client_interface" root handle 1: tbf' in text
    assert "trap cleanup EXIT INT TERM" in text


def test_performance_app_build_matches_runtime_and_excludes_local_env() -> None:
    assert APP_DOCKERFILE.read_bytes() == RUNTIME_DOCKERFILE.read_bytes()
    rules = APP_DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    assert rules[0] == "**"
    assert set(rules[1:]) == {
        "!requirements.txt",
        "!pyproject.toml",
        "!app/",
        "!app/**",
        "!migrations/",
        "!migrations/**",
        "!deploy/",
        "!deploy/runtime/",
        "!deploy/runtime/app-entrypoint.sh",
        "**/__pycache__/",
        "**/*.py[cod]",
        "**/.env",
        "**/.env.*",
        "**/*.env",
        "**/*.pem",
        "**/*.key",
        "**/*.p12",
        "**/*.pfx",
        "**/*credentials*.json",
        "**/*secret*.json",
        "**/*.log",
        "**/*.db",
        "**/*.db-*",
        "**/*.sqlite",
        "**/*.sqlite-*",
    }
    assert not any(rule in rules for rule in ("!.env", "!.env.*", "!*.pem"))


def test_shaper_image_proves_tc_is_installed_during_build() -> None:
    dockerfile = (PERFORMANCE_ROOT / "Dockerfile.shaper").read_text(
        encoding="utf-8"
    )
    assert "command -v tc" in dockerfile
    assert "tc -V" in dockerfile
    assert SHAPER_DOCKERIGNORE.read_text(encoding="utf-8").splitlines() == [
        "**",
        "!Dockerfile.shaper",
        "!shaper-entrypoint.sh",
    ]
