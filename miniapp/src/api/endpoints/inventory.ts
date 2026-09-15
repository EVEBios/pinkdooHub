import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { components, operations } from '@/api/schema'

export type InventoryAdjustmentRequest = components['schemas']['InventoryAdjustmentCreate']
export type InventoryAdjustment = components['schemas']['InventoryAdjustmentOut']
export type InventoryColorAdjustment = components['schemas']['InventoryColorAdjustmentOut']
export type InventoryTransaction = components['schemas']['InventoryTransactionListItem']
export type InventoryTransactionPage = components['schemas']['Page_InventoryTransactionListItem_']
export type InventoryTransactionType = components['schemas']['InventoryTransactionType']
export type InventorySourceType = components['schemas']['InventorySourceType']
export type ProductInventoryTransactionRequest = NonNullable<operations[
  'list_product_inventory_transactions_api_v1_admin_products_kit__product_id__inventory_transactions_get'
]['parameters']['query']>
export type GlobalInventoryTransactionRequest = NonNullable<operations[
  'list_inventory_transactions_api_v1_admin_inventory_transactions_get'
]['parameters']['query']>

export interface InventoryAdjustmentResult {
  readonly disposition: 'created' | 'replayed'
  readonly adjustment: InventoryAdjustment
}

export interface InventoryColorAdjustmentResult {
  readonly disposition: 'created' | 'replayed'
  readonly adjustment: InventoryColorAdjustment
}

type InventoryApiClient = Pick<ApiClient, 'request' | 'requestWithMeta'>

const UTC_DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/
const ORDER_NO_PATTERN = /^OD[0-9A-HJKMNP-TV-Z]{26}$/
const IDEMPOTENCY_KEY_PATTERN = /^[\x20-\x7E]{1,128}$/
const STOCK_MAX = 999_999

interface ParsedColorMetadata {
  readonly kit_color_id: number | null
  readonly bead_color_id: number | null
  readonly bead_color_slot_no: number | null
  readonly color_code: string | null
  readonly color_name: string | null
  readonly sale_unit_grams: 10 | null
}

export class InventoryApi {
  constructor(private readonly client: InventoryApiClient) {}

  async adjustStock(
    productId: number,
    request: InventoryAdjustmentRequest,
    idempotencyKey: string,
  ): Promise<InventoryAdjustmentResult> {
    assertPositiveSafeInteger(productId, 'Product ID')
    const body = projectAdjustmentRequest(request)
    const normalizedKey = idempotencyKey.trim()
    if (!IDEMPOTENCY_KEY_PATTERN.test(normalizedKey)) {
      throw new Error('Idempotency-Key 必须是 1 至 128 个可打印 ASCII 字符')
    }
    const operation = 'inventory.admin.adjust'
    const response = await this.client.requestWithMeta<unknown>({
      operation,
      path: `/api/v1/admin/products/kit/${productId}/inventory-adjustments`,
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': normalizedKey },
      body,
    })
    const adjustment = parseAdjustment(response.data)
    if (!adjustment || (response.statusCode !== 200 && response.statusCode !== 201)) {
      throw new ContractError({ operation, statusCode: response.statusCode })
    }
    return {
      disposition: response.statusCode === 201 ? 'created' : 'replayed',
      adjustment,
    }
  }

  async adjustColorStock(
    productId: number,
    kitColorId: number,
    request: InventoryAdjustmentRequest,
    idempotencyKey: string,
  ): Promise<InventoryColorAdjustmentResult> {
    assertPositiveSafeInteger(productId, 'Product ID')
    assertPositiveSafeInteger(kitColorId, 'Kit Color ID')
    const body = projectAdjustmentRequest(request)
    const normalizedKey = idempotencyKey.trim()
    if (!IDEMPOTENCY_KEY_PATTERN.test(normalizedKey)) {
      throw new Error('Idempotency-Key 必须是 1 至 128 个可打印 ASCII 字符')
    }
    const operation = 'inventory.admin.color.adjust'
    const response = await this.client.requestWithMeta<unknown>({
      operation,
      path: `/api/v1/admin/products/kit/${productId}/colors/${kitColorId}/inventory-adjustments`,
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': normalizedKey },
      body,
    })
    const adjustment = parseColorAdjustment(response.data)
    if (!adjustment || adjustment.product_id !== productId ||
      adjustment.kit_color_id !== kitColorId ||
      (response.statusCode !== 200 && response.statusCode !== 201)) {
      throw new ContractError({ operation, statusCode: response.statusCode })
    }
    return {
      disposition: response.statusCode === 201 ? 'created' : 'replayed',
      adjustment,
    }
  }

  async listProductTransactions(
    productId: number,
    request: ProductInventoryTransactionRequest = {},
  ): Promise<InventoryTransactionPage> {
    assertPositiveSafeInteger(productId, 'Product ID')
    const operation = 'inventory.admin.product_transactions.list'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/products/kit/${productId}/inventory-transactions`,
      method: 'GET',
      auth: 'required',
      query: projectProductTransactionRequest(request),
    })
    const page = parseTransactionPage(result)
    if (!page) throw new ContractError({ operation })
    return page
  }

  async listProductColorTransactions(
    productId: number,
    kitColorId: number,
    request: ProductInventoryTransactionRequest = {},
  ): Promise<InventoryTransactionPage> {
    assertPositiveSafeInteger(productId, 'Product ID')
    assertPositiveSafeInteger(kitColorId, 'Kit Color ID')
    const operation = 'inventory.admin.product_color_transactions.list'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/products/kit/${productId}/colors/${kitColorId}/inventory-transactions`,
      method: 'GET',
      auth: 'required',
      query: projectProductTransactionRequest(request),
    })
    const page = parseTransactionPage(result)
    if (!page || page.items.some((item) => (
      item.product_id !== productId || item.kit_color_id !== kitColorId
    ))) {
      throw new ContractError({ operation })
    }
    return page
  }

  async listTransactions(
    request: GlobalInventoryTransactionRequest = {},
  ): Promise<InventoryTransactionPage> {
    const operation = 'inventory.admin.transactions.list'
    const result = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/inventory-transactions',
      method: 'GET',
      auth: 'required',
      query: projectGlobalTransactionRequest(request),
    })
    const page = parseTransactionPage(result)
    if (!page) throw new ContractError({ operation })
    return page
  }
}

function projectAdjustmentRequest(request: InventoryAdjustmentRequest): InventoryAdjustmentRequest {
  if (!Number.isSafeInteger(request.change) || request.change === 0 ||
    request.change < -STOCK_MAX || request.change > STOCK_MAX) {
    throw new Error('库存变化量必须是 -999999 至 999999 之间的非零整数')
  }
  const reason = request.reason.trim()
  if (reason.length < 1 || reason.length > 256) {
    throw new Error('库存调整原因必须是 1 至 256 个字符')
  }
  return { change: request.change, reason }
}

function projectProductTransactionRequest(
  request: ProductInventoryTransactionRequest,
): ProductInventoryTransactionRequest {
  return projectTransactionRequest(request)
}

function projectGlobalTransactionRequest(
  request: GlobalInventoryTransactionRequest,
): GlobalInventoryTransactionRequest {
  return {
    ...projectTransactionRequest(request),
    ...(request.product_id === undefined || request.product_id === null
      ? {}
      : { product_id: request.product_id }),
    ...(request.kit_color_id === undefined || request.kit_color_id === null
      ? {}
      : { kit_color_id: request.kit_color_id }),
  }
}

function projectTransactionRequest<T extends ProductInventoryTransactionRequest>(request: T): T {
  return {
    ...(request.page === undefined ? {} : { page: request.page }),
    ...(request.page_size === undefined ? {} : { page_size: request.page_size }),
    ...(request.type === undefined || request.type === null ? {} : { type: request.type }),
    ...(request.source_type === undefined || request.source_type === null
      ? {}
      : { source_type: request.source_type }),
    ...(request.source_id === undefined || request.source_id === null
      ? {}
      : { source_id: request.source_id }),
    ...(request.created_from === undefined || request.created_from === null
      ? {}
      : { created_from: request.created_from }),
    ...(request.created_to === undefined || request.created_to === null
      ? {}
      : { created_to: request.created_to }),
  } as T
}

function parseAdjustment(value: unknown): InventoryAdjustment | undefined {
  if (!isRecord(value) || !isPositiveSafeInteger(value.product_id) ||
    !isStock(value.stock)) return undefined
  const transaction = parseTransaction(value.transaction)
  if (!transaction || transaction.product_id !== value.product_id ||
    transaction.transaction_type !== 'admin_adjustment' ||
    transaction.after_quantity !== value.stock) return undefined
  return { product_id: value.product_id, stock: value.stock, transaction }
}

function parseColorAdjustment(value: unknown): InventoryColorAdjustment | undefined {
  if (!isRecord(value) ||
    !isPositiveSafeInteger(value.product_id) ||
    !isPositiveSafeInteger(value.kit_color_id) ||
    !isPositiveSafeInteger(value.bead_color_id) ||
    !isPositiveSafeInteger(value.bead_color_slot_no) || value.bead_color_slot_no > 221 ||
    !(value.color_code === null || isBoundedString(value.color_code, 1, 50)) ||
    !(value.color_name === null || isBoundedString(value.color_name, 1, 100)) ||
    value.sale_unit_grams !== 10 ||
    !isStock(value.stock_units)) return undefined
  const transaction = parseTransaction(value.transaction)
  if (!transaction || transaction.product_id !== value.product_id ||
    transaction.kit_color_id !== value.kit_color_id ||
    transaction.bead_color_id !== value.bead_color_id ||
    transaction.bead_color_slot_no !== value.bead_color_slot_no ||
    transaction.color_code !== value.color_code ||
    transaction.color_name !== value.color_name ||
    transaction.sale_unit_grams !== value.sale_unit_grams ||
    transaction.transaction_type !== 'admin_adjustment' ||
    transaction.after_quantity !== value.stock_units) return undefined
  return {
    product_id: value.product_id,
    kit_color_id: value.kit_color_id,
    bead_color_id: value.bead_color_id,
    bead_color_slot_no: value.bead_color_slot_no,
    color_code: value.color_code,
    color_name: value.color_name,
    sale_unit_grams: 10,
    stock_units: value.stock_units,
    transaction,
  }
}

function parseTransactionPage(value: unknown): InventoryTransactionPage | undefined {
  if (!isRecord(value) || !Array.isArray(value.items) ||
    !isNonNegativeSafeInteger(value.total) ||
    !isPositiveSafeInteger(value.page) ||
    !isPositiveSafeInteger(value.page_size) || value.page_size > 100 ||
    !isNonNegativeSafeInteger(value.pages) ||
    value.pages !== Math.ceil(value.total / value.page_size) ||
    value.items.length > value.page_size) return undefined
  const items: InventoryTransaction[] = []
  for (const item of value.items) {
    const parsed = parseTransaction(item)
    if (!parsed) return undefined
    items.push(parsed)
  }
  return {
    items,
    total: value.total,
    page: value.page,
    page_size: value.page_size,
    pages: value.pages,
  }
}

function parseTransaction(value: unknown): InventoryTransaction | undefined {
  if (!isRecord(value) ||
    !isPositiveSafeInteger(value.id) ||
    !isPositiveSafeInteger(value.product_id) ||
    !hasOwn(value, 'kit_color_id') ||
    !hasOwn(value, 'bead_color_id') ||
    !hasOwn(value, 'bead_color_slot_no') ||
    !hasOwn(value, 'color_code') ||
    !hasOwn(value, 'color_name') ||
    !hasOwn(value, 'sale_unit_grams') ||
    !hasConsistentColorMetadata(value) ||
    !isTransactionType(value.transaction_type) ||
    !isInventoryChange(value.change_quantity) ||
    !isStock(value.before_quantity) || !isStock(value.after_quantity) ||
    value.after_quantity !== value.before_quantity + value.change_quantity ||
    !isBoundedString(value.reason, 1, 256) ||
    !isSourceType(value.source_type) ||
    !(value.source_id === null || isPositiveSafeInteger(value.source_id)) ||
    !(value.source_order_no === null || isOrderNo(value.source_order_no)) ||
    !(value.operator_id === null || isPositiveSafeInteger(value.operator_id)) ||
    !(value.operator_nickname === null || isBoundedString(value.operator_nickname, 1, 32)) ||
    !isUtcDatetime(value.created_at) ||
    !hasConsistentMetadata(value)) return undefined
  return {
    id: value.id,
    product_id: value.product_id,
    kit_color_id: value.kit_color_id,
    bead_color_id: value.bead_color_id,
    bead_color_slot_no: value.bead_color_slot_no,
    color_code: value.color_code,
    color_name: value.color_name,
    sale_unit_grams: value.sale_unit_grams,
    transaction_type: value.transaction_type,
    change_quantity: value.change_quantity,
    before_quantity: value.before_quantity,
    after_quantity: value.after_quantity,
    reason: value.reason,
    source_type: value.source_type,
    source_id: value.source_id,
    source_order_no: value.source_order_no,
    operator_id: value.operator_id,
    operator_nickname: value.operator_nickname,
    created_at: value.created_at,
  }
}

function hasConsistentColorMetadata(
  value: Record<string, unknown>,
): value is Record<string, unknown> & ParsedColorMetadata {
  if (value.kit_color_id === null) {
    return value.bead_color_id === null && value.bead_color_slot_no === null &&
      value.color_code === null && value.color_name === null && value.sale_unit_grams === null
  }
  return isPositiveSafeInteger(value.kit_color_id) &&
    isPositiveSafeInteger(value.bead_color_id) &&
    isPositiveSafeInteger(value.bead_color_slot_no) && value.bead_color_slot_no <= 221 &&
    (value.color_code === null || isBoundedString(value.color_code, 1, 50)) &&
    (value.color_name === null || isBoundedString(value.color_name, 1, 100)) &&
    value.sale_unit_grams === 10
}

function hasConsistentMetadata(value: Record<string, unknown>): boolean {
  if (value.transaction_type === 'opening_balance') {
    return value.source_type === 'migration' && value.before_quantity === 0 &&
      typeof value.change_quantity === 'number' && value.change_quantity > 0 &&
      value.source_id === null && value.source_order_no === null &&
      value.operator_id === null && value.operator_nickname === null
  }
  if (value.transaction_type === 'admin_adjustment') {
    return value.source_type === 'admin' &&
      value.source_id === null && value.source_order_no === null &&
      isPositiveSafeInteger(value.operator_id) && isBoundedString(value.operator_nickname, 1, 32)
  }
  const positive = value.transaction_type === 'order_cancellation_restore' ||
    value.transaction_type === 'order_refund_restore'
  return value.source_type === 'order' && isPositiveSafeInteger(value.source_id) &&
    isOrderNo(value.source_order_no) && typeof value.change_quantity === 'number' &&
    (positive ? value.change_quantity > 0 : value.change_quantity < 0) &&
    ((value.operator_id === null && value.operator_nickname === null) ||
      (isPositiveSafeInteger(value.operator_id) && isBoundedString(value.operator_nickname, 1, 32)))
}

function assertPositiveSafeInteger(value: number, label: string): void {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${label} 必须是正安全整数`)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function isPositiveSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function isStock(value: unknown): value is number {
  return isNonNegativeSafeInteger(value) && value <= STOCK_MAX
}

function isInventoryChange(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value !== 0 &&
    value >= -STOCK_MAX && value <= STOCK_MAX
}

function isBoundedString(value: unknown, min: number, max: number): value is string {
  return typeof value === 'string' && value.length >= min && value.length <= max
}

function isOrderNo(value: unknown): value is string {
  return typeof value === 'string' && ORDER_NO_PATTERN.test(value)
}

function isUtcDatetime(value: unknown): value is string {
  return typeof value === 'string' && UTC_DATETIME_PATTERN.test(value) && !Number.isNaN(Date.parse(value))
}

function isTransactionType(value: unknown): value is InventoryTransactionType {
  return value === 'opening_balance' || value === 'admin_adjustment' ||
    value === 'order_deduction' || value === 'order_cancellation_restore' ||
    value === 'order_refund_restore'
}

function isSourceType(value: unknown): value is InventorySourceType {
  return value === 'migration' || value === 'admin' || value === 'order'
}
