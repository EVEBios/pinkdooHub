import { act } from 'react'
import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'
import { AttentionApi } from '@/api/endpoints/attention'
import { CommerceReceipt, buildSessionHistoryUrl } from '../commerce'

const mockApi = { commerceSnapshot: jest.fn(), read: jest.fn() }
let mockHide: () => void
let mockShow: () => void
let mockUser = { id: 7, role: 'user' }
jest.mock('@tarojs/taro', () => ({
  ...jest.requireActual('@tarojs/taro'),
  useDidHide: (callback: () => void) => { mockHide = callback },
  useDidShow: (callback: () => void) => { mockShow = callback },
}))
jest.mock('@/auth', () => ({ useAuth: () => ({ status: 'authenticated', user: mockUser }) }))
jest.mock('../runtime', () => ({ getAttentionApi: () => mockApi, attentionStore: { invalidate: jest.fn() } }))
const sessionNo = `TS${'1'.repeat(26)}`
const time = '2026-09-14T01:00:00Z'
const event = { id: 15, event_type: 'order_manual_paid', label: '门店已确认收款', message: '门店已确认收款 ¥80.00。本次桌台已开始计时。', occurred_at: time, read: false, session_no: sessionNo }
const snapshot = { server_now: time, events: [event] }
const adjustment = { ...event, id: 22, event_type: 'wallet_adjusted', label: '门店已调整余额', message: '余额减少 ¥5.00，调整后余额 ¥95.00。', session_no: null,
  wallet_transaction: { id: 91, change_amount: '-5.00', before_balance: '100.00', after_balance: '95.00', reason: '订单差额纠正' } }
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('订单桌台结果完整展示与精确已读', () => {
  let util: ReactTestUtil
  beforeEach(() => {
    jest.useFakeTimers({ doNotFake: ['requestAnimationFrame', 'cancelAnimationFrame'] })
    util = new ReactTestUtil()
    mockUser = { id: 7, role: 'user' }
    mockApi.commerceSnapshot.mockResolvedValue(snapshot)
    mockApi.read.mockResolvedValue(undefined)
  })
  afterEach(() => { util.unmout(); jest.clearAllMocks(); jest.useRealTimers() })

  it('余额调整完整展示原流水与原因后才确认，已读后保留内容', async () => {
    mockApi.commerceSnapshot.mockResolvedValue({ server_now: time, events: [adjustment] })
    mockApi.read.mockImplementation(async () => {
      const text = util.queries.querySelector('.attention-receipt')?.textContent
      for (const value of ['91', '-5.00', '100.00', '95.00', '订单差额纠正', '本笔发生时']) expect(text).toContain(value)
    })
    await util.mount(() => <CommerceReceipt scope='wallet' target={22} />)
    await flush()
    expect(mockApi.read).toHaveBeenCalledWith(false, [22])
    expect(util.queries.querySelector('.attention-receipt')?.textContent).toContain('订单差额纠正')
    await act(async () => { jest.advanceTimersByTime(60_000) })
    expect(mockApi.commerceSnapshot).toHaveBeenCalledTimes(1)
  })

  it('余额变动查询失败及隐藏时迟到的结果都不清除提醒', async () => {
    mockApi.commerceSnapshot.mockRejectedValueOnce(new Error('offline'))
    await util.mount(() => <CommerceReceipt scope='wallet' target={22} />)
    await flush()
    expect(util.queries.querySelector('.attention-receipt')?.textContent).toContain('余额变动暂时无法读取')
    expect(mockApi.read).not.toHaveBeenCalled()
    const pending = deferred<{ server_now: string; events: typeof adjustment[] }>()
    mockApi.commerceSnapshot.mockReturnValueOnce(pending.promise)
    await act(async () => { util.fireEvent.click(util.queries.querySelector('.attention-receipt__action')!) })
    act(() => mockHide())
    await act(async () => pending.resolve({ server_now: time, events: [adjustment] }))
    expect(mockApi.read).not.toHaveBeenCalled()
    mockApi.commerceSnapshot.mockResolvedValue({ server_now: time, events: [adjustment] })
    act(() => mockShow())
    await flush()
    expect(mockApi.read).toHaveBeenCalledWith(false, [22])
  })

  it.each(['order_assisted_wallet_paid', 'order_wallet_refunded', 'order_manual_refunded'])('识别 %s 并归入同一订单快照', async (eventType) => {
    await util.mount(() => <></>)
    const request = jest.fn().mockResolvedValue({ server_now: time, events: [{ ...event, event_type: eventType }] })
    const api = new AttentionApi({ request })
    expect((await api.commerceSnapshot('orders', 42)).events[0].event_type).toBe(eventType)
  })

  it('余额结果 API 校验精确事件、完整流水、非零变化和余额一致性', async () => {
    await util.mount(() => <></>)
    const request = jest.fn().mockResolvedValue({ server_now: time, events: [adjustment] })
    const api = new AttentionApi({ request })
    expect((await api.commerceSnapshot('wallet', 22)).events[0].wallet_transaction?.id).toBe(91)
    expect(request).toHaveBeenLastCalledWith(expect.objectContaining({ path: '/api/v1/attention/wallet/22', auth: 'required' }))
    await expect(api.commerceSnapshot('wallet', 23)).rejects.toThrow()
    for (const walletTransaction of [null, { ...adjustment.wallet_transaction, change_amount: '0.00' }, { ...adjustment.wallet_transaction, after_balance: '99.00' }, { ...adjustment.wallet_transaction, reason: '' }]) {
      request.mockResolvedValue({ server_now: time, events: [{ ...adjustment, wallet_transaction: walletTransaction }] })
      await expect(api.commerceSnapshot('wallet', 22)).rejects.toThrow()
    }
  })

  it('余额列表无待付款和管理员入口，读取列表不发送已读', async () => {
    await util.mount(() => <></>)
    const item = { id: 22, scope: 'wallet', reference: '余额调整记录 #22', title: adjustment.message, status_label: adjustment.label, order_id: null, session_no: null, unread: true, created_at: time, payment_deadline_at: null }
    const request = jest.fn().mockResolvedValue({ items: [item], page: 1, page_size: 20, pages: 1, total: 1 })
    const api = new AttentionApi({ request })
    expect((await api.commerceList(false, 'wallet', 'unread')).items[0].id).toBe(22)
    expect(request).toHaveBeenLastCalledWith(expect.objectContaining({ path: '/api/v1/attention/wallet', query: { view: 'unread', page: 1, page_size: 20 } }))
    await expect(api.commerceList(true, 'wallet', 'all')).rejects.toThrow()
    await expect(api.commerceList(false, 'wallet', 'pending')).rejects.toThrow()
    expect(request).toHaveBeenCalledTimes(1)
  })

  it('先展示金额及桌台结果再确认，已读不移除结果文本', async () => {
    mockApi.read.mockImplementation(async () => {
      expect(util.queries.querySelector('.attention-receipt')?.textContent).toContain('¥80.00')
    })
    await util.mount(() => <CommerceReceipt scope='orders' target={42} />)
    await flush()
    expect(mockApi.read).toHaveBeenCalledWith(false, [15])
    expect(mockApi.read).toHaveBeenCalledTimes(1)
    expect(util.queries.querySelector('.attention-receipt')?.textContent).toContain('开始计时')
    const nav = jest.spyOn(Taro, 'navigateTo').mockResolvedValue({ errMsg: 'ok' })
    await act(async () => { util.queries.querySelector('.attention-receipt__action')?.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(nav).toHaveBeenCalledWith({ url: buildSessionHistoryUrl(sessionNo) })
    nav.mockRestore()
  })

  it('上方展示不同会话时仍保留历史结果的精确桌台入口', async () => {
    await util.mount(() => <CommerceReceipt scope='orders' target={42} linkedSessionNo={`TS${'2'.repeat(26)}`} />)
    await flush()
    const nav = jest.spyOn(Taro, 'navigateTo').mockResolvedValue({ errMsg: 'ok' })
    await act(async () => { util.fireEvent.click(util.queries.querySelector('.attention-receipt__action')!) })
    expect(nav).toHaveBeenCalledWith({ url: buildSessionHistoryUrl(sessionNo) })
    nav.mockRestore()
  })

  it('已确认的结果遇到后台旧快照不重复确认', async () => {
    await util.mount(() => <CommerceReceipt scope='orders' target={42} />)
    await flush()
    await act(async () => { jest.advanceTimersByTime(30_000); await Promise.resolve() })
    await flush()
    expect(mockApi.read).toHaveBeenCalledTimes(1)
    expect(util.queries.querySelector('.attention-receipt')?.textContent).toContain('开始计时')
  })

  it('离开页面时迟到的快照不确认，返回重新获取', async () => {
    const pending = deferred<typeof snapshot>()
    mockApi.commerceSnapshot.mockReturnValueOnce(pending.promise)
    await util.mount(() => <CommerceReceipt scope='orders' target={42} />)
    act(() => mockHide())
    await act(async () => pending.resolve(snapshot))
    expect(mockApi.read).not.toHaveBeenCalled()
    act(() => mockShow())
    await flush()
    expect(mockApi.read).toHaveBeenCalledWith(false, [15])
  })

  it('旧已读请求在途时的新事件仍会单独确认', async () => {
    const pending = deferred<void>()
    mockApi.read.mockReturnValueOnce(pending.promise)
    await util.mount(() => <CommerceReceipt scope='orders' target={42} />)
    await flush()
    const nextEvent = { ...event, id: 16, event_type: 'order_completed', label: '订单已完成', message: '门店已完成本次订单服务。' }
    mockApi.commerceSnapshot.mockResolvedValue({ server_now: time, events: [event, nextEvent] })
    await act(async () => { jest.advanceTimersByTime(30_000); await Promise.resolve() })
    expect(mockApi.read).toHaveBeenCalledTimes(1)
    await act(async () => pending.resolve())
    await flush()
    expect(mockApi.read).toHaveBeenLastCalledWith(false, [16])
  })

  it('保存失败保留提醒并允许重试，不忙循环', async () => {
    mockApi.read.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined)
    await util.mount(() => <CommerceReceipt scope='tables' target={sessionNo} />)
    await flush()
    expect(util.queries.querySelector('.attention-receipt')?.textContent).toContain('已读状态未保存')
    expect(mockApi.read).toHaveBeenCalledTimes(1)
    await act(async () => { util.queries.querySelector('.attention-receipt__action')?.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    await flush()
    expect(mockApi.read).toHaveBeenCalledTimes(2)
  })

  it('桌台页复用外层刷新节奏，隐藏后不再请求结果', async () => {
    await util.mount(() => <CommerceReceipt scope='tables' target={sessionNo} />)
    await flush()
    await act(async () => { jest.advanceTimersByTime(60_000) })
    expect(mockApi.commerceSnapshot).toHaveBeenCalledTimes(1)
    act(() => mockHide())
    await act(async () => { jest.advanceTimersByTime(60_000) })
    expect(mockApi.commerceSnapshot).toHaveBeenCalledTimes(1)
  })
})

describe('订单提醒响应契约', () => {
  it('拒绝不完整金额摘要和重复事件，不发已读请求', async () => {
    const request = jest.fn().mockResolvedValue(snapshot)
    const api = new AttentionApi({ request })
    expect((await api.commerceSnapshot('orders', 42)).events).toHaveLength(1)
    request.mockResolvedValue({ ...snapshot, events: [{ ...event, message: '' }] })
    await expect(api.commerceSnapshot('orders', 42)).rejects.toThrow()
    request.mockResolvedValue({ ...snapshot, events: [event, event] })
    await expect(api.commerceSnapshot('orders', 42)).rejects.toThrow()
  })

  it('桌台列表必须定位同一会话且分页数量准确', async () => {
    const item = { id: 1, scope: 'tables', reference: sessionNo, title: 'T01号桌', status_label: '待付款', order_id: 42, session_no: sessionNo, unread: false, created_at: time, payment_deadline_at: time }
    const value = { items: [item], total: 1, page: 1, page_size: 20, pages: 1 }
    const request = jest.fn().mockResolvedValue(value)
    const api = new AttentionApi({ request })
    expect((await api.commerceList(false, 'tables', 'all')).items[0].session_no).toBe(sessionNo)
    expect((await api.myTableSessions()).items[0].session_no).toBe(sessionNo)
    expect(request).toHaveBeenLastCalledWith(expect.objectContaining({ path: '/api/v1/attention/table-sessions', auth: 'required', query: { page: 1, page_size: 20 } }))
    request.mockResolvedValue({ ...value, items: [{ ...item, session_no: `TS${'2'.repeat(26)}` }] })
    await expect(api.commerceList(false, 'tables', 'all')).rejects.toThrow()
    await expect(api.myTableSessions()).rejects.toThrow()
    request.mockResolvedValue({ ...value, pages: 9 })
    await expect(api.commerceList(false, 'tables', 'all')).rejects.toThrow()
    await expect(api.myTableSessions()).rejects.toThrow()
  })
})
