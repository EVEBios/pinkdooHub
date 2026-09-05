"""Wallet ORM 数据到严格 API Schema 的同步纯映射。"""

from decimal import Decimal

from app.common.constants.wallet import WALLET_BALANCE_MAX
from app.common.pagination import Page
from app.core.config import settings
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction
from app.schemas.user import UserListItem, UserOut
from app.schemas.wallet_response import (
    AdminUserWalletOut,
    MemberOut,
    WalletAdjustmentOut,
    WalletCapabilitiesOut,
    WalletSummaryOut,
    WalletTransactionOut,
)


def map_wallet_summary(
    account: WalletAccount,
    *,
    balance: Decimal | None = None,
) -> WalletSummaryOut:
    """映射权威余额与当前环境能力开关。"""

    return WalletSummaryOut.model_validate(
        {
            "wallet_id": account.id,
            "user_id": account.user_id,
            "balance": account.balance if balance is None else balance,
            "balance_limit": WALLET_BALANCE_MAX,
            "status": account.status,
            "capabilities": WalletCapabilitiesOut(
                topup_enabled=settings.wallet_topup_available,
                wallet_payment_enabled=settings.wallet_order_payment_available,
                refund_enabled=settings.wallet_refund_available,
            ),
            "created_at": account.created_at,
            "updated_at": account.updated_at,
        }
    )


def map_member(user: User, account: WalletAccount) -> MemberOut:
    return MemberOut(
        user=UserOut.model_validate(user),
        wallet=map_wallet_summary(account),
    )


def map_admin_user_wallet(user: User, account: WalletAccount) -> AdminUserWalletOut:
    return AdminUserWalletOut(
        user=UserListItem.model_validate(user),
        wallet=map_wallet_summary(account),
    )


def map_wallet_transaction(transaction: WalletTransaction) -> WalletTransactionOut:
    operator_nickname = (
        transaction.operator.nickname
        if transaction.operator_id is not None
        else None
    )
    return WalletTransactionOut.model_validate(
        {
            "id": transaction.id,
            "transaction_type": transaction.transaction_type,
            "direction": "income" if transaction.change_amount > 0 else "expense",
            "change_amount": transaction.change_amount,
            "before_balance": transaction.before_balance,
            "after_balance": transaction.after_balance,
            "source_type": transaction.source_type,
            "source_id": transaction.source_id,
            "source_order_no": getattr(transaction, "source_order_no", None),
            "operator_id": transaction.operator_id,
            "operator_nickname": operator_nickname,
            "reason": transaction.reason,
            "created_at": transaction.created_at,
        }
    )


def map_wallet_transaction_page(
    page: Page[WalletTransaction],
) -> Page[WalletTransactionOut]:
    return Page[WalletTransactionOut](
        items=[map_wallet_transaction(item) for item in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def map_wallet_adjustment(
    account: WalletAccount,
    transaction: WalletTransaction,
    *,
    result_balance: Decimal,
) -> WalletAdjustmentOut:
    return WalletAdjustmentOut(
        wallet=map_wallet_summary(account, balance=result_balance),
        transaction=map_wallet_transaction(transaction),
    )
