"""ADMIN+ 全额退款编排，退款状态与 Order 主状态分离。"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError, OperationalError
from tortoise.transactions import in_transaction

from app.common.constants.inventory import (
    INVENTORY_ORDER_COLOR_REFUND_RESTORE_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_REFUND_RESTORE_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_REFUND_RESTORE_REASON,
    INVENTORY_STOCK_MAX,
)
from app.common.constants.order import ORDER_AUDIT_TARGET_TYPE
from app.common.constants.table_session import (
    TABLE_AUDIT_ACTION_RELEASE,
    TABLE_AUDIT_TARGET_TYPE,
)
from app.common.constants.wallet import (
    FINANCIAL_RETRYABLE_MYSQL_ERROR_CODES,
    FINANCIAL_TRANSACTION_MAX_ATTEMPTS,
    ORDER_REFUND_WINDOW_DAYS,
    REFUND_ADMIN_IDEMPOTENCY_PREFIX,
    REFUND_AUDIT_ACTION_COMPLETE,
    WALLET_BALANCE_MAX,
    WALLET_ORDER_REFUND_REASON,
    WALLET_REFUND_TRANSACTION_KEY,
)
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.enums.order import OrderStatus
from app.common.enums.table_session import TableSessionCloseReason, TableSessionStatus
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
from app.common.exceptions.inventory import (
    InventoryBalanceExceeded,
    InventoryTransactionConflict,
)
from app.common.exceptions.order import OrderNotFound
from app.common.exceptions.user import UserDeleted, UserNotFound
from app.common.exceptions.wallet import (
    PaymentNotFound,
    RefundStatusConflict,
    RefundWindowExpired,
    WalletBalanceExceeded,
    WalletNotFound,
    WalletTransactionConflict,
)
from app.common.financial_number import generate_refund_number
from app.core.config import settings
from app.core.exceptions import PermissionException, ServiceUnavailableException
from app.domain.table_session import automatic_close_for
from app.models.order import Order
from app.models.payment import Payment, PaymentSettlement, Refund
from app.models.table_session import TableSession
from app.models.user import User
from app.repositories.inventory_repo import (
    InventoryColorStockUpdateData,
    InventoryRepository,
    InventoryStockUpdateData,
    InventoryTransactionCreateData,
)
from app.repositories.order_repo import OrderCancellationItemData, OrderRepository
from app.repositories.payment_repo import (
    PaymentRepository,
    RefundCreateData,
)
from app.repositories.table_session_repo import TableSessionRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import (
    WalletRepository,
    WalletTransactionCreateData,
)
from app.services.audit_log_service import AuditLogService
from app.utils.database import get_database_error_code

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RefundResult:
    order: Order
    payment: Payment
    refund: Refund
    inventory_restored: bool
    is_replay: bool


class RefundService:
    """全额退款、钱包原路退回与 PAID Kit 库存恢复。"""

    def __init__(
        self,
        order_repository: OrderRepository,
        payment_repository: PaymentRepository,
        wallet_repository: WalletRepository,
        inventory_repository: InventoryRepository,
        user_repository: UserRepository,
        audit_log_service: AuditLogService,
        table_session_repository: TableSessionRepository | None = None,
    ) -> None:
        self.order_repository = order_repository
        self.payment_repository = payment_repository
        self.wallet_repository = wallet_repository
        self.inventory_repository = inventory_repository
        self.user_repository = user_repository
        self.audit_log_service = audit_log_service
        self.table_session_repository = table_session_repository

    async def refund_order(
        self,
        order_id: int,
        *,
        operator: User,
        reason: str,
        idempotency_key: str,
        ip_address: str,
    ) -> RefundResult:
        if not settings.wallet_refund_available:
            raise ServiceUnavailableException(message="Order refunds are disabled")
        self._ensure_admin(operator)
        internal_key = f"{REFUND_ADMIN_IDEMPOTENCY_PREFIX}{idempotency_key}"
        normalized_reason = reason.strip()

        for attempt in range(1, FINANCIAL_TRANSACTION_MAX_ATTEMPTS + 1):
            refund_no = generate_refund_number()
            try:
                result = await self._refund_once(
                    order_id=order_id,
                    operator=operator,
                    reason=normalized_reason,
                    internal_key=internal_key,
                    refund_no=refund_no,
                    ip_address=ip_address,
                )
            except IntegrityError:
                replay = await self._resolve_refund_replay(
                    order_id=order_id,
                    operator=operator,
                    reason=normalized_reason,
                    internal_key=internal_key,
                )
                if replay is not None:
                    result = replay
                else:
                    existing = await self.payment_repository.get_refund_by_order_id(
                        order_id
                    )
                    if existing is not None:
                        raise RefundStatusConflict()
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
                    "Retrying refund after MySQL transient error: "
                    "operator_id=%d order_id=%d error_code=%d attempt=%d",
                    operator.id,
                    order_id,
                    error_code,
                    attempt,
                )
                continue

            logger.info(
                "Order refunded: operator_id=%d order_id=%d refund_id=%d replay=%s",
                operator.id,
                order_id,
                result.refund.id,
                result.is_replay,
            )
            return result

        raise RuntimeError("Refund retry loop exhausted")

    async def _refund_once(
        self,
        *,
        order_id: int,
        operator: User,
        reason: str,
        internal_key: str,
        refund_no: str,
        ip_address: str,
    ) -> RefundResult:
        visible_order = await self.order_repository.get_order_by_id(order_id)
        if visible_order is None:
            raise OrderNotFound()

        async with in_transaction() as connection:
            owner = await self.user_repository.get_for_update(
                visible_order.user_id,
                using_db=connection,
            )
            if owner is None:
                raise UserNotFound()
            self._ensure_admin_target(operator=operator, target=owner)
            if owner.status == UserStatus.DELETED:
                raise UserDeleted()
            if owner.status not in (UserStatus.NORMAL, UserStatus.DISABLED):
                raise PermissionException(
                    message="Customer account status does not allow refund"
                )

            order = await self.order_repository.get_order_for_update(
                order_id,
                using_db=connection,
            )
            if order is None or order.user_id != owner.id:
                raise OrderNotFound()

            table_session = await self._lock_open_table_session(
                order_id=order.id,
                using_db=connection,
            )
            try:
                order_status = OrderStatus(order.status)
            except (TypeError, ValueError):
                raise RefundStatusConflict() from None

            settlement = await self.payment_repository.get_settlement_by_order_id(
                order.id,
                using_db=connection,
            )
            if settlement is None:
                raise PaymentNotFound()
            locked_settlement = (
                await self.payment_repository.get_settlement_for_update(
                    settlement.id,
                    using_db=connection,
                )
            )
            if (
                locked_settlement is None
                or locked_settlement.order_id != order.id
                or locked_settlement.amount != order.total_amount
            ):
                raise PaymentNotFound()
            payment = await self.payment_repository.get_payment_for_update(
                locked_settlement.payment_id,
                using_db=connection,
            )
            if (
                payment is None
                or payment.order_id != order.id
                or payment.recharge_order_id is not None
                or payment.user_id != owner.id
                or payment.purpose is not PaymentPurpose.ORDER
                or payment.status is not PaymentStatus.SUCCEEDED
                or payment.succeeded_at is None
                or payment.amount != locked_settlement.amount
            ):
                raise PaymentNotFound()

            existing_by_key = (
                await self.payment_repository.get_refund_by_idempotency_key(
                    internal_key,
                    using_db=connection,
                )
            )
            if existing_by_key is not None:
                return await self._build_refund_replay(
                    order=order,
                    settlement=locked_settlement,
                    payment=payment,
                    refund=existing_by_key,
                    operator=operator,
                    reason=reason,
                    using_db=connection,
                )
            self._validate_refundable_order(order, order_status=order_status)
            if (
                await self.payment_repository.get_refund_by_settlement_id(
                    locked_settlement.id,
                    using_db=connection,
                )
                is not None
            ):
                raise RefundStatusConflict()

            if payment.method is PaymentMethod.WECHAT:
                raise ServiceUnavailableException(
                    message="WeChat refunds are unavailable until merchant onboarding"
                )
            if payment.method not in (PaymentMethod.WALLET, PaymentMethod.MANUAL):
                raise PaymentNotFound()
            if payment.provider_transaction_id is not None:
                raise PaymentNotFound()

            items: list[OrderCancellationItemData] = []
            should_restore_inventory = False
            if order_status is OrderStatus.PAID:
                items = await self.order_repository.get_order_items(
                    order.id,
                    using_db=connection,
                )
                should_restore_inventory = any(
                    item.experience_option_id is None for item in items
                )

            refund = await self.payment_repository.create_refund(
                data=RefundCreateData(
                    refund_no=refund_no,
                    settlement_id=locked_settlement.id,
                    order_id=order.id,
                    operator_id=operator.id,
                    amount=locked_settlement.amount,
                    inventory_restored=should_restore_inventory,
                    reason=reason,
                    idempotency_key=internal_key,
                ),
                using_db=connection,
            )

            if payment.method is PaymentMethod.WALLET:
                await self._credit_wallet_refund(
                    owner=owner,
                    order=order,
                    refund=refund,
                    operator=operator,
                    using_db=connection,
                )

            inventory_restored = False
            if should_restore_inventory:
                inventory_restored = await self._restore_paid_kit_inventory(
                    order=order,
                    refund=refund,
                    operator=operator,
                    items=items,
                    using_db=connection,
                )

            succeeded_at = datetime.now(timezone.utc)
            await self.payment_repository.update_refund_status(
                refund,
                status=RefundStatus.SUCCEEDED,
                provider_refund_id=None,
                succeeded_at=succeeded_at,
                using_db=connection,
            )
            closed_session_no = await self._close_table_session_for_refund(
                table_session,
                operator_id=operator.id,
                closed_at=succeeded_at,
                ip_address=ip_address,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator.id,
                action=REFUND_AUDIT_ACTION_COMPLETE,
                target_type=ORDER_AUDIT_TARGET_TYPE,
                target_id=order.id,
                ip_address=ip_address,
                description=json.dumps(
                    {
                        "refund_id": refund.id,
                        "payment_id": payment.id,
                        "method": payment.method.value,
                        "amount": f"{refund.amount:.2f}",
                        "inventory_restored": inventory_restored,
                        "table_session_no": closed_session_no,
                    },
                    separators=(",", ":"),
                ),
                using_db=connection,
            )
            return RefundResult(
                order=order,
                payment=payment,
                refund=refund,
                inventory_restored=inventory_restored,
                is_replay=False,
            )

    async def _lock_open_table_session(
        self,
        *,
        order_id: int,
        using_db: BaseDBAsyncClient,
    ) -> TableSession | None:
        if self.table_session_repository is None:
            return None
        visible = await self.table_session_repository.get_open_session_by_order_id(
            order_id,
            using_db=using_db,
        )
        if visible is None:
            return None
        table = await self.table_session_repository.get_table_for_update(
            visible.table_id,
            using_db=using_db,
        )
        if table is None:
            raise RefundStatusConflict()
        locked = await self.table_session_repository.get_session_for_update(
            visible.id,
            using_db=using_db,
        )
        if locked is None:
            raise RefundStatusConflict()
        return locked

    async def _close_table_session_for_refund(
        self,
        session: TableSession | None,
        *,
        operator_id: int,
        closed_at: datetime,
        ip_address: str,
        using_db: BaseDBAsyncClient,
    ) -> str | None:
        if session is None or self.table_session_repository is None:
            return None
        status = TableSessionStatus(session.status)
        automatic = automatic_close_for(
            status=status,
            now=closed_at,
            payment_deadline_at=session.payment_deadline_at,
            table_release_at=session.table_release_at,
        )
        reason = (
            automatic.reason
            if automatic is not None
            else TableSessionCloseReason.REFUNDED
        )
        effective_closed_at = (
            automatic.closed_at if automatic is not None else closed_at
        )
        await self.table_session_repository.close_session(
            session,
            reason=reason,
            closed_at=effective_closed_at,
            closed_by_user_id=None if automatic is not None else operator_id,
            admin_close_reason=None,
            release_idempotency_key=None,
            using_db=using_db,
        )
        await self.audit_log_service.log(
            operator_id=operator_id,
            action=TABLE_AUDIT_ACTION_RELEASE,
            target_type=TABLE_AUDIT_TARGET_TYPE,
            target_id=session.id,
            ip_address=ip_address,
            description=json.dumps(
                {"close_reason": reason.value, "order_id": session.order_id},
                separators=(",", ":"),
            ),
            using_db=using_db,
        )
        return session.session_no

    async def _credit_wallet_refund(
        self,
        *,
        owner: User,
        order: Order,
        refund: Refund,
        operator: User,
        using_db: BaseDBAsyncClient,
    ) -> None:
        account = await self.wallet_repository.get_account_for_update(
            owner.id,
            using_db=using_db,
        )
        if account is None:
            raise WalletNotFound()
        if account.status is not WalletStatus.ACTIVE:
            raise PermissionException(message="Closed wallet cannot receive a refund")
        before_balance = account.balance
        after_balance = before_balance + refund.amount
        if after_balance > WALLET_BALANCE_MAX:
            raise WalletBalanceExceeded(
                user_id=owner.id,
                before_balance=before_balance,
                change_amount=refund.amount,
            )
        await self.wallet_repository.update_balance(
            account,
            balance=after_balance,
            using_db=using_db,
        )
        await self.wallet_repository.create_transaction(
            data=WalletTransactionCreateData(
                wallet_account_id=account.id,
                transaction_type=WalletTransactionType.REFUND,
                change_amount=refund.amount,
                before_balance=before_balance,
                after_balance=after_balance,
                source_type=WalletTransactionSourceType.REFUND,
                source_id=refund.id,
                operator_id=operator.id,
                reason=WALLET_ORDER_REFUND_REASON,
                idempotency_key=WALLET_REFUND_TRANSACTION_KEY.format(
                    refund_id=refund.id,
                    order_id=order.id,
                ),
            ),
            using_db=using_db,
        )

    async def _restore_paid_kit_inventory(
        self,
        *,
        order: Order,
        refund: Refund,
        operator: User,
        items: list[OrderCancellationItemData],
        using_db: BaseDBAsyncClient,
    ) -> bool:
        fixed_quantity_by_product: dict[int, int] = {}
        color_quantity_by_id: dict[int, tuple[int, int]] = {}
        for item in items:
            if item.experience_option_id is not None:
                continue
            if item.kit_color_id is None:
                fixed_quantity_by_product[item.product_id] = (
                    fixed_quantity_by_product.get(item.product_id, 0)
                    + item.quantity
                )
                continue
            existing_product_id, existing_quantity = color_quantity_by_id.get(
                item.kit_color_id,
                (item.product_id, 0),
            )
            if existing_product_id != item.product_id:
                raise InventoryTransactionConflict()
            color_quantity_by_id[item.kit_color_id] = (
                item.product_id,
                existing_quantity + item.quantity,
            )
        if not fixed_quantity_by_product and not color_quantity_by_id:
            return False

        product_ids = set(fixed_quantity_by_product)
        color_ids = set(color_quantity_by_id)
        kits = await self.inventory_repository.get_kits_for_update(
            product_ids,
            using_db=using_db,
        )
        kit_colors = await self.inventory_repository.get_kit_colors_for_update(
            color_ids,
            using_db=using_db,
        )
        kits_by_product = {kit.product_id: kit for kit in kits}
        if set(kits_by_product) != product_ids:
            raise InventoryTransactionConflict()
        colors_by_id = {kit_color.id: kit_color for kit_color in kit_colors}
        if set(colors_by_id) != color_ids or any(
            colors_by_id[kit_color_id].product_id != product_id
            for kit_color_id, (product_id, _) in color_quantity_by_id.items()
        ):
            raise InventoryTransactionConflict()

        keys = {
            INVENTORY_ORDER_REFUND_RESTORE_IDEMPOTENCY_KEY.format(
                refund_id=refund.id,
                product_id=product_id,
            )
            for product_id in product_ids
        }
        keys.update(
            INVENTORY_ORDER_COLOR_REFUND_RESTORE_IDEMPOTENCY_KEY.format(
                refund_id=refund.id,
                product_id=product_id,
                kit_color_id=kit_color_id,
            )
            for kit_color_id, (product_id, _) in color_quantity_by_id.items()
        )
        if await self.inventory_repository.get_transactions_by_idempotency_keys(
            keys,
            using_db=using_db,
        ):
            raise InventoryTransactionConflict()

        updates: list[InventoryStockUpdateData] = []
        color_updates: list[InventoryColorStockUpdateData] = []
        transactions: list[InventoryTransactionCreateData] = []
        for product_id in sorted(product_ids):
            kit = kits_by_product[product_id]
            quantity = fixed_quantity_by_product[product_id]
            before_quantity = kit.stock
            if before_quantity is None:
                raise InventoryTransactionConflict()
            after_quantity = before_quantity + quantity
            if after_quantity > INVENTORY_STOCK_MAX:
                raise InventoryBalanceExceeded(
                    product_id=product_id,
                    before_quantity=before_quantity,
                    change_quantity=quantity,
                )
            updates.append(InventoryStockUpdateData(kit=kit, stock=after_quantity))
            transactions.append(
                InventoryTransactionCreateData(
                    product_id=product_id,
                    transaction_type=InventoryTransactionType.ORDER_REFUND_RESTORE,
                    change_quantity=quantity,
                    before_quantity=before_quantity,
                    after_quantity=after_quantity,
                    source_type=InventorySourceType.ORDER,
                    source_id=order.id,
                    operator_id=operator.id,
                    reason=INVENTORY_ORDER_REFUND_RESTORE_REASON,
                    idempotency_key=(
                        INVENTORY_ORDER_REFUND_RESTORE_IDEMPOTENCY_KEY.format(
                            refund_id=refund.id,
                            product_id=product_id,
                        )
                    ),
                )
            )

        for kit_color in kit_colors:
            product_id, quantity = color_quantity_by_id[kit_color.id]
            before_quantity = kit_color.stock_units
            after_quantity = before_quantity + quantity
            if after_quantity > INVENTORY_STOCK_MAX:
                raise InventoryBalanceExceeded(
                    product_id=product_id,
                    kit_color_id=kit_color.id,
                    before_quantity=before_quantity,
                    change_quantity=quantity,
                )
            color_updates.append(
                InventoryColorStockUpdateData(
                    kit_color=kit_color,
                    stock_units=after_quantity,
                )
            )
            transactions.append(
                InventoryTransactionCreateData(
                    product_id=product_id,
                    kit_color_id=kit_color.id,
                    transaction_type=InventoryTransactionType.ORDER_REFUND_RESTORE,
                    change_quantity=quantity,
                    before_quantity=before_quantity,
                    after_quantity=after_quantity,
                    source_type=InventorySourceType.ORDER,
                    source_id=order.id,
                    operator_id=operator.id,
                    reason=INVENTORY_ORDER_REFUND_RESTORE_REASON,
                    idempotency_key=(
                        INVENTORY_ORDER_COLOR_REFUND_RESTORE_IDEMPOTENCY_KEY.format(
                            refund_id=refund.id,
                            product_id=product_id,
                            kit_color_id=kit_color.id,
                        )
                    ),
                )
            )
        await self.inventory_repository.bulk_update_stocks(
            updates=updates,
            using_db=using_db,
        )
        await self.inventory_repository.bulk_update_color_stocks(
            updates=color_updates,
            using_db=using_db,
        )
        await self.inventory_repository.bulk_create_transactions(
            transactions=transactions,
            using_db=using_db,
        )
        return True

    async def _resolve_refund_replay(
        self,
        *,
        order_id: int,
        operator: User,
        reason: str,
        internal_key: str,
    ) -> RefundResult | None:
        refund = await self.payment_repository.get_refund_by_idempotency_key(
            internal_key
        )
        order = await self.order_repository.get_order_by_id(order_id)
        if refund is None or order is None:
            return None
        settlement = await self.payment_repository.get_settlement_by_order_id(order_id)
        if settlement is None:
            raise WalletTransactionConflict()
        return await self._build_refund_replay(
            order=order,
            settlement=settlement,
            payment=settlement.payment,
            refund=refund,
            operator=operator,
            reason=reason,
        )

    async def _build_refund_replay(
        self,
        *,
        order: Order,
        settlement: PaymentSettlement,
        payment: Payment,
        refund: Refund,
        operator: User,
        reason: str,
        using_db: BaseDBAsyncClient | None = None,
    ) -> RefundResult:
        try:
            order_status = OrderStatus(order.status)
        except (TypeError, ValueError):
            raise WalletTransactionConflict() from None
        if (
            order_status not in (OrderStatus.PAID, OrderStatus.COMPLETED)
            or settlement.order_id != order.id
            or settlement.payment_id != payment.id
            or settlement.amount != order.total_amount
            or settlement.amount != payment.amount
            or payment.user_id != order.user_id
            or payment.order_id != order.id
            or payment.recharge_order_id is not None
            or payment.purpose is not PaymentPurpose.ORDER
            or payment.method not in (PaymentMethod.WALLET, PaymentMethod.MANUAL)
            or payment.status is not PaymentStatus.SUCCEEDED
            or payment.succeeded_at is None
            or payment.provider_transaction_id is not None
            or refund.settlement_id != settlement.id
            or refund.order_id != order.id
            or refund.operator_id != operator.id
            or refund.reason != reason
            or refund.amount != settlement.amount
            or refund.succeeded_at is None
            or refund.provider_refund_id is not None
        ):
            raise WalletTransactionConflict()
        if refund.status is not RefundStatus.SUCCEEDED:
            raise RefundStatusConflict()

        if payment.method is PaymentMethod.WALLET:
            account = await self.wallet_repository.get_account_by_user_id(
                order.user_id,
                using_db=using_db,
            )
            transaction = (
                await self.wallet_repository.get_transaction_by_idempotency_key(
                    WALLET_REFUND_TRANSACTION_KEY.format(
                        refund_id=refund.id,
                        order_id=order.id,
                    ),
                    using_db=using_db,
                )
            )
            if (
                account is None
                or transaction is None
                or transaction.wallet_account_id != account.id
                or transaction.transaction_type is not WalletTransactionType.REFUND
                or transaction.change_amount != refund.amount
                or transaction.after_balance
                != transaction.before_balance + transaction.change_amount
                or transaction.source_type is not WalletTransactionSourceType.REFUND
                or transaction.source_id != refund.id
                or transaction.operator_id != operator.id
                or transaction.reason != WALLET_ORDER_REFUND_REASON
            ):
                raise WalletTransactionConflict()
        return RefundResult(
            order=order,
            payment=payment,
            refund=refund,
            inventory_restored=refund.inventory_restored,
            is_replay=True,
        )

    @staticmethod
    def _validate_refundable_order(
        order: Order,
        *,
        order_status: OrderStatus,
    ) -> None:
        if order_status not in (OrderStatus.PAID, OrderStatus.COMPLETED):
            raise RefundStatusConflict()
        if (
            order_status is OrderStatus.COMPLETED
            and order.updated_at
            < datetime.now(timezone.utc) - timedelta(days=ORDER_REFUND_WINDOW_DAYS)
        ):
            raise RefundWindowExpired()

    @staticmethod
    def _ensure_admin(operator: User) -> None:
        if operator.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            raise PermissionException(message="Admin access required")

    @staticmethod
    def _ensure_admin_target(*, operator: User, target: User) -> None:
        RefundService._ensure_admin(operator)
        if operator.id == target.id or target.role != UserRole.USER:
            raise PermissionException(
                message="Administrators can refund customer orders only"
            )
