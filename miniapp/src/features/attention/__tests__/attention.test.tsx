import { act } from 'react'
import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'
import { AttentionApi, type AttentionSummary } from '@/api/endpoints/attention'
import type { Reservation } from '@/api/endpoints/reservations'
import { AttentionBadge, ReservationAttentionReceipt } from '../index'
import { AttentionStore } from '../runtime'
import { syncNativeReservationBadge } from '../tab_badge'

const mockApi = { snapshot: jest.fn(), read: jest.fn(), summary: jest.fn() }
let mockHide: () => void
let mockShow: () => void
jest.mock('@tarojs/taro', () => ({
  ...jest.requireActual('@tarojs/taro'),
  setTabBarBadge: jest.fn().mockResolvedValue(undefined),
  removeTabBarBadge: jest.fn().mockResolvedValue(undefined),
  useDidHide: (callback: () => void) => { mockHide = callback },
  useDidShow: (callback: () => void) => { mockShow = callback },
}))
jest.mock('@/auth', () => ({
  useAuth: () => ({ status: 'authenticated', user: { id: 7, role: 'user' } }),
  isAdminRole: (role: string) => role !== 'user',
}))
jest.mock('../runtime', () => ({
  ...jest.requireActual('../runtime'),
  getAttentionApi: () => mockApi,
  attentionStore: { refresh: jest.fn(), invalidate: jest.fn(), state: {} },
}))

const updated = '2026-09-14T01:00:00Z'
const reservation = { id: 31, updated_at: updated, status: { value: 'confirmed' }, scheduled_start_at: '2026-09-15T03:00:00Z' } as Reservation
const snapshot = { reservation_id: 31, reservation_updated_at: updated, server_now: updated, events: [{ id: 8, event_type: 'reservation_confirmed', label: '门店已确认预约', occurred_at: updated }] }
const summary: AttentionSummary = { wallet_unread: 0, order_pending: 0, order_fulfillment: 0, order_unread: 0, order_total: 0, table_pending: 0, table_unread: 0, table_total: 0, server_now: updated, reservation_actionable: 0, reservation_unread: 2, reservation_overdue: 0, reservation_total: 2 }
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })

describe('提醒展示与阅读', () => {
  let util: ReactTestUtil
  beforeEach(() => {
    jest.useFakeTimers({ doNotFake: ['requestAnimationFrame', 'cancelAnimationFrame'] })
    util = new ReactTestUtil()
    mockApi.snapshot.mockResolvedValue(snapshot)
    mockApi.read.mockResolvedValue(undefined)
  })
  afterEach(() => { util.unmout(); jest.clearAllMocks(); jest.useRealTimers() })

  it('角标显示 99+ 且不会展示 0', async () => {
    await util.mount(() => <><AttentionBadge count={0} /><AttentionBadge count={100} /></>)
    expect(util.queries.querySelectorAll('.attention-badge')).toHaveLength(1)
    expect(util.queries.querySelector('.attention-badge')?.textContent).toBe('99+')
  })

  it('前台详情展示对应版本后只确认精确事件', async () => {
    await util.mount(() => <ReservationAttentionReceipt reservation={reservation} refreshDetail={jest.fn()} />)
    await flush()
    expect(mockApi.read).toHaveBeenCalledWith(false, [8])
    expect(mockApi.read).toHaveBeenCalledTimes(1)
  })

  it('新事件与旧详情版本不一致时刷新详情，不误清新事件', async () => {
    const refresh = jest.fn()
    mockApi.snapshot.mockResolvedValue({ ...snapshot, reservation_updated_at: '2026-09-14T01:01:00Z' })
    await util.mount(() => <ReservationAttentionReceipt reservation={reservation} refreshDetail={refresh} />)
    await flush()
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(mockApi.read).not.toHaveBeenCalled()
  })

  it('离开页面后到达的快照不标已读，返回重新读取', async () => {
    const pending = deferred<typeof snapshot>()
    mockApi.snapshot.mockReturnValueOnce(pending.promise)
    await util.mount(() => <ReservationAttentionReceipt reservation={reservation} refreshDetail={jest.fn()} />)
    act(() => mockHide())
    await act(async () => pending.resolve(snapshot))
    expect(mockApi.read).not.toHaveBeenCalled()
    act(() => mockShow())
    await flush()
    expect(mockApi.read).toHaveBeenCalledWith(false, [8])
  })

  it('管理员打开变更不会自动知悉，点击后才确认', async () => {
    await util.mount(() => <ReservationAttentionReceipt admin reservation={reservation} refreshDetail={jest.fn()} />)
    await flush()
    expect(mockApi.read).not.toHaveBeenCalled()
    const button = util.queries.querySelector('.attention-receipt__action')
    expect(button?.textContent).toBe('已知悉')
    await act(async () => { button?.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(mockApi.read).toHaveBeenCalledWith(true, [8])
  })

  it('已读失败保留重试，不无限循环发送', async () => {
    mockApi.read.mockRejectedValueOnce(new Error('offline'))
    await util.mount(() => <ReservationAttentionReceipt reservation={reservation} refreshDetail={jest.fn()} />)
    await flush()
    expect(util.queries.querySelector('.attention-receipt')?.textContent).toContain('已读状态未保存')
    expect(mockApi.read).toHaveBeenCalledTimes(1)
    const button = util.queries.querySelector('.attention-receipt__action')
    await act(async () => { button?.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(mockApi.read).toHaveBeenCalledTimes(2)
  })
})

describe('跨入口汇总与协议校验', () => {
  it('原生底栏清除新账号等待加载和退出后的旧数字，失败保留已有汇总', () => {
    syncNativeReservationBadge({ identity: '7:user', summary, error: '更新失败' })
    expect(Taro.setTabBarBadge).toHaveBeenLastCalledWith({ index: 1, text: '2' })
    syncNativeReservationBadge({ identity: '9:user' })
    expect(Taro.removeTabBarBadge).toHaveBeenLastCalledWith({ index: 1 })
    syncNativeReservationBadge({})
    syncNativeReservationBadge({ identity: '7:admin', summary })
    expect(Taro.removeTabBarBadge).toHaveBeenCalledWith({ index: 3 })
    expect(Taro.removeTabBarBadge).toHaveBeenCalledTimes(7)
  })

  it('同一账号并发刷新合并，错误保留旧值，账号切换丢弃迟到响应', async () => {
    const store = new AttentionStore()
    store.setIdentity('7:user')
    const pending = deferred<AttentionSummary>()
    const source = { summary: jest.fn(() => pending.promise) }
    const first = store.refresh(false, source)
    const second = store.refresh(false, source)
    await Promise.resolve()
    expect(source.summary).toHaveBeenCalledTimes(1)
    pending.resolve(summary)
    await Promise.all([first, second])
    await store.refresh(false, { summary: jest.fn().mockRejectedValue(new Error('offline')) })
    expect(store.state.summary?.reservation_unread).toBe(2)
    expect(store.state.error).toBeTruthy()
    const late = deferred<AttentionSummary>()
    const active = store.refresh(false, { summary: () => late.promise })
    store.setIdentity('9:user')
    late.resolve(summary)
    await active
    expect(store.state).toEqual({ identity: '9:user' })
  })

  it('会员底栏合并余额结果，清除身份后同步移除', () => {
    syncNativeReservationBadge({ identity: '7:user', summary: { ...summary, wallet_unread: 2, order_total: 1, table_total: 1 } })
    expect(Taro.setTabBarBadge).toHaveBeenCalledWith({ index: 3, text: '4' })
    syncNativeReservationBadge({})
    expect(Taro.removeTabBarBadge).toHaveBeenCalledWith({ index: 3 })
  })

  it('余额汇总缺失或无效时不把未知伪装成零', async () => {
    const request = jest.fn()
    const api = new AttentionApi({ request })
    for (const walletUnread of [undefined, -1, 0.5, '1']) {
      request.mockResolvedValue({ ...summary, wallet_unread: walletUnread })
      await expect(api.summary(false)).rejects.toThrow()
    }
    request.mockResolvedValue({ ...summary, wallet_unread: 2 })
    expect((await api.summary(false)).wallet_unread).toBe(2)
  })

  it('拒绝假零、非法计数、详情资源不匹配和重复事件', async () => {
    const request = jest.fn()
    const api = new AttentionApi({ request })
    for (const value of [{ ...summary, reservation_unread: -1 }, { ...summary, reservation_total: 0 }, { ...summary, server_now: 'invalid' }]) {
      request.mockResolvedValueOnce(value)
      await expect(api.summary(false)).rejects.toThrow()
    }
    request.mockResolvedValueOnce({ ...snapshot, reservation_id: 32 })
    await expect(api.snapshot(false, 31)).rejects.toThrow()
    request.mockResolvedValueOnce({ ...snapshot, events: [snapshot.events[0], snapshot.events[0]] })
    await expect(api.snapshot(false, 31)).rejects.toThrow()
    await expect(api.read(false, [8, 8])).rejects.toThrow()
  })
})
