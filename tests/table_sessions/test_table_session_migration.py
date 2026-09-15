import importlib


async def test_m9_migration_has_exact_tables_constraints_and_safe_downgrade() -> None:
    module = importlib.import_module(
        "migrations.models.9_20260910180000_add_table_sessions"
    )
    sql = await module.upgrade(None)

    assert module.RUN_IN_TRANSACTION is False
    for table_name in (
        "store_tables",
        "table_sessions",
        "table_session_timers",
        "table_occupancies",
    ):
        assert f"CREATE TABLE `{table_name}`" in sql
    assert "COLLATE ascii_bin" in sql
    assert "DEFAULT 10" in sql
    for unique_name in (
        "uidx_store_table_no",
        "uidx_store_table_qr_token",
        "uidx_table_session_no",
        "uidx_table_session_claim_idempotency",
        "uidx_table_session_release_idempotency",
        "uidx_table_session_payment",
        "uidx_table_session_timer_duration",
        "uidx_table_occupancy_table",
        "uidx_table_occupancy_session",
        "uidx_table_occupancy_user",
        "uidx_table_occupancy_order",
    ):
        assert f"UNIQUE KEY `{unique_name}`" in sql
    assert sql.count(" ON DELETE RESTRICT") == 10

    downgrade = await module.downgrade(None)
    assert downgrade.index("table_occupancies") < downgrade.index("table_sessions")
    assert downgrade.index("table_session_timers") < downgrade.index("table_sessions")
