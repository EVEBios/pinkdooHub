import { createApiClient } from '@/api'
import { AdminProductApi } from '@/api/endpoints/admin_products'
import { ProductApi } from '@/api/endpoints/products'
import { getDefaultAuthRuntime } from '@/auth/runtime'

let defaultProductApi: ProductApi | undefined
let defaultAdminProductApi: AdminProductApi | undefined

export function getDefaultProductApi(): ProductApi {
  defaultProductApi ??= new ProductApi(createApiClient())
  return defaultProductApi
}

export function getDefaultAdminProductApi(): AdminProductApi {
  defaultAdminProductApi ??= new AdminProductApi(
    createApiClient(getDefaultAuthRuntime().session),
  )
  return defaultAdminProductApi
}
