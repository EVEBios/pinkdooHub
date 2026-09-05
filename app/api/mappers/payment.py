"""Payment、Settlement 与 Refund 的同步纯映射。"""

from decimal import Decimal

from app.api.mappers.order import map_order_status_value
from app.api.mappers.order import map_admin_order_detail
from app.common.enums.order import OrderStatus
from app.models.order import Order
from app.models.payment import Payment, Refund
from app.schemas.wallet_response import (
    AssistedWalletOrderOut,
    OrderFinancialOut,
    PaymentOut,
    RefundOut,
    WalletPaymentOut,
)


def map_assisted_wallet_order(
    order: Order,
    *,
    payment: Payment,
    post_payment_balance: Decimal,
) -> AssistedWalletOrderOut:
    return AssistedWalletOrderOut(
        order=map_admin_order_detail(order),
        payment=map_payment(payment),
        post_payment_balance=post_payment_balance,
    )


def map_payment(payment: Payment) -> PaymentOut:
    return PaymentOut.model_validate(
        {
            "id": payment.id,
            "payment_no": payment.payment_no,
            "order_id": payment.order_id,
            "recharge_order_id": payment.recharge_order_id,
            "purpose": payment.purpose,
            "method": payment.method,
            "amount": payment.amount,
            "status": payment.status,
            "created_at": payment.created_at,
            "updated_at": payment.updated_at,
            "succeeded_at": payment.succeeded_at,
        }
    )


def map_refund(
    refund: Refund,
    *,
    payment: Payment,
    inventory_restored: bool,
) -> RefundOut:
    return RefundOut.model_validate(
        {
            "id": refund.id,
            "refund_no": refund.refund_no,
            "order_id": refund.order_id,
            "method": payment.method,
            "amount": refund.amount,
            "status": refund.status,
            "reason": refund.reason,
            "operator_id": refund.operator_id,
            "inventory_restored": inventory_restored,
            "created_at": refund.created_at,
            "updated_at": refund.updated_at,
            "succeeded_at": refund.succeeded_at,
        }
    )


def map_order_financial(
    order: Order,
    *,
    payment: Payment | None,
    refund: Refund | None,
    inventory_restored: bool,
) -> OrderFinancialOut:
    return OrderFinancialOut(
        order_id=order.id,
        order_status=map_order_status_value(order.status),
        payment=map_payment(payment) if payment is not None else None,
        refund=(
            map_refund(
                refund,
                payment=payment,
                inventory_restored=inventory_restored,
            )
            if refund is not None and payment is not None
            else None
        ),
    )


def map_wallet_payment(
    order: Order,
    *,
    payment: Payment,
    post_payment_balance: Decimal,
) -> WalletPaymentOut:
    return WalletPaymentOut(
        order_id=order.id,
        order_no=order.order_no,
        order_status=map_order_status_value(order.status),
        payment=map_payment(payment),
        post_payment_balance=post_payment_balance,
    )
