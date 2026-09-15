import ReactTestUtil from '@tarojs/test-utils-react'
import Page from '../index'

const now = Date.parse('2026-09-15T04:00:00Z')
const mockSessionNo = `TS${'1'.repeat(26)}`
const iso = (minutes: number) => new Date(now + minutes * 60_000).toISOString()
const mockApi = { getAdminSession: jest.fn() }
jest.mock('@tarojs/taro', () => ({
  __esModule: true, default: { navigateBack: jest.fn() },
  useRouter: () => ({ params: { session_no: mockSessionNo } }), useDidShow: () => undefined, useDidHide: () => undefined,
}))
jest.mock('@/auth', () => ({ useAuth: () => ({ status: 'authenticated', user: { id: 1, role: 'admin' } }), isAdminRole: () => true }))
jest.mock('@/features/table_session', () => ({ getDefaultTableSessionApi: () => mockApi }))
const session = { session_no: mockSessionNo, source: 'order', table: { display_name: 'T01号桌' }, status: { value: 'active', label: '计时中' }, claimed_at: iso(-52), table_release_at: iso(78), server_now: iso(0), timers: [
  { id: 1, duration_minutes: 60, service_ends_at: iso(8), grace_ends_at: iso(18), experience_items: [] },
  { id: 2, duration_minutes: 120, service_ends_at: iso(68), grace_ends_at: iso(78), experience_items: [] },
] }
let util: ReactTestUtil
beforeEach(() => { util = new ReactTestUtil(); jest.spyOn(Date, 'now').mockReturnValue(now); mockApi.getAdminSession.mockResolvedValue(session) })
afterEach(() => { util.unmout(); jest.restoreAllMocks(); jest.clearAllMocks() })
it('详情仅突出临近结束的计时组，不把最长一组一并预警', async () => {
  await util.mount(Page); await new Promise(resolve => setTimeout(resolve, 15))
  expect(util.queries.querySelectorAll('.admin-session-card--warning')).toHaveLength(1)
  expect(util.queries.querySelector('.admin-session-card--warning')?.textContent).toContain('00:08:00')
  expect(util.queries.querySelector('.admin-session-card__warning')?.textContent).toContain('即将到时')
  expect(mockApi.getAdminSession).toHaveBeenCalledTimes(1)
})
it('计时走完但服务端仍活动时提示核实', async () => {
  mockApi.getAdminSession.mockResolvedValue({ ...session, table_release_at: iso(-1), timers: [{ ...session.timers[0], service_ends_at: iso(-11), grace_ends_at: iso(-1) }] })
  await util.mount(Page); await new Promise(resolve => setTimeout(resolve, 15))
  expect(util.queries.querySelector('.admin-session-page')?.textContent).toContain('正在确认释放状态')
  expect(util.queries.querySelector('.admin-session-card__countdown')?.textContent).toBe('本组时间已到')
})

it('服务端已关闭的会话不再突出预警', async () => {
  mockApi.getAdminSession.mockResolvedValue({ ...session, status: { value: 'closed', label: '已结束' } })
  await util.mount(Page); await new Promise(resolve => setTimeout(resolve, 15))
  expect(util.queries.querySelectorAll('.admin-session-card--warning')).toHaveLength(0)
  expect(util.queries.querySelector('.admin-session-card__countdown')?.textContent).toBe('已结束')
})
