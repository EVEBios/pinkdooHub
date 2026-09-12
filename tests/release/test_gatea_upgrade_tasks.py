"""Gate A 单步迁移与 Wallet 准备编排边界。"""

import json
from pathlib import Path

import pytest

from app.tasks import gatea_migrate_step as migration_step
from app.tasks import gatea_wallet_prepare as wallet_prepare
from app.tasks.legacy_manual_settlement_backfill import (
    LegacyManualSettlementTotals,
    LegacySettlementBlocker,
)
from app.tasks.wallet_account_backfill import WalletBackfillTotals
from app.tasks.wallet_reconcile import WalletReconciliationTotals


class _FakeSettings:
    app_env = "production"
    db_engine = "mysql"


@pytest.mark.parametrize("target", (2, 10))
async def test_migration_step_rejects_unapproved_targets(target: int) -> None:
    with pytest.raises(migration_step.GateAMigrationStepError, match="M3 through M9"):
        await migration_step.apply_migration_step(target)


async def test_migration_step_applies_only_the_next_approved_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = [migration_step.APPROVED_MIGRATIONS[:3]]
    migrated: list[str] = []

    class FakeCommand:
        def __init__(self, **kwargs: object) -> None:
            location = Path(str(kwargs["location"])) / "models"
            assert tuple(sorted(path.name for path in location.glob("*.py"))) == (
                migration_step.APPROVED_MIGRATIONS[:4]
            )

        async def init(self) -> None:
            return None

        async def upgrade(self) -> list[str]:
            migrated.append(migration_step.APPROVED_MIGRATIONS[3])
            versions[0] = migration_step.APPROVED_MIGRATIONS[:4]
            return migrated.copy()

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(migration_step, "settings", _FakeSettings())
    monkeypatch.setattr(migration_step, "Command", FakeCommand)
    monkeypatch.setattr(migration_step, "_validate_sources", lambda: None)
    monkeypatch.setattr(
        migration_step,
        "_current_versions",
        lambda: _async_value(versions[0]),
    )

    result = await migration_step.apply_migration_step(3)

    assert result.applied is True
    assert result.migration == migration_step.APPROVED_MIGRATIONS[3]
    assert result.aerich_versions == migration_step.APPROVED_MIGRATIONS[:4]
    assert migrated == [migration_step.APPROVED_MIGRATIONS[3]]


async def _async_value(value: object) -> object:
    return value


async def test_migration_step_replays_target_without_calling_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCommand:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def init(self) -> None:
            return None

        async def upgrade(self) -> list[str]:
            raise AssertionError("upgrade must not run for a completed target")

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(migration_step, "settings", _FakeSettings())
    monkeypatch.setattr(migration_step, "Command", FakeCommand)
    monkeypatch.setattr(migration_step, "_validate_sources", lambda: None)
    monkeypatch.setattr(
        migration_step,
        "_current_versions",
        lambda: _async_value(migration_step.APPROVED_MIGRATIONS[:5]),
    )

    result = await migration_step.apply_migration_step(4)

    assert result.applied is False
    assert result.aerich_versions == migration_step.APPROVED_MIGRATIONS[:5]


async def test_migration_step_rejects_unknown_or_skipped_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCommand:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def init(self) -> None:
            return None

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(migration_step, "settings", _FakeSettings())
    monkeypatch.setattr(migration_step, "Command", FakeCommand)
    monkeypatch.setattr(migration_step, "_validate_sources", lambda: None)
    monkeypatch.setattr(
        migration_step,
        "_current_versions",
        lambda: _async_value(("unexpected.py",)),
    )

    with pytest.raises(
        migration_step.GateAMigrationStepError,
        match="approved preceding version",
    ):
        await migration_step.apply_migration_step(4)


async def test_wallet_preparation_previews_before_writes_and_converges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool, int | None]] = []

    async def fake_init(**kwargs: object) -> None:
        return None

    async def fake_close() -> None:
        return None

    async def fake_wallet(**kwargs: object) -> WalletBackfillTotals:
        dry_run = bool(kwargs["dry_run"])
        through = kwargs["through_user_id"]
        calls.append(("wallet", dry_run, through))
        if through is None:
            return WalletBackfillTotals(through_user_id=9, would_create=3)
        if dry_run:
            return WalletBackfillTotals(through_user_id=9)
        return WalletBackfillTotals(through_user_id=9, scanned=3, created=3)

    async def fake_settlement(**kwargs: object) -> LegacyManualSettlementTotals:
        dry_run = bool(kwargs["dry_run"])
        through = kwargs["through_order_id"]
        calls.append(("settlement", dry_run, through))
        if through is None:
            return LegacyManualSettlementTotals(
                through_order_id=7,
                scanned=2,
                would_create=2,
            )
        if dry_run:
            return LegacyManualSettlementTotals(
                through_order_id=7,
                scanned=2,
                replayed=2,
            )
        return LegacyManualSettlementTotals(
            through_order_id=7,
            scanned=2,
            created=2,
        )

    monkeypatch.setattr(wallet_prepare, "settings", _FakeSettings())
    monkeypatch.setattr(wallet_prepare.Tortoise, "init", fake_init)
    monkeypatch.setattr(wallet_prepare.Tortoise, "close_connections", fake_close)
    monkeypatch.setattr(wallet_prepare, "_wallet_backfill", fake_wallet)
    monkeypatch.setattr(wallet_prepare, "_settlement_backfill", fake_settlement)
    monkeypatch.setattr(
        wallet_prepare.wallet_reconcile,
        "reconcile_all",
        lambda *args, **kwargs: _async_value(
            WalletReconciliationTotals(scanned=3)
        ),
    )

    result = await wallet_prepare.prepare_wallet_data()

    assert calls == [
        ("wallet", True, None),
        ("settlement", True, None),
        ("wallet", False, 9),
        ("settlement", False, 7),
        ("wallet", True, 9),
        ("settlement", True, 7),
    ]
    assert result == {
        "wallet_accounts": {
            "through_user_id": 9,
            "preview_would_create": 3,
            "created": 3,
            "replay_would_create": 0,
        },
        "legacy_settlements": {
            "through_order_id": 7,
            "preview_would_create": 2,
            "created": 2,
            "replayed": 0,
            "replay_would_create": 0,
            "blocked": 0,
        },
        "reconciliation": {"scanned": 3, "mismatches": 0, "violations": 0},
    }


async def test_wallet_preparation_blocker_stops_before_any_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    async def fake_init(**kwargs: object) -> None:
        return None

    async def fake_close() -> None:
        return None

    async def fake_wallet(**kwargs: object) -> WalletBackfillTotals:
        calls.append(("wallet", bool(kwargs["dry_run"])))
        return WalletBackfillTotals(through_user_id=2, would_create=1)

    async def fake_settlement(**kwargs: object) -> LegacyManualSettlementTotals:
        calls.append(("settlement", bool(kwargs["dry_run"])))
        return LegacyManualSettlementTotals(
            through_order_id=4,
            blockers=(LegacySettlementBlocker(order_id=4, reason="missing_audit"),),
        )

    monkeypatch.setattr(wallet_prepare, "settings", _FakeSettings())
    monkeypatch.setattr(wallet_prepare.Tortoise, "init", fake_init)
    monkeypatch.setattr(wallet_prepare.Tortoise, "close_connections", fake_close)
    monkeypatch.setattr(wallet_prepare, "_wallet_backfill", fake_wallet)
    monkeypatch.setattr(wallet_prepare, "_settlement_backfill", fake_settlement)

    with pytest.raises(
        wallet_prepare.GateAWalletPreparationError,
        match="count=1 reasons=missing_audit",
    ):
        await wallet_prepare.prepare_wallet_data()

    assert calls == [("wallet", True), ("settlement", True)]
