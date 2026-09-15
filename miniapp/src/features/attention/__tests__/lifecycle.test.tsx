import { act, useState } from 'react'
import ReactTestUtil from '@tarojs/test-utils-react'
import { Text } from '@tarojs/components'
import type { AttentionSummary } from '@/api/endpoints/attention'
import { useAttentionSummary } from '../hooks'
import { attentionStore } from '../runtime'

let mockHide: () => void
let mockShow: () => void
const mockSummary = jest.fn()
let mockAuth: { status: string; user?: { id: number; role: string } }
jest.mock('@tarojs/taro', () => ({
  ...jest.requireActual('@tarojs/taro'),
  useDidHide: (fn: () => void) => { mockHide = fn },
  useDidShow: (fn: () => void) => { mockShow = fn },
}))
jest.mock('@/auth', () => ({ useAuth: () => mockAuth, isAdminRole: (role: string) => role === 'admin' }))
jest.mock('@/api', () => ({ createApiClient: () => ({}) }))
jest.mock('@/auth/runtime', () => ({ getDefaultAuthRuntime: () => ({ session: {} }) }))
jest.mock('@/api/endpoints/attention', () => ({ AttentionApi: class { summary = mockSummary } }))
const result: AttentionSummary = {
  wallet_unread: 2, order_pending: 0, order_fulfillment: 0, order_unread: 1, order_total: 1,
  table_pending: 0, table_unread: 0, table_total: 0, server_now: '2026-09-14T01:00:00Z',
  reservation_actionable: 0, reservation_unread: 1, reservation_overdue: 0, reservation_total: 1,
}
const flush = () => act(async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve() })

describe('首页提醒真实 Hook 生命周期', () => {
  let util: ReactTestUtil
  let rerender!: () => void
  let current: ReturnType<typeof useAttentionSummary>
  function Probe() {
    const [, update] = useState(0)
    rerender = () => update((value) => value + 1)
    current = useAttentionSummary()
    return <Text>{current.summary?.wallet_unread ?? 'loading'}</Text>
  }
  beforeEach(() => {
    jest.useFakeTimers({ doNotFake: ['requestAnimationFrame', 'cancelAnimationFrame'] })
    util = new ReactTestUtil()
    attentionStore.setIdentity(undefined)
    mockAuth = { status: 'authenticated', user: { id: 7, role: 'user' } }
    mockSummary.mockReset().mockResolvedValue(result)
  })
  afterEach(() => { util.unmout(); attentionStore.setIdentity(undefined); jest.useRealTimers() })

  it('后台不轮询，返回立即刷新，退出清缓存并停止轮询', async () => {
    await util.mount(Probe); await flush()
    expect(mockSummary).toHaveBeenCalledTimes(1)
    await act(async () => { jest.advanceTimersByTime(30_000) }); await flush()
    expect(mockSummary).toHaveBeenCalledTimes(2)
    act(() => mockHide())
    await act(async () => { jest.advanceTimersByTime(120_000) }); await flush()
    expect(mockSummary).toHaveBeenCalledTimes(2)
    act(() => mockShow()); await flush()
    expect(mockSummary).toHaveBeenCalledTimes(3)
    mockAuth = { status: 'guest' }
    act(() => rerender()); await flush()
    expect(current.summary).toBeUndefined()
    expect(attentionStore.state.identity).toBeUndefined()
    await act(async () => { jest.advanceTimersByTime(120_000) }); await flush()
    expect(mockSummary).toHaveBeenCalledTimes(3)
  })

  it('网络失败保留旧数字和错误提示，恢复网络后重新获取结果', async () => {
    await util.mount(Probe); await flush()
    mockSummary.mockRejectedValue(new Error('offline'))
    await act(async () => { jest.advanceTimersByTime(30_000) }); await flush()
    expect(current.summary?.wallet_unread).toBe(2)
    expect(current.error).toContain('上次数据')
    const calls = mockSummary.mock.calls.length
    await act(async () => { jest.advanceTimersByTime(59_000) }); await flush()
    expect(mockSummary).toHaveBeenCalledTimes(calls)
    mockSummary.mockResolvedValue({ ...result, wallet_unread: 0 })
    await act(async () => { jest.advanceTimersByTime(1_000) }); await flush()
    expect(current.summary?.wallet_unread).toBe(0)
    expect(current.error).toBeUndefined()
  })
})
