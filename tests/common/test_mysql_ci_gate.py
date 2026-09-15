"""Phase 9.2.4 MySQL CI 门槛脚本的安全契约。"""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPOSITORY_ROOT / "scripts" / "ci" / "check_mysql_gate.py"
PHASE95_MIGRATION = "3_20260902125032_phase95_external_identity.py"
WALLET_MIGRATION = "4_20260905162243_add_wallet_payment_refund.py"
RESERVATION_MIGRATION = "5_20260906094653_add_reservations.py"
COLOR_SELECTABLE_KIT_MIGRATION = (
    "6_20260906123000_add_color_selectable_kits.py"
)
RESERVATION_SETTINGS_MIGRATION = (
    "7_20260907190000_add_reservation_settings.py"
)
BEAD_COLOR_SWATCH_HEX_MIGRATION = (
    "8_20260908140000_add_bead_color_swatch_hex.py"
)
TABLE_SESSION_MIGRATION = "9_20260910180000_add_table_sessions.py"
EXPECTED_MIGRATION_CHAIN = [
    "0_20260810101218_init.py",
    "1_20260813130455_add_order_tables.py",
    "2_20260814104655_add_inventory_transactions.py",
    PHASE95_MIGRATION,
    WALLET_MIGRATION,
    RESERVATION_MIGRATION,
    COLOR_SELECTABLE_KIT_MIGRATION,
    RESERVATION_SETTINGS_MIGRATION,
    BEAD_COLOR_SWATCH_HEX_MIGRATION,
    TABLE_SESSION_MIGRATION,
]
SAFE_ENVIRONMENT = {
    "APP_ENV": "testing",
    "DB_ENGINE": "mysql",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "13306",
    "DB_NAME": "pinkdoohub_inventory_4311_ci",
    "DB_USER": "root",
    "DB_PASSWORD": "test-only-password",
    "INVENTORY_MYSQL_TEST_ENABLED": "1",
    "INVENTORY_MYSQL_TEST_HOST": "127.0.0.1",
    "INVENTORY_MYSQL_TEST_PORT": "13306",
    "INVENTORY_MYSQL_TEST_DB": "pinkdoohub_inventory_4311_ci",
    "INVENTORY_MYSQL_TEST_USER": "root",
    "INVENTORY_MYSQL_TEST_PASSWORD": "test-only-password",
}


def _run_preflight(tmp_path: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(SAFE_ENVIRONMENT)
    environment.update(overrides)
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "preflight",
            "--report",
            str(tmp_path / "preflight.json"),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_preflight_accepts_only_the_frozen_disposable_target(tmp_path: Path) -> None:
    result = _run_preflight(tmp_path)

    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "preflight.json").read_text(encoding="utf-8"))
    assert report == {
        "database": "pinkdoohub_inventory_4311_ci",
        "host": "127.0.0.1",
        "port": 13306,
        "schema_version": 1,
        "status": "preflight-passed",
    }
    assert SAFE_ENVIRONMENT["INVENTORY_MYSQL_TEST_PASSWORD"] not in result.stdout
    assert SAFE_ENVIRONMENT["INVENTORY_MYSQL_TEST_PASSWORD"] not in result.stderr
    assert SAFE_ENVIRONMENT["INVENTORY_MYSQL_TEST_PASSWORD"] not in report.values()


def test_snapshot_contract_includes_complete_current_migration_chain() -> None:
    checker_namespace = runpy.run_path(str(CHECKER))

    assert checker_namespace["EXPECTED_MIGRATIONS"] == EXPECTED_MIGRATION_CHAIN


def test_m8_snapshot_uses_exact_frozen_mard_hex_projection() -> None:
    checker_namespace = runpy.run_path(str(CHECKER))

    rows = checker_namespace["_expected_mard_hex_rows"]()

    assert len(rows) == 221
    assert rows[0] == (1, "#FAF4C8")
    assert rows[-1] == (221, "#757D78")
    assert len({hex_value for _, hex_value in rows}) == 221


def test_m6_through_m9_snapshots_require_replay_and_schema_evidence() -> None:
    checker_source = CHECKER.read_text(encoding="utf-8")

    assert '"seed-m6-legacy"' in checker_source
    assert "EXPECTED_MIGRATIONS_THROUGH_M5" in checker_source
    assert "M6_LEGACY_PRODUCT_NAME" in checker_source
    assert '"palette_slots": 221' in checker_source
    assert '"legacy_fixed_kit_compatible": True' in checker_source
    assert "M6_EXPECTED_COLUMNS" in checker_source
    assert "M6_EXPECTED_FOREIGN_KEYS" in checker_source
    assert "M6_EXPECTED_INDEXES" in checker_source
    assert '"seed-m7-legacy"' in checker_source
    assert "EXPECTED_MIGRATIONS_THROUGH_M6" in checker_source
    assert "M7_LEGACY_USERNAME" in checker_source
    assert "M7_LEGACY_PRODUCT_NAME" in checker_source
    assert "M7_EXPECTED_COLUMNS" in checker_source
    assert "M7_EXPECTED_INDEXES" in checker_source
    assert '"default_weekly_closed_weekday": "monday"' in checker_source
    assert '"singleton_check_valid": True' in checker_source
    assert '"legacy_history_unchanged": True' in checker_source
    assert "M8_EXPECTED_COLUMN" in checker_source
    assert "_read_m8_evidence" in checker_source
    assert '"backfilled_slots": 221' in checker_source
    assert '"manifest_projection_matches": True' in checker_source
    assert "M9_EXPECTED_TABLES" in checker_source
    assert "M9_EXPECTED_UNIQUE_INDEXES" in checker_source
    assert "M9_EXPECTED_FOREIGN_KEY_COUNT" in checker_source
    assert "_read_m9_evidence" in checker_source
    assert '"table_count": 30' in checker_source
    assert '"unique_qr_token_count": 30' in checker_source
    assert "EXPECTED_MIGRATIONS[:-1]" not in checker_source
    assert "EXPECTED_MIGRATIONS[:-2]" not in checker_source


def test_m6_index_snapshot_groups_by_table_name_and_freezes_uniqueness() -> None:
    checker_namespace = runpy.run_path(str(CHECKER))
    group_rows = checker_namespace["_group_index_rows"]
    expected_indexes = checker_namespace["M6_EXPECTED_INDEXES"]

    grouped = group_rows(
        [
            ("bead_colors", "uidx_bead_colors_slot_no", 0, "slot_no"),
            (
                "product_kit_colors",
                "idx_product_kit_colors_product_enabled",
                1,
                "product_id",
            ),
            (
                "product_kit_colors",
                "idx_product_kit_colors_product_enabled",
                1,
                "is_enabled",
            ),
        ]
    )

    assert grouped == {
        ("bead_colors", "uidx_bead_colors_slot_no"): (0, ["slot_no"]),
        (
            "product_kit_colors",
            "idx_product_kit_colors_product_enabled",
        ): (1, ["product_id", "is_enabled"]),
    }
    assert all(
        isinstance(key, tuple) and len(key) == 2
        for key in expected_indexes
    )
    assert sum(non_unique == 0 for non_unique, _ in expected_indexes.values()) == 3


def test_preflight_rejects_disabled_default_port_remote_and_wrong_schema(
    tmp_path: Path,
) -> None:
    cases = [
        {"INVENTORY_MYSQL_TEST_ENABLED": "0"},
        {"INVENTORY_MYSQL_TEST_HOST": "mysql"},
        {"INVENTORY_MYSQL_TEST_PORT": "3306"},
        {"INVENTORY_MYSQL_TEST_DB": "pinkdoohub"},
        {"DB_NAME": "a_different_schema"},
        {"DB_PASSWORD": "a-different-password"},
    ]

    for overrides in cases:
        result = _run_preflight(tmp_path, **overrides)
        assert result.returncode != 0
        assert SAFE_ENVIRONMENT["INVENTORY_MYSQL_TEST_PASSWORD"] not in result.stderr


def test_preflight_rejects_invalid_port_without_a_traceback_or_secret(
    tmp_path: Path,
) -> None:
    result = _run_preflight(
        tmp_path,
        INVENTORY_MYSQL_TEST_PORT="not-a-port",
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert SAFE_ENVIRONMENT["INVENTORY_MYSQL_TEST_PASSWORD"] not in result.stderr
