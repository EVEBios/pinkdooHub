"""Wallet 余额锁定、不可变流水写入与分页查询。"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q
from tortoise.functions import Sum

from app.common.enums.wallet import (
    WalletStatus,
    WalletTransactionSourceType,
    WalletTransactionType,
)
from app.common.enums.user import UserRole, UserStatus
from app.common.pagination import Page
from app.models.order import Order
from app.models.payment import Refund
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction


@dataclass(frozen=True, slots=True)
class WalletTransactionCreateData:
    """一条已由调用方校验并计算完成的钱包流水。"""

    wallet_account_id: int
    transaction_type: WalletTransactionType
    change_amount: Decimal
    before_balance: Decimal
    after_balance: Decimal
    source_type: WalletTransactionSourceType
    source_id: int | None
    operator_id: int | None
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class WalletReconciliationRow:
    wallet_account_id: int
    user_id: int
    balance: Decimal
    ledger_total: Decimal


@dataclass(frozen=True, slots=True)
class WalletTransactionCursor:
    wallet_account_id: int
    created_at: datetime
    transaction_id: int


@dataclass(frozen=True, slots=True)
class WalletReconciliationTransactionRow:
    wallet_account_id: int
    transaction_id: int
    created_at: datetime
    change_amount: Decimal
    before_balance: Decimal
    after_balance: Decimal


class WalletRepository:
    """Wallet 数据访问层；不判断权限、余额规则或业务状态。"""

    async def create_account(
        self,
        *,
        user_id: int,
        using_db: BaseDBAsyncClient,
    ) -> WalletAccount:
        """在调用方事务中创建用户唯一钱包。"""

        return await WalletAccount.create(user_id=user_id, using_db=using_db)

    async def list_missing_customer_ids(
        self,
        *,
        after_user_id: int,
        through_user_id: int,
        limit: int,
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[int]:
        """按 User ID 游标扫描尚未创建钱包的普通用户。"""

        query = User.filter(
            id__gt=after_user_id,
            id__lte=through_user_id,
            role=UserRole.USER.value,
            status__in=(UserStatus.NORMAL.value, UserStatus.DISABLED.value),
            wallet_account__isnull=True,
        ).order_by("id").limit(limit)
        if using_db is not None:
            query = query.using_db(using_db)
        return list(await query.values_list("id", flat=True))

    async def bulk_create_accounts(
        self,
        *,
        user_ids: list[int],
        using_db: BaseDBAsyncClient,
    ) -> int:
        """批量创建零余额钱包；调用方负责锁定与重试。"""

        if not user_ids:
            return 0
        await WalletAccount.bulk_create(
            [WalletAccount(user_id=user_id) for user_id in user_ids],
            using_db=using_db,
        )
        return len(user_ids)

    async def get_account_user_ids(
        self,
        user_ids: list[int],
        *,
        using_db: BaseDBAsyncClient,
    ) -> set[int]:
        """一次读取指定 User 集合中已有钱包的 ID。"""

        if not user_ids:
            return set()
        rows = await (
            WalletAccount.filter(user_id__in=user_ids)
            .using_db(using_db)
            .values_list("user_id", flat=True)
        )
        return set(rows)

    async def list_reconciliation_rows(
        self,
        *,
        after_account_id: int,
        limit: int,
    ) -> list[WalletReconciliationRow]:
        """分页读取权威余额与已提交流水净额，不修改任何资金事实。"""

        accounts = await (
            WalletAccount.filter(id__gt=after_account_id)
            .order_by("id")
            .limit(limit)
            .values("id", "user_id", "balance")
        )
        if not accounts:
            return []
        account_ids = [int(account["id"]) for account in accounts]
        totals = await (
            WalletTransaction.filter(wallet_account_id__in=account_ids)
            .annotate(ledger_total=Sum("change_amount"))
            .group_by("wallet_account_id")
            .values("wallet_account_id", "ledger_total")
        )
        total_by_account_id = {
            int(row["wallet_account_id"]): Decimal(row["ledger_total"])
            for row in totals
        }
        return [
            WalletReconciliationRow(
                wallet_account_id=int(account["id"]),
                user_id=int(account["user_id"]),
                balance=Decimal(account["balance"]),
                ledger_total=total_by_account_id.get(
                    int(account["id"]),
                    Decimal("0.00"),
                ),
            )
            for account in accounts
        ]

    async def list_transactions_for_reconciliation(
        self,
        account_ids: list[int],
        *,
        cursor: WalletTransactionCursor | None,
        limit: int,
    ) -> list[WalletReconciliationTransactionRow]:
        """按钱包、时间和 ID 复合游标稳定读取只读对账流水。"""

        if not account_ids:
            return []
        query = WalletTransaction.filter(wallet_account_id__in=account_ids)
        if cursor is not None:
            query = query.filter(
                Q(wallet_account_id__gt=cursor.wallet_account_id)
                | Q(
                    wallet_account_id=cursor.wallet_account_id,
                    created_at__gt=cursor.created_at,
                )
                | Q(
                    wallet_account_id=cursor.wallet_account_id,
                    created_at=cursor.created_at,
                    id__gt=cursor.transaction_id,
                )
            )
        rows = await (
            query.order_by(
                "wallet_account_id",
                "created_at",
                "id",
            )
            .limit(limit)
            .values(
                "id",
                "wallet_account_id",
                "created_at",
                "change_amount",
                "before_balance",
                "after_balance",
            )
        )
        return [
            WalletReconciliationTransactionRow(
                wallet_account_id=int(row["wallet_account_id"]),
                transaction_id=int(row["id"]),
                created_at=row["created_at"],
                change_amount=Decimal(row["change_amount"]),
                before_balance=Decimal(row["before_balance"]),
                after_balance=Decimal(row["after_balance"]),
            )
            for row in rows
        ]

    async def get_account_by_user_id(
        self,
        user_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> WalletAccount | None:
        """按 User ID 读取钱包，不加行锁。"""

        query = WalletAccount.filter(user_id=user_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_account_for_update(
        self,
        user_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> WalletAccount | None:
        """在调用方事务内锁定 User 的唯一钱包。"""

        return await (
            WalletAccount.filter(user_id=user_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def update_balance(
        self,
        account: WalletAccount,
        *,
        balance: Decimal,
        using_db: BaseDBAsyncClient,
    ) -> WalletAccount:
        """保存调用方在行锁内计算完成的最终余额。"""

        account.balance = balance
        await account.save(
            using_db=using_db,
            update_fields=["balance", "updated_at"],
        )
        return account

    async def close_account(
        self,
        account: WalletAccount,
        *,
        using_db: BaseDBAsyncClient,
    ) -> WalletAccount:
        """把已通过调用方注销校验的钱包关闭。"""

        account.status = WalletStatus.CLOSED
        await account.save(
            using_db=using_db,
            update_fields=["status", "updated_at"],
        )
        return account

    async def create_transaction(
        self,
        *,
        data: WalletTransactionCreateData,
        using_db: BaseDBAsyncClient,
    ) -> WalletTransaction:
        """创建不可变钱包流水。"""

        return await WalletTransaction.create(
            wallet_account_id=data.wallet_account_id,
            transaction_type=data.transaction_type,
            change_amount=data.change_amount,
            before_balance=data.before_balance,
            after_balance=data.after_balance,
            source_type=data.source_type,
            source_id=data.source_id,
            operator_id=data.operator_id,
            reason=data.reason,
            idempotency_key=data.idempotency_key,
            using_db=using_db,
        )

    async def get_transaction_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> WalletTransaction | None:
        """按唯一业务身份读取历史流水，供严格重放比较。"""

        query = WalletTransaction.filter(idempotency_key=idempotency_key)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_transaction_detail(
        self,
        transaction_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> WalletTransaction | None:
        """读取流水及可安全映射的操作者关系。"""

        query = WalletTransaction.filter(id=transaction_id).select_related(
            "operator"
        )
        if using_db is not None:
            query = query.using_db(using_db)
        transaction = await query.first()
        if transaction is not None:
            await self._attach_source_order_numbers(
                [transaction],
                using_db=using_db,
            )
        return transaction

    async def list_transactions(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
        transaction_type: WalletTransactionType | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Page[WalletTransaction]:
        """按钱包、可选类型和稳定时间顺序分页。"""

        query = WalletTransaction.filter(wallet_account__user_id=user_id)
        if transaction_type is not None:
            query = query.filter(transaction_type=transaction_type)
        if using_db is not None:
            query = query.using_db(using_db)
        total = await query.count()
        items = await (
            query.select_related("operator")
            .order_by("-created_at", "-id")
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        await self._attach_source_order_numbers(items, using_db=using_db)
        return Page[WalletTransaction](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size,
        )

    @staticmethod
    async def _attach_source_order_numbers(
        transactions: list[WalletTransaction],
        *,
        using_db: BaseDBAsyncClient | None,
    ) -> None:
        """批量补齐订单来源展示字段，保证 Mapper 不追加查询。"""

        source_ids = {
            transaction.source_id
            for transaction in transactions
            if transaction.source_type is WalletTransactionSourceType.ORDER
            and transaction.source_id is not None
        }
        order_no_by_id: dict[int, str] = {}
        if source_ids:
            query = Order.filter(id__in=source_ids)
            if using_db is not None:
                query = query.using_db(using_db)
            rows = await query.values_list("id", "order_no")
            order_no_by_id = dict(rows)

        refund_source_ids = {
            transaction.source_id
            for transaction in transactions
            if transaction.source_type is WalletTransactionSourceType.REFUND
            and transaction.source_id is not None
        }
        order_no_by_refund_id: dict[int, str] = {}
        if refund_source_ids:
            query = Refund.filter(id__in=refund_source_ids)
            if using_db is not None:
                query = query.using_db(using_db)
            rows = await query.values_list("id", "order__order_no")
            order_no_by_refund_id = dict(rows)

        for transaction in transactions:
            if (
                transaction.source_type is WalletTransactionSourceType.ORDER
                and transaction.source_id is not None
            ):
                source_order_no = order_no_by_id.get(transaction.source_id)
            elif (
                transaction.source_type is WalletTransactionSourceType.REFUND
                and transaction.source_id is not None
            ):
                source_order_no = order_no_by_refund_id.get(transaction.source_id)
            else:
                source_order_no = None
            setattr(transaction, "source_order_no", source_order_no)
