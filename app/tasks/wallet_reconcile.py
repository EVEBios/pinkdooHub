"""只读核对 WalletAccount 权威余额与不可变流水逐行、链式完整性。"""

import argparse
import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal

from tortoise import Tortoise

from app.common.constants.wallet import WALLET_BALANCE_MAX, WALLET_BALANCE_MIN
from app.core.logging import setup_logging
from app.db.database import TORTOISE_ORM
from app.repositories.wallet_repo import (
    WalletReconciliationRow,
    WalletReconciliationTransactionRow,
    WalletRepository,
    WalletTransactionCursor,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WalletReconciliationTotals:
    scanned: int = 0
    mismatches: int = 0
    violations: int = 0


@dataclass(slots=True)
class _WalletScanState:
    previous_after_balance: Decimal | None = None
    saw_transaction: bool = False
    violations: int = 0


def _report_violation(
    row: WalletReconciliationRow,
    state: _WalletScanState,
    *,
    check: str,
    transaction_id: int | None = None,
) -> None:
    """仅记录定位所需内部 ID，不输出金额、原因或幂等键。"""

    state.violations += 1
    if transaction_id is None:
        logger.error(
            "Wallet reconciliation violation: wallet_account_id=%d "
            "user_id=%d check=%s",
            row.wallet_account_id,
            row.user_id,
            check,
        )
        return
    logger.error(
        "Wallet reconciliation violation: wallet_account_id=%d "
        "user_id=%d transaction_id=%d check=%s",
        row.wallet_account_id,
        row.user_id,
        transaction_id,
        check,
    )


def _inspect_transaction(
    row: WalletReconciliationRow,
    state: _WalletScanState,
    transaction: WalletReconciliationTransactionRow,
) -> None:
    if transaction.change_amount == Decimal("0.00"):
        _report_violation(
            row,
            state,
            check="zero_change_amount",
            transaction_id=transaction.transaction_id,
        )
    if (
        transaction.after_balance
        != transaction.before_balance + transaction.change_amount
    ):
        _report_violation(
            row,
            state,
            check="transaction_balance_arithmetic_mismatch",
            transaction_id=transaction.transaction_id,
        )
    if not (
        WALLET_BALANCE_MIN
        <= transaction.before_balance
        <= WALLET_BALANCE_MAX
        and WALLET_BALANCE_MIN
        <= transaction.after_balance
        <= WALLET_BALANCE_MAX
    ):
        _report_violation(
            row,
            state,
            check="transaction_balance_out_of_range",
            transaction_id=transaction.transaction_id,
        )
    if (
        state.saw_transaction
        and transaction.before_balance != state.previous_after_balance
    ):
        _report_violation(
            row,
            state,
            check="transaction_balance_chain_mismatch",
            transaction_id=transaction.transaction_id,
        )
    state.saw_transaction = True
    state.previous_after_balance = transaction.after_balance


async def _inspect_wallet_batch(
    repository: WalletRepository,
    rows: list[WalletReconciliationRow],
    *,
    transaction_batch_size: int,
) -> tuple[int, int]:
    """一次批量扫描多个钱包的流水，避免逐钱包 N+1 查询。"""

    row_by_account_id = {row.wallet_account_id: row for row in rows}
    state_by_account_id = {
        row.wallet_account_id: _WalletScanState() for row in rows
    }
    for row in rows:
        if row.balance != row.ledger_total:
            _report_violation(
                row,
                state_by_account_id[row.wallet_account_id],
                check="ledger_total_mismatch",
            )

    cursor: WalletTransactionCursor | None = None
    while True:
        transactions = await repository.list_transactions_for_reconciliation(
            list(row_by_account_id),
            cursor=cursor,
            limit=transaction_batch_size,
        )
        if not transactions:
            break
        for transaction in transactions:
            row = row_by_account_id[transaction.wallet_account_id]
            _inspect_transaction(
                row,
                state_by_account_id[transaction.wallet_account_id],
                transaction,
            )
        last = transactions[-1]
        cursor = WalletTransactionCursor(
            wallet_account_id=last.wallet_account_id,
            created_at=last.created_at,
            transaction_id=last.transaction_id,
        )
        if len(transactions) < transaction_batch_size:
            break

    for row in rows:
        state = state_by_account_id[row.wallet_account_id]
        if not state.saw_transaction:
            if row.balance != WALLET_BALANCE_MIN:
                _report_violation(
                    row,
                    state,
                    check="nonzero_balance_without_transactions",
                )
        elif state.previous_after_balance != row.balance:
            _report_violation(
                row,
                state,
                check="terminal_balance_mismatch",
            )

    return (
        sum(state.violations > 0 for state in state_by_account_id.values()),
        sum(state.violations for state in state_by_account_id.values()),
    )


async def reconcile_all(
    repository: WalletRepository,
    *,
    batch_size: int,
) -> WalletReconciliationTotals:
    """逐批核对余额、逐行算术与余额链；全程只读。"""

    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")

    totals = WalletReconciliationTotals()
    after_account_id = 0
    while True:
        rows = await repository.list_reconciliation_rows(
            after_account_id=after_account_id,
            limit=batch_size,
        )
        if not rows:
            return totals
        mismatch_count, violation_count = await _inspect_wallet_batch(
            repository,
            rows,
            transaction_batch_size=batch_size,
        )
        totals = WalletReconciliationTotals(
            scanned=totals.scanned + len(rows),
            mismatches=totals.mismatches + mismatch_count,
            violations=totals.violations + violation_count,
        )
        after_account_id = rows[-1].wallet_account_id
        if len(rows) < batch_size:
            return totals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify wallet balances and immutable transaction row/chain integrity."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        choices=range(1, 1001),
        metavar="1..1000",
    )
    return parser


async def run(*, batch_size: int) -> WalletReconciliationTotals:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        return await reconcile_all(WalletRepository(), batch_size=batch_size)
    finally:
        await Tortoise.close_connections()


def main() -> int:
    args = build_parser().parse_args()
    setup_logging()
    totals = asyncio.run(run(batch_size=args.batch_size))
    logger.info(
        "Wallet reconciliation complete: scanned=%d mismatches=%d violations=%d",
        totals.scanned,
        totals.mismatches,
        totals.violations,
    )
    return 1 if totals.mismatches or totals.violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
