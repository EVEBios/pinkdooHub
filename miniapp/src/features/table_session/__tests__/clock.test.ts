import type { TableSession } from '@/api/endpoints/table_sessions'

import { nextSessionBoundaryDelay, timerPhaseAt, timerPhaseLabel } from '../clock'

const baseSession: TableSession = {
  session_no: `TS${'1'.repeat(26)}`,
  table: { id: 1, table_no: 'T01', display_name: 'T01号桌', is_enabled: true },
  order_id: 8,
  order_no: `OD${'2'.repeat(26)}`,
  status: { value: 'awaiting_payment', label: '待支付' },
  claimed_at: '2026-09-10T04:00:00Z',
  payment_deadline_at: '2026-09-10T04:15:00Z',
  started_at: null,
  table_release_at: null,
  closed_at: null,
  close_reason: null,
  timers: [],
  server_now: '2026-09-10T04:14:59Z',
}

describe('桌台服务端时钟边界', () => {
  it('在待支付截止后立即安排一次服务端校准', () => {
    expect(nextSessionBoundaryDelay(baseSession)).toBe(1_100)
  })

  it('按绝对时间切换体验、缓冲与待确认结束阶段', () => {
    const serviceEnd = '2026-09-10T06:00:00Z'
    const graceEnd = '2026-09-10T06:10:00Z'
    expect(timerPhaseAt(serviceEnd, graceEnd, Date.parse('2026-09-10T05:59:59Z'))).toBe('experience')
    expect(timerPhaseAt(serviceEnd, graceEnd, Date.parse(serviceEnd))).toBe('grace')
    expect(timerPhaseAt(serviceEnd, graceEnd, Date.parse(graceEnd))).toBe('ended')
    expect(timerPhaseLabel('ended')).toBe('正在确认结束状态')
  })
})
