import { ORDER_LIST_PATH, type OrderListRedirect } from '@/auth/login_route'
import type { OrderStatusFilter } from './use_order_list'

export interface OrderDetailRoute {
  readonly orderId: number
}

export function parseOrderDetailRoute(
  params: Readonly<Record<string, string | undefined>>,
): OrderDetailRoute | undefined {
  if (!params.id || !/^[1-9]\d*$/.test(params.id)) {
    return undefined
  }
  const orderId = Number(params.id)
  return Number.isSafeInteger(orderId) ? { orderId } : undefined
}

export function buildOrderDetailUrl(orderId: number): string {
  if (!Number.isSafeInteger(orderId) || orderId <= 0) {
    throw new Error('Order ID 必须是正安全整数')
  }
  return `/pages/order-detail/index?id=${orderId}`
}

export function parseOrderStatusFilter(value: unknown): OrderStatusFilter {
  return value === 'pending' || value === 'paid' || value === 'completed' || value === 'cancelled'
    ? value
    : 'all'
}

export function buildOrderListUrl(status: OrderStatusFilter = 'all'): typeof ORDER_LIST_PATH | OrderListRedirect {
  return status === 'all' ? ORDER_LIST_PATH : `${ORDER_LIST_PATH}?status=${status}`
}
