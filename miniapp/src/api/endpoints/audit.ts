import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { components, operations } from '@/api/schema'

export type ProductAuditListRequest = NonNullable<operations[
  'list_product_audit_logs_api_v1_admin_products__product_id__audit_logs_get'
]['parameters']['query']>
export type AuditLogItem = components['schemas']['AuditLogOut']
export type AuditLogPage = components['schemas']['Page_AuditLogOut_']

type AuditApiClient = Pick<ApiClient, 'request'>

const UTC_DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/

export class AuditApi {
  constructor(private readonly client: AuditApiClient) {}

  async listProductAuditLogs(
    productId: number,
    request: ProductAuditListRequest = {},
  ): Promise<AuditLogPage> {
    assertPositiveSafeInteger(productId, 'Product ID')
    const operation = 'products.admin.audit.list'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/products/${productId}/audit-logs`,
      method: 'GET',
      auth: 'required',
      query: projectAuditListRequest(request),
    })
    const parsed = parseAuditLogPage(result, productId)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }
}

function projectAuditListRequest(request: ProductAuditListRequest): ProductAuditListRequest {
  return {
    ...(request.page === undefined ? {} : { page: request.page }),
    ...(request.page_size === undefined ? {} : { page_size: request.page_size }),
  }
}

function parseAuditLogPage(value: unknown, productId: number): AuditLogPage | undefined {
  if (!isRecord(value) || !Array.isArray(value.items)) return undefined
  const page = parsePageMeta(value)
  if (!page || value.items.length > page.page_size) return undefined
  const items: AuditLogItem[] = []
  for (const item of value.items) {
    const parsed = parseAuditLogItem(item, productId)
    if (!parsed) return undefined
    items.push(parsed)
  }
  return { items, ...page }
}

function parseAuditLogItem(value: unknown, productId: number): AuditLogItem | undefined {
  if (!isRecord(value) ||
    !isPositiveSafeInteger(value.id) ||
    !isPositiveSafeInteger(value.operator_id) ||
    !isBoundedString(value.action, 1, 50) ||
    value.target_type !== 'product' ||
    value.target_id !== productId ||
    !(value.description === null || isBoundedString(value.description, 0, 256)) ||
    !isBoundedString(value.ip_address, 1, 45) ||
    !isUtcDatetime(value.created_at)) return undefined
  return {
    id: value.id,
    operator_id: value.operator_id,
    action: value.action,
    target_type: 'product',
    target_id: value.target_id,
    description: value.description,
    ip_address: value.ip_address,
    created_at: value.created_at,
  }
}

function parsePageMeta(value: Record<string, unknown>): Omit<AuditLogPage, 'items'> | undefined {
  if (!isNonNegativeSafeInteger(value.total) ||
    !isPositiveSafeInteger(value.page) ||
    !isPositiveSafeInteger(value.page_size) || value.page_size > 100 ||
    !isNonNegativeSafeInteger(value.pages)) return undefined
  return {
    total: value.total,
    page: value.page,
    page_size: value.page_size,
    pages: value.pages,
  }
}

function assertPositiveSafeInteger(value: number, label: string): void {
  if (!isPositiveSafeInteger(value)) throw new Error(`${label} 必须是正安全整数`)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isPositiveSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function isBoundedString(value: unknown, min: number, max: number): value is string {
  return typeof value === 'string' && value.length >= min && value.length <= max
}

function isUtcDatetime(value: unknown): value is string {
  return typeof value === 'string' && UTC_DATETIME_PATTERN.test(value) && !Number.isNaN(Date.parse(value))
}
