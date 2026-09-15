import { createApiClient } from '@/api'
import { getDefaultAuthRuntime } from '@/auth/runtime'
import { StoreBeadStockApi } from '@/api/endpoints/store_bead_stock'

export { STORE_STOCK_PATH } from '@/navigation/store_stock_route'
let api: StoreBeadStockApi | undefined
export function getStoreStockApi(): StoreBeadStockApi {
  api ??= new StoreBeadStockApi(createApiClient(getDefaultAuthRuntime().session))
  return api
}
