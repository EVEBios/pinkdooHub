"""Recharge、Payment、Settlement 与 Refund 的数据访问。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q
from tortoise.functions import Sum

from app.common.constants.wallet import ORDER_REFUND_WINDOW_DAYS
from app.common.enums.order import OrderStatus
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    RechargeOrderStatus,
    RefundStatus,
)
from app.models.payment import Payment, PaymentSettlement, RechargeOrder, Refund


@dataclass(frozen=True, slots=True)
class RechargeOrderCreateData:
    recharge_no: str
    user_id: int
    wallet_account_id: int
    amount: Decimal
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class PaymentCreateData:
    payment_no: str
    user_id: int
    purpose: PaymentPurpose
    method: PaymentMethod
    amount: Decimal
    order_id: int | None
    recharge_order_id: int | None
    idempotency_key: str
    status: PaymentStatus = PaymentStatus.PENDING
    provider_transaction_id: str | None = None
    succeeded_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PaymentSettlementCreateData:
    payment_id: int
    order_id: int
    amount: Decimal


@dataclass(frozen=True, slots=True)
class RefundCreateData:
    refund_no: str
    settlement_id: int
    order_id: int
    operator_id: int
    amount: Decimal
    inventory_restored: bool
    reason: str
    idempotency_key: str


class PaymentRepository:
    """资金单据持久化；不判断跨字段、状态机或全额退款规则。"""

    async def has_in_flight_for_user(
        self,
        user_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> bool:
        """判断用户是否仍有任一处理中资金单据。"""

        if await (
            Payment.filter(user_id=user_id, status=PaymentStatus.PENDING)
            .using_db(using_db)
            .exists()
        ):
            return True
        if await (
            RechargeOrder.filter(
                user_id=user_id,
                status=RechargeOrderStatus.PENDING,
            )
            .using_db(using_db)
            .exists()
        ):
            return True
        return await (
            Refund.filter(
                order__user_id=user_id,
                status=RefundStatus.PENDING,
            )
            .using_db(using_db)
            .exists()
        )

    async def get_refundable_wallet_exposure(
        self,
        user_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> Decimal:
        """计算尚需为全额原路退回保留的钱包支付金额。"""

        refundable_since = datetime.now(timezone.utc) - timedelta(
            days=ORDER_REFUND_WINDOW_DAYS
        )
        rows = await (
            PaymentSettlement.filter(
                payment__user_id=user_id,
                payment__method=PaymentMethod.WALLET,
                payment__status=PaymentStatus.SUCCEEDED,
            )
            .filter(
                Q(refund__isnull=True)
                | Q(
                    refund__status__in=(
                        RefundStatus.PENDING,
                        RefundStatus.FAILED,
                    )
                )
            )
            .filter(
                Q(order__status=OrderStatus.PAID.value)
                | Q(
                    order__status=OrderStatus.COMPLETED.value,
                    order__updated_at__gte=refundable_since,
                )
            )
            .using_db(using_db)
            .annotate(total=Sum("amount"))
            .values_list("total", flat=True)
        )
        if not rows or rows[0] is None:
            return Decimal("0.00")
        return Decimal(rows[0])

    async def create_recharge_order(
        self,
        *,
        data: RechargeOrderCreateData,
        using_db: BaseDBAsyncClient,
    ) -> RechargeOrder:
        return await RechargeOrder.create(
            recharge_no=data.recharge_no,
            user_id=data.user_id,
            wallet_account_id=data.wallet_account_id,
            amount=data.amount,
            idempotency_key=data.idempotency_key,
            using_db=using_db,
        )

    async def get_recharge_order_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> RechargeOrder | None:
        query = RechargeOrder.filter(idempotency_key=idempotency_key)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_recharge_order_by_id(
        self,
        recharge_order_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> RechargeOrder | None:
        query = RechargeOrder.filter(id=recharge_order_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_recharge_order_for_update(
        self,
        recharge_order_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> RechargeOrder | None:
        return await (
            RechargeOrder.filter(id=recharge_order_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def update_recharge_order_status(
        self,
        recharge_order: RechargeOrder,
        *,
        status: RechargeOrderStatus,
        succeeded_at: datetime | None,
        using_db: BaseDBAsyncClient,
    ) -> RechargeOrder:
        recharge_order.status = status
        recharge_order.succeeded_at = succeeded_at
        await recharge_order.save(
            using_db=using_db,
            update_fields=["status", "succeeded_at", "updated_at"],
        )
        return recharge_order

    async def create_payment(
        self,
        *,
        data: PaymentCreateData,
        using_db: BaseDBAsyncClient,
    ) -> Payment:
        return await Payment.create(
            payment_no=data.payment_no,
            user_id=data.user_id,
            purpose=data.purpose,
            method=data.method,
            amount=data.amount,
            order_id=data.order_id,
            recharge_order_id=data.recharge_order_id,
            idempotency_key=data.idempotency_key,
            status=data.status,
            provider_transaction_id=data.provider_transaction_id,
            succeeded_at=data.succeeded_at,
            using_db=using_db,
        )

    async def bulk_create_payments(
        self,
        *,
        data: list[PaymentCreateData],
        using_db: BaseDBAsyncClient,
    ) -> None:
        """批量创建已由调用方验证的 Payment 事实。"""

        if not data:
            return
        await Payment.bulk_create(
            [
                Payment(
                    payment_no=item.payment_no,
                    user_id=item.user_id,
                    purpose=item.purpose,
                    method=item.method,
                    amount=item.amount,
                    order_id=item.order_id,
                    recharge_order_id=item.recharge_order_id,
                    idempotency_key=item.idempotency_key,
                    status=item.status,
                    provider_transaction_id=item.provider_transaction_id,
                    succeeded_at=item.succeeded_at,
                )
                for item in data
            ],
            using_db=using_db,
        )

    async def get_payment_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Payment | None:
        query = Payment.filter(idempotency_key=idempotency_key)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def payment_number_exists(self, payment_no: str) -> bool:
        """判断支付号是否已持久化，用于冲突重试归因。"""

        return await Payment.filter(payment_no=payment_no).exists()

    async def get_existing_payment_numbers(
        self,
        payment_numbers: set[str],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> set[str]:
        """批量返回已占用的支付号。"""

        if not payment_numbers:
            return set()
        query = Payment.filter(payment_no__in=payment_numbers)
        if using_db is not None:
            query = query.using_db(using_db)
        rows = await query.values_list("payment_no", flat=True)
        return set(rows)

    async def list_payments_by_order_ids(
        self,
        order_ids: set[int],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[Payment]:
        """批量读取订单关联的全部 Payment 尝试。"""

        if not order_ids:
            return []
        query = Payment.filter(order_id__in=order_ids).order_by("order_id", "id")
        if using_db is not None:
            query = query.using_db(using_db)
        return list(await query)

    async def list_payments_by_idempotency_keys(
        self,
        idempotency_keys: set[str],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[Payment]:
        """批量读取内部幂等键关联的 Payment。"""

        if not idempotency_keys:
            return []
        query = Payment.filter(idempotency_key__in=idempotency_keys).order_by("id")
        if using_db is not None:
            query = query.using_db(using_db)
        return list(await query)

    async def get_payment_by_id(
        self,
        payment_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Payment | None:
        query = Payment.filter(id=payment_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_payment_by_provider_transaction_id(
        self,
        provider_transaction_id: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Payment | None:
        query = Payment.filter(provider_transaction_id=provider_transaction_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_payment_by_order_id(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Payment | None:
        """按稳定倒序读取订单最近一次支付尝试。"""

        query = Payment.filter(order_id=order_id).order_by("-created_at", "-id")
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_payment_for_update(
        self,
        payment_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> Payment | None:
        return await (
            Payment.filter(id=payment_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def get_payment_by_order_id_for_update(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> Payment | None:
        """锁定订单最近一次支付尝试。"""

        return await (
            Payment.filter(order_id=order_id)
            .using_db(using_db)
            .order_by("-created_at", "-id")
            .select_for_update()
            .first()
        )

    async def update_payment_status(
        self,
        payment: Payment,
        *,
        status: PaymentStatus,
        provider_transaction_id: str | None,
        succeeded_at: datetime | None,
        using_db: BaseDBAsyncClient,
    ) -> Payment:
        payment.status = status
        payment.provider_transaction_id = provider_transaction_id
        payment.succeeded_at = succeeded_at
        await payment.save(
            using_db=using_db,
            update_fields=[
                "status",
                "provider_transaction_id",
                "succeeded_at",
                "updated_at",
            ],
        )
        return payment

    async def create_settlement(
        self,
        *,
        payment_id: int,
        order_id: int,
        amount: Decimal,
        using_db: BaseDBAsyncClient,
    ) -> PaymentSettlement:
        return await PaymentSettlement.create(
            payment_id=payment_id,
            order_id=order_id,
            amount=amount,
            using_db=using_db,
        )

    async def bulk_create_settlements(
        self,
        *,
        data: list[PaymentSettlementCreateData],
        using_db: BaseDBAsyncClient,
    ) -> None:
        """批量创建已验证的一次性成功结算事实。"""

        if not data:
            return
        await PaymentSettlement.bulk_create(
            [
                PaymentSettlement(
                    payment_id=item.payment_id,
                    order_id=item.order_id,
                    amount=item.amount,
                )
                for item in data
            ],
            using_db=using_db,
        )

    async def get_settlement_by_order_id(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> PaymentSettlement | None:
        query = PaymentSettlement.filter(order_id=order_id).select_related(
            "payment"
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_settlement_by_payment_id(
        self,
        payment_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> PaymentSettlement | None:
        query = PaymentSettlement.filter(payment_id=payment_id).select_related(
            "order"
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def list_settlements_by_order_ids(
        self,
        order_ids: set[int],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[PaymentSettlement]:
        """批量读取 Order 唯一结算事实。"""

        if not order_ids:
            return []
        query = PaymentSettlement.filter(order_id__in=order_ids).order_by(
            "order_id"
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return list(await query)

    async def get_settlement_for_update(
        self,
        settlement_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> PaymentSettlement | None:
        return await (
            PaymentSettlement.filter(id=settlement_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def get_settlement_by_order_id_for_update(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> PaymentSettlement | None:
        """按 Order 唯一键锁定成功结算。"""

        return await (
            PaymentSettlement.filter(order_id=order_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def create_refund(
        self,
        *,
        data: RefundCreateData,
        using_db: BaseDBAsyncClient,
    ) -> Refund:
        return await Refund.create(
            refund_no=data.refund_no,
            settlement_id=data.settlement_id,
            order_id=data.order_id,
            operator_id=data.operator_id,
            amount=data.amount,
            inventory_restored=data.inventory_restored,
            reason=data.reason,
            idempotency_key=data.idempotency_key,
            using_db=using_db,
        )

    async def get_refund_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Refund | None:
        query = Refund.filter(idempotency_key=idempotency_key)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_refund_by_settlement_id(
        self,
        settlement_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Refund | None:
        query = Refund.filter(settlement_id=settlement_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_refund_by_order_id(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Refund | None:
        query = Refund.filter(order_id=order_id).order_by("-created_at", "-id")
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_refund_for_update(
        self,
        refund_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> Refund | None:
        return await (
            Refund.filter(id=refund_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def get_refund_by_order_id_for_update(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> Refund | None:
        """按 Order 唯一键锁定退款记录。"""

        return await (
            Refund.filter(order_id=order_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def update_refund_status(
        self,
        refund: Refund,
        *,
        status: RefundStatus,
        provider_refund_id: str | None,
        succeeded_at: datetime | None,
        using_db: BaseDBAsyncClient,
    ) -> Refund:
        refund.status = status
        refund.provider_refund_id = provider_refund_id
        refund.succeeded_at = succeeded_at
        await refund.save(
            using_db=using_db,
            update_fields=[
                "status",
                "provider_refund_id",
                "succeeded_at",
                "updated_at",
            ],
        )
        return refund
