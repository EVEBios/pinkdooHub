import { createApiClient } from '@/api'
import { TableSessionApi } from '@/api/endpoints/table_sessions'
import { getDefaultAuthRuntime } from '@/auth/runtime'

let defaultTableSessionApi: TableSessionApi | undefined

export function getDefaultTableSessionApi(): TableSessionApi {
  defaultTableSessionApi ??= new TableSessionApi(
    createApiClient(getDefaultAuthRuntime().session),
  )
  return defaultTableSessionApi
}
