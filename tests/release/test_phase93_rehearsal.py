"""Phase 9.3 演练工作区安全边界测试。"""

from pathlib import Path
import socket

import pytest

from scripts.release.phase93_rehearsal import (
    HTTPS_HOST,
    PORTS,
    RehearsalError,
    config_for_run,
)


def test_config_uses_exact_disposable_names_and_non_default_ports() -> None:
    config = config_for_run("20260831t120000")

    assert config.project == "pinkdoohub-phase93-20260831t120000"
    assert config.root == Path("/tmp/pinkdoohub-phase93/20260831t120000")
    assert config.app_image == "pinkdoohub-phase93:20260831t120000"
    assert 3306 not in PORTS.values()
    assert len(set(PORTS.values())) == 4


@pytest.mark.parametrize(
    "run_id",
    (
        "20260831T120000",
        "20260831t1200",
        "20260230t120000",
        "../20260831t120000",
        "phase93",
    ),
)
def test_config_rejects_ambiguous_or_unsafe_run_ids(run_id: str) -> None:
    with pytest.raises(RehearsalError):
        config_for_run(run_id)


def test_compose_environment_contains_paths_but_no_secret_values() -> None:
    config = config_for_run("20260831t120000")
    environment = config.compose_environment()

    assert environment["PHASE93_COMPOSE_PROJECT"] == config.project
    assert environment["PHASE93_HTTPS_HOST"] == HTTPS_HOST
    assert environment["PHASE93_SECRET_DIR"] == str(config.secret_dir)
    assert "PASSWORD" not in " ".join(environment)
    assert not any("redis://" in value for value in environment.values())


def test_frozen_ports_are_currently_loopback_bindable() -> None:
    listeners: list[socket.socket] = []
    try:
        for port in PORTS.values():
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", port))
            listeners.append(listener)
    finally:
        for listener in listeners:
            listener.close()
