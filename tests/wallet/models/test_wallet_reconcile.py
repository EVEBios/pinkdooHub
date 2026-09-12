"""Wallet 只读对账任务测试。"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable
from unittest.mock import AsyncMock

import pytest
from tortoise import Tortoise, connections

from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import (
    WalletTransactionSourceType,
    WalletTransactionType,
)
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction
from app.repositories.wallet_repo import WalletRepository, WalletTransactionCursor
from app.tasks import wallet_reconcile as command
from app.tasks.wallet_reconcile import WalletReconciliationTotals, reconcile_all


async def _account(username: str, *, balance: Decimal) -> WalletAccount:
    user = await User.create(
        username=username,
        password="hashed-password",
        nickname=username,
        role=UserRole.USER.value,
        status=UserStatus.NORMAL.value,
    )
    return await WalletAccount.create(user=user, balance=balance)


async def _transaction(
    account: WalletAccount,
    *,
    change: Decimal,
    before: Decimal,
    after: Decimal,
    suffix: str,
    reason: str = "对账测试",
) -> WalletTransaction:
    return await WalletTransaction.create(
        wallet_account=account,
        transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
        change_amount=change,
        before_balance=before,
        after_balance=after,
        source_type=WalletTransactionSourceType.ADMIN,
        source_id=None,
        operator=None,
        reason=reason,
        idempotency_key=f"wallet:reconcile:{account.id}:{suffix}",
    )


async def _corrupt_with_sql(query: str, values: list[object]) -> None:
    """绕过当前 Model 校验，模拟升级前或直接 SQL 留下的坏数据。"""

    connection = Tortoise.get_connection("default")
    await connection.execute_query(query, values)


async def test_reconcile_reports_mismatch_without_mutating_wallets() -> None:
    consistent = await _account("reconcile-consistent", balance=Decimal("5.00"))
    inconsistent = await _account("reconcile-mismatch", balance=Decimal("9.00"))
    for account, key in (
        (consistent, "consistent"),
        (inconsistent, "mismatch"),
    ):
        await _transaction(
            account,
            change=Decimal("5.00"),
            before=Decimal("0.00"),
            after=Decimal("5.00"),
            suffix=key,
        )

    totals = await reconcile_all(WalletRepository(), batch_size=1)

    assert totals.scanned == 2
    assert totals.mismatches == 1
    assert totals.violations == 2
    await consistent.refresh_from_db()
    await inconsistent.refresh_from_db()
    assert consistent.balance == Decimal("5.00")
    assert inconsistent.balance == Decimal("9.00")


async def test_reconcile_accepts_zero_wallet_and_stable_same_timestamp_chain() -> None:
    await _account("reconcile-empty-zero", balance=Decimal("0.00"))
    chained = await _account("reconcile-stable-chain", balance=Decimal("5.00"))
    first = await _transaction(
        chained,
        change=Decimal("2.00"),
        before=Decimal("0.00"),
        after=Decimal("2.00"),
        suffix="same-time-first",
    )
    second = await _transaction(
        chained,
        change=Decimal("3.00"),
        before=Decimal("2.00"),
        after=Decimal("5.00"),
        suffix="same-time-second",
    )
    same_created_at = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    await WalletTransaction.filter(id__in=[first.id, second.id]).update(
        created_at=same_created_at
    )

    totals = await reconcile_all(WalletRepository(), batch_size=1)

    assert totals.scanned == 2
    assert totals.mismatches == 0
    assert totals.violations == 0


async def test_reconcile_queries_only_integrity_projection_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = await _account(
        "reconcile-query-projection",
        balance=Decimal("5.00"),
    )
    await _transaction(
        account,
        change=Decimal("5.00"),
        before=Decimal("0.00"),
        after=Decimal("5.00"),
        suffix="private-query-key",
        reason="private-query-reason",
    )
    connection = connections.get("default")
    original_execute_query_dict: Callable[..., Awaitable[Any]] = (
        connection.execute_query_dict
    )
    select_queries: list[str] = []

    async def capture_query(
        query: str,
        values: list[Any] | None = None,
    ) -> Any:
        if query.lstrip().upper().startswith("SELECT"):
            select_queries.append(query)
        return await original_execute_query_dict(query, values)

    monkeypatch.setattr(connection, "execute_query_dict", capture_query)

    totals = await reconcile_all(WalletRepository(), batch_size=10)

    assert totals == WalletReconciliationTotals(scanned=1)
    assert len(select_queries) == 3
    account_query = next(
        query
        for query in select_queries
        if 'FROM "wallet_accounts"' in query
    )
    transaction_query = next(
        query
        for query in select_queries
        if 'FROM "wallet_transactions"' in query and "SUM(" not in query
    )
    assert all(
        column not in account_query
        for column in ('"status"', '"created_at"', '"updated_at"')
    )
    assert all(
        column not in transaction_query
        for column in (
            '"reason"',
            '"idempotency_key"',
            '"transaction_type"',
            '"source_type"',
            '"source_id"',
            '"operator_id"',
            '"updated_at"',
        )
    )


async def test_reconciliation_transaction_cursor_crosses_accounts_stably() -> None:
    first_account = await _account(
        "reconcile-cursor-first",
        balance=Decimal("1.00"),
    )
    second_account = await _account(
        "reconcile-cursor-second",
        balance=Decimal("1.00"),
    )
    first_transaction = await _transaction(
        first_account,
        change=Decimal("1.00"),
        before=Decimal("0.00"),
        after=Decimal("1.00"),
        suffix="cursor-first",
    )
    second_transaction = await _transaction(
        second_account,
        change=Decimal("1.00"),
        before=Decimal("0.00"),
        after=Decimal("1.00"),
        suffix="cursor-second",
    )
    same_created_at = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc)
    await WalletTransaction.filter(
        id__in=[first_transaction.id, second_transaction.id]
    ).update(created_at=same_created_at)
    repository = WalletRepository()
    account_ids = [first_account.id, second_account.id]

    first_page = await repository.list_transactions_for_reconciliation(
        account_ids,
        cursor=None,
        limit=1,
    )
    first_row = first_page[0]
    second_page = await repository.list_transactions_for_reconciliation(
        account_ids,
        cursor=WalletTransactionCursor(
            wallet_account_id=first_row.wallet_account_id,
            created_at=first_row.created_at,
            transaction_id=first_row.transaction_id,
        ),
        limit=1,
    )
    second_row = second_page[0]
    final_page = await repository.list_transactions_for_reconciliation(
        account_ids,
        cursor=WalletTransactionCursor(
            wallet_account_id=second_row.wallet_account_id,
            created_at=second_row.created_at,
            transaction_id=second_row.transaction_id,
        ),
        limit=1,
    )

    assert [first_row.transaction_id, second_row.transaction_id] == [
        first_transaction.id,
        second_transaction.id,
    ]
    assert first_row.created_at == second_row.created_at
    assert not hasattr(first_row, "reason")
    assert not hasattr(first_row, "idempotency_key")
    assert final_page == []


async def test_reconcile_nonzero_wallet_without_transactions_is_one_mismatch() -> None:
    await _account("reconcile-nonzero-without-ledger", balance=Decimal("7.00"))

    totals = await reconcile_all(WalletRepository(), batch_size=10)

    assert totals.scanned == 1
    assert totals.mismatches == 1
    assert totals.violations == 2


async def test_reconcile_reports_overlapping_checks_in_stable_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    account = await _account(
        "reconcile-overlapping-checks",
        balance=Decimal("0.00"),
    )
    transaction = await _transaction(
        account,
        change=Decimal("1.00"),
        before=Decimal("0.00"),
        after=Decimal("1.00"),
        suffix="private-overlap-key",
        reason="private-overlap-reason",
    )
    await _corrupt_with_sql(
        'UPDATE "wallet_transactions" '
        'SET "change_amount" = ?, "before_balance" = ? WHERE "id" = ?',
        ["0.00", "-1.00", transaction.id],
    )
    caplog.set_level(logging.ERROR, logger="app.tasks.wallet_reconcile")

    totals = await reconcile_all(WalletRepository(), batch_size=1)

    assert totals.scanned == 1
    assert totals.mismatches == 1
    assert totals.violations == 4
    checks = [
        "check=zero_change_amount",
        "check=transaction_balance_arithmetic_mismatch",
        "check=transaction_balance_out_of_range",
        "check=terminal_balance_mismatch",
    ]
    positions = [caplog.text.index(check) for check in checks]
    assert positions == sorted(positions)
    assert caplog.text.count(f"transaction_id={transaction.id}") == 3
    assert "private-overlap-reason" not in caplog.text
    assert "private-overlap-key" not in caplog.text
    assert "-1.00" not in caplog.text


async def test_reconcile_detects_all_row_chain_and_terminal_invariants(
    caplog: pytest.LogCaptureFixture,
) -> None:
    zero = await _account("reconcile-zero-change", balance=Decimal("0.00"))
    zero_transaction = await _transaction(
        zero,
        change=Decimal("1.00"),
        before=Decimal("0.00"),
        after=Decimal("1.00"),
        suffix="private-zero-key",
        reason="private-zero-reason",
    )
    await _corrupt_with_sql(
        'UPDATE "wallet_transactions" '
        'SET "change_amount" = ?, "after_balance" = ? WHERE "id" = ?',
        ["0.00", "0.00", zero_transaction.id],
    )

    arithmetic = await _account(
        "reconcile-bad-arithmetic", balance=Decimal("2.00")
    )
    arithmetic_transaction = await _transaction(
        arithmetic,
        change=Decimal("2.00"),
        before=Decimal("0.00"),
        after=Decimal("2.00"),
        suffix="arithmetic",
    )
    await _corrupt_with_sql(
        'UPDATE "wallet_transactions" SET "before_balance" = ? WHERE "id" = ?',
        ["1.00", arithmetic_transaction.id],
    )

    out_of_range = await _account(
        "reconcile-out-of-range", balance=Decimal("1000.00")
    )
    range_transaction = await _transaction(
        out_of_range,
        change=Decimal("1.00"),
        before=Decimal("0.00"),
        after=Decimal("1.00"),
        suffix="range",
    )
    await _corrupt_with_sql(
        'UPDATE "wallet_transactions" '
        'SET "change_amount" = ?, "after_balance" = ? WHERE "id" = ?',
        ["1001.00", "1001.00", range_transaction.id],
    )
    await _corrupt_with_sql(
        'UPDATE "wallet_accounts" SET "balance" = ? WHERE "id" = ?',
        ["1001.00", out_of_range.id],
    )

    broken_chain = await _account(
        "reconcile-broken-chain", balance=Decimal("5.00")
    )
    await _transaction(
        broken_chain,
        change=Decimal("2.00"),
        before=Decimal("0.00"),
        after=Decimal("2.00"),
        suffix="chain-first",
    )
    await _transaction(
        broken_chain,
        change=Decimal("3.00"),
        before=Decimal("1.00"),
        after=Decimal("4.00"),
        suffix="chain-second",
    )
    await _account("reconcile-nonzero-empty", balance=Decimal("7.00"))

    accounts_before = await WalletAccount.all().order_by("id").values()
    transactions_before = await WalletTransaction.all().order_by("id").values()
    caplog.set_level(logging.ERROR, logger="app.tasks.wallet_reconcile")

    totals = await reconcile_all(WalletRepository(), batch_size=1)

    assert totals.scanned == 5
    assert totals.mismatches == 5
    assert totals.violations == 7
    for check in (
        "zero_change_amount",
        "transaction_balance_arithmetic_mismatch",
        "transaction_balance_out_of_range",
        "transaction_balance_chain_mismatch",
        "terminal_balance_mismatch",
        "ledger_total_mismatch",
        "nonzero_balance_without_transactions",
    ):
        assert f"check={check}" in caplog.text
    assert f"transaction_id={zero_transaction.id}" in caplog.text
    assert "private-zero-reason" not in caplog.text
    assert "private-zero-key" not in caplog.text
    assert "1001.00" not in caplog.text
    assert await WalletAccount.all().order_by("id").values() == accounts_before
    assert (
        await WalletTransaction.all().order_by("id").values()
        == transactions_before
    )


@pytest.mark.parametrize("batch_size", [0, 1001])
async def test_reconcile_rejects_invalid_batch_size(batch_size: int) -> None:
    with pytest.raises(ValueError, match="batch_size must be between 1 and 1000"):
        await reconcile_all(WalletRepository(), batch_size=batch_size)


@pytest.mark.parametrize(
    ("totals", "expected_exit_code"),
    [
        (WalletReconciliationTotals(scanned=1), 0),
        (WalletReconciliationTotals(scanned=1, mismatches=1, violations=1), 1),
        (WalletReconciliationTotals(scanned=1, violations=1), 1),
    ],
)
def test_reconcile_cli_returns_nonzero_for_any_violation(
    monkeypatch: pytest.MonkeyPatch,
    totals: WalletReconciliationTotals,
    expected_exit_code: int,
) -> None:
    monkeypatch.setattr(command, "run", AsyncMock(return_value=totals))
    monkeypatch.setattr("sys.argv", ["wallet_reconcile"])

    assert command.main() == expected_exit_code
