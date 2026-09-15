import type { AdminTable } from '@/api/endpoints/table_sessions'
import { tableAttentionCounts, tableNeedsAttention, tableTimeWarnings } from '../admin_table_attention'

const end = Date.parse('2026-09-15T04:00:00Z')
const minute = 60_000
const timer = { id: 1, duration_minutes: 60, service_ends_at: new Date(end).toISOString(), grace_ends_at: new Date(end + 10 * minute).toISOString() }
const long = { id: 2, duration_minutes: 120, service_ends_at: new Date(end + 60 * minute).toISOString(), grace_ends_at: new Date(end + 70 * minute).toISOString() }
const active: AdminTable = { id: 1, display_name: 'T01号桌', table_no: 'T01', is_enabled: true, state: 'active', timer_count: 2, current_status: { value: 'active', label: '计时中' }, timers: [timer, long], table_release_at: long.grace_ends_at }

it.each([
  [-10 * minute - 1, undefined], [-10 * minute, 'soon'], [-1, 'soon'],
  [0, 'grace'], [10 * minute - 1, 'grace'], [10 * minute, undefined],
])('体验结束偏移 %s 毫秒的边界', (offset, phase) => {
  expect(tableTimeWarnings('active', [timer], end + offset)[0]?.phase).toBe(phase)
})
it('长组不会盖住短组；短组缓冲结束后无需继续提醒', () => {
  expect(tableTimeWarnings('active', [long, timer], end)[0]).toMatchObject({ timer: { id: 1 }, phase: 'grace' })
  expect(tableNeedsAttention(active, end + 10 * minute)).toBeUndefined()
  expect(tableNeedsAttention(active, end + 50 * minute)).toBe('time')
})
it('直接开台及停用新开台中的会话同样提醒；已结束和待付款不误作到时', () => {
  expect(tableNeedsAttention({ ...active, is_enabled: false, state: 'disabled', current_source: 'direct' }, end)).toBe('time')
  expect(tableTimeWarnings('closed', [timer], end)).toEqual([])
  expect(tableTimeWarnings('awaiting_payment', [timer], end)).toEqual([])
})
it('同桌多组只计一桌；等待付款与计时切换不重复；付款到期后不催收', () => {
  const pending = { ...active, id: 2, current_status: { value: 'awaiting_payment', label: '待支付' }, payment_deadline_at: new Date(end).toISOString(), timers: [] }
  expect(tableAttentionCounts([active, active, pending], end)).toEqual({ payment: 1, time: 1, total: 2 })
  expect(tableAttentionCounts([active, { ...pending, current_status: { value: 'active', label: '计时中' }, timers: [timer] }], end)).toEqual({ payment: 0, time: 2, total: 2 })
  expect(tableNeedsAttention(pending, end + 1)).toBeUndefined()
})
it('全部时间已到仍等待服务端确认，不靠本地时钟清空提醒', () => {
  expect(tableNeedsAttention(active, end + 71 * minute)).toBe('time')
  expect(tableNeedsAttention({ ...active, current_status: null, timers: [], table_release_at: null }, end + 71 * minute)).toBeUndefined()
})
