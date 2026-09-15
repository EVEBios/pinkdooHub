import type { AdminProductRouteType } from '@/features/product'

export const ADMIN_PRODUCT_AUDIT_PATH = '/admin/pages/product-audit/index'

export interface ProductAuditRoute {
  readonly productId: number
  readonly productType: AdminProductRouteType
}

export function buildProductAuditUrl(
  productId: number,
  productType: AdminProductRouteType,
): string {
  if (!Number.isSafeInteger(productId) || productId <= 0) {
    throw new Error('Product ID 必须是正安全整数')
  }
  return `${ADMIN_PRODUCT_AUDIT_PATH}?id=${productId}&type=${productType}`
}

export function parseProductAuditRoute(
  params: Readonly<Record<string, string | undefined>>,
): ProductAuditRoute | undefined {
  if (!params.id || !/^[1-9]\d*$/.test(params.id) ||
    (params.type !== 'experience' && params.type !== 'kit')) return undefined
  const productId = Number(params.id)
  return Number.isSafeInteger(productId)
    ? { productId, productType: params.type }
    : undefined
}
