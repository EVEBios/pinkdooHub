import type { AdminTable } from '@/api/endpoints/table_sessions'

export const TABLE_TIME_WARNING_MINUTES = 10
export type TableTimerSummary = NonNullable<AdminTable['timers']>[number]
export interface TableTimeWarning {
  readonly timer: TableTimerSummary
  readonly phase: 'soon' | 'grace'
}

/** 逐组判断；短时长组结束后不继续预警，最长组仍由服务端确认释放。 */
export function tableTimeWarnings(status: string | undefined, timers: readonly TableTimerSummary[], now: number): readonly TableTimeWarning[] {
  if (status !== 'active') return []
  return timers.flatMap((timer): TableTimeWarning[] => {
    const service = Date.parse(timer.service_ends_at)
    const grace = Date.parse(timer.grace_ends_at)
    if (now >= grace || now < service - TABLE_TIME_WARNING_MINUTES * 60_000) return []
    return [{ timer, phase: now >= service ? 'grace' : 'soon' }]
  }).sort((a, b) => Date.parse(a.timer.service_ends_at) - Date.parse(b.timer.service_ends_at) || a.timer.id - b.timer.id)
}

export function tableNeedsAttention(table: AdminTable, now: number): 'payment' | 'time' | undefined {
  if (table.current_status?.value === 'awaiting_payment' && table.payment_deadline_at && now <= Date.parse(table.payment_deadline_at)) return 'payment'
  if (table.current_status?.value === 'active' && (
    tableTimeWarnings('active', table.timers ?? [], now).length > 0 ||
    (table.table_release_at && now >= Date.parse(table.table_release_at))
  )) return 'time'
  return undefined
}

/** 付款和计时从同一份桌台快照计数，状态转换时不会把同一桌算两次。 */
export function tableAttentionCounts(tables: readonly AdminTable[], now: number) {
  const payment = new Set<number>()
  const time = new Set<number>()
  for (const table of tables) {
    const kind = tableNeedsAttention(table, now)
    if (kind === 'payment') payment.add(table.id)
    if (kind === 'time') time.add(table.id)
  }
  return { payment: payment.size, time: time.size, total: new Set([...payment, ...time]).size }
}
