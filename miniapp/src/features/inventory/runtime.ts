import { createApiClient } from '@/api'
import { InventoryApi } from '@/api/endpoints/inventory'
import { getDefaultAuthRuntime } from '@/auth/runtime'

let defaultInventoryApi: InventoryApi | undefined

export function getDefaultInventoryApi(): InventoryApi {
  defaultInventoryApi ??= new InventoryApi(
    createApiClient(getDefaultAuthRuntime().session),
  )
  return defaultInventoryApi
}
