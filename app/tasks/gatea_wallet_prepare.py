"""在 Gate A M4 停写窗口中受控执行 Wallet 历史准备与只读对账。

先完成两个 preview，并在发现 legacy blocker 时保持零写入；通过后复用冻结的
``through_user_id`` / ``through_order_id`` 执行 apply、二次 preview 和全量
reconcile。输出只包含聚合计数，不包含用户资料、Token、Secret 或幂等键。
"""

from __future__ import annotations

import asyncio
import json

from tortoise import Tortoise

from app.core.config import settings
from app.db.database import TORTOISE_ORM
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import WalletRepository
from app.tasks import legacy_manual_settlement_backfill as settlement_backfill
from app.tasks import wallet_account_backfill
from app.tasks import wallet_reconcile


class GateAWalletPreparationError(RuntimeError):
    """不包含 PII、Secret 或幂等键的钱包准备错误。"""


async def _wallet_backfill(
    *,
    repository: WalletRepository,
    user_repository: UserRepository,
    dry_run: bool,
    through_user_id: int | None,
) -> wallet_account_backfill.WalletBackfillTotals:
    if through_user_id == 0:
        return wallet_account_backfill.WalletBackfillTotals()
    return await wallet_account_backfill.backfill_all(
        repository,
        user_repository,
        batch_size=500,
        dry_run=dry_run,
        through_user_id=through_user_id,
    )


async def _settlement_backfill(
    *,
    order_repository: OrderRepository,
    audit_repository: AuditLogRepository,
    payment_repository: PaymentRepository,
    user_repository: UserRepository,
    dry_run: bool,
    through_order_id: int | None,
) -> settlement_backfill.LegacyManualSettlementTotals:
    if through_order_id == 0:
        return settlement_backfill.LegacyManualSettlementTotals()
    return await settlement_backfill.backfill_all(
        order_repository,
        audit_repository,
        payment_repository,
        user_repository,
        batch_size=200,
        dry_run=dry_run,
        through_order_id=through_order_id,
    )


async def prepare_wallet_data() -> dict[str, object]:
    """预览、补齐并复核 M4 历史资金事实，任一不一致即非零失败。"""

    if settings.app_env != "production" or settings.db_engine != "mysql":
        raise GateAWalletPreparationError(
            "Gate A wallet preparation requires production MySQL semantics"
        )

    await Tortoise.init(config=TORTOISE_ORM)
    try:
        wallet_repository = WalletRepository()
        user_repository = UserRepository()
        order_repository = OrderRepository()
        audit_repository = AuditLogRepository()
        payment_repository = PaymentRepository()

        wallet_preview = await _wallet_backfill(
            repository=wallet_repository,
            user_repository=user_repository,
            dry_run=True,
            through_user_id=None,
        )
        settlement_preview = await _settlement_backfill(
            order_repository=order_repository,
            audit_repository=audit_repository,
            payment_repository=payment_repository,
            user_repository=user_repository,
            dry_run=True,
            through_order_id=None,
        )
        if settlement_preview.blocked:
            reasons = sorted(
                {blocker.reason for blocker in settlement_preview.blockers}
            )
            raise GateAWalletPreparationError(
                "legacy settlement preview is blocked: "
                f"count={settlement_preview.blocked} reasons={','.join(reasons)}"
            )

        wallet_apply = await _wallet_backfill(
            repository=wallet_repository,
            user_repository=user_repository,
            dry_run=False,
            through_user_id=wallet_preview.through_user_id,
        )
        settlement_apply = await _settlement_backfill(
            order_repository=order_repository,
            audit_repository=audit_repository,
            payment_repository=payment_repository,
            user_repository=user_repository,
            dry_run=False,
            through_order_id=settlement_preview.through_order_id,
        )
        if settlement_apply.blocked:
            raise GateAWalletPreparationError(
                "legacy settlement apply became blocked after preview"
            )

        wallet_replay = await _wallet_backfill(
            repository=wallet_repository,
            user_repository=user_repository,
            dry_run=True,
            through_user_id=wallet_preview.through_user_id,
        )
        settlement_replay = await _settlement_backfill(
            order_repository=order_repository,
            audit_repository=audit_repository,
            payment_repository=payment_repository,
            user_repository=user_repository,
            dry_run=True,
            through_order_id=settlement_preview.through_order_id,
        )
        reconciliation = await wallet_reconcile.reconcile_all(
            wallet_repository,
            batch_size=500,
        )
        if wallet_replay.would_create:
            raise GateAWalletPreparationError(
                "wallet account replay still finds missing accounts"
            )
        if settlement_replay.would_create or settlement_replay.blocked:
            raise GateAWalletPreparationError(
                "legacy settlement replay did not converge"
            )
        if reconciliation.mismatches or reconciliation.violations:
            raise GateAWalletPreparationError("wallet reconciliation failed")

        return {
            "wallet_accounts": {
                "through_user_id": wallet_preview.through_user_id,
                "preview_would_create": wallet_preview.would_create,
                "created": wallet_apply.created,
                "replay_would_create": wallet_replay.would_create,
            },
            "legacy_settlements": {
                "through_order_id": settlement_preview.through_order_id,
                "preview_would_create": settlement_preview.would_create,
                "created": settlement_apply.created,
                "replayed": settlement_apply.replayed,
                "replay_would_create": settlement_replay.would_create,
                "blocked": settlement_replay.blocked,
            },
            "reconciliation": {
                "scanned": reconciliation.scanned,
                "mismatches": reconciliation.mismatches,
                "violations": reconciliation.violations,
            },
        }
    finally:
        await Tortoise.close_connections()


def main() -> int:
    try:
        result = asyncio.run(prepare_wallet_data())
    except GateAWalletPreparationError as error:
        print(f"Gate A wallet preparation failed: {error}")
        return 1
    except Exception as error:
        print(
            "Gate A wallet preparation failed: " f"error_type={type(error).__name__}"
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
