import { createApiClient } from '@/api'
import { AuthApi } from '@/api/endpoints/auth'
import { TaroStorageAdapter } from '@/platform/storage'

import { SessionManager } from './session'

export interface AuthRuntime {
  api: AuthApi
  session: SessionManager
}

let defaultRuntime: AuthRuntime | undefined

export function createAuthRuntime(): AuthRuntime {
  let authApi: AuthApi
  const session = new SessionManager(
    new TaroStorageAdapter(),
    (refreshToken) => authApi.refresh(refreshToken),
  )
  const client = createApiClient(session)
  authApi = new AuthApi(client)
  return { api: authApi, session }
}

export function getDefaultAuthRuntime(): AuthRuntime {
  defaultRuntime ??= createAuthRuntime()
  return defaultRuntime
}
