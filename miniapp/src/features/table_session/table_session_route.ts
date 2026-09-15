import {
  ADMIN_TABLES_PATH,
  TABLE_ENTRY_PATH,
  type TableEntryRedirect,
} from '@/auth/login_route'

export { ADMIN_TABLES_PATH, TABLE_ENTRY_PATH }

const TOKEN_PATTERN = /^[A-Za-z0-9]{32}$/
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

export function buildTableEntryUrl(token: string): TableEntryRedirect {
  const parsed = parseTableToken(token)
  if (!parsed) throw new Error('桌台二维码无效')
  return `${TABLE_ENTRY_PATH}?token=${parsed}`
}

export function buildAdminTableSessionUrl(sessionNo: string): string {
  if (!/^TS[0-9A-HJKMNP-TV-Z]{26}$/.test(sessionNo)) {
    throw new Error('桌台会话编号无效')
  }
  return `/admin/pages/table-session-detail/index?session_no=${sessionNo}`
}
