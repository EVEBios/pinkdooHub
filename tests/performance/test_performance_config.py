"""性能压测 run identity、路径与私有文件安全契约。"""

import os
from pathlib import Path
import socket

import pytest

from scripts.performance import config as module
from scripts.performance.config import (
    PerformanceConfigError,
    config_for_run,
    content_digest,
    write_private,
)


def test_run_config_derives_only_exact_unique_names_and_safe_summary() -> None:
    config = config_for_run("20260909t120000", http_port=18083, cpuset="0-1")

    assert config.project == "pinkdoohub-performance-20260909t120000"
    assert config.app_image == "pinkdoohub-performance-app:20260909t120000"
    assert config.shaper_image == "pinkdoohub-performance-shaper:20260909t120000"
    assert config.base_url == "http://127.0.0.1:18083"
    summary = config.safe_summary()
    assert "secret_categories" in summary
    assert not any("password=" in str(value) for value in summary.values())


@pytest.mark.parametrize(
    "run_id",
    (
        "",
        "20260909T120000",
        "2026-09-09t120000",
        "20260230t120000",
        "../../escape",
    ),
)
def test_run_id_must_be_a_real_strict_lowercase_timestamp(run_id: str) -> None:
    with pytest.raises(PerformanceConfigError):
        config_for_run(run_id)


@pytest.mark.parametrize("port", (1, 3306, 6379, 8000, 65536))
def test_default_and_developer_ports_are_rejected(port: int) -> None:
    with pytest.raises(PerformanceConfigError):
        config_for_run("20260909t120000", http_port=port)


@pytest.mark.parametrize("cpuset", ("0", "0-0", "0-2", "2-1", "0,1", "a-b"))
def test_cpuset_must_be_exactly_two_consecutive_cpus(cpuset: str) -> None:
    with pytest.raises(PerformanceConfigError):
        config_for_run("20260909t120000", cpuset=cpuset)


def test_port_probe_rejects_listener_and_accepts_immediately_released_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = int(server.getsockname()[1])
        assert module.port_is_available(port) is False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(("127.0.0.1", port))
            connection, _ = server.accept()
            connection.close()
            client.recv(1)

    assert module.port_is_available(port) is True


def test_write_private_is_0600_and_refuses_replacement(tmp_path: Path) -> None:
    target = tmp_path / "secret"
    write_private(target, "contract-test-only")

    assert target.read_text(encoding="utf-8") == "contract-test-only\n"
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_private(target, "replacement")


def test_content_digest_ignores_python_cache_and_rejects_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    source = root / "source"
    cache = source / "__pycache__"
    cache.mkdir(parents=True)
    (source / "module.py").write_text("value = 1\n", encoding="utf-8")
    (cache / "module.pyc").write_bytes(b"first")
    monkeypatch.setattr(module, "REPOSITORY_ROOT", root)

    first = content_digest((source,))
    (cache / "module.pyc").write_bytes(b"second")
    assert content_digest((source,)) == first
    with pytest.raises(PerformanceConfigError):
        content_digest((tmp_path / "outside",))


def test_existing_symlink_roots_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    workspace = tmp_path / "workspace"
    os.symlink(destination, workspace)
    monkeypatch.setattr(module, "WORKSPACE_ROOT", workspace)
    monkeypatch.setattr(module, "ARTIFACT_ROOT", tmp_path / "artifacts")

    with pytest.raises(PerformanceConfigError, match="must not be a symlink"):
        config_for_run("20260909t120000")
