import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { components } from '@/api/schema'

export type PublicTableCode = components['schemas']['PublicTableCodeOut']
export type EligibleOrder = components['schemas']['EligibleOrderListItemOut']
export type EligibleOrderPage = components['schemas']['Page_EligibleOrderListItemOut_']
export type TableSession = components['schemas']['TableSessionOut']
export type AdminTable = components['schemas']['AdminTableOut']
export type AdminTableList = components['schemas']['AdminTableListOut']
export type DirectTableDurations = components['schemas']['DirectTableDurationListOut']
export type DirectTableDuration = components['schemas']['DirectTableDurationOut']
export type AdminTableSession = components['schemas']['AdminTableSessionOut']
export type AdminTableSessionPage = components['schemas']['Page_AdminTableSessionListItemOut_']

type TableApiClient = Pick<ApiClient, 'request'>
type SessionStatusEnum = components['schemas']['TableEnumOut'] & {
  readonly value: components['schemas']['TableSessionStatus']
}
type CloseReasonEnum = components['schemas']['TableEnumOut'] & {
  readonly value: components['schemas']['TableSessionCloseReason']
}
const TOKEN_PATTERN = /^[A-Za-z0-9]{32}$/
const SESSION_PATTERN = /^TS[0-9A-HJKMNP-TV-Z]{26}$/
const ORDER_PATTERN = /^OD[0-9A-HJKMNP-TV-Z]{26}$/

export class TableSessionApi {
  constructor(private readonly client: TableApiClient) {}

  async resolveTableCode(qrToken: string): Promise<PublicTableCode> {
    assertToken(qrToken)
    return this.requestParsed(
      'tables.code.resolve',
      `/api/v1/table-codes/${qrToken}`,
      'none',
      parsePublicTableCode,
    )
  }

  async resolveTableNumber(tableNo: string): Promise<PublicTableCode> {
    if (!isTableNo(tableNo)) throw new Error('请输入 1–30 号桌')
    return this.requestParsed('tables.number.resolve', `/api/v1/tables/by-number/${tableNo}`,
      'required', parsePublicTableCode)
  }

  async createSessionByNumber(tableNo: string, orderId: number, idempotencyKey: string): Promise<TableSession> {
    if (!isTableNo(tableNo)) throw new Error('桌台号无效')
    assertPositiveId(orderId)
    assertIntent(idempotencyKey)
    const operation = 'tables.session.create'
    const value = await this.client.request<unknown>({ operation, path: '/api/v1/table-sessions',
      method: 'POST', auth: 'required', headers: { 'Idempotency-Key': idempotencyKey },
      body: { table_no: tableNo, order_id: orderId } })
    const session = requireParsed(operation, value, parseTableSession)
    if (session.order_id !== orderId || session.table.table_no !== tableNo) throw new ContractError({ operation })
    return session
  }

  async listEligibleOrders(page = 1): Promise<EligibleOrderPage> {
    const operation = 'tables.orders.eligible'
    const value = await this.client.request<unknown>({
      operation,
      path: '/api/v1/table-sessions/eligible-orders',
      method: 'GET',
      auth: 'required',
      query: { page, page_size: 100 },
    })
    return requireParsed(operation, value, parseEligibleOrderPage)
  }

  async createSession(
    qrToken: string,
    orderId: number,
    idempotencyKey: string,
  ): Promise<TableSession> {
    assertToken(qrToken)
    assertPositiveId(orderId)
    assertIntent(idempotencyKey)
    const operation = 'tables.session.create'
    const value = await this.client.request<unknown>({
      operation,
      path: '/api/v1/table-sessions',
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { qr_token: qrToken, order_id: orderId },
    })
    const session = requireParsed(operation, value, parseTableSession)
    if (session.order_id !== orderId) throw new ContractError({ operation })
    return session
  }

  async getCurrentSession(): Promise<TableSession | null> {
    const operation = 'tables.session.current'
    const value = await this.client.request<unknown>({
      operation,
      path: '/api/v1/table-sessions/current',
      method: 'GET',
      auth: 'required',
    })
    if (value === null) return null
    return requireParsed(operation, value, parseTableSession)
  }

  async getHistorySession(sessionNo: string): Promise<TableSession> {
    const operation = 'tables.history'
    if (!SESSION_PATTERN.test(sessionNo)) throw new Error('桌台记录无效')
    const value = await this.client.request<unknown>({ operation, path: `/api/v1/table-sessions/history/${sessionNo}`, method: 'GET', auth: 'required' })
    const session = requireParsed(operation, value, parseTableSession)
    if (session.session_no !== sessionNo) throw new ContractError({ operation })
    return session
  }

  async getOrderSession(orderId: number): Promise<TableSession | null> {
    assertPositiveId(orderId)
    const operation = 'tables.session.order'
    const value = await this.client.request<unknown>({
      operation,
      path: `/api/v1/orders/${orderId}/table-session`,
      method: 'GET',
      auth: 'required',
    })
    if (value === null) return null
    const session = requireParsed(operation, value, parseTableSession)
    if (session.order_id !== orderId) throw new ContractError({ operation })
    return session
  }

  async listAdminTables(): Promise<AdminTableList> {
    return this.requestParsed(
      'tables.admin.list',
      '/api/v1/admin/tables',
      'required',
      parseAdminTableList,
    )
  }

  async listDirectDurations(): Promise<DirectTableDurations> {
    return this.requestParsed('tables.admin.durations', '/api/v1/admin/table-duration-options', 'required', (value) => {
      if (!isRecord(value) || value.buffer_minutes !== 10 || !Array.isArray(value.items)) return undefined
      const items: DirectTableDuration[] = []
      for (const item of value.items) {
        if (!isRecord(item) || !isPositiveId(item.option_id) || !isPositiveId(item.duration_minutes) ||
          items.some((existing) => existing.duration_minutes >= Number(item.duration_minutes))) return undefined
        items.push({ option_id: item.option_id, duration_minutes: item.duration_minutes })
      }
      return { items, buffer_minutes: 10 }
    })
  }

  async createDirectSession(tableId: number, option: DirectTableDuration, note: string, key: string): Promise<AdminTableSession> {
    assertPositiveId(tableId)
    assertPositiveId(option.option_id)
    assertPositiveId(option.duration_minutes)
    assertIntent(key)
    if (note.trim().length > 200) throw new Error('备注最多 200 个字符')
    const operation = 'tables.admin.direct.create'
    const value = await this.client.request<unknown>({
      operation, path: `/api/v1/admin/tables/${tableId}/direct-sessions`, method: 'POST', auth: 'required',
      headers: { 'Idempotency-Key': key },
      body: { option_id: option.option_id, duration_minutes: option.duration_minutes, note: note.trim() || null },
    })
    const session = requireParsed(operation, value, parseAdminTableSession)
    if (session.table.id !== tableId || session.source !== 'direct' || session.direct_duration_minutes !== option.duration_minutes) {
      throw new ContractError({ operation })
    }
    return session
  }

  async confirmAdminPayment(orderId: number, sessionNo: string): Promise<void> {
    assertPositiveId(orderId)
    assertSessionNo(sessionNo)
    await this.client.request<unknown>({
      operation: 'tables.admin.payment.confirm', path: `/api/v1/admin/orders/${orderId}/paid`,
      method: 'PATCH', auth: 'required', headers: { 'Table-Session-No': sessionNo },
    })
  }

  async updateAdminTable(
    tableId: number,
    isEnabled: boolean,
    reason: string,
  ): Promise<components['schemas']['TableSummaryOut']> {
    assertPositiveId(tableId)
    assertReason(reason)
    const operation = 'tables.admin.update'
    const value = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/tables/${tableId}`,
      method: 'PATCH',
      auth: 'required',
      body: { is_enabled: isEnabled, reason: reason.trim() },
    })
    return requireParsed(operation, value, parseTableSummary)
  }

  async listAdminSessions(page = 1, orderId?: number): Promise<AdminTableSessionPage> {
    if (orderId !== undefined) assertPositiveId(orderId)
    const operation = 'tables.admin.sessions'
    const value = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/table-sessions',
      method: 'GET',
      auth: 'required',
      query: { page, page_size: 100, ...(orderId === undefined ? {} : { order_id: orderId }) },
    })
    return requireParsed(operation, value, parseAdminSessionPage)
  }

  async getAdminOrderSession(orderId: number): Promise<AdminTableSession | null> {
    const page = await this.listAdminSessions(1, orderId)
    const latest = page.items[0]
    if (!latest) return null
    const result = await this.getAdminSession(latest.session_no)
    if (result.order_id !== orderId) throw new ContractError({ operation: 'tables.admin.order.session' })
    return result
  }

  async getAdminSession(sessionNo: string): Promise<AdminTableSession> {
    assertSessionNo(sessionNo)
    const session = await this.requestParsed(
      'tables.admin.session.detail',
      `/api/v1/admin/table-sessions/${sessionNo}`,
      'required',
      parseAdminTableSession,
    )
    if (session.session_no !== sessionNo) throw new ContractError({ operation: 'tables.admin.session.detail' })
    return session
  }

  async releaseAdminSession(
    sessionNo: string,
    reason: string,
    idempotencyKey: string,
  ): Promise<AdminTableSession> {
    assertSessionNo(sessionNo)
    assertReason(reason)
    assertIntent(idempotencyKey)
    const operation = 'tables.admin.session.release'
    const value = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/table-sessions/${sessionNo}/release`,
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { reason: reason.trim() },
    })
    const session = requireParsed(operation, value, parseAdminTableSession)
    if (session.session_no !== sessionNo || session.status.value !== 'closed') {
      throw new ContractError({ operation })
    }
    return session
  }

  private async requestParsed<T>(
    operation: string,
    path: string,
    auth: 'none' | 'required',
    parser: (value: unknown) => T | undefined,
  ): Promise<T> {
    const value = await this.client.request<unknown>({ operation, path, method: 'GET', auth })
    return requireParsed(operation, value, parser)
  }
}

export function parsePublicTableCode(value: unknown): PublicTableCode | undefined {
  if (!isRecord(value) || !isTableNo(value.table_no) ||
    typeof value.display_name !== 'string' || value.display_name.length === 0 ||
    typeof value.is_enabled !== 'boolean' || typeof value.is_available !== 'boolean') return undefined
  return {
    table_no: value.table_no,
    display_name: value.display_name,
    is_enabled: value.is_enabled,
    is_available: value.is_available,
  }
}

export function parseTableSession(value: unknown): TableSession | undefined {
  if (!isRecord(value) || !isPositiveId(value.order_id) || typeof value.order_no !== 'string' ||
    !ORDER_PATTERN.test(value.order_no) || !isUtcDate(value.payment_deadline_at)) return undefined
  const base = parseSessionBase(value)
  if (!base || base.timers.some((timer) => timer.experience_items.length === 0)) return undefined
  return { ...base, order_id: value.order_id, order_no: value.order_no, payment_deadline_at: value.payment_deadline_at }
}

function parseSessionBase(value: unknown): Omit<TableSession, 'order_id' | 'order_no' | 'payment_deadline_at'> | undefined {
  if (!isRecord(value) || typeof value.session_no !== 'string' || !SESSION_PATTERN.test(value.session_no) ||
    !isRecord(value.status) || !isSessionStatus(value.status.value) || typeof value.status.label !== 'string' ||
    !isUtcDate(value.claimed_at) || !isUtcDate(value.server_now) ||
    !isNullableUtcDate(value.started_at) || !isNullableUtcDate(value.table_release_at) ||
    !isNullableUtcDate(value.closed_at) || !Array.isArray(value.timers)) return undefined
  const table = parseTableSummary(value.table)
  const timers = value.timers.map(parseTimer)
  if (!table || timers.some((timer) => timer === undefined)) return undefined
  const closeReason = value.close_reason === null || value.close_reason === undefined
    ? null
    : parseCloseReasonEnum(value.close_reason)
  if (value.close_reason !== null && value.close_reason !== undefined && !closeReason) return undefined
  return {
    session_no: value.session_no,
    table,
    status: { value: value.status.value, label: value.status.label },
    claimed_at: value.claimed_at,
    started_at: value.started_at ?? null,
    table_release_at: value.table_release_at ?? null,
    closed_at: value.closed_at ?? null,
    close_reason: closeReason,
    timers: timers as TableSession['timers'],
    server_now: value.server_now,
  }
}

function parseTimer(value: unknown): TableSession['timers'][number] | undefined {
  if (!isRecord(value) || !isPositiveId(value.id) || !isPositiveId(value.duration_minutes) ||
    value.buffer_minutes !== 10 || !isUtcDate(value.started_at) || !isUtcDate(value.service_ends_at) ||
    !isUtcDate(value.grace_ends_at) || !isNullableUtcDate(value.ended_at) || !isRecord(value.phase) ||
    !['experience', 'grace', 'ended'].includes(String(value.phase.value)) ||
    typeof value.phase.label !== 'string' || !Array.isArray(value.experience_items)) return undefined
  const items = value.experience_items.map(parseTimerItem)
  if (items.some((item) => item === undefined)) return undefined
  return {
    id: value.id,
    duration_minutes: value.duration_minutes,
    buffer_minutes: 10,
    started_at: value.started_at,
    service_ends_at: value.service_ends_at,
    grace_ends_at: value.grace_ends_at,
    phase: { value: String(value.phase.value), label: value.phase.label },
    ended_at: value.ended_at ?? null,
    experience_items: items as TableSession['timers'][number]['experience_items'],
  }
}

function parseTimerItem(value: unknown): TableSession['timers'][number]['experience_items'][number] | undefined {
  if (!isRecord(value) || !isPositiveId(value.order_item_id) || !isPositiveId(value.product_id) ||
    typeof value.product_name !== 'string' || !isPositiveId(value.quantity) ||
    !isNullablePositiveId(value.participants_per_unit) || !isNullablePositiveId(value.total_participants)) return undefined
  return {
    order_item_id: value.order_item_id,
    product_id: value.product_id,
    product_name: value.product_name,
    quantity: value.quantity,
    participants_per_unit: value.participants_per_unit ?? null,
    total_participants: value.total_participants ?? null,
  }
}

function parseEligibleOrderPage(value: unknown): EligibleOrderPage | undefined {
  if (!isPage(value)) return undefined
  const items = value.items.map(parseEligibleOrder)
  return items.some((item) => item === undefined) ? undefined : {
    items: items as readonly EligibleOrder[],
    total: value.total,
    page: value.page,
    page_size: value.page_size,
    pages: value.pages,
  }
}

function parseEligibleOrder(value: unknown): EligibleOrder | undefined {
  if (!isRecord(value) || !isPositiveId(value.id) || typeof value.order_no !== 'string' ||
    typeof value.total_amount !== 'string' || !isUtcDate(value.created_at) ||
    !isPositiveId(value.experience_item_count) || !isNonNegativeInteger(value.kit_item_count) ||
    !Array.isArray(value.duration_groups)) return undefined
  const groups = value.duration_groups.map((group) => {
    if (!isRecord(group) || !isPositiveId(group.duration_minutes) || group.buffer_minutes !== 10 ||
      !isPositiveId(group.experience_item_count) || !isPositiveId(group.total_quantity)) return undefined
    return {
      duration_minutes: group.duration_minutes,
      buffer_minutes: 10 as const,
      experience_item_count: group.experience_item_count,
      total_quantity: group.total_quantity,
    }
  })
  if (groups.length === 0 || groups.some((group) => group === undefined)) return undefined
  return {
    id: value.id,
    order_no: value.order_no,
    total_amount: value.total_amount,
    created_at: value.created_at,
    experience_item_count: value.experience_item_count,
    kit_item_count: value.kit_item_count,
    duration_groups: groups as EligibleOrder['duration_groups'],
  }
}

function parseAdminTableList(value: unknown): AdminTableList | undefined {
  if (!isRecord(value) || !isUtcDate(value.server_now) || !Array.isArray(value.items)) return undefined
  const items = value.items.map(parseAdminTable)
  if (items.length > 30 || items.some((item) => item === undefined)) return undefined
  return { items: items as readonly AdminTable[], server_now: value.server_now }
}

function parseAdminTable(value: unknown): AdminTable | undefined {
  const table = parseTableSummary(value)
  if (!table || !isRecord(value) || !['available', 'awaiting_payment', 'active', 'disabled'].includes(String(value.state)) ||
    !isNullableMatchingString(value.current_session_no, SESSION_PATTERN) ||
    !isNullableMatchingString(value.current_order_no, ORDER_PATTERN) ||
    !isNullablePositiveId(value.current_user_id) || !isNullableUtcDate(value.claimed_at) ||
    !isNullableUtcDate(value.payment_deadline_at) || !isNullableUtcDate(value.table_release_at) ||
    !isNullableUtcDate(value.service_ends_at) || (value.timer_count !== undefined && !isNonNegativeInteger(value.timer_count)) ||
    (value.current_source != null && value.current_source !== 'order' && value.current_source !== 'direct')) return undefined
  const currentStatus = value.current_status === null || value.current_status === undefined
    ? null
    : parseSessionStatusEnum(value.current_status)
  if (value.current_status !== null && value.current_status !== undefined && !currentStatus) return undefined
  // 新客户端必须拿到全部计时组，不能将旧接口的最长一组误作全部。
  if (!Array.isArray(value.timers) || value.timers.length !== value.timer_count) return undefined
  const timers = value.timers.map((timer) => {
    if (!isRecord(timer) || !isPositiveId(timer.id) || !isPositiveId(timer.duration_minutes) ||
      !isUtcDate(timer.service_ends_at) || !isUtcDate(timer.grace_ends_at) ||
      Date.parse(timer.grace_ends_at) - Date.parse(timer.service_ends_at) !== 600_000) return undefined
    return { id: timer.id, duration_minutes: timer.duration_minutes, service_ends_at: timer.service_ends_at, grace_ends_at: timer.grace_ends_at }
  })
  if (timers.some((timer) => !timer) || new Set(timers.map((timer) => timer?.id)).size !== timers.length ||
    new Set(timers.map((timer) => timer?.duration_minutes)).size !== timers.length) return undefined
  if (currentStatus?.value === 'active') {
    if (!timers.length || Date.parse(value.service_ends_at as string) !== Math.max(...timers.map((timer) => Date.parse(timer!.service_ends_at))) ||
      Date.parse(value.table_release_at as string) !== Math.max(...timers.map((timer) => Date.parse(timer!.grace_ends_at)))) return undefined
  } else if (timers.length) return undefined
  return {
    ...table,
    timers: timers as AdminTable['timers'],
    state: value.state as AdminTable['state'],
    current_session_no: value.current_session_no ?? null,
    current_status: currentStatus,
    current_order_no: value.current_order_no ?? null,
    current_source: value.current_source ?? null,
    service_ends_at: value.service_ends_at ?? null,
    timer_count: value.timer_count ?? 0,
    current_user_id: value.current_user_id ?? null,
    claimed_at: value.claimed_at ?? null,
    payment_deadline_at: value.payment_deadline_at ?? null,
    table_release_at: value.table_release_at ?? null,
  }
}

function parseAdminSessionPage(value: unknown): AdminTableSessionPage | undefined {
  if (!isPage(value)) return undefined
  const items = value.items.map((item) => {
    if (!isRecord(item) || typeof item.session_no !== 'string' || !SESSION_PATTERN.test(item.session_no) ||
      !validAdminIdentity(item) ||
      !isNonNegativeInteger(item.timer_count) || !isNullablePositiveId(item.minimum_duration_minutes) ||
      !isNullablePositiveId(item.maximum_duration_minutes) || !isUtcDate(item.claimed_at) ||
      !isNullableUtcDate(item.payment_deadline_at) || !isNullableUtcDate(item.started_at) ||
      !isNullableUtcDate(item.table_release_at) || !isNullableUtcDate(item.closed_at)) return undefined
    const table = parseTableSummary(item.table)
    const status = parseSessionStatusEnum(item.status)
    const closeReason = item.close_reason === null || item.close_reason === undefined
      ? null
      : parseCloseReasonEnum(item.close_reason)
    if (!table || !status || (item.close_reason !== null && item.close_reason !== undefined && !closeReason) ||
      !isAdminSessionListShapeConsistent(item, status.value, closeReason?.value ?? null)) return undefined
    return {
      source: (item.source === 'direct' ? 'direct' : 'order') as 'direct' | 'order',
      session_no: item.session_no,
      table,
      order_id: item.order_id as number | null,
      order_no: item.order_no as string | null,
      user_id: item.user_id as number | null,
      user_nickname: item.user_nickname as string | null,
      status,
      close_reason: closeReason,
      timer_count: item.timer_count,
      minimum_duration_minutes: item.minimum_duration_minutes ?? null,
      maximum_duration_minutes: item.maximum_duration_minutes ?? null,
      claimed_at: item.claimed_at,
      payment_deadline_at: item.payment_deadline_at as string | null,
      started_at: item.started_at ?? null,
      table_release_at: item.table_release_at ?? null,
      closed_at: item.closed_at ?? null,
    }
  })
  return items.some((item) => item === undefined) ? undefined : {
    items: items as AdminTableSessionPage['items'],
    total: value.total,
    page: value.page,
    page_size: value.page_size,
    pages: value.pages,
  }
}

function validAdminIdentity(value: Record<string, unknown>): boolean {
  if (value.source === 'direct') {
    return value.order_id === null && value.order_no === null && value.user_id === null &&
      value.user_nickname === null && value.payment_deadline_at === null &&
      isRecord(value.status) && value.status.value !== 'awaiting_payment'
  }
  return (value.source === undefined || value.source === 'order') && isPositiveId(value.order_id) &&
    typeof value.order_no === 'string' && ORDER_PATTERN.test(value.order_no) && isPositiveId(value.user_id) &&
    typeof value.user_nickname === 'string' && value.user_nickname.length > 0 && isUtcDate(value.payment_deadline_at)
}

export function parseAdminTableSession(value: unknown): AdminTableSession | undefined {
  const session = parseSessionBase(value)
  if (!session || !isRecord(value) || !validAdminIdentity(value) || !isNullablePositiveId(value.payment_id) ||
    !isNullablePositiveId(value.closed_by_user_id) || !isNullableString(value.admin_close_reason) ||
    !isNullablePositiveId(value.opened_by_user_id) || !isNullablePositiveId(value.source_option_id) ||
    !isNullablePositiveId(value.direct_duration_minutes) || !isNullableString(value.opening_note) ||
    (value.order_experience_durations !== undefined && (!Array.isArray(value.order_experience_durations) || !value.order_experience_durations.every(isPositiveId))) ||
    (value.order_total_amount != null && (typeof value.order_total_amount !== 'string' || !/^\d+\.\d{2}$/.test(value.order_total_amount)))) return undefined
  const direct = value.source === 'direct'
  if (direct && (value.payment_id !== null || value.order_total_amount !== null ||
    !isPositiveId(value.opened_by_user_id) || !isPositiveId(value.source_option_id) || !isPositiveId(value.direct_duration_minutes) ||
    session.status.value === 'awaiting_payment' || session.timers.length !== 1 || session.started_at !== session.claimed_at ||
    session.timers[0].duration_minutes !== value.direct_duration_minutes || session.timers[0].experience_items.length !== 0)) return undefined
  if (!direct && session.timers.some((timer) => timer.experience_items.length === 0)) return undefined
  return {
    ...session,
    source: direct ? 'direct' : 'order',
    order_id: value.order_id as number | null,
    order_no: value.order_no as string | null,
    payment_deadline_at: value.payment_deadline_at as string | null,
    order_total_amount: value.order_total_amount as string | null | undefined ?? null,
    order_experience_durations: value.order_experience_durations as number[] | undefined ?? [],
    user_id: value.user_id as number | null,
    user_nickname: value.user_nickname as string | null,
    payment_id: value.payment_id ?? null,
    opened_by_user_id: value.opened_by_user_id ?? null,
    source_option_id: value.source_option_id ?? null,
    direct_duration_minutes: value.direct_duration_minutes ?? null,
    opening_note: value.opening_note ?? null,
    closed_by_user_id: value.closed_by_user_id ?? null,
    admin_close_reason: value.admin_close_reason ?? null,
  }
}

function parseTableSummary(value: unknown): components['schemas']['TableSummaryOut'] | undefined {
  if (!isRecord(value) || !isPositiveId(value.id) || !isTableNo(value.table_no) ||
    typeof value.display_name !== 'string' || value.display_name.length === 0 || typeof value.is_enabled !== 'boolean') return undefined
  return { id: value.id, table_no: value.table_no, display_name: value.display_name, is_enabled: value.is_enabled }
}

function parseEnum(value: unknown): components['schemas']['TableEnumOut'] | undefined {
  return isRecord(value) && typeof value.value === 'string' && typeof value.label === 'string'
    ? { value: value.value, label: value.label }
    : undefined
}

function parseSessionStatusEnum(value: unknown): SessionStatusEnum | undefined {
  const parsed = parseEnum(value)
  return parsed && isSessionStatus(parsed.value) ? parsed as SessionStatusEnum : undefined
}

function parseCloseReasonEnum(value: unknown): CloseReasonEnum | undefined {
  const parsed = parseEnum(value)
  return parsed && isCloseReason(parsed.value) ? parsed as CloseReasonEnum : undefined
}

function isAdminSessionListShapeConsistent(
  item: Record<string, unknown>,
  status: components['schemas']['TableSessionStatus'],
  closeReason: string | null,
): boolean {
  const minimum = item.minimum_duration_minutes
  const maximum = item.maximum_duration_minutes
  const hasTimers = item.timer_count !== 0
  const hasDurationRange = minimum !== null && minimum !== undefined && maximum !== null && maximum !== undefined
  if (hasTimers !== hasDurationRange) return false
  if (typeof minimum === 'number' && typeof maximum === 'number' && minimum > maximum) return false
  if (status === 'awaiting_payment') {
    return !hasTimers && item.started_at == null && item.table_release_at == null && item.closed_at == null && closeReason === null
  }
  if (status === 'active') {
    return hasTimers && item.started_at != null && item.table_release_at != null && item.closed_at == null && closeReason === null
  }
  return item.closed_at != null && closeReason !== null
}

function isPage(value: unknown): value is Record<string, unknown> & {
  readonly items: unknown[]; readonly total: number; readonly page: number; readonly page_size: number; readonly pages: number
} {
  return isRecord(value) && Array.isArray(value.items) && isNonNegativeInteger(value.total) &&
    isPositiveId(value.page) && isPositiveId(value.page_size) && isNonNegativeInteger(value.pages)
}

function requireParsed<T>(operation: string, value: unknown, parser: (value: unknown) => T | undefined): T {
  const parsed = parser(value)
  if (!parsed) throw new ContractError({ operation })
  return parsed
}

function assertToken(value: string): void {
  if (!TOKEN_PATTERN.test(value)) throw new Error('桌台二维码无效')
}

function assertSessionNo(value: string): void {
  if (!SESSION_PATTERN.test(value)) throw new Error('桌台会话编号无效')
}

function assertPositiveId(value: number): void {
  if (!isPositiveId(value)) throw new Error('ID 必须是正安全整数')
}

function assertIntent(value: string): void {
  if (value.trim() !== value || value.length < 1 || value.length > 128 || !/^[\x20-\x7e]+$/.test(value)) {
    throw new Error('幂等标识无效')
  }
}

function assertReason(value: string): void {
  if (value.trim().length < 1 || value.trim().length > 200) throw new Error('原因必须为 1–200 个字符')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isPositiveId(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0
}

function isNullablePositiveId(value: unknown): value is number | null | undefined {
  return value === null || value === undefined || isPositiveId(value)
}

function isNullableString(value: unknown): value is string | null | undefined {
  return value === null || value === undefined || typeof value === 'string'
}

function isNullableMatchingString(value: unknown, pattern: RegExp): value is string | null | undefined {
  return value === null || value === undefined || (typeof value === 'string' && pattern.test(value))
}

function isTableNo(value: unknown): value is string {
  return typeof value === 'string' && /^T(?:0[1-9]|[12]\d|30)$/.test(value)
}

function isSessionStatus(value: unknown): value is components['schemas']['TableSessionStatus'] {
  return value === 'awaiting_payment' || value === 'active' || value === 'closed'
}

function isCloseReason(value: unknown): value is components['schemas']['TableSessionCloseReason'] {
  return value === 'payment_timeout' || value === 'time_expired' || value === 'order_cancelled' ||
    value === 'order_completed' || value === 'refunded' || value === 'admin_released'
}

function isUtcDate(value: unknown): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T.*(?:Z|\+00:00)$/.test(value) && !Number.isNaN(Date.parse(value))
}

function isNullableUtcDate(value: unknown): value is string | null | undefined {
  return value === null || value === undefined || isUtcDate(value)
}
