import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import { parseUserProfile } from '@/api/endpoints/auth'
import {
  parseAdminOrderDetail,
  type OrderCreateRequest,
} from '@/api/endpoints/orders'
import type { components } from '@/api/schema'

export type WalletStatus = components['schemas']['WalletStatus']
export type WalletTransactionType = components['schemas']['WalletTransactionType']
export type WalletTransactionDirection = components['schemas']['WalletTransactionOut']['direction']
export type WalletTransactionSourceType = components['schemas']['WalletTransactionSourceType']
export type PaymentMethod = components['schemas']['PaymentMethod']
export type PaymentPurpose = components['schemas']['PaymentPurpose']
export type PaymentStatus = components['schemas']['PaymentStatus']
export type RefundStatus = components['schemas']['RefundStatus']
export type WalletCapabilities = components['schemas']['WalletCapabilitiesOut']
export type WalletSummary = components['schemas']['WalletSummaryOut']
export type MemberWallet = components['schemas']['MemberOut']
export type AdminWalletUser = components['schemas']['UserListItem']
export type AdminUserWallet = components['schemas']['AdminUserWalletOut']
export type WalletTransaction = components['schemas']['WalletTransactionOut']
export type WalletTransactionPage = components['schemas']['Page_WalletTransactionOut_']
export type PaymentRecord = components['schemas']['PaymentOut']
export type RefundRecord = components['schemas']['RefundOut']
export type OrderFinancial = components['schemas']['OrderFinancialOut']
export type WalletPaymentResult = components['schemas']['WalletPaymentOut']
export type WalletAdjustmentResult = components['schemas']['WalletAdjustmentOut']
export type AssistedWalletOrderResult = components['schemas']['AssistedWalletOrderOut']

export interface WalletTransactionRequest {
  readonly page?: number
  readonly page_size?: number
}

type WalletApiClient = Pick<ApiClient, 'request'>
const ORDER_NO_PATTERN = /^OD[0-9A-HJKMNP-TV-Z]{26}$/
const ASSISTED_ORDER_NON_COLOR_ITEM_LIMIT = 10
const ASSISTED_ORDER_COLOR_ITEM_LIMIT = 20
const ASSISTED_ORDER_ITEM_LIMIT = (
  ASSISTED_ORDER_NON_COLOR_ITEM_LIMIT + ASSISTED_ORDER_COLOR_ITEM_LIMIT
)

export class WalletApi {
  constructor(private readonly client: WalletApiClient) {}

  async getMemberWallet(): Promise<MemberWallet> {
    return this.requestParsed('wallet.member', '/api/v1/wallet', parseMemberWallet)
  }

  async listWalletTransactions(request: WalletTransactionRequest = {}): Promise<WalletTransactionPage> {
    const operation = 'wallet.transactions.list'
    const result = await this.client.request<unknown>({
      operation,
      path: '/api/v1/wallet/transactions',
      method: 'GET',
      auth: 'required',
      query: projectPageRequest(request),
    })
    return requireParsed(operation, result, parseWalletTransactionPage)
  }

  async createRecharge(amount: string, idempotencyKey: string): Promise<void> {
    const amountCents = assertMoneyInput(amount, false)
    if (amountCents < 100 || amountCents > 100000) {
      throw new Error('单笔充值金额必须为 1.00–1000.00 元')
    }
    assertIdempotencyKey(idempotencyKey)
    const operation = 'wallet.recharge.create'
    const result = await this.client.request<unknown>({
      operation,
      path: '/api/v1/wallet/recharges',
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { amount },
    })
    if (result !== null) throw new ContractError({ operation })
  }

  async getOrderFinancials(orderId: number): Promise<OrderFinancial> {
    assertPositiveSafeInteger(orderId, 'Order ID')
    const operation = 'payments.order.financials'
    const result = await this.requestParsed(
      operation,
      `/api/v1/orders/${orderId}/financials`,
      parseOrderFinancial,
    )
    if (result.order_id !== orderId) throw new ContractError({ operation })
    return result
  }

  async payOrderWithWallet(
    orderId: number,
    idempotencyKey: string,
    tableSessionNo?: string,
  ): Promise<WalletPaymentResult> {
    assertPositiveSafeInteger(orderId, 'Order ID')
    assertIdempotencyKey(idempotencyKey)
    const operation = 'payments.order.wallet'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/orders/${orderId}/payments/wallet`,
      method: 'POST',
      auth: 'required',
      headers: {
        'Idempotency-Key': idempotencyKey,
        ...(tableSessionNo ? { 'Table-Session-No': tableSessionNo } : {}),
      },
    })
    const parsed = requireParsed(operation, result, parseWalletPaymentResult)
    if (parsed.order_id !== orderId) throw new ContractError({ operation })
    return parsed
  }

  async createWechatOrderPayment(orderId: number, idempotencyKey: string): Promise<void> {
    assertPositiveSafeInteger(orderId, 'Order ID')
    assertIdempotencyKey(idempotencyKey)
    const operation = 'payments.order.wechat'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/orders/${orderId}/payments/wechat`,
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': idempotencyKey },
    })
    if (result !== null) throw new ContractError({ operation })
  }

  async getAdminUserWallet(userId: number): Promise<AdminUserWallet> {
    assertPositiveSafeInteger(userId, 'User ID')
    const operation = 'wallet.admin.detail'
    const result = await this.requestParsed(
      operation,
      `/api/v1/admin/users/${userId}/wallet`,
      parseAdminUserWallet,
    )
    if (result.user.id !== userId || result.wallet.user_id !== userId) {
      throw new ContractError({ operation })
    }
    return result
  }

  async listAdminUserWalletTransactions(
    userId: number,
    request: WalletTransactionRequest = {},
  ): Promise<WalletTransactionPage> {
    assertPositiveSafeInteger(userId, 'User ID')
    const operation = 'wallet.admin.transactions.list'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/users/${userId}/wallet-transactions`,
      method: 'GET',
      auth: 'required',
      query: projectPageRequest(request),
    })
    return requireParsed(operation, result, parseWalletTransactionPage)
  }

  async adjustAdminUserWallet(
    userId: number,
    request: { readonly change: string; readonly reason: string },
    idempotencyKey: string,
  ): Promise<WalletAdjustmentResult> {
    assertPositiveSafeInteger(userId, 'User ID')
    const changeCents = assertMoneyInput(request.change, true)
    if (Math.abs(changeCents) > 100000) {
      throw new Error('单次余额调整绝对值不得超过 1000.00 元')
    }
    assertReason(request.reason)
    assertIdempotencyKey(idempotencyKey)
    const operation = 'wallet.admin.adjust'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/users/${userId}/wallet-adjustments`,
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { change: request.change, reason: request.reason.trim() },
    })
    const parsed = requireParsed(operation, result, parseWalletAdjustmentResult)
    if (parsed.wallet.user_id !== userId ||
      parsed.transaction.change_amount !== request.change ||
      parsed.transaction.reason !== request.reason.trim()) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async createAssistedWalletOrder(
    userId: number,
    request: OrderCreateRequest,
    idempotencyKey: string,
  ): Promise<AssistedWalletOrderResult> {
    assertPositiveSafeInteger(userId, 'User ID')
    assertIdempotencyKey(idempotencyKey)
    const operation = 'wallet.admin.order.create'
    const intent = projectAssistedWalletOrderRequest(request)
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/users/${userId}/wallet-orders`,
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: intent,
    })
    const parsed = parseAssistedWalletOrderResult(result)
    if (!parsed || parsed.order.user_id !== userId ||
      !matchesAssistedWalletOrderIntent(parsed, intent)) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async getAdminOrderFinancials(orderId: number): Promise<OrderFinancial> {
    assertPositiveSafeInteger(orderId, 'Order ID')
    const operation = 'payments.admin.financials'
    const result = await this.requestParsed(
      operation,
      `/api/v1/admin/orders/${orderId}/financials`,
      parseOrderFinancial,
    )
    if (result.order_id !== orderId) throw new ContractError({ operation })
    return result
  }

  async refundAdminOrder(
    orderId: number,
    reason: string,
    idempotencyKey: string,
  ): Promise<RefundRecord> {
    assertPositiveSafeInteger(orderId, 'Order ID')
    assertReason(reason)
    assertIdempotencyKey(idempotencyKey)
    const operation = 'payments.admin.refund'
    const result = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/orders/${orderId}/refunds`,
      method: 'POST',
      auth: 'required',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { reason: reason.trim() },
    })
    const parsed = requireParsed(operation, result, parseRefundRecord)
    if (parsed.order_id !== orderId || parsed.reason !== reason.trim() ||
      parsed.status !== 'succeeded' || parsed.succeeded_at === null) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  private async requestParsed<T>(
    operation: string,
    path: string,
    parser: (value: unknown) => T | undefined,
  ): Promise<T> {
    const result = await this.client.request<unknown>({ operation, path, method: 'GET', auth: 'required' })
    return requireParsed(operation, result, parser)
  }
}

function projectPageRequest(request: WalletTransactionRequest): Record<string, number> {
  if (request.page !== undefined) assertPositiveSafeInteger(request.page, 'Page')
  if (request.page_size !== undefined) assertPositiveSafeInteger(request.page_size, 'Page size')
  return {
    ...(request.page === undefined ? {} : { page: request.page }),
    ...(request.page_size === undefined ? {} : { page_size: request.page_size }),
  }
}

function projectAssistedWalletOrderRequest(request: OrderCreateRequest): OrderCreateRequest {
  if (!Array.isArray(request.items) || request.items.length < 1 ||
    request.items.length > ASSISTED_ORDER_ITEM_LIMIT) {
    throw new Error('代客订单必须包含有效商品配置')
  }
  const seen = new Set<string>()
  let colorItemCount = 0
  let nonColorItemCount = 0
  const items = request.items.map((item) => {
    if (!isPositiveSafeInteger(item.product_id) || !isPositiveSafeInteger(item.quantity) || item.quantity > 99 ||
      !(item.experience_option_id === undefined || item.experience_option_id === null ||
        isPositiveSafeInteger(item.experience_option_id)) ||
      !(item.kit_color_id === undefined || item.kit_color_id === null ||
        isPositiveSafeInteger(item.kit_color_id))) {
      throw new Error('代客订单商品、配置或数量无效')
    }
    const optionId = item.experience_option_id ?? null
    const colorId = item.kit_color_id ?? null
    if (optionId !== null && colorId !== null) {
      throw new Error('代客订单商品配置无效')
    }
    if (colorId === null) nonColorItemCount += 1
    else colorItemCount += 1
    const identity = `${item.product_id}:${optionId ?? 'none'}:${colorId ?? 'none'}`
    if (seen.has(identity)) throw new Error('代客订单不能包含重复商品配置')
    seen.add(identity)
    return {
      product_id: item.product_id,
      quantity: item.quantity,
      ...(optionId === null ? {} : { experience_option_id: optionId }),
      ...(colorId === null ? {} : { kit_color_id: colorId }),
    }
  })
  if (colorItemCount > ASSISTED_ORDER_COLOR_ITEM_LIMIT ||
    nonColorItemCount > ASSISTED_ORDER_NON_COLOR_ITEM_LIMIT) {
    throw new Error('代客订单最多包含 20 种颜色和 10 种其他商品配置')
  }
  if (!(request.remark === undefined || request.remark === null || typeof request.remark === 'string')) {
    throw new Error('代客订单备注格式无效')
  }
  const remark = request.remark?.trim()
  if (remark !== undefined && remark.length > 500) throw new Error('代客订单备注最多 500 个字符')
  return remark ? { items, remark } : { items }
}

function matchesAssistedWalletOrderIntent(
  result: AssistedWalletOrderResult,
  intent: OrderCreateRequest,
): boolean {
  if (result.order.remark !== (intent.remark ?? null) ||
    result.order.items.length !== intent.items.length) {
    return false
  }

  const expectedItems = new Map<string, number>()
  for (const item of intent.items) {
    expectedItems.set(
      `${item.product_id}:${item.experience_option_id ?? 'none'}:${item.kit_color_id ?? 'none'}`,
      item.quantity,
    )
  }
  for (const item of result.order.items) {
    const identity = `${item.product_id}:${item.experience_option_id ?? 'none'}:${item.kit_color_id ?? 'none'}`
    if (expectedItems.get(identity) !== item.quantity) return false
    expectedItems.delete(identity)
  }
  return expectedItems.size === 0
}

function parseMemberWallet(value: unknown): MemberWallet | undefined {
  if (!isRecord(value)) return undefined
  const user = parseUserProfile(value.user)
  const wallet = parseWalletSummary(value.wallet)
  return user && wallet && user.id === wallet.user_id ? { user, wallet } : undefined
}

function parseAdminUserWallet(value: unknown): AdminUserWallet | undefined {
  if (!isRecord(value)) return undefined
  const user = parseAdminWalletUser(value.user)
  const wallet = parseWalletSummary(value.wallet)
  return user && wallet && user.id === wallet.user_id ? { user, wallet } : undefined
}

function parseAdminWalletUser(value: unknown): AdminWalletUser | undefined {
  if (!isRecord(value) || !isPositiveSafeInteger(value.id) ||
    !isBoundedString(value.username, 3, 32) || !isBoundedString(value.nickname, 1, 32) ||
    !isOneOf(value.role, ['user', 'admin', 'super_admin']) ||
    !isOneOf(value.status, ['normal', 'disabled', 'deleted']) ||
    !(value.last_login_at === null || isUtcDatetime(value.last_login_at)) ||
    !isUtcDatetime(value.created_at)) return undefined
  return {
    id: value.id,
    username: value.username,
    nickname: value.nickname,
    role: value.role,
    status: value.status,
    last_login_at: value.last_login_at,
    created_at: value.created_at,
  }
}

function parseWalletSummary(value: unknown): WalletSummary | undefined {
  if (!isRecord(value) || !isPositiveSafeInteger(value.wallet_id) ||
    !isPositiveSafeInteger(value.user_id) || !isUnsignedMoney(value.balance) ||
    !isUnsignedMoney(value.balance_limit) || !isOneOf(value.status, ['active', 'closed']) ||
    !isRecord(value.capabilities) || typeof value.capabilities.topup_enabled !== 'boolean' ||
    typeof value.capabilities.wallet_payment_enabled !== 'boolean' ||
    typeof value.capabilities.refund_enabled !== 'boolean' ||
    !isUtcDatetime(value.created_at) || !isUtcDatetime(value.updated_at)) return undefined
  return {
    wallet_id: value.wallet_id,
    user_id: value.user_id,
    balance: value.balance,
    balance_limit: value.balance_limit,
    status: value.status,
    capabilities: {
      topup_enabled: value.capabilities.topup_enabled,
      wallet_payment_enabled: value.capabilities.wallet_payment_enabled,
      refund_enabled: value.capabilities.refund_enabled,
    },
    created_at: value.created_at,
    updated_at: value.updated_at,
  }
}

function parseWalletTransactionPage(value: unknown): WalletTransactionPage | undefined {
  if (!isRecord(value) || !Array.isArray(value.items) || !isNonNegativeSafeInteger(value.total) ||
    !isPositiveSafeInteger(value.page) || !isPositiveSafeInteger(value.page_size) ||
    value.page_size > 100 || !isNonNegativeSafeInteger(value.pages) || value.items.length > value.page_size) {
    return undefined
  }
  const items: WalletTransaction[] = []
  for (const item of value.items) {
    const parsed = parseWalletTransaction(item)
    if (!parsed) return undefined
    items.push(parsed)
  }
  return { items, total: value.total, page: value.page, page_size: value.page_size, pages: value.pages }
}

function parseWalletTransaction(value: unknown): WalletTransaction | undefined {
  if (!isRecord(value) || !isPositiveSafeInteger(value.id) ||
    !isOneOf(value.transaction_type, ['recharge', 'order_payment', 'admin_adjustment', 'refund']) ||
    !isOneOf(value.direction, ['income', 'expense']) || !isSignedMoney(value.change_amount) ||
    !isUnsignedMoney(value.before_balance) || !isUnsignedMoney(value.after_balance) ||
    !isOneOf(value.source_type, ['recharge_order', 'order', 'admin', 'refund']) ||
    !(value.source_id === null || isPositiveSafeInteger(value.source_id)) ||
    !(value.source_order_no === null || isBoundedString(value.source_order_no, 1, 32)) ||
    !(value.operator_id === null || isPositiveSafeInteger(value.operator_id)) ||
    !(value.operator_nickname === null || isBoundedString(value.operator_nickname, 1, 32)) ||
    !isBoundedString(value.reason, 1, 256) || !isUtcDatetime(value.created_at)) return undefined
  const income = !value.change_amount.startsWith('-')
  const changeCents = parseMoneyCents(value.change_amount)
  const beforeCents = parseMoneyCents(value.before_balance)
  const afterCents = parseMoneyCents(value.after_balance)
  if ((value.direction === 'income') !== income || changeCents === 0 ||
    changeCents === undefined || beforeCents === undefined || afterCents === undefined ||
    beforeCents + changeCents !== afterCents) return undefined
  return {
    id: value.id,
    transaction_type: value.transaction_type,
    direction: value.direction,
    change_amount: value.change_amount,
    before_balance: value.before_balance,
    after_balance: value.after_balance,
    source_type: value.source_type,
    source_id: value.source_id,
    source_order_no: value.source_order_no,
    operator_id: value.operator_id,
    operator_nickname: value.operator_nickname,
    reason: value.reason,
    created_at: value.created_at,
  }
}

function parseOrderFinancial(value: unknown): OrderFinancial | undefined {
  if (!isRecord(value) || !isPositiveSafeInteger(value.order_id)) return undefined
  const orderStatus = parseOrderStatus(value.order_status)
  if (!orderStatus) return undefined

  let payment: PaymentRecord | null
  if (value.payment === null) {
    payment = null
  } else {
    const parsedPayment = parsePaymentRecord(value.payment)
    if (!parsedPayment) return undefined
    payment = parsedPayment
  }

  let refund: RefundRecord | null
  if (value.refund === null) {
    refund = null
  } else {
    const parsedRefund = parseRefundRecord(value.refund)
    if (!parsedRefund) return undefined
    refund = parsedRefund
  }

  if (payment !== null && (payment.order_id !== value.order_id ||
    payment.recharge_order_id !== null || payment.purpose !== 'order' ||
    payment.status !== 'succeeded' || payment.succeeded_at === null ||
    !isSettledOrderStatus(orderStatus.value))) return undefined
  if (refund !== null && (payment === null || refund.order_id !== value.order_id ||
    refund.method !== payment.method || refund.amount !== payment.amount)) return undefined
  return { order_id: value.order_id, order_status: orderStatus, payment, refund }
}

function parseWalletPaymentResult(value: unknown): WalletPaymentResult | undefined {
  if (!isRecord(value) || !isPositiveSafeInteger(value.order_id) ||
    typeof value.order_no !== 'string' || !ORDER_NO_PATTERN.test(value.order_no) ||
    !isUnsignedMoney(value.post_payment_balance)) return undefined
  const orderStatus = parseOrderStatus(value.order_status)
  const payment = parsePaymentRecord(value.payment)
  if (!orderStatus || !isSettledOrderStatus(orderStatus.value) || !payment ||
    payment.order_id !== value.order_id ||
    payment.recharge_order_id !== null || payment.purpose !== 'order' ||
    payment.method !== 'wallet' || payment.status !== 'succeeded' ||
    payment.succeeded_at === null) return undefined
  return {
    order_id: value.order_id,
    order_no: value.order_no,
    order_status: orderStatus,
    payment,
    post_payment_balance: value.post_payment_balance,
  }
}

function parseWalletAdjustmentResult(value: unknown): WalletAdjustmentResult | undefined {
  if (!isRecord(value)) return undefined
  const wallet = parseWalletSummary(value.wallet)
  const transaction = parseWalletTransaction(value.transaction)
  return wallet && transaction && transaction.transaction_type === 'admin_adjustment' &&
    transaction.source_type === 'admin' && transaction.source_id === null &&
    transaction.source_order_no === null && transaction.after_balance === wallet.balance
    ? { wallet, transaction }
    : undefined
}

export function parseAssistedWalletOrderResult(value: unknown): AssistedWalletOrderResult | undefined {
  if (!isRecord(value) || !isUnsignedMoney(value.post_payment_balance)) return undefined
  const order = parseAdminOrderDetail(value.order)
  const payment = parsePaymentRecord(value.payment)
  const balanceCents = parseMoneyCents(value.post_payment_balance)
  if (!order || !payment || balanceCents === undefined || balanceCents < 0 || balanceCents > 100000 ||
    order.status.value !== 'paid' || payment.status !== 'succeeded' || payment.succeeded_at === null ||
    payment.method !== 'wallet' || payment.purpose !== 'order' || payment.order_id !== order.id ||
    payment.recharge_order_id !== null || payment.amount !== order.total_amount) return undefined
  return { order, payment, post_payment_balance: value.post_payment_balance }
}

export function parsePaymentRecord(value: unknown): PaymentRecord | undefined {
  if (!isRecord(value) || !isPositiveSafeInteger(value.id) ||
    !/^PY[0-9A-HJKMNP-TV-Z]{26}$/.test(String(value.payment_no)) ||
    !(value.order_id === null || isPositiveSafeInteger(value.order_id)) ||
    !(value.recharge_order_id === null || isPositiveSafeInteger(value.recharge_order_id)) ||
    !isOneOf(value.purpose, ['order', 'recharge']) || !isOneOf(value.method, ['wallet', 'wechat', 'manual']) ||
    !isUnsignedMoney(value.amount) || Number(value.amount) <= 0 ||
    !isOneOf(value.status, ['pending', 'succeeded', 'failed', 'closed']) ||
    !isUtcDatetime(value.created_at) || !isUtcDatetime(value.updated_at) ||
    !(value.succeeded_at === null || isUtcDatetime(value.succeeded_at))) return undefined
  return {
    id: value.id,
    payment_no: String(value.payment_no),
    order_id: value.order_id,
    recharge_order_id: value.recharge_order_id,
    purpose: value.purpose,
    method: value.method,
    amount: value.amount,
    status: value.status,
    created_at: value.created_at,
    updated_at: value.updated_at,
    succeeded_at: value.succeeded_at,
  }
}

function parseRefundRecord(value: unknown): RefundRecord | undefined {
  if (!isRecord(value) || !isPositiveSafeInteger(value.id) ||
    !/^RF[0-9A-HJKMNP-TV-Z]{26}$/.test(String(value.refund_no)) ||
    !isPositiveSafeInteger(value.order_id) || !isOneOf(value.method, ['wallet', 'wechat', 'manual']) ||
    !isUnsignedMoney(value.amount) || Number(value.amount) <= 0 ||
    !isOneOf(value.status, ['pending', 'succeeded', 'failed']) ||
    !isBoundedString(value.reason, 1, 256) || !isPositiveSafeInteger(value.operator_id) ||
    typeof value.inventory_restored !== 'boolean' || !isUtcDatetime(value.created_at) ||
    !isUtcDatetime(value.updated_at) || !(value.succeeded_at === null || isUtcDatetime(value.succeeded_at))) {
    return undefined
  }
  return {
    id: value.id,
    refund_no: String(value.refund_no),
    order_id: value.order_id,
    method: value.method,
    amount: value.amount,
    status: value.status,
    reason: value.reason,
    operator_id: value.operator_id,
    inventory_restored: value.inventory_restored,
    created_at: value.created_at,
    updated_at: value.updated_at,
    succeeded_at: value.succeeded_at,
  }
}

function parseOrderStatus(value: unknown): OrderFinancial['order_status'] | undefined {
  if (!isRecord(value) || !isOneOf(value.value, ['pending', 'paid', 'cancelled', 'completed']) ||
    !isBoundedString(value.label, 1, 32)) return undefined
  return { value: value.value, label: value.label }
}

function isSettledOrderStatus(value: string): value is 'paid' | 'completed' {
  return value === 'paid' || value === 'completed'
}

function requireParsed<T>(operation: string, value: unknown, parser: (value: unknown) => T | undefined): T {
  const parsed = parser(value)
  if (!parsed) throw new ContractError({ operation })
  return parsed
}

function assertPositiveSafeInteger(value: number, label: string): void {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${label} 必须是正安全整数`)
}

function assertMoneyInput(value: string, allowNegative: boolean): number {
  const pattern = allowNegative ? /^-?(?:0|[1-9]\d{0,7})\.\d{2}$/ : /^(?:0|[1-9]\d{0,7})\.\d{2}$/
  const cents = parseMoneyCents(value)
  if (!pattern.test(value) || cents === undefined || cents === 0) {
    throw new Error('金额必须是非零的两位小数字符串')
  }
  return cents
}

function assertReason(reason: string): void {
  const normalized = reason.trim()
  if (normalized.length < 1 || normalized.length > 256) throw new Error('原因长度必须为 1–256 个字符')
}

function assertIdempotencyKey(value: string): void {
  if (value.length < 1 || value.length > 128 || !/^[\x21-\x7E](?:[\x20-\x7E]{0,126}[\x21-\x7E])?$/.test(value)) {
    throw new Error('Idempotency-Key 格式无效')
  }
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

function isUnsignedMoney(value: unknown): value is string {
  return typeof value === 'string' && /^(?:0|[1-9]\d{0,7})\.\d{2}$/.test(value)
}

function isSignedMoney(value: unknown): value is string {
  return typeof value === 'string' && /^-?(?:0|[1-9]\d{0,7})\.\d{2}$/.test(value)
}

function parseMoneyCents(value: string): number | undefined {
  if (!isSignedMoney(value)) return undefined
  const negative = value.startsWith('-')
  const unsigned = negative ? value.slice(1) : value
  const [integer, decimal] = unsigned.split('.')
  const cents = Number(integer) * 100 + Number(decimal)
  return negative ? -cents : cents
}

function isUtcDatetime(value: unknown): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value) &&
    !Number.isNaN(Date.parse(value))
}

function isOneOf<const T extends readonly string[]>(value: unknown, choices: T): value is T[number] {
  return typeof value === 'string' && (choices as readonly string[]).includes(value)
}
