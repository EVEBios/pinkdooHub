import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { components } from '@/api/schema'

export type FollowupKind = 'contact' | 'overdue'
export type FollowupSnapshot = components['schemas']['FollowupSnapshotOut']
export type FollowupRecord = components['schemas']['FollowupRecordOut']
export type FollowupItem = components['schemas']['FollowupItemOut']
export type FollowupCounts = components['schemas']['FollowupCounts']
export type FollowupWrite = components['schemas']['FollowupWrite']
export type FollowupPage<T> = { items: T[]; total: number; page: number; page_size: number; pages: number }
const root = '/api/v1/admin/reservation-followups'
const record = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null
const count = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0
const time = (v: unknown) => typeof v === 'string' && /(?:Z|\+00:00)$/.test(v) && Number.isFinite(Date.parse(v))
const outcomes = ['retry', 'unreachable', 'contacted', 'resolved']
function validRecord(v: unknown): v is FollowupRecord {
  return record(v) && count(v.id) && v.id > 0 && count(v.revision) && v.revision > 0 && outcomes.includes(String(v.outcome)) && typeof v.label === 'string' && !!v.label && typeof v.note === 'string' && !!v.note.trim() && Array.from(v.note).length <= 500 && count(v.operator_id) && v.operator_id > 0 && time(v.created_at)
}
function validSnapshot(v: unknown): v is FollowupSnapshot {
  return record(v) && count(v.reservation_id) && v.reservation_id > 0 && ['contact', 'overdue'].includes(String(v.kind)) && typeof v.eligible === 'boolean' && typeof v.completed === 'boolean' && count(v.revision) && time(v.server_now) &&
    (v.latest === null ? v.revision === 0 && !v.completed : validRecord(v.latest) && v.latest.revision === v.revision && v.completed === ['contacted', 'resolved'].includes(v.latest.outcome))
}
function pageOf<T>(v: unknown, page: number, validate: (item: unknown) => item is T): v is FollowupPage<T> {
  return record(v) && Array.isArray(v.items) && v.items.length <= 20 && v.items.every(validate) && count(v.total) && v.page === page && v.page_size === 20 && v.pages === Math.ceil(v.total / 20)
}

export class ReservationFollowupApi {
  constructor(private readonly client: Pick<ApiClient, 'request'>) {}
  async counts(): Promise<FollowupCounts> {
    const operation = 'followup.counts'
    const v = await this.client.request<unknown>({ operation, path: `${root}/summary`, method: 'GET', auth: 'required' })
    if (!record(v) || !time(v.server_now) || !count(v.contact_pending) || !count(v.overdue_pending)) throw new ContractError({ operation })
    return v as FollowupCounts
  }
  async list(kind: FollowupKind, view: 'pending' | 'completed', page = 1): Promise<FollowupPage<FollowupItem>> {
    const operation = 'followup.list'
    const v = await this.client.request<unknown>({ operation, path: root, method: 'GET', auth: 'required', query: { kind, view, page, page_size: 20 } })
    const valid = (item: unknown): item is FollowupItem => record(item) && typeof item.customer_name === 'string' && (item.product_name === null || typeof item.product_name === 'string') && time(item.scheduled_start_at) && validSnapshot(item) && item.kind === kind && item.completed === (view === 'completed') && (view === 'completed' || item.eligible)
    if (!pageOf(v, page, valid) || new Set(v.items.map((i) => i.reservation_id)).size !== v.items.length) throw new ContractError({ operation })
    return v
  }
  async detail(id: number, kind: FollowupKind): Promise<FollowupSnapshot> {
    const operation = 'followup.detail'
    const v = await this.client.request<unknown>({ operation, path: `${root}/${id}/${kind}`, method: 'GET', auth: 'required' })
    if (!validSnapshot(v) || v.reservation_id !== id || v.kind !== kind) throw new ContractError({ operation })
    return v
  }
  async history(id: number, kind: FollowupKind, page = 1): Promise<FollowupPage<FollowupRecord>> {
    const operation = 'followup.history'
    const v = await this.client.request<unknown>({ operation, path: `${root}/${id}/${kind}/history`, method: 'GET', auth: 'required', query: { page, page_size: 20 } })
    if (!pageOf(v, page, validRecord) || new Set(v.items.map((i) => i.revision)).size !== v.items.length) throw new ContractError({ operation })
    return v
  }
  async write(id: number, kind: FollowupKind, body: FollowupWrite): Promise<FollowupSnapshot> {
    const operation = 'followup.write'
    const v = await this.client.request<unknown>({ operation, path: `${root}/${id}/${kind}`, method: 'POST', auth: 'required', body })
    if (!validSnapshot(v) || v.reservation_id !== id || v.kind !== kind) throw new ContractError({ operation })
    return v
  }
}
