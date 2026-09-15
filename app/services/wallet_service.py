"""Wallet 余额查询、流水查询与 ADMIN+ 调账编排。"""

import json
import logging
from dataclasses import dataclass
from decimal import Decimal

from tortoise.exceptions import IntegrityError, OperationalError
from tortoise.transactions import in_transaction

from app.common.constants.wallet import (
    FINANCIAL_RETRYABLE_MYSQL_ERROR_CODES,
    FINANCIAL_TRANSACTION_MAX_ATTEMPTS,
    WALLET_ADMIN_IDEMPOTENCY_PREFIX,
    WALLET_AUDIT_ACTION_ADJUST,
    WALLET_AUDIT_TARGET_TYPE,
    WALLET_BALANCE_MAX,
    WALLET_BALANCE_MIN,
)
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import (
    WalletStatus,
    WalletTransactionSourceType,
    WalletTransactionType,
)
from app.common.exceptions.user import UserDeleted, UserNotFound
from app.common.exceptions.wallet import (
    WalletBalanceExceeded,
    WalletNotFound,
    WalletRefundCapacityExceeded,
    WalletTransactionConflict,
)
from app.common.pagination import Page
from app.core.config import settings
from app.core.exceptions import PermissionException, ServiceUnavailableException
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction
from app.repositories.user_repo import UserRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.wallet_repo import (
    WalletRepository,
    WalletTransactionCreateData,
)
from app.services.audit_log_service import AuditLogService
from app.utils.database import get_database_error_code

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WalletAdjustmentResult:
    account: WalletAccount
    transaction: WalletTransaction
    result_balance: Decimal
    is_replay: bool


class WalletService:
    """Wallet 查询与受审计管理写入的业务规则所有者。"""

    def __init__(
        self,
        wallet_repository: WalletRepository,
        user_repository: UserRepository,
        audit_log_service: AuditLogService,
        payment_repository: PaymentRepository | None = None,
    ) -> None:
        self.wallet_repository = wallet_repository
        self.user_repository = user_repository
        self.audit_log_service = audit_log_service
        self.payment_repository = payment_repository or PaymentRepository()

    async def get_member_wallet(self, user: User) -> WalletAccount:
        self._ensure_wallet_owner(user)
        account = await self.wallet_repository.get_account_by_user_id(user.id)
        if account is None:
            raise WalletNotFound()
        self._ensure_account_active(account)
        return account

    async def get_admin_user_wallet(
        self,
        *,
        operator: User,
        user_id: int,
    ) -> tuple[User, WalletAccount]:
        target = await self.user_repository.get_by_id(user_id)
        if target is None:
            raise UserNotFound()
        self._ensure_admin_target(operator=operator, target=target)
        account = await self.wallet_repository.get_account_by_user_id(user_id)
        if account is None:
            raise WalletNotFound()
        return target, account

    async def list_user_transactions(
        self,
        *,
        user: User,
        page: int,
        page_size: int,
    ) -> Page[WalletTransaction]:
        self._ensure_wallet_owner(user)
        if await self.wallet_repository.get_account_by_user_id(user.id) is None:
            raise WalletNotFound()
        return await self.wallet_repository.list_transactions(
            user_id=user.id,
            page=page,
            page_size=page_size,
        )

    async def list_admin_user_transactions(
        self,
        *,
        operator: User,
        user_id: int,
        page: int,
        page_size: int,
    ) -> Page[WalletTransaction]:
        await self.get_admin_user_wallet(operator=operator, user_id=user_id)
        return await self.wallet_repository.list_transactions(
            user_id=user_id,
            page=page,
            page_size=page_size,
        )

    async def adjust_balance(
        self,
        *,
        operator: User,
        user_id: int,
        change: Decimal,
        reason: str,
        idempotency_key: str,
        ip_address: str,
    ) -> WalletAdjustmentResult:
        if not settings.wallet_admin_write_available:
            raise ServiceUnavailableException(
                message="Wallet administration is temporarily disabled"
            )
        internal_key = f"{WALLET_ADMIN_IDEMPOTENCY_PREFIX}{idempotency_key}"
        normalized_reason = reason.strip()

        for attempt in range(1, FINANCIAL_TRANSACTION_MAX_ATTEMPTS + 1):
            try:
                result = await self._adjust_once(
                    operator=operator,
                    user_id=user_id,
                    change=change,
                    reason=normalized_reason,
                    internal_key=internal_key,
                    ip_address=ip_address,
                )
            except IntegrityError:
                replay = await self._resolve_adjustment_replay(
                    operator=operator,
                    user_id=user_id,
                    change=change,
                    reason=normalized_reason,
                    internal_key=internal_key,
                )
                if replay is None:
                    raise
                result = replay
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in FINANCIAL_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= FINANCIAL_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying wallet adjustment after MySQL transient error: "
                    "operator_id=%d user_id=%d error_code=%d attempt=%d",
                    operator.id,
                    user_id,
                    error_code,
                    attempt,
                )
                continue

            logger.info(
                "Wallet adjusted: operator_id=%d user_id=%d "
                "transaction_id=%d replay=%s",
                operator.id,
                user_id,
                result.transaction.id,
                result.is_replay,
            )
            return result

        raise RuntimeError("Wallet adjustment retry loop exhausted")

    async def _adjust_once(
        self,
        *,
        operator: User,
        user_id: int,
        change: Decimal,
        reason: str,
        internal_key: str,
        ip_address: str,
    ) -> WalletAdjustmentResult:
        async with in_transaction() as connection:
            target = await self.user_repository.get_for_update(
                user_id,
                using_db=connection,
            )
            if target is None:
                raise UserNotFound()
            self._ensure_admin_target(operator=operator, target=target)
            if target.status == UserStatus.DELETED:
                raise UserDeleted()
            if target.status not in (UserStatus.NORMAL, UserStatus.DISABLED):
                raise PermissionException(
                    message="Customer account status does not allow wallet adjustment"
                )

            account = await self.wallet_repository.get_account_for_update(
                user_id,
                using_db=connection,
            )
            if account is None:
                raise WalletNotFound()
            self._ensure_account_active(account)

            existing = (
                await self.wallet_repository.get_transaction_by_idempotency_key(
                    internal_key,
                    using_db=connection,
                )
            )
            if existing is not None:
                if not self._matches_adjustment(
                    existing,
                    account_id=account.id,
                    change=change,
                    reason=reason,
                    operator_id=operator.id,
                ):
                    raise WalletTransactionConflict()
                detail = await self.wallet_repository.get_transaction_detail(
                    existing.id,
                    using_db=connection,
                )
                if detail is None:
                    raise RuntimeError("Wallet replay transaction not found")
                return WalletAdjustmentResult(
                    account=account,
                    transaction=detail,
                    result_balance=detail.after_balance,
                    is_replay=True,
                )

            before_balance = account.balance
            after_balance = before_balance + change
            if not WALLET_BALANCE_MIN <= after_balance <= WALLET_BALANCE_MAX:
                raise WalletBalanceExceeded(
                    user_id=user_id,
                    before_balance=before_balance,
                    change_amount=change,
                )
            if change > 0:
                refundable_exposure = (
                    await self.payment_repository.get_refundable_wallet_exposure(
                        user_id,
                        using_db=connection,
                    )
                )
                if after_balance + refundable_exposure > WALLET_BALANCE_MAX:
                    raise WalletRefundCapacityExceeded(
                        requested_balance=after_balance,
                        refundable_exposure=refundable_exposure,
                    )
            await self.wallet_repository.update_balance(
                account,
                balance=after_balance,
                using_db=connection,
            )
            transaction = await self.wallet_repository.create_transaction(
                data=WalletTransactionCreateData(
                    wallet_account_id=account.id,
                    transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
                    change_amount=change,
                    before_balance=before_balance,
                    after_balance=after_balance,
                    source_type=WalletTransactionSourceType.ADMIN,
                    source_id=None,
                    operator_id=operator.id,
                    reason=reason,
                    idempotency_key=internal_key,
                ),
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator.id,
                action=WALLET_AUDIT_ACTION_ADJUST,
                target_type=WALLET_AUDIT_TARGET_TYPE,
                target_id=account.id,
                ip_address=ip_address,
                description=json.dumps(
                    {
                        "transaction_id": transaction.id,
                        "user_id": user_id,
                        "before_balance": f"{before_balance:.2f}",
                        "change_amount": f"{change:.2f}",
                        "after_balance": f"{after_balance:.2f}",
                    },
                    separators=(",", ":"),
                ),
                using_db=connection,
            )
            detail = await self.wallet_repository.get_transaction_detail(
                transaction.id,
                using_db=connection,
            )
            if detail is None:
                raise RuntimeError("Created wallet transaction not found")
            return WalletAdjustmentResult(
                account=account,
                transaction=detail,
                result_balance=after_balance,
                is_replay=False,
            )

    async def _resolve_adjustment_replay(
        self,
        *,
        operator: User,
        user_id: int,
        change: Decimal,
        reason: str,
        internal_key: str,
    ) -> WalletAdjustmentResult | None:
        transaction = (
            await self.wallet_repository.get_transaction_by_idempotency_key(
                internal_key
            )
        )
        account = await self.wallet_repository.get_account_by_user_id(user_id)
        if transaction is None or account is None:
            return None
        if not self._matches_adjustment(
            transaction,
            account_id=account.id,
            change=change,
            reason=reason,
            operator_id=operator.id,
        ):
            raise WalletTransactionConflict()
        detail = await self.wallet_repository.get_transaction_detail(transaction.id)
        if detail is None:
            return None
        return WalletAdjustmentResult(
            account=account,
            transaction=detail,
            result_balance=detail.after_balance,
            is_replay=True,
        )

    @staticmethod
    def _matches_adjustment(
        transaction: WalletTransaction,
        *,
        account_id: int,
        change: Decimal,
        reason: str,
        operator_id: int,
    ) -> bool:
        return (
            transaction.wallet_account_id == account_id
            and transaction.transaction_type
            is WalletTransactionType.ADMIN_ADJUSTMENT
            and transaction.source_type is WalletTransactionSourceType.ADMIN
            and transaction.source_id is None
            and transaction.change_amount == change
            and transaction.after_balance
            == transaction.before_balance + transaction.change_amount
            and transaction.reason == reason
            and transaction.operator_id == operator_id
        )

    @staticmethod
    def _ensure_wallet_owner(user: User) -> None:
        if user.role != UserRole.USER:
            raise PermissionException(message="Wallet is available to customers only")

    @staticmethod
    def _ensure_admin_target(*, operator: User, target: User) -> None:
        if operator.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            raise PermissionException(message="Admin access required")
        if operator.id == target.id or target.role != UserRole.USER:
            raise PermissionException(
                message="Administrators can operate customer wallets only"
            )

    @staticmethod
    def _ensure_account_active(account: WalletAccount) -> None:
        if account.status is not WalletStatus.ACTIVE:
            raise PermissionException(message="Wallet account is closed")
