import { createApiClient } from '@/api'
import { ProductApi } from '@/api/endpoints/products'

let defaultProductApi: ProductApi | undefined

export function getDefaultProductApi(): ProductApi {
  defaultProductApi ??= new ProductApi(createApiClient())
  return defaultProductApi
}
