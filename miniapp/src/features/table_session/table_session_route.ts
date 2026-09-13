import {
  ADMIN_TABLES_PATH,
  ORDER_CONFIRM_PATH,
  TABLE_ENTRY_PATH,
  type OrderConfirmRedirect,
  type TableEntryRedirect,
} from '@/auth/login_route'

export { ADMIN_TABLES_PATH, TABLE_ENTRY_PATH }

const TOKEN_PATTERN = /^[A-Za-z0-9]{32}$/
const ORDER_ID_PATTERN = /^[1-9]\d*$/
const CHECKOUT_INTENT_PATTERN = /^miniapp-table-checkout-[a-z0-9]+-[a-z0-9]+-[a-z0-9]{20}$/
const PLACEHOLDER_PREFIX = 'PINKDOOHUB_TABLE:v1:'

export function parseTableToken(value: unknown): string | undefined {
  if (typeof value !== 'string' || value.length === 0) return undefined
  let decoded: string
  try {
    decoded = decodeURIComponent(value)
  } catch {
    return undefined
  }
  const token = decoded.startsWith(PLACEHOLDER_PREFIX)
    ? decoded.slice(PLACEHOLDER_PREFIX.length)
    : decoded
  return TOKEN_PATTERN.test(token) ? token : undefined
}

export function parseTableEntryRoute(
  params: Readonly<Record<string, string | undefined>>,
): string | undefined {
  return parseTableToken(params.scene ?? params.token)
}

/**
 * 新订单 ID 只用于扫码开台页在服务端返回的 eligible 列表中定位对应订单。
 * 这里的严格解析不能替代桌台领取时的服务端资格校验。
 */
export function parseTableEntryOrderId(
  params: Readonly<Record<string, string | undefined>>,
): number | undefined {
  const value = params.order_id
  if (!value || !ORDER_ID_PATTERN.test(value)) return undefined
  const orderId = Number(value)
  return Number.isSafeInteger(orderId) ? orderId : undefined
}

export function parseTableCheckoutIntentId(value: unknown): string | undefined {
  return typeof value === 'string' && CHECKOUT_INTENT_PATTERN.test(value)
    ? value
    : undefined
}

export function parseTableOrderConfirmRoute(
  params: Readonly<Record<string, string | undefined>>,
): string | undefined {
  return parseTableCheckoutIntentId(params.table_intent)
}

export function buildTableOrderConfirmUrl(intentId: string): OrderConfirmRedirect {
  const parsed = parseTableCheckoutIntentId(intentId)
  if (!parsed) throw new Error('桌台结算意图无效')
  return `${ORDER_CONFIRM_PATH}?table_intent=${parsed}`
}

export function buildTableEntryUrl(
  token: string,
  orderId?: number,
  intentId?: string,
): TableEntryRedirect {
  const parsed = parseTableToken(token)
  if (!parsed) throw new Error('桌台二维码无效')
  if (orderId === undefined) {
    if (intentId !== undefined) throw new Error('桌台结算意图缺少订单')
    return `${TABLE_ENTRY_PATH}?token=${parsed}`
  }
  if (!Number.isSafeInteger(orderId) || orderId <= 0) throw new Error('订单标识无效')
  if (intentId === undefined) return `${TABLE_ENTRY_PATH}?token=${parsed}&order_id=${orderId}`
  const parsedIntentId = parseTableCheckoutIntentId(intentId)
  if (!parsedIntentId) throw new Error('桌台结算意图无效')
  return `${TABLE_ENTRY_PATH}?token=${parsed}&order_id=${orderId}&table_intent=${parsedIntentId}`
}

export function buildAdminTableSessionUrl(sessionNo: string): string {
  if (!/^TS[0-9A-HJKMNP-TV-Z]{26}$/.test(sessionNo)) {
    throw new Error('桌台会话编号无效')
  }
  return `/admin/pages/table-session-detail/index?session_no=${sessionNo}`
}
