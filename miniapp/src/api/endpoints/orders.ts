import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { components, operations } from '@/api/schema'

export type OrderCreateRequest = operations[
  'create_order_api_v1_orders_post'
]['requestBody']['content']['application/json']
export type OrderListRequest = NonNullable<operations[
  'list_orders_api_v1_orders_get'
]['parameters']['query']>
export type OrderDetail = components['schemas']['OrderDetailOut']
export type OrderItem = components['schemas']['OrderItemOut']
export type OrderListItem = components['schemas']['OrderListItemOut']
export type OrderListPage = components['schemas']['Page_OrderListItemOut_']
export type OrderStatusResult = components['schemas']['OrderStatusOut']
export type AdminOrderListRequest = NonNullable<operations[
  'list_admin_orders_api_v1_admin_orders_get'
]['parameters']['query']>
export type AdminOrderListItem = components['schemas']['AdminOrderListItemOut']
export type AdminOrderListPage = components['schemas']['Page_AdminOrderListItemOut_']
export type AdminOrderDetail = components['schemas']['AdminOrderDetailOut']

type OrderApiClient = Pick<ApiClient, 'request'>

const ORDER_STATUS_LABELS = {
  pending: '待支付',
  paid: '已支付',
  cancelled: '已取消',
  completed: '已完成',
} as const

const DAY_TYPE_LABELS = {
  weekday: '工作日',
  holiday: '节假日',
} as const

const ORDER_NO_PATTERN = /^OD[0-9A-HJKMNP-TV-Z]{26}$/
const UTC_DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/
const ORDER_AMOUNT_MAX_CENTS = 9_999_999_999
const PRODUCT_PRICE_MAX_CENTS = 9_999_900

export class OrderApi {
  constructor(private readonly client: OrderApiClient) {}

  async createOrder(request: OrderCreateRequest): Promise<OrderDetail> {
    const operation = 'orders.create'
    const result = await this.client.request<unknown>({
      operation,
      path: '/api/v1/orders',
      method: 'POST',
      auth: 'required',
      body: projectOrderCreateRequest(request),
    })
    const parsed = parseOrderDetail(result)
    if (!parsed) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async listOrders(request: OrderListRequest = {}): Promise<OrderListPage> {
    const operation = 'orders.list'
    const result = await this.client.request<unknown>({
      operation,
      path: '/api/v1/orders',
      method: 'GET',
      auth: 'required',
      query: projectOrderListRequest(request),
    })
    const parsed = parseOrderListPage(result)
    if (!parsed) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async getOrderDetail(orderId: number): Promise<OrderDetail> {
    assertOrderId(orderId)
    const operation = 'orders.detail'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/orders/${orderId}`,
      method: 'GET',
      auth: 'required',
    })
    const parsed = parseOrderDetail(result)
    if (!parsed) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async cancelOrder(orderId: number): Promise<OrderStatusResult> {
    assertOrderId(orderId)
    const operation = 'orders.cancel'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/orders/${orderId}/cancel`,
      method: 'PATCH',
      auth: 'required',
    })
    const parsed = parseOrderStatusResult(result)
    if (!parsed || parsed.status.value !== 'cancelled') {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async listAdminOrders(request: AdminOrderListRequest = {}): Promise<AdminOrderListPage> {
    const operation = 'orders.admin.list'
    const result = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/orders',
      method: 'GET',
      auth: 'required',
      query: projectAdminOrderListRequest(request),
    })
    const parsed = parseAdminOrderListPage(result)
    if (!parsed) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async getAdminOrderDetail(orderId: number): Promise<AdminOrderDetail> {
    assertOrderId(orderId)
    const operation = 'orders.admin.detail'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/orders/${orderId}`,
      method: 'GET',
      auth: 'required',
    })
    const parsed = parseAdminOrderDetail(result)
    if (!parsed) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async markOrderPaid(orderId: number): Promise<OrderStatusResult> {
    return this.transitionAdminOrder(orderId, 'paid')
  }

  async completeOrder(orderId: number): Promise<OrderStatusResult> {
    return this.transitionAdminOrder(orderId, 'completed')
  }

  private async transitionAdminOrder(
    orderId: number,
    targetStatus: 'paid' | 'completed',
  ): Promise<OrderStatusResult> {
    assertOrderId(orderId)
    const action = targetStatus === 'paid' ? 'markPaid' : 'complete'
    const pathAction = targetStatus === 'paid' ? 'paid' : 'complete'
    const operation = `orders.admin.${action}`
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/orders/${orderId}/${pathAction}`,
      method: 'PATCH',
      auth: 'required',
    })
    const parsed = parseOrderStatusResult(result)
    if (!parsed || parsed.status.value !== targetStatus) {
      throw new ContractError({ operation })
    }
    return parsed
  }
}

function projectAdminOrderListRequest(request: AdminOrderListRequest): AdminOrderListRequest {
  return {
    ...(request.page === undefined ? {} : { page: request.page }),
    ...(request.page_size === undefined ? {} : { page_size: request.page_size }),
    ...(request.status === undefined || request.status === null ? {} : { status: request.status }),
    ...(request.order_no === undefined || request.order_no === null ? {} : { order_no: request.order_no }),
    ...(request.product_name === undefined || request.product_name === null
      ? {}
      : { product_name: request.product_name }),
    ...(request.user_id === undefined || request.user_id === null ? {} : { user_id: request.user_id }),
    ...(request.created_from === undefined || request.created_from === null
      ? {}
      : { created_from: request.created_from }),
    ...(request.created_to === undefined || request.created_to === null
      ? {}
      : { created_to: request.created_to }),
  }
}

function projectOrderListRequest(request: OrderListRequest): OrderListRequest {
  return {
    ...(request.page === undefined ? {} : { page: request.page }),
    ...(request.page_size === undefined ? {} : { page_size: request.page_size }),
    ...(request.status === undefined || request.status === null ? {} : { status: request.status }),
  }
}

function projectOrderCreateRequest(request: OrderCreateRequest): OrderCreateRequest {
  const items = request.items.map((item) => {
    const projected = {
      product_id: item.product_id,
      quantity: item.quantity,
    }
    return item.experience_option_id === undefined || item.experience_option_id === null
      ? projected
      : { ...projected, experience_option_id: item.experience_option_id }
  })

  return request.remark === undefined
    ? { items }
    : { items, remark: request.remark }
}

export function parseOrderDetail(value: unknown): OrderDetail | undefined {
  if (!isRecord(value) || !(
    isPositiveInteger(value.id) &&
    typeof value.order_no === 'string' && ORDER_NO_PATTERN.test(value.order_no) &&
    hasOwn(value, 'remark') && isNullableBoundedText(value.remark, 500) &&
    isUtcDatetime(value.created_at) &&
    isUtcDatetime(value.updated_at) &&
    Array.isArray(value.items) && value.items.length >= 1 && value.items.length <= 10
  )) {
    return undefined
  }

  const status = parseOrderStatus(value.status)
  const items = value.items.map(parseOrderItem)
  const totalAmountCents = parseMoneyCents(value.total_amount, ORDER_AMOUNT_MAX_CENTS)
  if (
    !status ||
    items.some((item) => item === undefined) ||
    totalAmountCents === undefined
  ) {
    return undefined
  }

  const parsedItems = items as OrderItem[]
  const subtotalCents = parsedItems.reduce((total, item) => {
    return total + (parseMoneyCents(item.subtotal, ORDER_AMOUNT_MAX_CENTS) ?? 0)
  }, 0)
  if (totalAmountCents !== subtotalCents) {
    return undefined
  }

  return {
    id: value.id,
    order_no: value.order_no,
    total_amount: value.total_amount as string,
    status,
    remark: value.remark as string | null,
    items: parsedItems,
    created_at: value.created_at as string,
    updated_at: value.updated_at as string,
  }
}

export function parseOrderListPage(value: unknown): OrderListPage | undefined {
  if (!isRecord(value) || !(
    Array.isArray(value.items) &&
    isNonNegativeInteger(value.total) &&
    isPositiveInteger(value.page) &&
    isPositiveInteger(value.page_size) && value.page_size <= 100 &&
    isNonNegativeInteger(value.pages)
  )) {
    return undefined
  }
  const items = value.items.map(parseOrderListItem)
  const expectedPages = Math.ceil(value.total / value.page_size)
  if (
    items.some((item) => item === undefined) ||
    items.length > value.page_size ||
    items.length > value.total ||
    value.pages !== expectedPages
  ) {
    return undefined
  }
  return {
    items: items as OrderListItem[],
    total: value.total,
    page: value.page,
    page_size: value.page_size,
    pages: value.pages,
  }
}

export function parseOrderStatusResult(value: unknown): OrderStatusResult | undefined {
  if (!isRecord(value) || !(
    isPositiveInteger(value.id) &&
    typeof value.order_no === 'string' && ORDER_NO_PATTERN.test(value.order_no) &&
    isUtcDatetime(value.updated_at)
  )) {
    return undefined
  }
  const status = parseOrderStatus(value.status)
  return status
    ? {
        id: value.id,
        order_no: value.order_no,
        status,
        updated_at: value.updated_at,
      }
    : undefined
}

export function parseAdminOrderListPage(value: unknown): AdminOrderListPage | undefined {
  if (!isRecord(value) || !(
    Array.isArray(value.items) &&
    isNonNegativeInteger(value.total) &&
    isPositiveInteger(value.page) &&
    isPositiveInteger(value.page_size) && value.page_size <= 100 &&
    isNonNegativeInteger(value.pages)
  )) {
    return undefined
  }
  const items = value.items.map(parseAdminOrderListItem)
  const expectedPages = Math.ceil(value.total / value.page_size)
  if (
    items.some((item) => item === undefined) ||
    items.length > value.page_size ||
    items.length > value.total ||
    value.pages !== expectedPages
  ) {
    return undefined
  }
  return {
    items: items as AdminOrderListItem[],
    total: value.total,
    page: value.page,
    page_size: value.page_size,
    pages: value.pages,
  }
}

export function parseAdminOrderDetail(value: unknown): AdminOrderDetail | undefined {
  if (!isRecord(value) || !(
    isPositiveInteger(value.user_id) &&
    isBoundedText(value.user_nickname, 32)
  )) {
    return undefined
  }
  const detail = parseOrderDetail(value)
  return detail
    ? {
        ...detail,
        user_id: value.user_id,
        user_nickname: value.user_nickname,
      }
    : undefined
}

function parseAdminOrderListItem(value: unknown): AdminOrderListItem | undefined {
  if (!isRecord(value) || !(
    isPositiveInteger(value.user_id) &&
    isBoundedText(value.user_nickname, 32)
  )) {
    return undefined
  }
  const item = parseOrderListItem(value)
  return item
    ? {
        ...item,
        user_id: value.user_id,
        user_nickname: value.user_nickname,
      }
    : undefined
}

function parseOrderListItem(value: unknown): OrderListItem | undefined {
  if (!isRecord(value) || !(
    isPositiveInteger(value.id) &&
    typeof value.order_no === 'string' && ORDER_NO_PATTERN.test(value.order_no) &&
    isPositiveInteger(value.item_count) && value.item_count <= 10 &&
    isUtcDatetime(value.created_at) &&
    isUtcDatetime(value.updated_at) &&
    parseMoneyCents(value.total_amount, ORDER_AMOUNT_MAX_CENTS) !== undefined
  )) {
    return undefined
  }
  const status = parseOrderStatus(value.status)
  return status
    ? {
        id: value.id,
        order_no: value.order_no,
        total_amount: value.total_amount as string,
        status,
        item_count: value.item_count,
        created_at: value.created_at,
        updated_at: value.updated_at,
      }
    : undefined
}

function parseOrderItem(value: unknown): OrderItem | undefined {
  if (!isRecord(value) || !(
    isPositiveInteger(value.id) &&
    isPositiveInteger(value.product_id) &&
    hasOwn(value, 'experience_option_id') &&
    (value.experience_option_id === null || isPositiveInteger(value.experience_option_id)) &&
    isBoundedText(value.product_name, 100) &&
    hasOwn(value, 'option_duration_minutes') &&
    hasOwn(value, 'option_participants') &&
    hasOwn(value, 'option_day_type') &&
    isPositiveInteger(value.quantity) && value.quantity <= 99
  )) {
    return undefined
  }

  const productPriceCents = parseMoneyCents(value.product_price, PRODUCT_PRICE_MAX_CENTS)
  const subtotalCents = parseMoneyCents(value.subtotal, ORDER_AMOUNT_MAX_CENTS)
  if (
    productPriceCents === undefined ||
    subtotalCents === undefined ||
    subtotalCents !== productPriceCents * value.quantity
  ) {
    return undefined
  }

  let optionDurationMinutes: number | null
  let optionParticipants: number | null
  let optionDayType: OrderItem['option_day_type']
  if (value.experience_option_id === null) {
    if (
      value.option_duration_minutes !== null ||
      value.option_participants !== null ||
      value.option_day_type !== null
    ) {
      return undefined
    }
    optionDurationMinutes = null
    optionParticipants = null
    optionDayType = null
  } else {
    if (!isPositiveInteger(value.option_duration_minutes) || !isPositiveInteger(value.option_participants)) {
      return undefined
    }
    const parsedDayType = parseDayType(value.option_day_type)
    if (!parsedDayType) {
      return undefined
    }
    optionDurationMinutes = value.option_duration_minutes
    optionParticipants = value.option_participants
    optionDayType = parsedDayType
  }

  return {
    id: value.id,
    product_id: value.product_id,
    experience_option_id: value.experience_option_id,
    product_name: value.product_name,
    option_duration_minutes: optionDurationMinutes,
    option_participants: optionParticipants,
    option_day_type: optionDayType,
    product_price: value.product_price as string,
    quantity: value.quantity,
    subtotal: value.subtotal as string,
  }
}

function parseOrderStatus(value: unknown): OrderDetail['status'] | undefined {
  if (!isRecord(value) || typeof value.value !== 'string' || typeof value.label !== 'string') {
    return undefined
  }
  const status = value.value as keyof typeof ORDER_STATUS_LABELS
  if (!(status in ORDER_STATUS_LABELS) || value.label !== ORDER_STATUS_LABELS[status]) {
    return undefined
  }
  return { value: status, label: value.label }
}

function parseDayType(value: unknown): NonNullable<OrderItem['option_day_type']> | undefined {
  if (!isRecord(value) || typeof value.value !== 'string' || typeof value.label !== 'string') {
    return undefined
  }
  const dayType = value.value as keyof typeof DAY_TYPE_LABELS
  if (!(dayType in DAY_TYPE_LABELS) || value.label !== DAY_TYPE_LABELS[dayType]) {
    return undefined
  }
  return { value: dayType, label: value.label }
}

function parseMoneyCents(value: unknown, maxCents: number): number | undefined {
  if (typeof value !== 'string') {
    return undefined
  }
  const match = /^(0|[1-9]\d*)\.(\d{2})$/.exec(value)
  if (!match) {
    return undefined
  }
  const cents = Number(match[1]) * 100 + Number(match[2])
  return Number.isSafeInteger(cents) && cents > 0 && cents <= maxCents
    ? cents
    : undefined
}

function isUtcDatetime(value: unknown): value is string {
  return typeof value === 'string' &&
    UTC_DATETIME_PATTERN.test(value) &&
    !Number.isNaN(Date.parse(value))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function assertOrderId(orderId: number): void {
  if (!isPositiveInteger(orderId)) {
    throw new Error('Order ID 必须是正整数')
  }
}

function isBoundedText(value: unknown, maxLength: number): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= maxLength
}

function isNullableBoundedText(value: unknown, maxLength: number): value is string | null {
  return value === null || (typeof value === 'string' && value.length > 0 && value.length <= maxLength)
}
