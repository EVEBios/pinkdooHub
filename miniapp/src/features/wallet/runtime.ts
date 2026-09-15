import { createApiClient } from '@/api'
import { WalletApi } from '@/api/endpoints/wallet'
import { getDefaultAuthRuntime } from '@/auth/runtime'

let defaultWalletApi: WalletApi | undefined

export function getDefaultWalletApi(): WalletApi {
  defaultWalletApi ??= new WalletApi(createApiClient(getDefaultAuthRuntime().session))
  return defaultWalletApi
}
