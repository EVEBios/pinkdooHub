import { resolveEnv } from '@/config/env'

import { ApiClient } from './client'
import { TaroHttpTransport } from './taro_transport'
import type { AuthSession } from './types'

export function createApiClient(authSession?: AuthSession): ApiClient {
  const environment = resolveEnv()
  return new ApiClient({
    baseUrl: environment.apiOrigin,
    transport: new TaroHttpTransport(),
    authSession,
  })
}
