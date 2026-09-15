import { createApiClient } from '@/api'
import { OrderApi } from '@/api/endpoints/orders'
import { getDefaultAuthRuntime } from '@/auth/runtime'
import { TaroStorageAdapter } from '@/platform/storage'

import { CartStore } from './cart'
import type { OrderCreator } from './submission'

export interface CartRuntime {
  readonly store: CartStore
}

let defaultRuntime: CartRuntime | undefined
let defaultOrderApi: OrderApi | undefined

export function createCartRuntime(): CartRuntime {
  return { store: new CartStore(new TaroStorageAdapter()) }
}

export function getDefaultCartRuntime(): CartRuntime {
  defaultRuntime ??= createCartRuntime()
  return defaultRuntime
}

export function getDefaultOrderCreator(): OrderCreator {
  return getDefaultOrderApi()
}

export function getDefaultOrderApi(): OrderApi {
  defaultOrderApi ??= new OrderApi(
    createApiClient(getDefaultAuthRuntime().session),
  )
  return defaultOrderApi
}
