import { createApiClient } from '@/api'
import { AdminUserApi } from '@/api/endpoints/admin_users'
import { getDefaultAuthRuntime } from '@/auth/runtime'

let defaultAdminUserApi: AdminUserApi | undefined

export function getDefaultAdminUserApi(): AdminUserApi {
  defaultAdminUserApi ??= new AdminUserApi(
    createApiClient(getDefaultAuthRuntime().session),
  )
  return defaultAdminUserApi
}
