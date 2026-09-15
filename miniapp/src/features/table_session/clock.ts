import type { TableSession } from '@/api/endpoints/table_sessions'

const BOUNDARY_REFRESH_SAFETY_MS = 100
const MAX_TIMER_DELAY_MS = 2_147_483_647

export function nextSessionBoundaryDelay(session: TableSession): number | undefined {
  const serverNow = Date.parse(session.server_now)
  if (!Number.isFinite(serverNow) || session.status.value === 'closed') return undefined
  const boundaries = session.status.value === 'awaiting_payment'
    ? [session.payment_deadline_at]
    : [
        ...session.timers.flatMap((timer) => [timer.service_ends_at, timer.grace_ends_at]),
        ...(session.table_release_at ? [session.table_release_at] : []),
      ]
  const futureDelays = boundaries
    .map((value) => Date.parse(value) - serverNow)
    .filter((delay) => Number.isFinite(delay) && delay >= 0)
  if (futureDelays.length === 0) return undefined
  return Math.min(Math.min(...futureDelays) + BOUNDARY_REFRESH_SAFETY_MS, MAX_TIMER_DELAY_MS)
}

export function timerPhaseAt(
  serviceEndsAt: string,
  graceEndsAt: string,
  estimatedServerNow: number,
): 'experience' | 'grace' | 'ended' {
  if (estimatedServerNow >= Date.parse(graceEndsAt)) return 'ended'
  if (estimatedServerNow >= Date.parse(serviceEndsAt)) return 'grace'
  return 'experience'
}

export function timerPhaseLabel(phase: 'experience' | 'grace' | 'ended'): string {
  if (phase === 'experience') return '体验中'
  if (phase === 'grace') return '缓冲中'
  return '正在确认结束状态'
}
