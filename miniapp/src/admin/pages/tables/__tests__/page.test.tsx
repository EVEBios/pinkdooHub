import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import { TimeoutError } from '@/api/errors'
import AdminTablesPage from '../index'

const now = '2026-09-14T04:00:00Z'
const mockApi = {
  listAdminTables: jest.fn(), listDirectDurations: jest.fn(), createDirectSession: jest.fn(),
  getAdminSession: jest.fn(), confirmAdminPayment: jest.fn(), updateAdminTable: jest.fn(),
}
let mockRole = 'admin'
jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: { navigateTo: jest.fn(), pageScrollTo: jest.fn(async () => undefined), showModal: jest.fn(async () => ({ confirm: true })) },
  useDidShow: () => undefined,
  useDidHide: () => undefined,
}))
jest.mock('@/auth', () => ({
  useAuth: () => ({ status: 'authenticated', user: { id: 1, role: mockRole } }),
  isAdminRole: (role: string) => role === 'admin',
}))
jest.mock('@/features/table_session', () => ({
  getDefaultTableSessionApi: () => mockApi,
  buildAdminTableSessionUrl: (value: string) => `/admin/pages/table-session-detail/index?session_no=${value}`,
}))

const emptyTable = { id: 1, table_no: 'T01', display_name: 'T01号桌', is_enabled: true, state: 'available', current_session_no: null }
let util: ReactTestUtil
async function flush() { await new Promise((resolve) => setTimeout(resolve, 15)) }
function button(text: string) {
  const element = Array.from(util.queries.querySelectorAll('button, taro-button-core')).find((item) => item.textContent === text)
  if (!element) throw new Error(`Missing button ${text}`)
  return element
}

beforeEach(() => {
  util = new ReactTestUtil()
  mockRole = 'admin'
  jest.spyOn(Date, 'now').mockReturnValue(Date.parse(now))
  mockApi.listAdminTables.mockResolvedValue({ server_now: now, items: [emptyTable] })
  mockApi.listDirectDurations.mockResolvedValue({ buffer_minutes: 10, items: [{ option_id: 5, duration_minutes: 60 }, { option_id: 6, duration_minutes: 120 }] })
})
afterEach(() => { util.unmout(); jest.restoreAllMocks(); jest.clearAllMocks() })

it('体验、缓冲和停用新开台的桌台都显示剩余时间', async () => {
  mockApi.listAdminTables.mockResolvedValue({ server_now: now, items: [
    { ...emptyTable, state: 'active', current_session_no: 'TS1', current_status: { value: 'active' }, current_source: 'order', timer_count: 2,
      service_ends_at: '2026-09-14T05:00:00Z', table_release_at: '2026-09-14T05:10:00Z' },
    { ...emptyTable, id: 2, table_no: 'T02', state: 'disabled', is_enabled: false, current_session_no: 'TS2', current_status: { value: 'active' }, current_source: 'direct',
      service_ends_at: '2026-09-14T03:55:00Z', table_release_at: '2026-09-14T04:05:00Z' },
  ] })
  await util.mount(AdminTablesPage); await flush()
  const cards = util.queries.querySelectorAll('.admin-table')
  expect(cards[0].textContent).toContain('01:00:00')
  expect(cards[0].textContent).toContain('共 2 组计时')
  expect(cards[1].textContent).toContain('缓冲中')
  expect(cards[1].textContent).toContain('00:05:00')
  expect(cards[1].textContent).toContain('暂停新开台')
})

it('直接开台选择配置后提交，超时重试保持原操作身份', async () => {
  mockApi.createDirectSession.mockRejectedValueOnce(new TimeoutError({ operation: 'direct' }, null)).mockResolvedValueOnce({})
  await util.mount(AdminTablesPage); await flush()
  util.fireEvent.click(button('直接开台')); await flush()
  util.fireEvent.click(button('60 分钟'))
  util.fireEvent.click(button('确认开始计时')); await flush()
  expect(button('取消').hasAttribute('disabled')).toBe(true)
  util.fireEvent.click(button('重试原操作并确认结果')); await flush()
  expect(mockApi.createDirectSession).toHaveBeenCalledTimes(2)
  expect(mockApi.createDirectSession.mock.calls[0]).toEqual(mockApi.createDirectSession.mock.calls[1])
  expect(mockApi.createDirectSession.mock.calls[0].slice(0, 3)).toEqual([1, { option_id: 5, duration_minutes: 60 }, ''])
})

it('待付款桌台先展示整单收款信息，确认后绑定该会话付款', async () => {
  mockApi.listAdminTables.mockResolvedValue({ server_now: now, items: [{ ...emptyTable, state: 'awaiting_payment', current_session_no: 'TS1', current_status: { value: 'awaiting_payment' }, payment_deadline_at: '2026-09-14T04:15:00Z' }] })
  mockApi.getAdminSession.mockResolvedValue({ table: emptyTable, status: { value: 'awaiting_payment' }, order_id: 8, order_no: 'OD8', user_nickname: '顾客', order_total_amount: '80.00', order_experience_durations: [60, 120] })
  mockApi.confirmAdminPayment.mockResolvedValue(undefined)
  await util.mount(AdminTablesPage); await flush()
  util.fireEvent.click(button('确认已收款并计时')); await flush()
  expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({ content: expect.stringContaining('¥80.00') }))
  expect(mockApi.confirmAdminPayment).toHaveBeenCalledWith(8, 'TS1')
})

it('普通顾客不加载桌台管理数据', async () => {
  mockRole = 'user'
  await util.mount(AdminTablesPage); await flush()
  expect(mockApi.listAdminTables).not.toHaveBeenCalled()
})

it('逐组预警并用完整按钮筛选，读页面不清提醒', async () => {
  const short = { id: 1, duration_minutes: 60, service_ends_at: '2026-09-14T04:08:00Z', grace_ends_at: '2026-09-14T04:18:00Z' }
  const long = { id: 2, duration_minutes: 120, service_ends_at: '2026-09-14T05:08:00Z', grace_ends_at: '2026-09-14T05:18:00Z' }
  mockApi.listAdminTables.mockResolvedValue({ server_now: now, items: [
    { ...emptyTable, state: 'active', current_status: { value: 'active' }, current_session_no: 'TS1', timers: [short, long], timer_count: 2, service_ends_at: long.service_ends_at, table_release_at: long.grace_ends_at },
    { ...emptyTable, id: 2, table_no: 'T02' },
  ] })
  await util.mount(AdminTablesPage); await flush()
  expect(util.queries.querySelector('.admin-table__warning')?.textContent).toContain('60 分钟组 · 即将到时')
  expect(util.queries.querySelector('.admin-tables-attention__title')?.textContent).toBe('待收款 0 桌 · 到时提醒 1 桌')
  util.fireEvent.click(button('需关注 1')); await flush()
  expect(util.queries.querySelectorAll('.admin-table')).toHaveLength(1)
  util.fireEvent.click(button('全部桌台')); await flush()
  expect(util.queries.querySelectorAll('.admin-table')).toHaveLength(2)
  expect(button('需关注 1')).toBeDefined()
})
