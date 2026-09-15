import { act, useState } from 'react'
import { Text } from '@tarojs/components'
import ReactTestUtil from '@tarojs/test-utils-react'
import { useAdminTableOverview } from '../use_admin_table_overview'

let mockHide: () => void
let mockShow: () => void
const mockApi = { listAdminTables: jest.fn() }
jest.mock('@tarojs/taro', () => ({ ...jest.requireActual('@tarojs/taro'), useDidHide: (fn: () => void) => { mockHide = fn }, useDidShow: (fn: () => void) => { mockShow = fn } }))
jest.mock('@/features/table_session', () => ({ getDefaultTableSessionApi: () => mockApi }))
const now = Date.parse('2026-09-15T04:00:00Z')
const summary = { server_now: new Date(now).toISOString(), items: [{ id: 1, current_status: { value: 'active' }, timers: [
  { id: 1, duration_minutes: 60, service_ends_at: new Date(now + 600_000).toISOString(), grace_ends_at: new Date(now + 1200_000).toISOString() },
], table_release_at: new Date(now + 1200_000).toISOString() }] }
const flush = () => act(async () => { for (let i = 0; i < 10; i += 1) await Promise.resolve() })
let current: ReturnType<typeof useAdminTableOverview>
function Probe() { current = useAdminTableOverview(); return <Text>{current.counts.total}</Text> }
let util: ReactTestUtil
beforeEach(() => {
  jest.useFakeTimers({ doNotFake: ['requestAnimationFrame', 'cancelAnimationFrame'] }); jest.setSystemTime(now)
  util = new ReactTestUtil(); mockApi.listAdminTables.mockReset().mockResolvedValue(summary)
})
afterEach(() => { util.unmout(); jest.useRealTimers() })
it('后台暂停请求与秒级更新，回前台立即刷新；浏览本身不消除预警', async () => {
  await util.mount(Probe); await flush()
  expect(current.counts.total).toBe(1)
  expect(mockApi.listAdminTables).toHaveBeenCalledTimes(1)
  act(() => mockHide()); const stopped = current.now
  await act(async () => { jest.advanceTimersByTime(120_000) }); await flush()
  expect(current.now).toBe(stopped); expect(mockApi.listAdminTables).toHaveBeenCalledTimes(1)
  act(() => mockShow()); await flush()
  expect(mockApi.listAdminTables).toHaveBeenCalledTimes(2)
  expect(current.now).toBe(now + 120_000); expect(current.counts.total).toBe(1)
})
it('慢请求不重叠；请求中发生手动刷新时在完成后重读一次', async () => {
  let resolve!: (value: unknown) => void
  mockApi.listAdminTables.mockReturnValueOnce(new Promise((done) => { resolve = done }))
  await util.mount(Probe); await flush()
  await act(async () => { jest.advanceTimersByTime(30_000) }); await flush()
  expect(mockApi.listAdminTables).toHaveBeenCalledTimes(1)
  act(() => { current.refresh(); current.refresh() }); resolve(summary); await flush()
  expect(mockApi.listAdminTables).toHaveBeenCalledTimes(2)
})
it('断网保留上次数据，服务器确认释放后清除提醒和错误', async () => {
  await util.mount(Probe); await flush()
  mockApi.listAdminTables.mockRejectedValueOnce(new Error('offline'))
  act(() => current.refresh()); await flush()
  expect(current.counts.total).toBe(1); expect(current.error).toContain('上次数据')
  mockApi.listAdminTables.mockResolvedValue({ ...summary, items: [] })
  act(() => current.refresh()); await flush()
  expect(current.counts.total).toBe(0); expect(current.error).toBe('')
})
it('身份变化重新挂载不继承旧数据，旧请求不能覆盖新身份', async () => {
  let change!: () => void
  function Host() { const [id, setId] = useState(1); change = () => setId(2); return <Probe key={id} /> }
  let resolve!: (value: unknown) => void
  mockApi.listAdminTables.mockReturnValueOnce(new Promise((done) => { resolve = done })).mockResolvedValue({ ...summary, items: [] })
  await util.mount(Host); await flush(); act(() => change()); await flush(); resolve(summary); await flush()
  expect(current.counts.total).toBe(0); expect(mockApi.listAdminTables).toHaveBeenCalledTimes(2)
})
