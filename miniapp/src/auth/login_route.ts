import { isAdminRole } from './role'

export const MALL_PATH = '/pages/index/index'
export const ADMIN_WORKBENCH_PATH = '/admin/pages/workbench/index'
export const ORDER_CONFIRM_PATH = '/pages/order-confirm/index'
export const ORDER_LIST_PATH = '/pages/orders/index'
export const RESERVATION_CREATE_PATH = '/pages/reservation-create/index'
export const RESERVATION_LIST_PATH = '/pages/reservations/index'
export const ADMIN_ORDER_LIST_PATH = '/admin/pages/orders/index'
export const ADMIN_RESERVATION_LIST_PATH = '/admin/pages/reservations/index'
export const ADMIN_STORE_CLOSURE_LIST_PATH = '/admin/pages/store-closures/index'
export const ADMIN_PRODUCT_LIST_PATH = '/admin/pages/products/index'
export const ADMIN_USER_LIST_PATH = '/admin/pages/users/index'
export const ADMIN_INVENTORY_LIST_PATH = '/admin/pages/inventory-transactions/index'
export const ADMIN_TABLES_PATH = '/admin/pages/tables/index'
export const TABLE_ENTRY_PATH = '/pages/table-entry/index'
export const REGISTER_PATH = '/pages/register/index'
export const MEMBER_PATH = '/pages/member/index'
export const WALLET_RECHARGE_PATH = '/pages/wallet-recharge/index'
export const WALLET_TRANSACTION_LIST_PATH = '/pages/wallet-transactions/index'

export type ReservationCreateRedirect = `${typeof RESERVATION_CREATE_PATH}?product_id=${number}&option_id=${number}`
export type TableEntryRedirect = `${typeof TABLE_ENTRY_PATH}?token=${string}`

export type LoginRedirect =
  | typeof ADMIN_WORKBENCH_PATH
  | typeof ORDER_CONFIRM_PATH
  | typeof ORDER_LIST_PATH
  | typeof RESERVATION_LIST_PATH
  | ReservationCreateRedirect
  | TableEntryRedirect
  | typeof ADMIN_ORDER_LIST_PATH
  | typeof ADMIN_RESERVATION_LIST_PATH
  | typeof ADMIN_STORE_CLOSURE_LIST_PATH
  | typeof ADMIN_PRODUCT_LIST_PATH
  | typeof ADMIN_USER_LIST_PATH
  | typeof ADMIN_INVENTORY_LIST_PATH
  | typeof ADMIN_TABLES_PATH
  | typeof MEMBER_PATH
  | typeof WALLET_RECHARGE_PATH
  | typeof WALLET_TRANSACTION_LIST_PATH

const ALLOWED_REDIRECTS = new Set<LoginRedirect>([
  ADMIN_WORKBENCH_PATH,
  ORDER_CONFIRM_PATH,
  ORDER_LIST_PATH,
  RESERVATION_LIST_PATH,
  ADMIN_ORDER_LIST_PATH,
  ADMIN_RESERVATION_LIST_PATH,
  ADMIN_STORE_CLOSURE_LIST_PATH,
  ADMIN_PRODUCT_LIST_PATH,
  ADMIN_USER_LIST_PATH,
  ADMIN_INVENTORY_LIST_PATH,
  ADMIN_TABLES_PATH,
  MEMBER_PATH,
  WALLET_RECHARGE_PATH,
  WALLET_TRANSACTION_LIST_PATH,
])

const ADMIN_REDIRECTS = new Set<LoginRedirect>([
  ADMIN_WORKBENCH_PATH,
  ADMIN_ORDER_LIST_PATH,
  ADMIN_RESERVATION_LIST_PATH,
  ADMIN_STORE_CLOSURE_LIST_PATH,
  ADMIN_PRODUCT_LIST_PATH,
  ADMIN_USER_LIST_PATH,
  ADMIN_INVENTORY_LIST_PATH,
  ADMIN_TABLES_PATH,
])

export function buildLoginUrl(redirect?: LoginRedirect): string {
  return redirect
    ? `/pages/login/index?redirect=${encodeURIComponent(redirect)}`
    : '/pages/login/index'
}

export function buildRegisterUrl(redirect?: LoginRedirect): string {
  return redirect
    ? `${REGISTER_PATH}?redirect=${encodeURIComponent(redirect)}`
    : REGISTER_PATH
}

export function parseLoginRedirect(value: unknown): LoginRedirect | undefined {
  if (typeof value !== 'string' || value.length === 0) {
    return undefined
  }
  let decoded: string
  try {
    decoded = decodeURIComponent(value)
  } catch {
    return undefined
  }
  if (ALLOWED_REDIRECTS.has(decoded as LoginRedirect)) {
    return decoded as LoginRedirect
  }
  return isReservationCreateRedirect(decoded)
    ? decoded as ReservationCreateRedirect
    : isTableEntryRedirect(decoded)
      ? decoded as TableEntryRedirect
      : undefined
}

/**
 * 登录成功后只保留与当前角色相容的白名单目标，避免角色先落入另一套界面再二次跳转。
 */
export function resolveAuthenticatedLanding(
  role: string | undefined,
  redirect?: LoginRedirect,
): LoginRedirect | typeof MALL_PATH | undefined {
  if (isAdminRole(role)) {
    return redirect && ADMIN_REDIRECTS.has(redirect)
      ? redirect
      : ADMIN_WORKBENCH_PATH
  }
  if (role === 'user') {
    return redirect && !ADMIN_REDIRECTS.has(redirect)
      ? redirect
      : MALL_PATH
  }
  return undefined
}

function isReservationCreateRedirect(value: string): boolean {
  const match = /^\/pages\/reservation-create\/index\?product_id=([1-9]\d*)&option_id=([1-9]\d*)$/.exec(value)
  if (!match) return false
  return match.slice(1).every((part) => Number.isSafeInteger(Number(part)))
}

function isTableEntryRedirect(value: string): boolean {
  return /^\/pages\/table-entry\/index\?token=[A-Za-z0-9]{32}$/.test(value)
}
