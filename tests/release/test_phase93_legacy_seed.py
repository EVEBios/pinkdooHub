"""Phase 9.3 旧迁移 fixture 的隔离目标契约。"""

import re

import pytest

from app.common.constants.order import ORDER_NO_LENGTH, ORDER_NO_PATTERN
from app.tasks.phase93_legacy_seed import (
    PHASE93_LEGACY_ORDER_NO,
    LegacySeedError,
    validate_target,
)


def _environment(version: int) -> dict[str, str]:
    return {
        "PHASE93_LEGACY_SEED_ENABLED": "1",
        "APP_ENV": "testing",
        "DB_ENGINE": "mysql",
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "14306",
        "DB_NAME": f"pinkdoohub_phase93_m{version}",
        "DB_USER": "root",
    }


@pytest.mark.parametrize("version", (0, 1))
def test_legacy_seed_accepts_only_frozen_synthetic_targets(version: int) -> None:
    validate_target(_environment(version), version)


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("PHASE93_LEGACY_SEED_ENABLED", "0"),
        ("APP_ENV", "production"),
        ("DB_ENGINE", "sqlite"),
        ("DB_HOST", "mysql.internal"),
        ("DB_PORT", "3306"),
        ("DB_NAME", "pinkdoohub"),
        ("DB_USER", "pinkdoo"),
    ),
)
def test_legacy_seed_rejects_unsafe_target_changes(key: str, value: str) -> None:
    environment = _environment(0)
    environment[key] = value

    with pytest.raises(LegacySeedError):
        validate_target(environment, 0)


def test_legacy_seed_rejects_unknown_migration_version() -> None:
    with pytest.raises(LegacySeedError):
        validate_target(_environment(0), 2)


def test_migration_one_seed_accepts_only_the_named_failure_scenario_alias() -> None:
    environment = _environment(1)
    environment["DB_NAME"] = "pinkdoohub_phase93_failure"
    validate_target(environment, 1)

    environment["DB_NAME"] = "pinkdoohub_phase93_failure_typo"
    with pytest.raises(LegacySeedError):
        validate_target(environment, 1)


def test_migration_one_fixture_order_number_matches_domain_contract() -> None:
    assert len(PHASE93_LEGACY_ORDER_NO) == ORDER_NO_LENGTH
    assert re.fullmatch(ORDER_NO_PATTERN, PHASE93_LEGACY_ORDER_NO)
