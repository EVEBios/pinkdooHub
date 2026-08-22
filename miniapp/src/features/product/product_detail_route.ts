import type { ProductType } from '@/api/endpoints/products'

export interface ProductDetailRoute {
  productId: number
  productType: ProductType
}

export function parseProductDetailRoute(
  params: Readonly<Record<string, string | undefined>>,
): ProductDetailRoute | undefined {
  if (!params.id || !/^[1-9]\d*$/.test(params.id)) {
    return undefined
  }
  const productId = Number(params.id)
  if (!Number.isSafeInteger(productId)) {
    return undefined
  }
  if (params.type !== 'experience' && params.type !== 'kit') {
    return undefined
  }
  return { productId, productType: params.type }
}

export function buildProductDetailUrl(productId: number, productType: ProductType): string {
  if (!Number.isSafeInteger(productId) || productId <= 0) {
    throw new Error('Product ID 必须是正安全整数')
  }
  return `/pages/product-detail/index?id=${productId}&type=${productType}`
}
