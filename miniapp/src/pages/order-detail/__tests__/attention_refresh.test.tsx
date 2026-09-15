import { act } from 'react'
import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'
import type { OrderDetail } from '@/api/endpoints/orders'
import { AuthenticatedOrderDetail } from '../index'

const time = '2026-09-14T01:00:00Z'
const pendingOrder: OrderDetail = {
  id: 101, order_no: `OD${'1'.repeat(26)}`, total_amount: '80.00',
  status: { value: 'pending', label: '待支付' }, remark: null, items: [],
  created_at: time, updated_at: time,
}
const paidOrder: OrderDetail = {
  ...pendingOrder, status: { value: 'paid', label: '已支付' }, updated_at: '2026-09-14T02:00:00Z',
}
const paidEvent = {
  id: 15, event_type: 'order_wallet_paid', label: '余额支付成功',
  message: '已使用余额支付 ¥80.00。', occurred_at: time, read: false, session_no: null as string | null,
}
let mockOrder: OrderDetail
let mockEvents: typeof paidEvent[]
const mockOrderApi = { getOrderDetail: jest.fn(), cancelOrder: jest.fn() }
const mockWalletApi = { getOrderFinancials: jest.fn(), payOrderWithWallet: jest.fn() }
const mockAttentionApi = { commerceSnapshot: jest.fn(), read: jest.fn() }
const mockTableApi = { getOrderSession: jest.fn() }

jest.mock('@tarojs/taro', () => ({
  ...jest.requireActual('@tarojs/taro'), useDidHide: jest.fn(), useDidShow: jest.fn(),
}))
jest.mock('@/auth', () => ({
  ORDER_LIST_PATH: '/pages/orders/index',
  useAuth: () => ({ status: 'authenticated', user: { id: 7, role: 'user' } }),
}))
jest.mock('@/features/order/runtime', () => ({ getDefaultOrderApi: () => mockOrderApi }))
jest.mock('@/features/wallet/runtime', () => ({ getDefaultWalletApi: () => mockWalletApi }))
jest.mock('@/features/attention/runtime', () => ({
  getAttentionApi: () => mockAttentionApi, attentionStore: { invalidate: jest.fn() },
}))
jest.mock('@/features/wallet/use_member_wallet', () => ({
  useMemberWallet: () => ({ state: { status: 'content', member: {
    user: { status: 'normal' }, wallet: { balance: '500.00', status: 'active', capabilities: { wallet_payment_enabled: true } },
  } }, retry: jest.fn() }),
}))

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })

describe('真实订单 Hook 与结果提醒组合刷新', () => {
  let util: ReactTestUtil
  beforeEach(() => {
    jest.useFakeTimers({ doNotFake: ['requestAnimationFrame', 'cancelAnimationFrame'] })
    util = new ReactTestUtil()
    mockOrder = pendingOrder
    mockEvents = []
    mockTableApi.getOrderSession.mockResolvedValue(null)
    mockOrderApi.getOrderDetail.mockImplementation(() => {
      // 旧实现会不断重挂载；限制夹具响应次数，让回归明确失败而非无限运行。
      if (mockOrderApi.getOrderDetail.mock.calls.length > 8) return new Promise(() => undefined)
      return Promise.resolve(mockOrder)
    })
    mockWalletApi.getOrderFinancials.mockImplementation(async () => ({
      order_id: 101, order_status: mockOrder.status, payment: null, refund: null,
    }))
    mockWalletApi.payOrderWithWallet.mockImplementation(async () => {
      mockOrder = paidOrder
      mockEvents = [{ ...paidEvent }]
      return { order_id: 101, order_status: paidOrder.status }
    })
    mockAttentionApi.commerceSnapshot.mockImplementation(async () => ({ server_now: time, events: mockEvents }))
    mockAttentionApi.read.mockImplementation(async (_admin, ids: number[]) => {
      expect(util.queries.querySelector('.attention-receipt')?.textContent).toContain('80.00')
      mockEvents = mockEvents.map((event) => ids.includes(event.id) ? { ...event, read: true } : event)
    })
    jest.spyOn(Taro, 'showModal').mockResolvedValue({ confirm: true, cancel: false, errMsg: 'ok' })
  })
  afterEach(() => {
    util.unmout(); jest.resetAllMocks(); jest.useRealTimers()
  })

  it('余额支付后稳定展示订单与结果，不反复加载或重复扣款', async () => {
    await util.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    await flush()
    await act(async () => { util.fireEvent.click(util.queries.querySelector('.order-payment__submit')!) })
    await flush()
    expect(mockWalletApi.payOrderWithWallet).toHaveBeenCalledTimes(1)
    expect(mockOrderApi.getOrderDetail).toHaveBeenCalledTimes(3)
    expect(mockAttentionApi.read).toHaveBeenCalledTimes(1)
    const heading = util.queries.querySelector('.order-detail-heading')
    expect(heading?.textContent).toContain('已支付')
    expect(util.queries.querySelector('.attention-receipt')?.textContent).toContain('余额支付成功')
    await act(async () => { jest.advanceTimersByTime(90_000) })
    await flush()
    expect(util.queries.querySelector('.order-detail-heading')).toBe(heading)
    expect(mockOrderApi.getOrderDetail).toHaveBeenCalledTimes(3)
    expect(mockWalletApi.payOrderWithWallet).toHaveBeenCalledTimes(1)
  })

  it.each(['loaded', 'error', 'missing'])('桌台%s时，同次桌台的多条结果只保留一个可用入口', async (state) => {
    const sessionNo = `TS${'1'.repeat(26)}`
    mockOrder = paidOrder
    mockEvents = [
      { ...paidEvent, session_no: sessionNo },
      { ...paidEvent, id: 16, event_type: 'order_manual_paid', label: '门店已确认收款', session_no: sessionNo },
    ]
    if (state === 'loaded') mockTableApi.getOrderSession.mockResolvedValue({
      session_no: sessionNo, table: { table_no: 'T01' },
      status: { value: 'in_use', label: '计时中' }, server_now: time, payment_deadline_at: time,
    })
    if (state === 'error') mockTableApi.getOrderSession.mockRejectedValue(new Error('桌台读取失败'))
    await util.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    await flush()
    const page = util.queries.querySelector('.order-detail-page')!
    expect(page.textContent?.match(/查看这次桌台/g)).toHaveLength(1)
    expect(util.queries.querySelector('.attention-receipt')?.textContent).toContain('已使用余额支付 ¥80.00')
    const selector = state === 'loaded' ? '.table-selector__clear' : '.attention-receipt__action'
    if (state === 'loaded') expect(util.queries.querySelector('.attention-receipt__action')).toBeNull()
    await act(async () => { util.fireEvent.click(util.queries.querySelector(selector)!) })
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: `/pages/table-history/index?sessionNo=${sessionNo}` })
    expect(mockAttentionApi.read).toHaveBeenCalledWith(false, [15, 16])
  })

  it.each([false, true])('进入已有结果的订单保持稳定（read=%s），新结果仍会更新', async (read) => {
    mockOrder = paidOrder
    mockEvents = [{ ...paidEvent, read }]
    await util.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    await flush()
    expect(mockOrderApi.getOrderDetail).toHaveBeenCalledTimes(2)
    const heading = util.queries.querySelector('.order-detail-heading')
    expect(heading).not.toBeNull()
    await act(async () => { jest.advanceTimersByTime(30_000) })
    expect(mockOrderApi.getOrderDetail).toHaveBeenCalledTimes(2)
    mockOrder = { ...paidOrder, status: { value: 'completed', label: '已完成' }, updated_at: '2026-09-14T03:00:00Z' }
    mockEvents = [...mockEvents, { ...paidEvent, id: 16, event_type: 'order_completed', label: '订单已完成', message: '门店已完成本次订单服务。' }]
    await act(async () => { jest.advanceTimersByTime(30_000) })
    await flush()
    expect(mockOrderApi.getOrderDetail).toHaveBeenCalledTimes(3)
    expect(util.queries.querySelector('.order-detail-heading')).toBe(heading)
    expect(heading?.textContent).toContain('已完成')
    await act(async () => { jest.advanceTimersByTime(30_000) })
    expect(mockOrderApi.getOrderDetail).toHaveBeenCalledTimes(3)
  })

  it('后台更新失败保留已显示内容与结果，允许主动重试且不忙循环', async () => {
    mockOrder = paidOrder
    mockEvents = [{ ...paidEvent }]
    mockOrderApi.getOrderDetail.mockResolvedValueOnce(paidOrder).mockRejectedValueOnce(new Error('offline'))
    await util.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    await flush()
    expect(util.queries.querySelector('.order-detail-heading')?.textContent).toContain('已支付')
    expect(util.queries.querySelector('.order-payment__feedback')?.textContent).toContain('订单更新失败')
    expect(mockOrderApi.getOrderDetail).toHaveBeenCalledTimes(2)
    await act(async () => { jest.advanceTimersByTime(30_000) })
    expect(mockOrderApi.getOrderDetail).toHaveBeenCalledTimes(2)
    await act(async () => { util.fireEvent.click(util.queries.querySelector('.order-payment__retry')!) })
    await flush()
    expect(mockOrderApi.getOrderDetail).toHaveBeenCalledTimes(3)
    expect(util.queries.querySelector('.order-payment__feedback')).toBeNull()
  })
})

jest.mock('@/features/table_session/runtime', () => ({ getDefaultTableSessionApi: () => mockTableApi }))
