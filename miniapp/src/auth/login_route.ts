export const ORDER_CONFIRM_PATH = '/pages/order-confirm/index'
export const ORDER_LIST_PATH = '/pages/orders/index'
export const ADMIN_ORDER_LIST_PATH = '/admin/pages/orders/index'
export const ADMIN_PRODUCT_LIST_PATH = '/admin/pages/products/index'
export const ADMIN_USER_LIST_PATH = '/admin/pages/users/index'
export const ADMIN_INVENTORY_LIST_PATH = '/admin/pages/inventory-transactions/index'
export const REGISTER_PATH = '/pages/register/index'

export type LoginRedirect =
  | typeof ORDER_CONFIRM_PATH
  | typeof ORDER_LIST_PATH
  | typeof ADMIN_ORDER_LIST_PATH
  | typeof ADMIN_PRODUCT_LIST_PATH
  | typeof ADMIN_USER_LIST_PATH
  | typeof ADMIN_INVENTORY_LIST_PATH

const ALLOWED_REDIRECTS = new Set<LoginRedirect>([
  ORDER_CONFIRM_PATH,
  ORDER_LIST_PATH,
  ADMIN_ORDER_LIST_PATH,
  ADMIN_PRODUCT_LIST_PATH,
  ADMIN_USER_LIST_PATH,
  ADMIN_INVENTORY_LIST_PATH,
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
  return ALLOWED_REDIRECTS.has(decoded as LoginRedirect)
    ? decoded as LoginRedirect
    : undefined
}
