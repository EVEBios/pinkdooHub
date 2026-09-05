"""订单钱包支付与独立资金状态查询。"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError, OperationalError
from tortoise.transactions import in_transaction

from app.common.constants.order import ORDER_AUDIT_TARGET_TYPE
from app.common.constants.wallet import (
    FINANCIAL_RETRYABLE_MYSQL_ERROR_CODES,
    FINANCIAL_TRANSACTION_MAX_ATTEMPTS,
    PAYMENT_AUDIT_ACTION_PAY_ORDER,
    WALLET_ORDER_PAYMENT_REASON,
    WALLET_ORDER_TRANSACTION_KEY,
    WALLET_PAYMENT_IDEMPOTENCY_PREFIX,
)
from app.common.enums.order import OrderStatus
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    RefundStatus,
    WalletStatus,
    WalletTransactionSourceType,
    WalletTransactionType,
)
from app.common.exceptions.order import OrderNotFound, OrderStatusConflict
from app.common.exceptions.user import UserDeleted, UserDisabled
from app.common.exceptions.wallet import (
    InsufficientWalletBalance,
    PaymentSettlementConflict,
    PaymentStatusConflict,
    WalletNotFound,
    WalletTransactionConflict,
)
from app.core.config import settings
from app.core.exceptions import PermissionException, ServiceUnavailableException
from app.models.order import Order
from app.models.payment import Payment, PaymentSettlement, Refund
from app.models.user import User
from app.models.wallet import WalletTransaction
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentCreateData, PaymentRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import (
    WalletRepository,
    WalletTransactionCreateData,
)
from app.services.audit_log_service import AuditLogService
from app.common.financial_number import generate_payment_number
from app.utils.database import get_database_error_code

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WalletPaymentResult:
    order: Order
    payment: Payment
    transaction: WalletTransaction
    post_payment_balance: Decimal
    is_replay: bool


@dataclass(frozen=True, slots=True)
class OrderFinancialResult:
    order: Order
    payment: Payment | None
    refund: Refund | None
    inventory_restored: bool


class PaymentService:
    """订单结算编排；客户端事件不能直接改变支付终态。"""

    def __init__(
        self,
        order_repository: OrderRepository,
        payment_repository: PaymentRepository,
        wallet_repository: WalletRepository,
        user_repository: UserRepository,
        audit_log_service: AuditLogService,
    ) -> None:
        self.order_repository = order_repository
        self.payment_repository = payment_repository
        self.wallet_repository = wallet_repository
        self.user_repository = user_repository
        self.audit_log_service = audit_log_service

    async def create_recharge_intent(
        self,
        *,
        user: User,
        amount: Decimal,
        idempotency_key: str,
    ) -> None:
        """保留真实充值边界；Provider 未接入前不写入任何资金单据。"""

        raise ServiceUnavailableException(
            message=(
                "Wallet top-up is not available until the supervised payment "
                "channel and WeChat merchant account are ready"
            )
        )

    async def create_wechat_order_payment(
        self,
        order_id: int,
        *,
        user: User,
        idempotency_key: str,
    ) -> None:
        """保留微信订单支付边界；当前版本明确 fail closed。"""

        raise ServiceUnavailableException(
            message="WeChat order payment is not available yet"
        )

    async def pay_order_with_wallet(
        self,
        order_id: int,
        *,
        user: User,
        idempotency_key: str,
        ip_address: str,
    ) -> WalletPaymentResult:
        if not settings.wallet_order_payment_available:
            raise ServiceUnavailableException(
                message="Wallet order payment is temporarily disabled"
            )
        internal_key = f"{WALLET_PAYMENT_IDEMPOTENCY_PREFIX}{idempotency_key}"

        for attempt in range(1, FINANCIAL_TRANSACTION_MAX_ATTEMPTS + 1):
            payment_no = generate_payment_number()
            try:
                result = await self._pay_order_with_wallet_once(
                    order_id=order_id,
                    user=user,
                    internal_key=internal_key,
                    payment_no=payment_no,
                    ip_address=ip_address,
                )
            except IntegrityError:
                replay = await self._resolve_wallet_payment_replay(
                    order_id=order_id,
                    user=user,
                    internal_key=internal_key,
                )
                if replay is not None:
                    result = replay
                else:
                    settlement = (
                        await self.payment_repository.get_settlement_by_order_id(
                            order_id
                        )
                    )
                    if settlement is not None:
                        raise PaymentSettlementConflict()
                    if attempt >= FINANCIAL_TRANSACTION_MAX_ATTEMPTS:
                        raise
                    continue
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in FINANCIAL_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= FINANCIAL_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying wallet payment after MySQL transient error: "
                    "user_id=%d order_id=%d error_code=%d attempt=%d",
                    user.id,
                    order_id,
                    error_code,
                    attempt,
                )
                continue

            logger.info(
                "Order paid with wallet: user_id=%d order_id=%d "
                "payment_id=%d replay=%s",
                user.id,
                order_id,
                result.payment.id,
                result.is_replay,
            )
            return result

        raise RuntimeError("Wallet payment retry loop exhausted")

    async def _pay_order_with_wallet_once(
        self,
        *,
        order_id: int,
        user: User,
        internal_key: str,
        payment_no: str,
        ip_address: str,
    ) -> WalletPaymentResult:
        async with in_transaction() as connection:
            locked_user = await self.user_repository.get_for_update(
                user.id,
                using_db=connection,
            )
            if locked_user is None or locked_user.status == UserStatus.DELETED:
                raise UserDeleted()
            if locked_user.status == UserStatus.DISABLED:
                raise UserDisabled()
            if locked_user.status != UserStatus.NORMAL:
                raise PermissionException(
                    message="Customer account status does not allow wallet payment"
                )
            if locked_user.role != UserRole.USER:
                raise PermissionException(message="Customer wallet required")

            order = await self.order_repository.get_order_for_update(
                order_id,
                user_id=locked_user.id,
                using_db=connection,
            )
            if order is None:
                raise OrderNotFound()

            existing = await self.payment_repository.get_payment_by_idempotency_key(
                internal_key,
                using_db=connection,
            )
            if existing is not None:
                return await self._locked_payment_replay(
                    order=order,
                    payment=existing,
                    user=locked_user,
                    using_db=connection,
                )

            current_status = OrderStatus(order.status)
            if current_status is not OrderStatus.PENDING:
                raise OrderStatusConflict(
                    operation="wallet_pay",
                    current_status=current_status,
                    required_status=OrderStatus.PENDING,
                )
            if (
                await self.payment_repository.get_settlement_by_order_id(
                    order.id,
                    using_db=connection,
                )
                is not None
            ):
                raise PaymentSettlementConflict()

            account = await self.wallet_repository.get_account_for_update(
                locked_user.id,
                using_db=connection,
            )
            if account is None:
                raise WalletNotFound()
            if account.status is not WalletStatus.ACTIVE:
                raise PermissionException(message="Wallet account is closed")
            if account.balance < order.total_amount:
                raise InsufficientWalletBalance(
                    user_id=locked_user.id,
                    requested_amount=order.total_amount,
                )

            payment = await self.payment_repository.create_payment(
                data=PaymentCreateData(
                    payment_no=payment_no,
                    user_id=locked_user.id,
                    purpose=PaymentPurpose.ORDER,
                    method=PaymentMethod.WALLET,
                    amount=order.total_amount,
                    order_id=order.id,
                    recharge_order_id=None,
                    idempotency_key=internal_key,
                ),
                using_db=connection,
            )
            succeeded_at = datetime.now(timezone.utc)
            await self.payment_repository.update_payment_status(
                payment,
                status=PaymentStatus.SUCCEEDED,
                provider_transaction_id=None,
                succeeded_at=succeeded_at,
                using_db=connection,
            )

            before_balance = account.balance
            after_balance = before_balance - order.total_amount
            await self.wallet_repository.update_balance(
                account,
                balance=after_balance,
                using_db=connection,
            )
            transaction = await self.wallet_repository.create_transaction(
                data=WalletTransactionCreateData(
                    wallet_account_id=account.id,
                    transaction_type=WalletTransactionType.ORDER_PAYMENT,
                    change_amount=-order.total_amount,
                    before_balance=before_balance,
                    after_balance=after_balance,
                    source_type=WalletTransactionSourceType.ORDER,
                    source_id=order.id,
                    operator_id=locked_user.id,
                    reason=WALLET_ORDER_PAYMENT_REASON,
                    idempotency_key=WALLET_ORDER_TRANSACTION_KEY.format(
                        payment_id=payment.id,
                        order_id=order.id,
                    ),
                ),
                using_db=connection,
            )
            await self.payment_repository.create_settlement(
                payment_id=payment.id,
                order_id=order.id,
                amount=order.total_amount,
                using_db=connection,
            )
            await self.order_repository.update_status(
                order,
                status=OrderStatus.PAID,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=locked_user.id,
                action=PAYMENT_AUDIT_ACTION_PAY_ORDER,
                target_type=ORDER_AUDIT_TARGET_TYPE,
                target_id=order.id,
                ip_address=ip_address,
                description=json.dumps(
                    {
                        "payment_id": payment.id,
                        "method": PaymentMethod.WALLET.value,
                        "amount": f"{payment.amount:.2f}",
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
                raise RuntimeError("Wallet payment transaction not found")
            return WalletPaymentResult(
                order=order,
                payment=payment,
                transaction=detail,
                post_payment_balance=after_balance,
                is_replay=False,
            )

    async def _locked_payment_replay(
        self,
        *,
        order: Order,
        payment: Payment,
        user: User,
        using_db: BaseDBAsyncClient,
    ) -> WalletPaymentResult:
        settlement = await self.payment_repository.get_settlement_by_order_id(
            order.id,
            using_db=using_db,
        )
        if settlement is None:
            raise PaymentSettlementConflict()
        return await self._build_wallet_payment_replay(
            order=order,
            settlement=settlement,
            payment=payment,
            user=user,
            using_db=using_db,
        )

    async def _resolve_wallet_payment_replay(
        self,
        *,
        order_id: int,
        user: User,
        internal_key: str,
    ) -> WalletPaymentResult | None:
        payment = await self.payment_repository.get_payment_by_idempotency_key(
            internal_key
        )
        order = await self.order_repository.get_order_by_id(order_id)
        if payment is None or order is None:
            return None
        settlement = await self.payment_repository.get_settlement_by_order_id(order_id)
        if settlement is None:
            raise PaymentSettlementConflict()
        return await self._build_wallet_payment_replay(
            order=order,
            settlement=settlement,
            payment=payment,
            user=user,
        )

    async def _build_wallet_payment_replay(
        self,
        *,
        order: Order,
        settlement: PaymentSettlement,
        payment: Payment,
        user: User,
        using_db: BaseDBAsyncClient | None = None,
    ) -> WalletPaymentResult:
        if not self._matches_wallet_payment(payment, order=order, user=user):
            raise WalletTransactionConflict()
        if payment.status is not PaymentStatus.SUCCEEDED:
            raise PaymentStatusConflict()
        if (
            payment.provider_transaction_id is not None
            or payment.succeeded_at is None
            or order.status not in (OrderStatus.PAID, OrderStatus.COMPLETED)
        ):
            raise WalletTransactionConflict()
        if (
            settlement.order_id != order.id
            or settlement.payment_id != payment.id
            or settlement.amount != order.total_amount
            or settlement.amount != payment.amount
        ):
            raise PaymentSettlementConflict()
        account = await self.wallet_repository.get_account_by_user_id(
            user.id,
            using_db=using_db,
        )
        if account is None:
            raise WalletTransactionConflict()
        transaction = (
            await self.wallet_repository.get_transaction_by_idempotency_key(
                WALLET_ORDER_TRANSACTION_KEY.format(
                    payment_id=payment.id,
                    order_id=order.id,
                ),
                using_db=using_db,
            )
        )
        if (
            transaction is None
            or transaction.wallet_account_id != account.id
            or transaction.transaction_type is not WalletTransactionType.ORDER_PAYMENT
            or transaction.change_amount != -order.total_amount
            or transaction.after_balance
            != transaction.before_balance + transaction.change_amount
            or transaction.source_type is not WalletTransactionSourceType.ORDER
            or transaction.source_id != order.id
            or transaction.operator_id != user.id
            or transaction.reason != WALLET_ORDER_PAYMENT_REASON
        ):
            raise WalletTransactionConflict()
        detail = await self.wallet_repository.get_transaction_detail(
            transaction.id,
            using_db=using_db,
        )
        if detail is None:
            raise WalletTransactionConflict()
        return WalletPaymentResult(
            order=order,
            payment=payment,
            transaction=detail,
            post_payment_balance=detail.after_balance,
            is_replay=True,
        )

    async def get_user_order_financials(
        self,
        order_id: int,
        *,
        user_id: int,
    ) -> OrderFinancialResult:
        order = await self.order_repository.get_order_detail(
            order_id,
            user_id=user_id,
        )
        if order is None:
            raise OrderNotFound()
        return await self._load_financials(order)

    async def get_admin_order_financials(
        self,
        order_id: int,
    ) -> OrderFinancialResult:
        order = await self.order_repository.get_order_detail(order_id)
        if order is None:
            raise OrderNotFound()
        return await self._load_financials(order)

    async def _load_financials(self, order: Order) -> OrderFinancialResult:
        settlement = await self.payment_repository.get_settlement_by_order_id(order.id)
        payment = settlement.payment if settlement is not None else None
        if settlement is not None and payment is not None:
            self._validate_successful_order_settlement(
                order=order,
                settlement=settlement,
                payment=payment,
            )
        refund = (
            await self.payment_repository.get_refund_by_settlement_id(settlement.id)
            if settlement is not None
            else None
        )
        if refund is not None:
            if (
                payment is None
                or refund.order_id != order.id
                or refund.settlement_id != settlement.id
                or refund.amount != settlement.amount
                or (
                    refund.status is RefundStatus.SUCCEEDED
                    and refund.succeeded_at is None
                )
                or (
                    payment.method in (PaymentMethod.WALLET, PaymentMethod.MANUAL)
                    and refund.provider_refund_id is not None
                )
            ):
                raise PaymentSettlementConflict()
        inventory_restored = bool(
            refund is not None
            and refund.status is RefundStatus.SUCCEEDED
            and refund.inventory_restored
        )
        return OrderFinancialResult(
            order=order,
            payment=payment,
            refund=refund,
            inventory_restored=inventory_restored,
        )

    @staticmethod
    def _matches_wallet_payment(
        payment: Payment,
        *,
        order: Order,
        user: User,
    ) -> bool:
        return (
            payment.user_id == user.id
            and payment.order_id == order.id
            and payment.recharge_order_id is None
            and payment.purpose is PaymentPurpose.ORDER
            and payment.method is PaymentMethod.WALLET
            and payment.amount == order.total_amount
        )

    @staticmethod
    def _validate_successful_order_settlement(
        *,
        order: Order,
        settlement: PaymentSettlement,
        payment: Payment,
    ) -> None:
        if (
            settlement.order_id != order.id
            or settlement.payment_id != payment.id
            or settlement.amount != order.total_amount
            or settlement.amount != payment.amount
            or payment.user_id != order.user_id
            or payment.order_id != order.id
            or payment.recharge_order_id is not None
            or payment.purpose is not PaymentPurpose.ORDER
            or payment.status is not PaymentStatus.SUCCEEDED
            or payment.succeeded_at is None
            or order.status not in (OrderStatus.PAID, OrderStatus.COMPLETED)
            or (
                payment.method in (PaymentMethod.WALLET, PaymentMethod.MANUAL)
                and payment.provider_transaction_id is not None
            )
            or (
                payment.method is PaymentMethod.WECHAT
                and payment.provider_transaction_id is None
            )
        ):
            raise PaymentSettlementConflict()
