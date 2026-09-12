export { ADMIN_INVENTORY_LIST_PATH } from '@/auth/login_route'

export const ADMIN_KIT_INVENTORY_PATH = '/admin/pages/product-inventory/index'

export interface KitInventoryRoute {
  readonly productId: number
}

export function parseKitInventoryRoute(
  params: Readonly<Record<string, string | undefined>>,
): KitInventoryRoute | undefined {
  if (!params.id || !/^[1-9]\d*$/.test(params.id)) return undefined
  const productId = Number(params.id)
  return Number.isSafeInteger(productId) ? { productId } : undefined
}

export function buildKitInventoryUrl(productId: number): string {
  if (!Number.isSafeInteger(productId) || productId <= 0) {
    throw new Error('Product ID 必须是正安全整数')
  }
  return `${ADMIN_KIT_INVENTORY_PATH}?id=${productId}`
}
