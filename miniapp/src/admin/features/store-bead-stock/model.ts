import type { StockEntry, StockWrite, StoreStock } from '@/api/endpoints/store_bead_stock'

export const STOCK_FILTERS = [{ value: 'all', label: '全部' }, { value: 'available', label: '有库存' }, { value: 'empty', label: '无库存' }, { value: 'low', label: '库存不足' }] as const
export type StockFilter = typeof STOCK_FILTERS[number]['value']
export const COLOR_GROUPS = ['全部', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'M'] as const
export const REASONS = [{ value: 'stocktake', label: '库存盘点' }, { value: 'restock', label: '补货入库' }, { value: 'opening', label: '开包领用' }, { value: 'other', label: '其他' }] as const
export const MAX_PACKS = 999999
export type Draft = Readonly<Record<number, string>>
export function colorLabel(item: Pick<StoreStock, 'color_code' | 'color_name' | 'slot_no'>): string {
  return item.color_code || item.color_name || `颜色 ${item.slot_no}`
}
export function matchesStock(item: StoreStock, filter: StockFilter, group: string): boolean {
  if (group !== '全部' && item.color_code?.slice(0, 1).toUpperCase() !== group) return false
  if (filter === 'all') return true
  if (item.packs === null) return false
  return filter === 'available' ? item.packs >= 1 : filter === 'empty' ? item.packs === 0 : item.packs <= 1
}
export function parsePacks(value: string): number | undefined {
  if (!/^\d+$/.test(value)) return undefined
  const n = Number(value)
  return Number.isSafeInteger(n) && n <= MAX_PACKS ? n : undefined
}
export function changes(rows: readonly StoreStock[], draft: Draft): { items: StockWrite['items']; invalid: string[] } {
  const items: StockWrite['items'][number][] = [], invalid: string[] = []
  for (const row of rows) {
    const raw = draft[row.bead_color_id]
    if (raw === undefined) continue
    const packs = parsePacks(raw)
    if (packs === undefined) { invalid.push(colorLabel(row)); continue }
    if (packs !== row.packs) items.push({ bead_color_id: row.bead_color_id, expected_revision: row.revision, packs })
  }
  return { items, invalid }
}
export function summarize(entries: readonly Pick<StockEntry, 'before_packs' | 'after_packs'>[]) {
  return entries.reduce((result, item) => {
    if (item.before_packs === null) { result.initialColors++; result.initialPacks += item.after_packs }
    else if (item.after_packs > item.before_packs) result.added += item.after_packs - item.before_packs
    else result.removed += item.before_packs - item.after_packs
    return result
  }, { added: 0, removed: 0, initialColors: 0, initialPacks: 0 })
}
export function newRequestKey(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const n = Math.floor(Math.random() * 16)
    return (c === 'x' ? n : (n & 3) | 8).toString(16)
  })
}
