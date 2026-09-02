"""Phase 9.3 运行时合成角色的安全目标契约。"""

import pytest

from app.tasks.phase93_runtime_seed import RuntimeSeedError, validate_target


def _environment() -> dict[str, str]:
    return {
        "PHASE93_RUNTIME_SEED_ENABLED": "1",
        "PINKDOOHUB_BOOTSTRAP_PASSWORD": "synthetic-test-only",
        "APP_ENV": "production",
        "DB_ENGINE": "mysql",
        "DB_HOST": "mysql-source",
        "DB_PORT": "3306",
        "DB_NAME": "pinkdoohub_phase93_source",
        "DB_USER": "pinkdoo",
    }


def test_runtime_seed_accepts_only_frozen_source_target() -> None:
    validate_target(_environment())


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("PHASE93_RUNTIME_SEED_ENABLED", "0"),
        ("PINKDOOHUB_BOOTSTRAP_PASSWORD", ""),
        ("APP_ENV", "testing"),
        ("DB_ENGINE", "sqlite"),
        ("DB_HOST", "127.0.0.1"),
        ("DB_PORT", "14306"),
        ("DB_NAME", "pinkdoohub"),
        ("DB_USER", "root"),
    ),
)
def test_runtime_seed_rejects_any_target_drift(key: str, value: str) -> None:
    environment = _environment()
    environment[key] = value

    with pytest.raises(RuntimeSeedError):
        validate_target(environment)
