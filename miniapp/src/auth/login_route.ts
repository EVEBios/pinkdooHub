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
export const REGISTER_PATH = '/pages/register/index'
export const MEMBER_PATH = '/pages/member/index'
export const WALLET_RECHARGE_PATH = '/pages/wallet-recharge/index'
export const WALLET_TRANSACTION_LIST_PATH = '/pages/wallet-transactions/index'

export type ReservationCreateRedirect = `${typeof RESERVATION_CREATE_PATH}?product_id=${number}&option_id=${number}`

export type LoginRedirect =
  | typeof ORDER_CONFIRM_PATH
  | typeof ORDER_LIST_PATH
  | typeof RESERVATION_LIST_PATH
  | ReservationCreateRedirect
  | typeof ADMIN_ORDER_LIST_PATH
  | typeof ADMIN_RESERVATION_LIST_PATH
  | typeof ADMIN_STORE_CLOSURE_LIST_PATH
  | typeof ADMIN_PRODUCT_LIST_PATH
  | typeof ADMIN_USER_LIST_PATH
  | typeof ADMIN_INVENTORY_LIST_PATH
  | typeof MEMBER_PATH
  | typeof WALLET_RECHARGE_PATH
  | typeof WALLET_TRANSACTION_LIST_PATH

const ALLOWED_REDIRECTS = new Set<LoginRedirect>([
  ORDER_CONFIRM_PATH,
  ORDER_LIST_PATH,
  RESERVATION_LIST_PATH,
  ADMIN_ORDER_LIST_PATH,
  ADMIN_RESERVATION_LIST_PATH,
  ADMIN_STORE_CLOSURE_LIST_PATH,
  ADMIN_PRODUCT_LIST_PATH,
  ADMIN_USER_LIST_PATH,
  ADMIN_INVENTORY_LIST_PATH,
  MEMBER_PATH,
  WALLET_RECHARGE_PATH,
  WALLET_TRANSACTION_LIST_PATH,
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
    : undefined
}

function isReservationCreateRedirect(value: string): boolean {
  const match = /^\/pages\/reservation-create\/index\?product_id=([1-9]\d*)&option_id=([1-9]\d*)$/.exec(value)
  if (!match) return false
  return match.slice(1).every((part) => Number.isSafeInteger(Number(part)))
}
