"""为历史正常/禁用普通 USER 可续跑地补建零余额钱包。

默认只预览；显式传入 ``--apply`` 才会写库。任务不为 ADMIN /
SUPER_ADMIN 或已注销用户创建钱包，也不伪造零金额资金流水。
"""

import argparse
import asyncio
import logging
from dataclasses import dataclass

from tortoise import Tortoise
from tortoise.transactions import in_transaction

from app.core.logging import setup_logging
from app.db.database import TORTOISE_ORM
from app.common.enums.user import UserRole, UserStatus
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import WalletRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WalletBackfillTotals:
    through_user_id: int = 0
    scanned: int = 0
    created: int = 0
    would_create: int = 0


async def backfill_all(
    repository: WalletRepository,
    user_repository: UserRepository,
    *,
    batch_size: int,
    dry_run: bool,
    through_user_id: int | None = None,
) -> WalletBackfillTotals:
    """按 User ID 稳定游标扫描，每批独立事务便于失败后续跑。"""

    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if not dry_run and through_user_id is None:
        raise ValueError("apply requires an explicit through_user_id")
    if through_user_id is not None and through_user_id < 1:
        raise ValueError("through_user_id must be positive")
    scope_end = (
        await user_repository.get_latest_user_id()
        if through_user_id is None
        else through_user_id
    )
    totals = WalletBackfillTotals(through_user_id=scope_end)
    after_user_id = 0
    while True:
        user_ids = await repository.list_missing_customer_ids(
            after_user_id=after_user_id,
            through_user_id=scope_end,
            limit=batch_size,
        )
        if not user_ids:
            return totals
        after_user_id = user_ids[-1]
        if dry_run:
            totals = WalletBackfillTotals(
                through_user_id=scope_end,
                scanned=totals.scanned + len(user_ids),
                created=totals.created,
                would_create=totals.would_create + len(user_ids),
            )
        else:
            async with in_transaction() as connection:
                locked_users = await user_repository.list_by_ids_for_update(
                    set(user_ids),
                    using_db=connection,
                )
                eligible_user_ids = [
                    user.id
                    for user in locked_users
                    if user.role == UserRole.USER
                    and user.status in (UserStatus.NORMAL, UserStatus.DISABLED)
                ]
                existing_user_ids = await repository.get_account_user_ids(
                    eligible_user_ids,
                    using_db=connection,
                )
                still_missing = [
                    user_id
                    for user_id in eligible_user_ids
                    if user_id not in existing_user_ids
                ]
                created = await repository.bulk_create_accounts(
                    user_ids=still_missing,
                    using_db=connection,
                )
            totals = WalletBackfillTotals(
                through_user_id=scope_end,
                scanned=totals.scanned + len(user_ids),
                created=totals.created + created,
                would_create=totals.would_create,
            )
        if len(user_ids) < batch_size:
            return totals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill zero-balance wallets for historical customer users.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        choices=range(1, 1001),
        metavar="1..1000",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write missing wallets. Without this flag the command only previews.",
    )
    parser.add_argument(
        "--through-user-id",
        type=int,
        help=(
            "Freeze apply scope to the through_user_id printed by a completed "
            "preview. Required with --apply."
        ),
    )
    return parser


async def run(
    *,
    batch_size: int,
    dry_run: bool,
    through_user_id: int | None,
) -> WalletBackfillTotals:
    if not dry_run and through_user_id is None:
        raise ValueError("apply requires an explicit through_user_id")
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        return await backfill_all(
            WalletRepository(),
            UserRepository(),
            batch_size=batch_size,
            dry_run=dry_run,
            through_user_id=through_user_id,
        )
    finally:
        await Tortoise.close_connections()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.apply and args.through_user_id is None:
        parser.error("--apply requires --through-user-id from a completed preview")
    setup_logging()
    totals = asyncio.run(
        run(
            batch_size=args.batch_size,
            dry_run=not args.apply,
            through_user_id=args.through_user_id,
        )
    )
    logger.info(
        "Wallet account backfill complete: mode=%s through_user_id=%d "
        "scanned=%d created=%d would_create=%d",
        "apply" if args.apply else "preview",
        totals.through_user_id,
        totals.scanned,
        totals.created,
        totals.would_create,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
