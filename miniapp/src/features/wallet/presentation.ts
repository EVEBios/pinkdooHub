import type { PaymentMethod, PaymentStatus, RefundStatus, WalletTransactionType } from '@/api/endpoints/wallet'

const TRANSACTION_LABELS: Readonly<Record<WalletTransactionType, string>> = {
  recharge: '余额充值',
  order_payment: '订单支付',
  admin_adjustment: '人工调账',
  refund: '订单退款',
}

const PAYMENT_METHOD_LABELS: Readonly<Record<PaymentMethod, string>> = {
  wallet: '余额支付',
  wechat: '微信支付',
  manual: '人工登记',
}

const PAYMENT_STATUS_LABELS: Readonly<Record<PaymentStatus, string>> = {
  pending: '处理中',
  succeeded: '已支付',
  failed: '失败',
  closed: '已关闭',
}

const REFUND_STATUS_LABELS: Readonly<Record<RefundStatus, string>> = {
  pending: '退款处理中',
  succeeded: '已退款',
  failed: '退款失败',
}

export function getWalletTransactionLabel(type: WalletTransactionType): string {
  return TRANSACTION_LABELS[type]
}

export function getPaymentMethodLabel(method: PaymentMethod): string {
  return PAYMENT_METHOD_LABELS[method]
}

export function getPaymentStatusLabel(status: PaymentStatus): string {
  return PAYMENT_STATUS_LABELS[status]
}

export function getRefundStatusLabel(status: RefundStatus): string {
  return REFUND_STATUS_LABELS[status]
}
