import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { components } from '@/api/generated/schema'

export type StoreStock = components['schemas']['StoreBeadStockOut']
export type StockWrite = components['schemas']['StoreBeadStockWrite']
export type StockBatch = components['schemas']['StoreBeadStockBatchOut']
export type StockBatchSummary = components['schemas']['StoreBeadStockBatchSummary']
export type StockEntry = components['schemas']['StoreBeadStockEntryOut']
export type StockPage<T> = { items: T[]; page: number; page_size: number; total: number; pages: number }
const root = '/api/v1/admin/store-bead-stock'
const record = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null
const integer = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0
const packs = (v: unknown): v is number => integer(v) && v <= 999999
const nullableText = (v: unknown) => v === null || typeof v === 'string'
const color = (v: unknown): v is Record<string, unknown> => record(v) && integer(v.bead_color_id) && v.bead_color_id > 0 && integer(v.slot_no) && v.slot_no >= 1 && v.slot_no <= 221 && nullableText(v.color_code) && nullableText(v.color_name)
const stock = (v: unknown): v is StoreStock => color(v) && integer(v.revision) && (v.packs === null ? v.revision === 0 : packs(v.packs) && v.revision > 0)
const summary = (v: unknown): v is StockBatchSummary => record(v) && integer(v.id) && v.id > 0 && integer(v.operator_id) && v.operator_id > 0 && typeof v.operator_name === 'string' && typeof v.created_at === 'string' && /(?:Z|\+00:00)$/.test(v.created_at) && Number.isFinite(Date.parse(v.created_at)) && ['stocktake', 'restock', 'opening', 'other'].includes(String(v.reason)) && typeof v.note === 'string' && integer(v.changed_colors) && v.changed_colors > 0 && v.changed_colors <= 221
const entry = (v: unknown): v is StockEntry => color(v) && packs(v.after_packs) && integer(v.revision) && (v.before_packs === null ? v.revision === 1 : packs(v.before_packs) && v.before_packs !== v.after_packs && v.revision > 1)
function batch(v: unknown): v is StockBatch {
  if (!record(v) || !Array.isArray(v.items)) return false
  const items: unknown[] = v.items
  return summary(v) && items.length === v.changed_colors && items.every(entry) && new Set(items.map(i => i.bead_color_id)).size === items.length
}
function pageOf<T>(v: unknown, page: number, size: number, check: (item: unknown) => item is T): v is StockPage<T> {
  return record(v) && Array.isArray(v.items) && v.items.length <= size && v.items.every(check) && integer(v.total) && v.page === page && v.page_size === size && v.pages === Math.ceil(v.total / size)
}

export class StoreBeadStockApi {
  constructor(private readonly client: Pick<ApiClient, 'request'>) {}
  async list(): Promise<StoreStock[]> {
    const operation = 'storeStock.list'
    const v = await this.client.request<unknown>({ operation, path: root, method: 'GET', auth: 'required', query: { page: 1, page_size: 221 } })
    if (!pageOf(v, 1, 221, stock) || v.total !== 221 || v.items.length !== 221 || new Set(v.items.map(i => i.bead_color_id)).size !== 221 || new Set(v.items.map(i => i.slot_no)).size !== 221) throw new ContractError({ operation })
    return v.items
  }
  async write(body: StockWrite): Promise<StockBatch> {
    const operation = 'storeStock.write'
    const v = await this.client.request<unknown>({ operation, path: `${root}/batches`, method: 'POST', auth: 'required', body })
    if (!batch(v) || v.reason !== (body.reason ?? 'stocktake') || v.note !== (body.note ?? '').trim() || v.items.length !== body.items.length || !body.items.every(i => v.items.some(e => e.bead_color_id === i.bead_color_id && e.after_packs === i.packs && e.revision === i.expected_revision + 1))) throw new ContractError({ operation })
    return v
  }
  async byRequest(key: string): Promise<StockBatch> {
    const operation = 'storeStock.byRequest'
    const v = await this.client.request<unknown>({ operation, path: `${root}/batches/by-request/${encodeURIComponent(key)}`, method: 'GET', auth: 'required' })
    if (!batch(v)) throw new ContractError({ operation })
    return v
  }
  async history(page = 1): Promise<StockPage<StockBatchSummary>> {
    const operation = 'storeStock.history'
    const v = await this.client.request<unknown>({ operation, path: `${root}/batches`, method: 'GET', auth: 'required', query: { page, page_size: 20 } })
    if (!pageOf(v, page, 20, summary)) throw new ContractError({ operation })
    return v
  }
  async detail(id: number): Promise<StockBatch> {
    const operation = 'storeStock.detail'
    const v = await this.client.request<unknown>({ operation, path: `${root}/batches/${id}`, method: 'GET', auth: 'required' })
    if (!batch(v) || v.id !== id) throw new ContractError({ operation })
    return v
  }
}
