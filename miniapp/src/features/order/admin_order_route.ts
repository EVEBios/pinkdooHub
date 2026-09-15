export { ADMIN_ORDER_LIST_PATH } from '@/auth/login_route'
export { isAdminRole } from '@/auth/role'

export interface AdminOrderDetailRoute {
  readonly orderId: number
}

export function parseAdminOrderDetailRoute(
  params: Readonly<Record<string, string | undefined>>,
): AdminOrderDetailRoute | undefined {
  if (!params.id || !/^[1-9]\d*$/.test(params.id)) {
    return undefined
  }
  const orderId = Number(params.id)
  return Number.isSafeInteger(orderId) ? { orderId } : undefined
}

export function buildAdminOrderDetailUrl(orderId: number): string {
  if (!Number.isSafeInteger(orderId) || orderId <= 0) {
    throw new Error('Order ID 必须是正安全整数')
  }
  return `/admin/pages/order-detail/index?id=${orderId}`
}
