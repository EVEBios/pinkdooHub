import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { components, operations } from '@/api/schema'

export type AdminUserListRequest = NonNullable<operations[
  'list_users_api_v1_admin_users_get'
]['parameters']['query']>
export type AdminUserListItem = components['schemas']['UserListItem']
export type AdminUserListPage = components['schemas']['Page_UserListItem_']

type AdminUserApiClient = Pick<ApiClient, 'request'>
const UTC_DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/
const USER_ROLES = new Set(['user', 'admin', 'super_admin'])
const USER_STATUSES = new Set(['normal', 'disabled'])

export class AdminUserApi {
  constructor(private readonly client: AdminUserApiClient) {}

  async listUsers(request: AdminUserListRequest = {}): Promise<AdminUserListPage> {
    const operation = 'users.admin.list'
    const result = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/users',
      method: 'GET',
      auth: 'required',
      query: projectAdminUserListRequest(request),
    })
    const parsed = parseAdminUserListPage(result)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async disableUser(userId: number): Promise<void> {
    assertPositiveSafeInteger(userId, 'User ID')
    const operation = 'users.admin.disable'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/users/${userId}/disable`,
      method: 'PUT',
      auth: 'required',
    })
    if (result !== null) throw new ContractError({ operation })
  }
}

function projectAdminUserListRequest(request: AdminUserListRequest): AdminUserListRequest {
  return {
    ...(request.page === undefined ? {} : { page: request.page }),
    ...(request.page_size === undefined ? {} : { page_size: request.page_size }),
    ...(request.status === undefined || request.status === null ? {} : { status: request.status }),
    ...(request.role === undefined || request.role === null ? {} : { role: request.role }),
  }
}

function parseAdminUserListPage(value: unknown): AdminUserListPage | undefined {
  if (!isRecord(value) || !Array.isArray(value.items)) return undefined
  const page = parsePageMeta(value)
  if (!page || value.items.length > page.page_size) return undefined
  const items: AdminUserListItem[] = []
  for (const item of value.items) {
    const parsed = parseAdminUserListItem(item)
    if (!parsed) return undefined
    items.push(parsed)
  }
  return { items, ...page }
}

function parseAdminUserListItem(value: unknown): AdminUserListItem | undefined {
  if (!isRecord(value) ||
    !isPositiveSafeInteger(value.id) ||
    !isBoundedString(value.username, 3, 32) ||
    !isBoundedString(value.nickname, 1, 32) ||
    typeof value.role !== 'string' || !USER_ROLES.has(value.role) ||
    typeof value.status !== 'string' || !USER_STATUSES.has(value.status) ||
    !(value.last_login_at === null || isUtcDatetime(value.last_login_at)) ||
    !isUtcDatetime(value.created_at)) return undefined
  return {
    id: value.id,
    username: value.username,
    nickname: value.nickname,
    role: value.role as AdminUserListItem['role'],
    status: value.status as AdminUserListItem['status'],
    last_login_at: value.last_login_at,
    created_at: value.created_at,
  }
}

function parsePageMeta(value: Record<string, unknown>): Omit<AdminUserListPage, 'items'> | undefined {
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
