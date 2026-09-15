import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { components } from '@/api/schema'
import { parseReservation, type Reservation } from './reservations'

export type AttentionSummary = components['schemas']['AttentionSummaryOut']
export type AttentionSnapshot = components['schemas']['ReservationAttentionSnapshotOut']
export type AttentionView = 'actionable' | 'unread' | 'overdue'
export type AttentionPage = { readonly items: readonly Reservation[]; readonly total: number; readonly page: number; readonly pages: number; readonly page_size: number }

const isRecord = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object'
const isCount = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0
const isTime = (value: unknown): value is string => typeof value === 'string' && /(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value))
const COMMERCE_EVENTS = new Set(['order_manual_paid', 'order_wallet_paid', 'order_completed', 'order_assisted_wallet_paid', 'order_wallet_refunded', 'order_manual_refunded', 'wallet_adjusted', 'session_payment_timeout', 'session_time_expired', 'session_admin_released'])
const EVENT_TYPES = new Set(['reservation_confirmed', 'reservation_rejected', 'reservation_store_closed', 'reservation_customer_cancelled'])

export class AttentionApi {
  constructor(private readonly client: Pick<ApiClient, 'request'>) {}

  async summary(admin: boolean): Promise<AttentionSummary> {
    const operation = 'attention.summary'
    const value = await this.client.request<unknown>({ operation, path: this.path(admin), method: 'GET', auth: 'required' })
    if (!isRecord(value) || !isTime(value.server_now) ||
      (!isCount(value.wallet_unread) || (admin && value.wallet_unread !== 0)) ||
      !['reservation_actionable', 'reservation_unread', 'reservation_overdue', 'reservation_total', 'order_pending', 'order_fulfillment', 'order_unread', 'order_total', 'table_pending', 'table_unread', 'table_total'].every((key) => isCount(value[key])) ||
      value.reservation_total !== Number(value.reservation_actionable) + Number(value.reservation_unread) ||
      value.table_total !== Number(value.table_pending) + Number(value.table_unread) ||
      (admin && (value.order_unread !== 0 || value.table_unread !== 0 || value.order_total !== Number(value.order_pending) + Number(value.order_fulfillment))) ||
      (!admin && (value.order_fulfillment !== 0 || Number(value.order_total) < Math.max(Number(value.order_pending), Number(value.order_unread)) || Number(value.order_total) > Number(value.order_pending) + Number(value.order_unread))) ||
      (!admin && (value.reservation_actionable !== 0 || value.reservation_overdue !== 0))) throw new ContractError({ operation })
    return value as unknown as AttentionSummary
  }

  async list(admin: boolean, view: AttentionView, page = 1): Promise<AttentionPage> {
    const operation = 'attention.reservations'
    const value = await this.client.request<unknown>({ operation, path: `${this.path(admin)}/reservations`, method: 'GET', auth: 'required', query: { view, page, page_size: 20 } })
    if (!isRecord(value) || !Array.isArray(value.items) || !isCount(value.total) || value.page !== page || value.page_size !== 20 || !isCount(value.pages) || value.pages !== Math.ceil(value.total / 20)) throw new ContractError({ operation })
    const items = value.items.map(parseReservation)
    if (items.some((item) => !item) || items.length > 20 || new Set(items.map((item) => item?.id)).size !== items.length) throw new ContractError({ operation })
    return { items: items as Reservation[], total: value.total, page, pages: value.pages, page_size: 20 }
  }

  async snapshot(admin: boolean, reservationId: number): Promise<AttentionSnapshot> {
    const operation = 'attention.snapshot'
    const value = await this.client.request<unknown>({ operation, path: `${this.path(admin)}/reservations/${reservationId}`, method: 'GET', auth: 'required' })
    if (!isRecord(value) || value.reservation_id !== reservationId || !isTime(value.reservation_updated_at) || !isTime(value.server_now) || !Array.isArray(value.events) || value.events.some((event) =>
      !isRecord(event) || !isCount(event.id) || event.id === 0 || !EVENT_TYPES.has(String(event.event_type)) || typeof event.label !== 'string' || !event.label || !isTime(event.occurred_at)) ||
      new Set(value.events.map((event) => event.id)).size !== value.events.length) throw new ContractError({ operation })
    return value as unknown as AttentionSnapshot
  }

  async read(admin: boolean, ids: readonly number[]): Promise<void> {
    if (!ids.length || ids.length > 100 || ids.some((id) => !isCount(id) || id === 0) || new Set(ids).size !== ids.length) throw new Error('阅读记录无效，请刷新后重试')
    await this.client.request({ operation: 'attention.read', path: `${this.path(admin)}/${admin ? 'acknowledge' : 'read'}`, method: 'POST', auth: 'required', body: { event_ids: ids } })
  }

  async commerceList(admin: boolean, scope: CommerceScope, view: CommerceView, page = 1): Promise<CommercePage> {
    if (scope === 'wallet') {
      if (admin || (view !== 'all' && view !== 'unread')) throw new Error('余额变动入口无效')
      return this.requestCommercePage('/api/v1/attention/wallet', scope, page, view)
    }
    return this.requestCommercePage(`${this.path(admin)}/commerce/${scope}`, scope, page, view)
  }

  async myTableSessions(page = 1): Promise<CommercePage> {
    return this.requestCommercePage('/api/v1/attention/table-sessions', 'tables', page)
  }

  private async requestCommercePage(path: string, scope: CommerceScope, page: number, view?: CommerceView): Promise<CommercePage> {
    const operation = 'attention.commerce'
    const value = await this.client.request<unknown>({ operation, path, method: 'GET', auth: 'required', query: { ...(view ? { view } : {}), page, page_size: 20 } })
    if (!isRecord(value) || !Array.isArray(value.items) || !isCount(value.total) || value.page !== page || value.page_size !== 20 || value.pages !== Math.ceil(value.total / 20) || value.items.length > 20 || value.items.some((item) =>
      !isRecord(item) || !isCount(item.id) || item.id === 0 || item.scope !== scope || typeof item.reference !== 'string' || typeof item.title !== 'string' || typeof item.status_label !== 'string' || typeof item.unread !== 'boolean' || !isTime(item.created_at) ||
      (item.payment_deadline_at !== null && !isTime(item.payment_deadline_at)) ||
      (item.order_id !== null && (!isCount(item.order_id) || item.order_id === 0)) ||
      (item.session_no !== null && (typeof item.session_no !== 'string' || !/^TS[0-9A-HJKMNP-TV-Z]{26}$/.test(item.session_no))) ||
      (scope === 'orders' ? item.order_id !== item.id : scope === 'tables' ? item.session_no !== item.reference : item.order_id !== null || item.session_no !== null || item.payment_deadline_at !== null)) ||
      new Set(value.items.map((item) => item.id)).size !== value.items.length) throw new ContractError({ operation })
    return value as unknown as CommercePage
  }

  async commerceSnapshot(scope: CommerceScope, target: number | string): Promise<CommerceSnapshot> {
    const operation = 'attention.commerceSnapshot'
    const value = await this.client.request<unknown>({ operation, path: `${this.path(false)}/${scope}/${encodeURIComponent(target)}`, method: 'GET', auth: 'required' })
    if (!isRecord(value) || !isTime(value.server_now) || !Array.isArray(value.events) || value.events.some((event) =>
      !isRecord(event) || !isCount(event.id) || event.id === 0 || !COMMERCE_EVENTS.has(String(event.event_type)) || !isTime(event.occurred_at) || typeof event.label !== 'string' || !event.label || typeof event.message !== 'string' || !event.message || typeof event.read !== 'boolean' ||
      (scope === 'wallet' ? event.id !== target || event.event_type !== 'wallet_adjusted' || !isWalletTransaction(event.wallet_transaction) || event.session_no !== null : event.event_type === 'wallet_adjusted' || event.wallet_transaction != null) ||
      (event.session_no !== null && (typeof event.session_no !== 'string' || !/^TS[0-9A-HJKMNP-TV-Z]{26}$/.test(event.session_no)))) ||
      new Set(value.events.map((event) => event.id)).size !== value.events.length) throw new ContractError({ operation })
    if (scope === 'wallet' && value.events.length !== 1) throw new ContractError({ operation })
    return value as unknown as CommerceSnapshot
  }

  private path(admin: boolean): string { return admin ? '/api/v1/admin/attention' : '/api/v1/attention' }
}

export type CommerceScope = 'orders' | 'tables' | 'wallet'
export type CommerceView = 'all' | 'pending' | 'fulfillment' | 'unread'
export type CommerceItem = components['schemas']['CommerceAttentionItemOut']
export type CommercePage = { readonly items: readonly CommerceItem[]; readonly total: number; readonly page: number; readonly pages: number; readonly page_size: number }
export type CommerceSnapshot = components['schemas']['CommerceAttentionSnapshotOut']

function isWalletTransaction(value: unknown): boolean {
  if (!isRecord(value) || !isCount(value.id) || value.id === 0 || typeof value.reason !== 'string' || !value.reason.trim() || Array.from(value.reason).length > 256) return false
  const money = (input: unknown) => {
    if (typeof input !== 'string' || !/^-?(?:0|[1-9]\d{0,3})\.\d{2}$/.test(input)) return undefined
    return Number(input.replace('.', ''))
  }
  const change = money(value.change_amount)
  const before = money(value.before_balance)
  const after = money(value.after_balance)
  return change !== undefined && change !== 0 && before !== undefined && after !== undefined &&
    before >= 0 && before <= 100_000 && after >= 0 && after <= 100_000 && before + change === after
}
