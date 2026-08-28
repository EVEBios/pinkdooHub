import { createApiClient } from '@/api'
import { AuditApi } from '@/api/endpoints/audit'
import { getDefaultAuthRuntime } from '@/auth/runtime'

let defaultAuditApi: AuditApi | undefined

export function getDefaultAuditApi(): AuditApi {
  defaultAuditApi ??= new AuditApi(
    createApiClient(getDefaultAuthRuntime().session),
  )
  return defaultAuditApi
}
