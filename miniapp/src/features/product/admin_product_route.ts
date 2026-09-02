export { ADMIN_PRODUCT_LIST_PATH } from '@/auth/login_route'

export const ADMIN_PRODUCT_CREATE_PATH = '/admin/pages/product-create/index'
export const ADMIN_PRODUCT_EDIT_PATH = '/admin/pages/product-edit/index'
export const ADMIN_PRODUCT_CONFIGURATION_PATH = '/admin/pages/product-configuration/index'
export const ADMIN_PRODUCT_IMAGES_PATH = '/admin/pages/product-images/index'

export type AdminProductRouteType = 'experience' | 'kit'

export interface AdminProductDetailRoute {
  readonly productId: number
  readonly productType: AdminProductRouteType
}

export interface AdminProductCreateRoute {
  readonly productType: AdminProductRouteType
}

export function parseAdminProductDetailRoute(
  params: Readonly<Record<string, string | undefined>>,
): AdminProductDetailRoute | undefined {
  if (!params.id || !/^[1-9]\d*$/.test(params.id) ||
    (params.type !== 'experience' && params.type !== 'kit')) return undefined
  const productId = Number(params.id)
  return Number.isSafeInteger(productId)
    ? { productId, productType: params.type }
    : undefined
}

export function buildAdminProductDetailUrl(
  productId: number,
  productType: AdminProductRouteType,
): string {
  if (!Number.isSafeInteger(productId) || productId <= 0) {
    throw new Error('Product ID 必须是正安全整数')
  }
  return `/admin/pages/product-detail/index?id=${productId}&type=${productType}`
}

export function parseAdminProductCreateRoute(
  params: Readonly<Record<string, string | undefined>>,
): AdminProductCreateRoute | undefined {
  return isAdminProductType(params.type) ? { productType: params.type } : undefined
}

export function buildAdminProductCreateUrl(productType: AdminProductRouteType): string {
  assertAdminProductType(productType)
  return `${ADMIN_PRODUCT_CREATE_PATH}?type=${productType}`
}

export function parseAdminProductEditRoute(
  params: Readonly<Record<string, string | undefined>>,
): AdminProductDetailRoute | undefined {
  return parseAdminProductDetailRoute(params)
}

export function buildAdminProductEditUrl(
  productId: number,
  productType: AdminProductRouteType,
): string {
  if (!Number.isSafeInteger(productId) || productId <= 0) {
    throw new Error('Product ID 必须是正安全整数')
  }
  assertAdminProductType(productType)
  return `${ADMIN_PRODUCT_EDIT_PATH}?id=${productId}&type=${productType}`
}

export function parseAdminProductConfigurationRoute(
  params: Readonly<Record<string, string | undefined>>,
): AdminProductDetailRoute | undefined {
  return parseAdminProductDetailRoute(params)
}

export function buildAdminProductConfigurationUrl(
  productId: number,
  productType: AdminProductRouteType,
): string {
  if (!Number.isSafeInteger(productId) || productId <= 0) {
    throw new Error('Product ID 必须是正安全整数')
  }
  assertAdminProductType(productType)
  return `${ADMIN_PRODUCT_CONFIGURATION_PATH}?id=${productId}&type=${productType}`
}

export function parseAdminProductImagesRoute(
  params: Readonly<Record<string, string | undefined>>,
): AdminProductDetailRoute | undefined {
  return parseAdminProductDetailRoute(params)
}

export function buildAdminProductImagesUrl(
  productId: number,
  productType: AdminProductRouteType,
): string {
  if (!Number.isSafeInteger(productId) || productId <= 0) {
    throw new Error('Product ID 必须是正安全整数')
  }
  assertAdminProductType(productType)
  return `${ADMIN_PRODUCT_IMAGES_PATH}?id=${productId}&type=${productType}`
}

function assertAdminProductType(productType: string): asserts productType is AdminProductRouteType {
  if (!isAdminProductType(productType)) {
    throw new Error('Product type 必须是 experience 或 kit')
  }
}

function isAdminProductType(value: unknown): value is AdminProductRouteType {
  return value === 'experience' || value === 'kit'
}
