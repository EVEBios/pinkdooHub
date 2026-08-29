import type {
  GlobalInventoryTransactionRequest,
  InventorySourceType,
  InventoryTransactionType,
  ProductInventoryTransactionRequest,
} from '@/api/endpoints/inventory'

export type InventoryTransactionTypeFilter = 'all' | InventoryTransactionType
export type InventorySourceTypeFilter = 'all' | InventorySourceType

export interface InventoryFilterDraft {
  readonly transactionType: InventoryTransactionTypeFilter
  readonly sourceType: InventorySourceTypeFilter
  readonly sourceId: string
  readonly productId: string
  readonly createdFrom: string
  readonly createdTo: string
}

export interface InventoryFilters {
  readonly transactionType: InventoryTransactionTypeFilter
  readonly sourceType: InventorySourceTypeFilter
  readonly sourceId?: number
  readonly productId?: number
  readonly createdFrom?: string
  readonly createdTo?: string
}

export interface InventoryInputSnapshot {
  readonly sourceId: string
  readonly productId: string
  readonly createdFrom: string
  readonly createdTo: string
}

export type InventoryFilterParseResult =
  | { readonly filters: InventoryFilters; readonly error?: never }
  | { readonly filters?: never; readonly error: string }

export const EMPTY_INVENTORY_FILTER_DRAFT: InventoryFilterDraft = {
  transactionType: 'all',
  sourceType: 'all',
  sourceId: '',
  productId: '',
  createdFrom: '',
  createdTo: '',
}

export const EMPTY_INVENTORY_FILTERS: InventoryFilters = {
  transactionType: 'all',
  sourceType: 'all',
}

export const EMPTY_INVENTORY_INPUT_SNAPSHOT: InventoryInputSnapshot = {
  sourceId: '',
  productId: '',
  createdFrom: '',
  createdTo: '',
}

const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/

export function createInventoryInputSnapshot(
  draft: InventoryFilterDraft,
  options: { readonly allowProductId: boolean },
): InventoryInputSnapshot {
  return {
    sourceId: draft.sourceType === 'order' ? draft.sourceId.trim() : '',
    productId: options.allowProductId ? draft.productId.trim() : '',
    createdFrom: draft.createdFrom.trim(),
    createdTo: draft.createdTo.trim(),
  }
}

export function inventoryInputSnapshotsEqual(
  left: InventoryInputSnapshot,
  right: InventoryInputSnapshot,
): boolean {
  return left.sourceId === right.sourceId && left.productId === right.productId &&
    left.createdFrom === right.createdFrom && left.createdTo === right.createdTo
}

export function parseInventoryFilters(
  draft: InventoryFilterDraft,
  options: { readonly allowProductId: boolean },
): InventoryFilterParseResult {
  const sourceId = parseOptionalPositiveId(draft.sourceId, 'Order source ID')
  if (typeof sourceId === 'string') return { error: sourceId }
  const productId = options.allowProductId
    ? parseOptionalPositiveId(draft.productId, 'Product ID')
    : undefined
  if (typeof productId === 'string') return { error: productId }
  if (sourceId !== undefined && draft.sourceType !== 'order') {
    return { error: '填写 Order source ID 时，来源必须选择“订单”' }
  }

  const fromText = draft.createdFrom.trim()
  const toText = draft.createdTo.trim()
  const fromDate = parseDate(fromText)
  const toDate = parseDate(toText)
  if (fromText && !fromDate) return { error: '开始日期必须是有效的 YYYY-MM-DD' }
  if (toText && !toDate) return { error: '结束日期必须是有效的 YYYY-MM-DD' }
  if (fromDate && toDate && fromDate.getTime() > toDate.getTime()) {
    return { error: '结束日期不能早于开始日期' }
  }

  return {
    filters: {
      transactionType: draft.transactionType,
      sourceType: draft.sourceType,
      ...(sourceId === undefined ? {} : { sourceId }),
      ...(productId === undefined ? {} : { productId }),
      ...(fromDate ? { createdFrom: fromDate.toISOString() } : {}),
      ...(toDate ? { createdTo: addUtcDay(toDate).toISOString() } : {}),
    },
  }
}

export function buildProductInventoryRequest(
  filters: InventoryFilters,
  page: number,
): ProductInventoryTransactionRequest {
  return buildBaseRequest(filters, page)
}

export function buildGlobalInventoryRequest(
  filters: InventoryFilters,
  page: number,
): GlobalInventoryTransactionRequest {
  return {
    ...buildBaseRequest(filters, page),
    ...(filters.productId === undefined ? {} : { product_id: filters.productId }),
  }
}

export function replaceInventorySourceType(
  filters: InventoryFilters,
  sourceType: InventorySourceTypeFilter,
): InventoryFilters {
  const next = { ...filters, sourceType }
  if (sourceType !== 'order') delete next.sourceId
  return next
}

function buildBaseRequest(
  filters: InventoryFilters,
  page: number,
): ProductInventoryTransactionRequest {
  return {
    page,
    page_size: 20,
    ...(filters.transactionType === 'all' ? {} : { type: filters.transactionType }),
    ...(filters.sourceType === 'all' ? {} : { source_type: filters.sourceType }),
    ...(filters.sourceId === undefined ? {} : { source_id: filters.sourceId }),
    ...(filters.createdFrom ? { created_from: filters.createdFrom } : {}),
    ...(filters.createdTo ? { created_to: filters.createdTo } : {}),
  }
}

function parseOptionalPositiveId(value: string, label: string): number | string | undefined {
  const normalized = value.trim()
  if (!normalized) return undefined
  if (!/^[1-9]\d*$/.test(normalized)) return `${label} 必须是正整数`
  const parsed = Number(normalized)
  return Number.isSafeInteger(parsed) ? parsed : `${label} 超出安全整数范围`
}

function parseDate(value: string): Date | undefined {
  if (!value) return undefined
  const match = DATE_PATTERN.exec(value)
  if (!match) return undefined
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day ? date : undefined
}

function addUtcDay(date: Date): Date {
  return new Date(date.getTime() + 24 * 60 * 60 * 1000)
}
