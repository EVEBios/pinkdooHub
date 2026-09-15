import ReactTestUtil from '@tarojs/test-utils-react'
import { act } from 'react'
import type { TableSession } from '@/api/endpoints/table_sessions'
import TableHistoryPage from '../index'

const mockSessionNo = `TS${'1'.repeat(26)}`
const mockGetHistory = jest.fn()
let mockHide: () => void
let mockShow: () => void
let mockRole = 'user'
let mockAuthenticated = true
const mockReceipt = jest.fn(() => null)
jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { navigateTo: jest.fn() },
  useRouter: () => ({ params: { sessionNo: mockSessionNo } }),
  useDidHide: (callback: () => void) => { mockHide = callback },
  useDidShow: (callback: () => void) => { mockShow = callback },
}))
jest.mock('@/auth', () => ({
  useAuth: () => ({ status: mockAuthenticated ? 'authenticated' : 'guest', user: { id: 7, role: mockRole } }),
  buildLoginUrl: () => '/pages/login/index',
}))
jest.mock('@/features/table_session/runtime', () => ({ getDefaultTableSessionApi: () => ({ getHistorySession: mockGetHistory }) }))
jest.mock('@/features/attention', () => ({ CommerceReceipt: () => mockReceipt() }))
jest.mock('@/features/attention/runtime', () => ({ attentionStore: {} }))
jest.mock('@/features/order', () => ({ buildOrderDetailUrl: (id: number) => `/pages/order-detail/index?id=${id}` }))
jest.mock('@/features/reservation', () => ({ formatShanghaiUtc: (value: string) => value }))

const serverNow = '2026-09-14T04:00:00Z'
const at = (seconds: number) => new Date(Date.parse(serverNow) + seconds * 1_000).toISOString()
const base: TableSession = {
  session_no: mockSessionNo, table: { id: 1, table_no: 'T01', display_name: 'T01号桌', is_enabled: true },
  order_id: 8, order_no: `OD${'2'.repeat(26)}`, status: { value: 'awaiting_payment', label: '待付款' },
  claimed_at: at(-600), payment_deadline_at: at(300), server_now: serverNow, timers: [],
}
const timer = (id: number, end: number, phase = 'experience'): TableSession['timers'][number] => ({
  id, duration_minutes: id * 60, buffer_minutes: 10, started_at: at(-3600),
  service_ends_at: at(end), grace_ends_at: at(end + 600), phase: { value: phase, label: phase },
  experience_items: [{ order_item_id: id, product_id: id, product_name: `体验项目${id}`, quantity: 1 }],
})

describe('本次桌台倒计时', () => {
  let util: ReactTestUtil
  const text = () => util.queries.querySelector('.attention-page')?.textContent ?? ''
  const values = () => Array.from(util.queries.querySelectorAll('.table-history-countdowns__value')).map((node) => node.textContent)
  const advance = async (ms: number) => act(async () => { jest.advanceTimersByTime(ms); await Promise.resolve() })

  beforeEach(() => {
    jest.useFakeTimers({ doNotFake: ['requestAnimationFrame', 'cancelAnimationFrame'] })
    jest.setSystemTime(new Date('2026-09-15T12:00:00Z'))
    util = new ReactTestUtil()
    mockRole = 'user'
    mockAuthenticated = true
    mockGetHistory.mockReset().mockResolvedValue(base)
    mockReceipt.mockClear()
  })
  afterEach(() => { util.unmout(); jest.useRealTimers() })

  it('以服务端时间校准，每秒只更新数字，不重载详情或重复处理结果', async () => {
    await util.mount(TableHistoryPage)
    expect(values()).toEqual(['00:05:00'])
    const receiptRenders = mockReceipt.mock.calls.length
    await advance(3_000)
    expect(values()).toEqual(['00:04:57'])
    expect(mockGetHistory).toHaveBeenCalledTimes(1)
    expect(mockReceipt).toHaveBeenCalledTimes(receiptRenders)
    expect(text()).not.toContain('正在读取')
    await advance(2_000)
    expect(mockGetHistory).toHaveBeenCalledTimes(2)
  })

  it('多时长分组独立倒计时，缓冲组和体验组同时展示', async () => {
    mockGetHistory.mockResolvedValue({ ...base, status: { value: 'active', label: '体验中' }, timers: [timer(1, -300, 'grace'), timer(2, 3300)], table_release_at: at(3900) })
    await util.mount(TableHistoryPage)
    expect(values()).toEqual(['00:05:00', '00:55:00'])
    expect(text()).toContain('60 分钟体验 · 缓冲剩余时间')
    expect(text()).toContain('120 分钟体验 · 体验剩余时间')
    expect(text()).toContain('整桌预计结束')
    await advance(1_000)
    expect(values()).toEqual(['00:04:59', '00:54:59'])
  })

  it('付款归零后核对服务端，失败保留零和确认提示，不伪造已结束', async () => {
    mockGetHistory.mockResolvedValueOnce({ ...base, payment_deadline_at: at(1) }).mockRejectedValue(new Error('offline'))
    await util.mount(TableHistoryPage)
    await advance(1_000)
    expect(values()).toEqual(['00:00:00'])
    expect(text()).toContain('正在确认付款状态')
    expect(mockGetHistory).toHaveBeenCalledTimes(1)
    await advance(100)
    expect(mockGetHistory).toHaveBeenCalledTimes(2)
    expect(text()).toContain('请重试')
    await advance(2_000)
    expect(values()).toEqual(['00:00:00'])
    expect(text()).not.toContain('本次桌台已结束')
    expect(mockGetHistory).toHaveBeenCalledTimes(2)
  })

  it('体验边界查询确认后切入缓冲，最终关闭停止倒计时和查询', async () => {
    mockGetHistory.mockResolvedValueOnce({ ...base, status: { value: 'active', label: '体验中' }, timers: [timer(1, 1)] })
      .mockResolvedValueOnce({ ...base, status: { value: 'active', label: '体验中' }, server_now: at(1.1), timers: [timer(1, 1, 'grace')] })
      .mockResolvedValue({ ...base, status: { value: 'closed', label: '已结束' }, close_reason: { value: 'admin_released', label: '门店已结束本次桌台' }, timers: [timer(1, 1, 'ended')] })
    await util.mount(TableHistoryPage)
    await advance(1_000)
    expect(text()).toContain('正在确认缓冲时间')
    await advance(100)
    expect(text()).toContain('缓冲剩余时间')
    expect(values()).toEqual(['00:10:00'])
    await advance(3_900)
    expect(values()).toEqual([])
    expect(text()).toContain('门店已结束本次桌台')
    await advance(60_000)
    expect(mockGetHistory).toHaveBeenCalledTimes(3)
  })

  it('缓冲归零不会擅自释放，服务端已结束的短组不继续计时', async () => {
    mockGetHistory.mockResolvedValueOnce({ ...base, status: { value: 'active', label: '体验中' }, timers: [timer(1, -700, 'ended'), timer(2, -599, 'grace')] }).mockRejectedValue(new Error('offline'))
    await util.mount(TableHistoryPage)
    expect(values()).toEqual(['00:00:01'])
    expect(text()).toContain('60 分钟体验 · 已结束')
    await advance(1_100)
    expect(text()).toContain('正在确认结束状态')
    expect(values()).toEqual(['00:00:00'])
  })

  it('隐藏停止本地计时及请求，回来立即校准，卸载后无残留定时器', async () => {
    await util.mount(TableHistoryPage)
    act(() => mockHide())
    await advance(120_000)
    expect(mockGetHistory).toHaveBeenCalledTimes(1)
    expect(values()).toEqual(['00:05:00'])
    mockGetHistory.mockResolvedValue({ ...base, server_now: at(120) })
    await act(async () => mockShow())
    expect(mockGetHistory).toHaveBeenCalledTimes(2)
    expect(values()).toEqual(['00:03:00'])
    util.unmout()
    await advance(60_000)
    expect(mockGetHistory).toHaveBeenCalledTimes(2)
    expect(jest.getTimerCount()).toBe(0)
  })

  it('初次读取失败能重试恢复倒计时', async () => {
    mockGetHistory.mockRejectedValueOnce(new Error('offline'))
    await util.mount(TableHistoryPage)
    expect(text()).toContain('请重试')
    await act(async () => util.fireEvent.click(util.queries.querySelector('.attention-page__retry')!))
    expect(values()).toEqual(['00:05:00'])
    expect(text()).not.toContain('请重试')
  })

  it('慢请求期间不叠加轮询，隐藏后返回的旧响应不覆盖前台新状态', async () => {
    let resolve!: (value: TableSession) => void
    mockGetHistory.mockReturnValueOnce(new Promise<TableSession>((done) => { resolve = done }))
    await util.mount(TableHistoryPage)
    await advance(15_000)
    expect(mockGetHistory).toHaveBeenCalledTimes(1)
    act(() => mockHide())
    mockGetHistory.mockResolvedValue({ ...base, server_now: at(30) })
    await act(async () => mockShow())
    expect(values()).toEqual(['00:04:30'])
    await act(async () => resolve(base))
    expect(values()).toEqual(['00:04:30'])
  })

  it('恰好在付款截止时仍向服务端核实，不在本地关闭或连续请求', async () => {
    mockGetHistory.mockResolvedValueOnce({ ...base, payment_deadline_at: serverNow })
      .mockResolvedValue({ ...base, payment_deadline_at: serverNow, server_now: at(0.1) })
    await util.mount(TableHistoryPage)
    expect(values()).toEqual(['00:00:00'])
    await advance(100)
    expect(mockGetHistory).toHaveBeenCalledTimes(2)
    await advance(2_000)
    expect(mockGetHistory).toHaveBeenCalledTimes(2)
    expect(text()).toContain('正在确认付款状态')
  })

  it.each(['guest', 'admin'])('%s 不读取顾客桌台或启动计时', async (role) => {
    mockAuthenticated = role !== 'guest'
    mockRole = role
    await util.mount(TableHistoryPage)
    await advance(60_000)
    expect(mockGetHistory).not.toHaveBeenCalled()
    expect(values()).toEqual([])
  })
})
