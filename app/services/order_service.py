"""Order Service —— 订单查询与后续写用例的业务编排层。"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError, OperationalError
from tortoise.transactions import in_transaction

from app.common.constants.order import (
    ORDER_AUDIT_ACTION_CANCEL,
    ORDER_AUDIT_ACTION_COMPLETE,
    ORDER_AUDIT_ACTION_CREATE,
    ORDER_AUDIT_ACTION_MARK_PAID,
    ORDER_AUDIT_TARGET_TYPE,
    ORDER_NO_GENERATION_MAX_ATTEMPTS,
    ORDER_OPERATION_CANCEL,
    ORDER_OPERATION_COMPLETE,
    ORDER_OPERATION_MARK_PAID,
    ORDER_STATUS_BY_VALUE,
    ORDER_STATUS_VALUES,
)
from app.common.constants.inventory import (
    INVENTORY_ORDER_DEDUCTION_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_DEDUCTION_REASON,
    INVENTORY_ORDER_RESTORE_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_RESTORE_REASON,
    INVENTORY_RETRYABLE_MYSQL_ERROR_CODES,
    INVENTORY_STOCK_MAX,
    INVENTORY_TRANSACTION_MAX_ATTEMPTS,
)
from app.common.constants.wallet import (
    ASSISTED_WALLET_ORDER_IDEMPOTENCY_PREFIX,
    ASSISTED_WALLET_ORDER_PAYMENT_REASON,
    ASSISTED_WALLET_ORDER_TRANSACTION_KEY,
    MANUAL_PAYMENT_IDEMPOTENCY_KEY,
    PAYMENT_AUDIT_ACTION_PAY_ORDER,
)
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.enums.order import OrderStatus, OrderStatusValue
from app.common.enums.product import ProductStatus, ProductType
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
from app.common.exceptions import (
    InsufficientStock,
    InventoryBalanceExceeded,
    InventoryTransactionConflict,
    OrderNotFound,
    OrderOptionUnavailable,
    OrderProductUnavailable,
    OrderStatusConflict,
    UserDeleted,
    UserDisabled,
)
from app.common.exceptions.wallet import (
    InsufficientWalletBalance,
    PaymentSettlementConflict,
    RefundStatusConflict,
    WalletNotFound,
    WalletTransactionConflict,
)
from app.common.financial_number import generate_payment_number
from app.common.order_number import generate_order_number
from app.common.pagination import Page
from app.core.config import settings
from app.core.exceptions import PermissionException, ServiceUnavailableException
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.payment import Payment
from app.models.user import User
from app.repositories.order_repo import (
    OrderCancellationItemData,
    OrderItemCreateData,
    OrderRepository,
)
from app.repositories.inventory_repo import (
    InventoryRepository,
    InventoryStockUpdateData,
    InventoryTransactionCreateData,
)
from app.repositories.product_repo import ProductRepository
from app.repositories.payment_repo import PaymentCreateData, PaymentRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import (
    WalletRepository,
    WalletTransactionCreateData,
)
from app.services.audit_log_service import AuditLogService
from app.utils.database import get_database_error_code

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OrderItemInput:
    """创建订单的领域输入，不包含任何客户端可伪造快照。"""

    product_id: int
    experience_option_id: int | None
    quantity: int


@dataclass(frozen=True, slots=True)
class AssistedWalletOrderResult:
    """管理员代客商品扣款的不可变结果。"""

    order: Order
    payment: Payment
    post_payment_balance: Decimal
    is_replay: bool


class OrderService:
    """Order 创建、状态变迁与查询用例的业务编排层。"""

    def __init__(
        self,
        order_repository: OrderRepository,
        product_repository: ProductRepository,
        inventory_repository: InventoryRepository,
        audit_log_service: AuditLogService,
        *,
        user_repository: UserRepository,
        order_number_generator: Callable[[], str] = generate_order_number,
        payment_repository: PaymentRepository | None = None,
        payment_number_generator: Callable[[], str] = generate_payment_number,
        wallet_repository: WalletRepository | None = None,
    ) -> None:
        self.order_repository = order_repository
        self.product_repository = product_repository
        self.inventory_repository = inventory_repository
        self.audit_log_service = audit_log_service
        self.user_repository = user_repository
        self.order_number_generator = order_number_generator
        self.payment_repository = payment_repository
        self.payment_number_generator = payment_number_generator
        self.wallet_repository = wallet_repository

    async def create_assisted_wallet_order(
        self,
        *,
        operator: User,
        user_id: int,
        items: list[OrderItemInput],
        remark: str | None,
        idempotency_key: str,
        ip_address: str,
    ) -> AssistedWalletOrderResult:
        """原子创建真实订单、扣库存、扣钱包并生成成功结算。"""

        self._ensure_assisted_order_operator(operator, user_id=user_id)
        payment_repository, _ = self._require_assisted_order_dependencies()
        internal_key = f"{ASSISTED_WALLET_ORDER_IDEMPOTENCY_PREFIX}{idempotency_key}"

        replay = await self._resolve_assisted_wallet_order_replay(
            operator=operator,
            user_id=user_id,
            items=items,
            remark=remark,
            internal_key=internal_key,
        )
        if replay is not None:
            return replay
        if not settings.wallet_admin_write_available:
            raise ServiceUnavailableException(
                message="Wallet administration is temporarily disabled"
            )

        snapshots, total_amount, kit_items = await self._build_order_snapshots(items)
        for attempt in range(ORDER_NO_GENERATION_MAX_ATTEMPTS):
            order_no = self.order_number_generator()
            payment_no = self.payment_number_generator()
            try:
                result = await self._create_assisted_wallet_order_with_retry(
                    operator=operator,
                    user_id=user_id,
                    snapshots=snapshots,
                    kit_items=kit_items,
                    total_amount=total_amount,
                    remark=remark,
                    internal_key=internal_key,
                    order_no=order_no,
                    payment_no=payment_no,
                    ip_address=ip_address,
                )
            except IntegrityError:
                replay = await self._resolve_assisted_wallet_order_replay(
                    operator=operator,
                    user_id=user_id,
                    items=items,
                    remark=remark,
                    internal_key=internal_key,
                )
                if replay is not None:
                    return replay
                collision = await self.order_repository.order_number_exists(order_no)
                collision = collision or (
                    await payment_repository.payment_number_exists(payment_no)
                )
                if collision and attempt + 1 < ORDER_NO_GENERATION_MAX_ATTEMPTS:
                    continue
                raise

            logger.info(
                "Assisted wallet order created: operator_id=%d user_id=%d "
                "order_id=%d payment_id=%d",
                operator.id,
                user_id,
                result.order.id,
                result.payment.id,
            )
            return result

        raise RuntimeError("Assisted wallet order number retry loop exhausted")

    async def _create_assisted_wallet_order_with_retry(
        self,
        *,
        operator: User,
        user_id: int,
        snapshots: list[OrderItemCreateData],
        kit_items: list[OrderItemInput],
        total_amount: Decimal,
        remark: str | None,
        internal_key: str,
        order_no: str,
        payment_no: str,
        ip_address: str,
    ) -> AssistedWalletOrderResult:
        """对 MySQL 锁超时/死锁以全新事务重试整个代客扣款用例。"""

        for attempt in range(1, INVENTORY_TRANSACTION_MAX_ATTEMPTS + 1):
            try:
                return await self._create_assisted_wallet_order_once(
                    operator=operator,
                    user_id=user_id,
                    snapshots=snapshots,
                    kit_items=kit_items,
                    total_amount=total_amount,
                    remark=remark,
                    internal_key=internal_key,
                    order_no=order_no,
                    payment_no=payment_no,
                    ip_address=ip_address,
                )
            except IntegrityError:
                raise
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in INVENTORY_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= INVENTORY_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying assisted wallet order after MySQL transient error: "
                    "operator_id=%d user_id=%d error_code=%d attempt=%d",
                    operator.id,
                    user_id,
                    error_code,
                    attempt,
                )
        raise RuntimeError("Assisted wallet order retry loop exhausted")

    async def _create_assisted_wallet_order_once(
        self,
        *,
        operator: User,
        user_id: int,
        snapshots: list[OrderItemCreateData],
        kit_items: list[OrderItemInput],
        total_amount: Decimal,
        remark: str | None,
        internal_key: str,
        order_no: str,
        payment_no: str,
        ip_address: str,
    ) -> AssistedWalletOrderResult:
        payment_repository, wallet_repository = (
            self._require_assisted_order_dependencies()
        )
        async with in_transaction() as connection:
            target = await self.user_repository.get_for_update(
                user_id,
                using_db=connection,
            )
            if target is None or target.status == UserStatus.DELETED:
                raise UserDeleted()
            self._ensure_assisted_order_operator(operator, user_id=target.id)
            if target.role != UserRole.USER:
                raise PermissionException(
                    message="Administrators can charge customer wallets only"
                )
            if target.status == UserStatus.DISABLED:
                raise UserDisabled()
            if target.status != UserStatus.NORMAL:
                raise PermissionException(
                    message="Customer account status does not allow assisted purchase"
                )

            order = await self.order_repository.create_order(
                order_no=order_no,
                user_id=target.id,
                total_amount=total_amount,
                remark=remark,
                using_db=connection,
            )
            account = await wallet_repository.get_account_for_update(
                target.id,
                using_db=connection,
            )
            if account is None:
                raise WalletNotFound()
            if account.status is not WalletStatus.ACTIVE:
                raise PermissionException(message="Wallet account is closed")
            if account.balance < total_amount:
                raise InsufficientWalletBalance(
                    user_id=target.id,
                    requested_amount=total_amount,
                )

            await self._deduct_kit_stock(
                order_id=order.id,
                user_id=operator.id,
                kit_items=kit_items,
                using_db=connection,
            )
            await self.order_repository.bulk_create_items(
                order=order,
                items=snapshots,
                using_db=connection,
            )
            payment = await payment_repository.create_payment(
                data=PaymentCreateData(
                    payment_no=payment_no,
                    user_id=target.id,
                    purpose=PaymentPurpose.ORDER,
                    method=PaymentMethod.WALLET,
                    amount=total_amount,
                    order_id=order.id,
                    recharge_order_id=None,
                    idempotency_key=internal_key,
                ),
                using_db=connection,
            )
            await payment_repository.update_payment_status(
                payment,
                status=PaymentStatus.SUCCEEDED,
                provider_transaction_id=None,
                succeeded_at=datetime.now(timezone.utc),
                using_db=connection,
            )

            before_balance = account.balance
            after_balance = before_balance - total_amount
            await wallet_repository.update_balance(
                account,
                balance=after_balance,
                using_db=connection,
            )
            await wallet_repository.create_transaction(
                data=WalletTransactionCreateData(
                    wallet_account_id=account.id,
                    transaction_type=WalletTransactionType.ORDER_PAYMENT,
                    change_amount=-total_amount,
                    before_balance=before_balance,
                    after_balance=after_balance,
                    source_type=WalletTransactionSourceType.ORDER,
                    source_id=order.id,
                    operator_id=operator.id,
                    reason=ASSISTED_WALLET_ORDER_PAYMENT_REASON,
                    idempotency_key=ASSISTED_WALLET_ORDER_TRANSACTION_KEY.format(
                        payment_id=payment.id,
                        order_id=order.id,
                    ),
                ),
                using_db=connection,
            )
            await payment_repository.create_settlement(
                payment_id=payment.id,
                order_id=order.id,
                amount=total_amount,
                using_db=connection,
            )
            await self.order_repository.update_status(
                order,
                status=OrderStatus.PAID,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator.id,
                action=ORDER_AUDIT_ACTION_CREATE,
                target_type=ORDER_AUDIT_TARGET_TYPE,
                target_id=order.id,
                ip_address=ip_address,
                description=json.dumps(
                    {
                        "assisted_for_user_id": target.id,
                        "item_count": len(snapshots),
                        "total_amount": f"{total_amount:.2f}",
                    },
                    separators=(",", ":"),
                ),
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator.id,
                action=PAYMENT_AUDIT_ACTION_PAY_ORDER,
                target_type=ORDER_AUDIT_TARGET_TYPE,
                target_id=order.id,
                ip_address=ip_address,
                description=json.dumps(
                    {
                        "payment_id": payment.id,
                        "method": PaymentMethod.WALLET.value,
                        "amount": f"{total_amount:.2f}",
                    },
                    separators=(",", ":"),
                ),
                using_db=connection,
            )
            loaded = await self.order_repository.get_order_detail(
                order.id,
                using_db=connection,
            )
            if loaded is None:
                raise RuntimeError("Persisted assisted order not found")
            return AssistedWalletOrderResult(
                order=loaded,
                payment=payment,
                post_payment_balance=after_balance,
                is_replay=False,
            )

    async def _resolve_assisted_wallet_order_replay(
        self,
        *,
        operator: User,
        user_id: int,
        items: list[OrderItemInput],
        remark: str | None,
        internal_key: str,
    ) -> AssistedWalletOrderResult | None:
        payment_repository, wallet_repository = (
            self._require_assisted_order_dependencies()
        )
        payment = await payment_repository.get_payment_by_idempotency_key(
            internal_key
        )
        if payment is None:
            return None
        if payment.order_id is None:
            raise WalletTransactionConflict()
        order = await self.order_repository.get_order_detail(payment.order_id)
        if order is None:
            raise WalletTransactionConflict()
        expected_items = [
            (item.product_id, item.experience_option_id, item.quantity)
            for item in items
        ]
        actual_items = [
            (item.product_id, item.experience_option_id, item.quantity)
            for item in order.items
        ]
        if (
            payment.user_id != user_id
            or order.user_id != user_id
            or payment.purpose is not PaymentPurpose.ORDER
            or payment.method is not PaymentMethod.WALLET
            or payment.status is not PaymentStatus.SUCCEEDED
            or payment.recharge_order_id is not None
            or payment.provider_transaction_id is not None
            or payment.succeeded_at is None
            or payment.amount != order.total_amount
            or OrderStatus(order.status) is not OrderStatus.PAID
            or order.remark != remark
            or actual_items != expected_items
        ):
            raise WalletTransactionConflict()
        settlement = await payment_repository.get_settlement_by_order_id(order.id)
        if (
            settlement is None
            or settlement.payment_id != payment.id
            or settlement.order_id != order.id
            or settlement.amount != order.total_amount
            or settlement.amount != payment.amount
        ):
            raise PaymentSettlementConflict()
        account = await wallet_repository.get_account_by_user_id(user_id)
        if account is None:
            raise WalletTransactionConflict()
        transaction = await wallet_repository.get_transaction_by_idempotency_key(
            ASSISTED_WALLET_ORDER_TRANSACTION_KEY.format(
                payment_id=payment.id,
                order_id=order.id,
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
            or transaction.operator_id != operator.id
            or transaction.reason != ASSISTED_WALLET_ORDER_PAYMENT_REASON
        ):
            raise WalletTransactionConflict()
        return AssistedWalletOrderResult(
            order=order,
            payment=payment,
            post_payment_balance=transaction.after_balance,
            is_replay=True,
        )

    def _require_assisted_order_dependencies(
        self,
    ) -> tuple[PaymentRepository, WalletRepository]:
        if self.payment_repository is None or self.wallet_repository is None:
            raise RuntimeError("Assisted wallet order dependencies are unavailable")
        return self.payment_repository, self.wallet_repository

    @staticmethod
    def _ensure_assisted_order_operator(operator: User, *, user_id: int) -> None:
        if operator.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            raise PermissionException(message="Admin access required")
        if operator.id == user_id:
            raise PermissionException(message="Administrators cannot charge themselves")

    async def create_order(
        self,
        *,
        user_id: int,
        items: list[OrderItemInput],
        remark: str | None,
        ip_address: str,
    ) -> Order:
        """校验 Experience/Kit Items，并原子创建订单、扣减、快照与审计。"""

        snapshots, total_amount, kit_items = await self._build_order_snapshots(
            items
        )
        audit_description = json.dumps(
            {
                "item_count": len(snapshots),
                "total_amount": f"{total_amount:.2f}",
            },
            separators=(",", ":"),
        )

        for attempt in range(ORDER_NO_GENERATION_MAX_ATTEMPTS):
            order_no = self.order_number_generator()
            try:
                loaded = await self._create_order_with_transient_retry(
                    order_no=order_no,
                    user_id=user_id,
                    snapshots=snapshots,
                    kit_items=kit_items,
                    total_amount=total_amount,
                    remark=remark,
                    ip_address=ip_address,
                    audit_description=audit_description,
                )
            except IntegrityError:
                is_order_number_collision = (
                    await self.order_repository.order_number_exists(order_no)
                )
                if (
                    is_order_number_collision
                    and attempt + 1 < ORDER_NO_GENERATION_MAX_ATTEMPTS
                ):
                    continue
                raise

            logger.info(
                "Order created: user_id=%d order_id=%d item_count=%d",
                user_id,
                loaded.id,
                len(snapshots),
            )
            return loaded

        raise RuntimeError("Order number retry loop exhausted")

    async def _create_order_with_transient_retry(
        self,
        *,
        order_no: str,
        user_id: int,
        snapshots: list[OrderItemCreateData],
        kit_items: list[OrderItemInput],
        total_amount: Decimal,
        remark: str | None,
        ip_address: str,
        audit_description: str,
    ) -> Order:
        """仅对 MySQL 锁瞬态错误以全新事务重试完整创建写集。"""

        for attempt in range(1, INVENTORY_TRANSACTION_MAX_ATTEMPTS + 1):
            try:
                return await self._create_order_once(
                    order_no=order_no,
                    user_id=user_id,
                    snapshots=snapshots,
                    kit_items=kit_items,
                    total_amount=total_amount,
                    remark=remark,
                    ip_address=ip_address,
                    audit_description=audit_description,
                )
            except IntegrityError:
                raise
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in INVENTORY_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= INVENTORY_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying order creation after MySQL transient error: "
                    "user_id=%d error_code=%d attempt=%d",
                    user_id,
                    error_code,
                    attempt,
                )

        raise RuntimeError("Order creation retry loop exhausted")

    async def _create_order_once(
        self,
        *,
        order_no: str,
        user_id: int,
        snapshots: list[OrderItemCreateData],
        kit_items: list[OrderItemInput],
        total_amount: Decimal,
        remark: str | None,
        ip_address: str,
        audit_description: str,
    ) -> Order:
        """在一条事务中写入 Order、库存、Items、Audit 并重载详情。"""

        async with in_transaction() as connection:
            user = await self.user_repository.get_for_update(
                user_id,
                using_db=connection,
            )
            if user is None or user.status == UserStatus.DELETED:
                raise UserDeleted()
            if user.role != UserRole.USER:
                raise PermissionException(message="Customer account required")
            if user.status == UserStatus.DISABLED:
                raise UserDisabled()
            if user.status != UserStatus.NORMAL:
                raise PermissionException(
                    message="Customer account status does not allow order creation"
                )
            order = await self.order_repository.create_order(
                order_no=order_no,
                user_id=user_id,
                total_amount=total_amount,
                remark=remark,
                using_db=connection,
            )
            await self._deduct_kit_stock(
                order_id=order.id,
                user_id=user_id,
                kit_items=kit_items,
                using_db=connection,
            )
            await self.order_repository.bulk_create_items(
                order=order,
                items=snapshots,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=user_id,
                action=ORDER_AUDIT_ACTION_CREATE,
                target_type=ORDER_AUDIT_TARGET_TYPE,
                target_id=order.id,
                ip_address=ip_address,
                description=audit_description,
                using_db=connection,
            )
            loaded = await self.order_repository.get_order_detail(
                order.id,
                user_id=user_id,
                using_db=connection,
            )
            if loaded is None:
                raise RuntimeError("Persisted order not found")
            return loaded

    async def _deduct_kit_stock(
        self,
        *,
        order_id: int,
        user_id: int,
        kit_items: list[OrderItemInput],
        using_db: BaseDBAsyncClient,
    ) -> None:
        """稳定锁定全部 Kit，锁后重检并批量持久化余额与流水。"""

        if not kit_items:
            return
        product_ids = {item.product_id for item in kit_items}
        locked_kits = await self.inventory_repository.get_kits_for_update(
            product_ids,
            using_db=using_db,
        )
        products = await self.product_repository.get_products_by_ids(
            product_ids,
            using_db=using_db,
        )
        kits_by_product_id = {kit.product_id: kit for kit in locked_kits}
        products_by_id = {product.id: product for product in products}

        for item in kit_items:
            product = (
                products_by_id[item.product_id]
                if item.product_id in products_by_id
                else None
            )
            if (
                product is None
                or product.is_deleted
                or product.status is not ProductStatus.ONLINE
                or product.product_type is not ProductType.KIT
                or item.product_id not in kits_by_product_id
            ):
                raise OrderProductUnavailable(product_id=item.product_id)

        stock_updates: list[InventoryStockUpdateData] = []
        transactions: list[InventoryTransactionCreateData] = []
        for item in kit_items:
            kit = kits_by_product_id[item.product_id]
            before_quantity = kit.stock
            if before_quantity < item.quantity:
                raise InsufficientStock(
                    product_id=item.product_id,
                    requested_quantity=item.quantity,
                )
            after_quantity = before_quantity - item.quantity
            stock_updates.append(
                InventoryStockUpdateData(kit=kit, stock=after_quantity)
            )
            transactions.append(
                InventoryTransactionCreateData(
                    product_id=item.product_id,
                    transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
                    change_quantity=-item.quantity,
                    before_quantity=before_quantity,
                    after_quantity=after_quantity,
                    source_type=InventorySourceType.ORDER,
                    source_id=order_id,
                    operator_id=user_id,
                    reason=INVENTORY_ORDER_DEDUCTION_REASON,
                    idempotency_key=(
                        INVENTORY_ORDER_DEDUCTION_IDEMPOTENCY_KEY.format(
                            order_id=order_id,
                            product_id=item.product_id,
                        )
                    ),
                )
            )

        await self.inventory_repository.bulk_update_stocks(
            updates=stock_updates,
            using_db=using_db,
        )
        await self.inventory_repository.bulk_create_transactions(
            transactions=transactions,
            using_db=using_db,
        )

    async def cancel_order(
        self,
        order_id: int,
        *,
        user_id: int,
        ip_address: str,
    ) -> Order:
        """由订单所属用户取消 Pending Order，并幂等恢复全部 Kit 库存。"""

        loaded = await self._cancel_order_with_transient_retry(
            order_id=order_id,
            user_id=user_id,
            ip_address=ip_address,
        )
        logger.info(
            "Order status changed: operator_id=%d order_id=%d operation=%s",
            user_id,
            loaded.id,
            ORDER_OPERATION_CANCEL,
        )
        return loaded

    async def _cancel_order_with_transient_retry(
        self,
        *,
        order_id: int,
        user_id: int,
        ip_address: str,
    ) -> Order:
        """仅对 MySQL 锁瞬态错误以全新事务重试完整取消恢复写集。"""

        for attempt in range(1, INVENTORY_TRANSACTION_MAX_ATTEMPTS + 1):
            try:
                return await self._cancel_order_once(
                    order_id=order_id,
                    user_id=user_id,
                    ip_address=ip_address,
                )
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in INVENTORY_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= INVENTORY_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying order cancellation after MySQL transient error: "
                    "user_id=%d order_id=%d error_code=%d attempt=%d",
                    user_id,
                    order_id,
                    error_code,
                    attempt,
                )

        raise RuntimeError("Order cancellation retry loop exhausted")

    async def _cancel_order_once(
        self,
        *,
        order_id: int,
        user_id: int,
        ip_address: str,
    ) -> Order:
        """在单个事务中锁定 Order，恢复 Kit，再提交状态、审计与重载。"""

        audit_description = json.dumps(
            {
                "before_status": ORDER_STATUS_VALUES[OrderStatus.PENDING],
                "after_status": ORDER_STATUS_VALUES[OrderStatus.CANCELLED],
            },
            separators=(",", ":"),
        )
        async with in_transaction() as connection:
            order = await self.order_repository.get_order_for_update(
                order_id,
                user_id=user_id,
                using_db=connection,
            )
            if order is None:
                raise OrderNotFound()

            current_status = OrderStatus(order.status)
            if current_status is not OrderStatus.PENDING:
                raise OrderStatusConflict(
                    operation=ORDER_OPERATION_CANCEL,
                    current_status=current_status,
                    required_status=OrderStatus.PENDING,
                )

            items = await self.order_repository.get_order_items(
                order.id,
                using_db=connection,
            )
            await self._restore_kit_stock_after_cancellation(
                order_id=order.id,
                user_id=user_id,
                items=items,
                using_db=connection,
            )
            await self.order_repository.update_status(
                order,
                status=OrderStatus.CANCELLED,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=user_id,
                action=ORDER_AUDIT_ACTION_CANCEL,
                target_type=ORDER_AUDIT_TARGET_TYPE,
                target_id=order.id,
                ip_address=ip_address,
                description=audit_description,
                using_db=connection,
            )
            loaded = await self.order_repository.get_order_by_id(
                order.id,
                using_db=connection,
            )
            if loaded is None:
                raise RuntimeError("Updated order not found")
            return loaded

    async def _restore_kit_stock_after_cancellation(
        self,
        *,
        order_id: int,
        user_id: int,
        items: list[OrderCancellationItemData],
        using_db: BaseDBAsyncClient,
    ) -> None:
        """稳定锁定 Kit，并批量保存取消恢复余额及不可变流水。"""

        quantity_by_product_id: dict[int, int] = {}
        for item in items:
            if item.experience_option_id is not None:
                continue
            quantity_by_product_id[item.product_id] = (
                quantity_by_product_id[item.product_id] + item.quantity
                if item.product_id in quantity_by_product_id
                else item.quantity
            )
        if not quantity_by_product_id:
            return

        product_ids = set(quantity_by_product_id)
        locked_kits = await self.inventory_repository.get_kits_for_update(
            product_ids,
            using_db=using_db,
        )
        kits_by_product_id = {kit.product_id: kit for kit in locked_kits}
        if set(kits_by_product_id) != product_ids:
            raise InventoryTransactionConflict()

        idempotency_keys = {
            INVENTORY_ORDER_RESTORE_IDEMPOTENCY_KEY.format(
                order_id=order_id,
                product_id=product_id,
            )
            for product_id in product_ids
        }
        existing = (
            await self.inventory_repository.get_transactions_by_idempotency_keys(
                idempotency_keys,
                using_db=using_db,
            )
        )
        if existing:
            raise InventoryTransactionConflict()

        stock_updates: list[InventoryStockUpdateData] = []
        transactions: list[InventoryTransactionCreateData] = []
        for product_id in sorted(product_ids):
            kit = kits_by_product_id[product_id]
            change_quantity = quantity_by_product_id[product_id]
            before_quantity = kit.stock
            after_quantity = before_quantity + change_quantity
            if after_quantity > INVENTORY_STOCK_MAX:
                raise InventoryBalanceExceeded(
                    product_id=product_id,
                    before_quantity=before_quantity,
                    change_quantity=change_quantity,
                )
            stock_updates.append(
                InventoryStockUpdateData(kit=kit, stock=after_quantity)
            )
            transactions.append(
                InventoryTransactionCreateData(
                    product_id=product_id,
                    transaction_type=(
                        InventoryTransactionType.ORDER_CANCELLATION_RESTORE
                    ),
                    change_quantity=change_quantity,
                    before_quantity=before_quantity,
                    after_quantity=after_quantity,
                    source_type=InventorySourceType.ORDER,
                    source_id=order_id,
                    operator_id=user_id,
                    reason=INVENTORY_ORDER_RESTORE_REASON,
                    idempotency_key=(
                        INVENTORY_ORDER_RESTORE_IDEMPOTENCY_KEY.format(
                            order_id=order_id,
                            product_id=product_id,
                        )
                    ),
                )
            )

        await self.inventory_repository.bulk_update_stocks(
            updates=stock_updates,
            using_db=using_db,
        )
        await self.inventory_repository.bulk_create_transactions(
            transactions=transactions,
            using_db=using_db,
        )

    async def mark_order_paid(
        self,
        order_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> Order:
        """由 ADMIN+ 执行 ``pending → paid``；角色权限由 API 依赖保证。"""

        return await self._transition_order(
            order_id,
            operator_id=operator_id,
            visible_user_id=None,
            operation=ORDER_OPERATION_MARK_PAID,
            required_status=OrderStatus.PENDING,
            target_status=OrderStatus.PAID,
            audit_action=ORDER_AUDIT_ACTION_MARK_PAID,
            ip_address=ip_address,
        )

    async def complete_order(
        self,
        order_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> Order:
        """由 ADMIN+ 执行 ``paid → completed``；角色权限由 API 依赖保证。"""

        return await self._transition_order(
            order_id,
            operator_id=operator_id,
            visible_user_id=None,
            operation=ORDER_OPERATION_COMPLETE,
            required_status=OrderStatus.PAID,
            target_status=OrderStatus.COMPLETED,
            audit_action=ORDER_AUDIT_ACTION_COMPLETE,
            ip_address=ip_address,
        )

    async def _transition_order(
        self,
        order_id: int,
        *,
        operator_id: int,
        visible_user_id: int | None,
        operation: str,
        required_status: OrderStatus,
        target_status: OrderStatus,
        audit_action: str,
        ip_address: str,
    ) -> Order:
        """在行锁保护下执行一条由公开用例固定的状态变迁。"""

        if (
            operation in (ORDER_OPERATION_MARK_PAID, ORDER_OPERATION_COMPLETE)
            and self.payment_repository is None
        ):
            raise RuntimeError(
                "PaymentRepository is required for financial order transitions"
            )

        financial_target_user_id: int | None = None
        if operation == ORDER_OPERATION_MARK_PAID:
            visible_order = await self.order_repository.get_order_by_id(order_id)
            if visible_order is None:
                raise OrderNotFound()
            financial_target_user_id = visible_order.user_id

        audit_description = json.dumps(
            {
                "before_status": ORDER_STATUS_VALUES[required_status],
                "after_status": ORDER_STATUS_VALUES[target_status],
            },
            separators=(",", ":"),
        )
        async with in_transaction() as connection:
            if financial_target_user_id is not None:
                financial_target = await self.user_repository.get_for_update(
                    financial_target_user_id,
                    using_db=connection,
                )
                if (
                    financial_target is None
                    or financial_target.status == UserStatus.DELETED
                ):
                    raise UserDeleted()
                if financial_target.role != UserRole.USER:
                    raise PermissionException(
                        message="Manual payment can target customers only"
                    )
                if financial_target.status == UserStatus.DISABLED:
                    raise UserDisabled()
                if financial_target.status != UserStatus.NORMAL:
                    raise PermissionException(
                        message="Customer account status does not allow manual payment"
                    )

            order = await self.order_repository.get_order_for_update(
                order_id,
                user_id=visible_user_id,
                using_db=connection,
            )
            if order is None:
                raise OrderNotFound()
            if (
                financial_target_user_id is not None
                and order.user_id != financial_target_user_id
            ):
                raise OrderNotFound()

            current_status = OrderStatus(order.status)
            if current_status != required_status:
                raise OrderStatusConflict(
                    operation=operation,
                    current_status=current_status,
                    required_status=required_status,
                )

            if self.payment_repository is not None:
                settlement = (
                    await self.payment_repository.get_settlement_by_order_id(
                        order.id,
                        using_db=connection,
                    )
                )
                if operation == ORDER_OPERATION_MARK_PAID:
                    if settlement is not None:
                        raise PaymentSettlementConflict()
                    payment = await self.payment_repository.create_payment(
                        data=PaymentCreateData(
                            payment_no=self.payment_number_generator(),
                            user_id=order.user_id,
                            purpose=PaymentPurpose.ORDER,
                            method=PaymentMethod.MANUAL,
                            amount=order.total_amount,
                            order_id=order.id,
                            recharge_order_id=None,
                            idempotency_key=(
                                MANUAL_PAYMENT_IDEMPOTENCY_KEY.format(
                                    order_id=order.id
                                )
                            ),
                        ),
                        using_db=connection,
                    )
                    await self.payment_repository.update_payment_status(
                        payment,
                        status=PaymentStatus.SUCCEEDED,
                        provider_transaction_id=None,
                        succeeded_at=datetime.now(timezone.utc),
                        using_db=connection,
                    )
                    await self.payment_repository.create_settlement(
                        payment_id=payment.id,
                        order_id=order.id,
                        amount=order.total_amount,
                        using_db=connection,
                    )
                elif operation == ORDER_OPERATION_COMPLETE and settlement is not None:
                    refund = (
                        await self.payment_repository.get_refund_by_settlement_id(
                            settlement.id,
                            using_db=connection,
                        )
                    )
                    if refund is not None and refund.status in (
                        RefundStatus.PENDING,
                        RefundStatus.SUCCEEDED,
                    ):
                        raise RefundStatusConflict()

            await self.order_repository.update_status(
                order,
                status=target_status,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action=audit_action,
                target_type=ORDER_AUDIT_TARGET_TYPE,
                target_id=order.id,
                ip_address=ip_address,
                description=audit_description,
                using_db=connection,
            )
            loaded = await self.order_repository.get_order_by_id(
                order.id,
                using_db=connection,
            )
            if loaded is None:
                raise RuntimeError("Updated order not found")

        logger.info(
            "Order status changed: operator_id=%d order_id=%d operation=%s",
            operator_id,
            loaded.id,
            operation,
        )
        return loaded

    async def _build_order_snapshots(
        self,
        items: list[OrderItemInput],
    ) -> tuple[list[OrderItemCreateData], Decimal, list[OrderItemInput]]:
        """批量读取权威聚合，并按请求顺序构造候选快照。"""

        products = await self.product_repository.get_products_by_ids(
            {item.product_id for item in items}
        )
        options = await self.product_repository.get_options_by_ids(
            {
                item.experience_option_id
                for item in items
                if item.experience_option_id is not None
            }
        )
        kits = await self.product_repository.get_kits_by_product_ids(
            {item.product_id for item in items}
        )
        products_by_id = {product.id: product for product in products}
        options_by_id = {option.id: option for option in options}
        kits_by_product_id = {kit.product_id: kit for kit in kits}

        snapshots: list[OrderItemCreateData] = []
        kit_items: list[OrderItemInput] = []
        total_amount = Decimal("0.00")
        for item in items:
            product = (
                products_by_id[item.product_id]
                if item.product_id in products_by_id
                else None
            )
            if (
                product is None
                or product.is_deleted
                or product.status is not ProductStatus.ONLINE
            ):
                raise OrderProductUnavailable(product_id=item.product_id)

            if product.product_type is ProductType.EXPERIENCE:
                option = (
                    options_by_id[item.experience_option_id]
                    if item.experience_option_id is not None
                    and item.experience_option_id in options_by_id
                    else None
                )
                if (
                    option is None
                    or option.is_deleted
                    or option.product_id != product.id
                ):
                    raise OrderOptionUnavailable(
                        product_id=item.product_id,
                        experience_option_id=item.experience_option_id,
                    )
                unit_price = option.price
                experience_option_id = option.id
                option_duration_minutes = option.duration
                option_participants = option.participants
                option_day_type = option.day_type
            elif product.product_type is ProductType.KIT:
                if item.experience_option_id is not None:
                    raise OrderOptionUnavailable(
                        product_id=item.product_id,
                        experience_option_id=item.experience_option_id,
                    )
                kit = (
                    kits_by_product_id[product.id]
                    if product.id in kits_by_product_id
                    else None
                )
                if kit is None:
                    raise OrderProductUnavailable(product_id=item.product_id)
                unit_price = kit.price
                experience_option_id = None
                option_duration_minutes = None
                option_participants = None
                option_day_type = None
                kit_items.append(item)
            else:
                raise OrderOptionUnavailable(
                    product_id=item.product_id,
                    experience_option_id=item.experience_option_id,
                )

            subtotal = unit_price * item.quantity
            snapshots.append(
                OrderItemCreateData(
                    product_id=product.id,
                    experience_option_id=experience_option_id,
                    option_duration_minutes=option_duration_minutes,
                    option_participants=option_participants,
                    option_day_type=option_day_type,
                    product_name=product.name,
                    product_price=unit_price,
                    quantity=item.quantity,
                    subtotal=subtotal,
                )
            )
            total_amount += subtotal

        return snapshots, total_amount, kit_items

    async def list_user_orders(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
        status: OrderStatusValue | None = None,
    ) -> Page[Order]:
        """查询当前用户可见的订单摘要。"""

        return await self.order_repository.list_user_orders(
            user_id=user_id,
            page=page,
            page_size=page_size,
            status=ORDER_STATUS_BY_VALUE[status] if status is not None else None,
        )

    async def get_user_order_detail(
        self,
        order_id: int,
        *,
        user_id: int,
    ) -> Order:
        """查询用户订单；不存在与他人订单统一隐藏为 OrderNotFound。"""

        order = await self.order_repository.get_order_detail(
            order_id,
            user_id=user_id,
        )
        if order is None:
            raise OrderNotFound()
        return order

    async def list_admin_orders(
        self,
        *,
        page: int,
        page_size: int,
        status: OrderStatusValue | None = None,
        order_no: str | None = None,
        product_name: str | None = None,
        user_id: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> Page[Order]:
        """查询管理端订单摘要并原样转发已校验筛选条件。"""

        return await self.order_repository.list_admin_orders(
            page=page,
            page_size=page_size,
            status=ORDER_STATUS_BY_VALUE[status] if status is not None else None,
            order_no=order_no,
            product_name=product_name,
            user_id=user_id,
            created_from=created_from,
            created_to=created_to,
        )

    async def get_admin_order_detail(self, order_id: int) -> Order:
        """查询任意管理端订单详情。"""

        order = await self.order_repository.get_order_detail(order_id)
        if order is None:
            raise OrderNotFound()
        return order

    async def list_order_audit_logs(
        self,
        order_id: int,
        *,
        page: int,
        page_size: int,
    ) -> Page[AuditLog]:
        """确认 Order 存在后委托共享审计服务分页查询。"""

        order = await self.order_repository.get_order_by_id(order_id)
        if order is None:
            raise OrderNotFound()
        return await self.audit_log_service.list_logs(
            target_type=ORDER_AUDIT_TARGET_TYPE,
            target_id=order_id,
            page=page,
            page_size=page_size,
        )
