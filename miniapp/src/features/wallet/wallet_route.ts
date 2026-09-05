export const ADMIN_USER_WALLET_PATH = '/admin/pages/user-wallet/index'
export const ADMIN_WALLET_ORDER_PATH = '/admin/pages/wallet-order/index'

export interface AdminUserWalletRoute {
  readonly userId: number
}

export type AdminWalletOrderRoute = AdminUserWalletRoute

export function parseAdminUserWalletRoute(
  params: Readonly<Record<string, string | undefined>>,
): AdminUserWalletRoute | undefined {
  if (!params.id || !/^[1-9]\d*$/.test(params.id)) return undefined
  const userId = Number(params.id)
  return Number.isSafeInteger(userId) ? { userId } : undefined
}

export function buildAdminUserWalletUrl(userId: number): string {
  if (!Number.isSafeInteger(userId) || userId <= 0) {
    throw new Error('User ID 必须是正安全整数')
  }
  return `${ADMIN_USER_WALLET_PATH}?id=${userId}`
}

export function parseAdminWalletOrderRoute(
  params: Readonly<Record<string, string | undefined>>,
): AdminWalletOrderRoute | undefined {
  return parseAdminUserWalletRoute(params)
}

export function buildAdminWalletOrderUrl(userId: number): string {
  if (!Number.isSafeInteger(userId) || userId <= 0) {
    throw new Error('User ID 必须是正安全整数')
  }
  return `${ADMIN_WALLET_ORDER_PATH}?id=${userId}`
}
