"""站内提醒的稳定展示与批次边界。"""

from app.common.enums.attention import AttentionEventType

ATTENTION_READ_BATCH_LIMIT = 100
ATTENTION_EVENT_LABELS = {
    AttentionEventType.ORDER_ASSISTED_WALLET_PAID: "门店代下单并扣款",
    AttentionEventType.ORDER_WALLET_REFUNDED: "退款已退回余额",
    AttentionEventType.ORDER_MANUAL_REFUNDED: "门店已登记线下退款",
    AttentionEventType.WALLET_ADJUSTED: "门店已调整余额",
    AttentionEventType.ORDER_MANUAL_PAID: "门店已确认收款",
    AttentionEventType.ORDER_WALLET_PAID: "余额支付成功",
    AttentionEventType.ORDER_COMPLETED: "订单已完成",
    AttentionEventType.SESSION_PAYMENT_TIMEOUT: "付款占台已超时",
    AttentionEventType.SESSION_TIME_EXPIRED: "本次桌台体验已结束",
    AttentionEventType.SESSION_ADMIN_RELEASED: "门店已释放本次桌台",
    AttentionEventType.RESERVATION_CONFIRMED: "门店已确认预约",
    AttentionEventType.RESERVATION_REJECTED: "门店已拒绝预约：当前时段无空位",
    AttentionEventType.RESERVATION_STORE_CLOSED: "门店店休，本次预约已取消",
    AttentionEventType.RESERVATION_CUSTOMER_CANCELLED: "顾客取消了已确认预约，请调整安排",
}
