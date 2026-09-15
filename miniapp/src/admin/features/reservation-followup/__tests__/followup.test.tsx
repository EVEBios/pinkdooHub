import { act } from 'react'
import ReactTestUtil from '@tarojs/test-utils-react'
import { FollowupList } from '@/admin/pages/reservation-followups'
import { FollowupPanel } from '../panel'
import { FollowupEntry } from '../entry'

const mockApi = { detail: jest.fn(), history: jest.fn(), write: jest.fn(), list: jest.fn(), counts: jest.fn() }
let mockHide: () => void
let mockShow: () => void
jest.mock('@tarojs/taro', () => ({ ...jest.requireActual('@tarojs/taro'), useDidHide: (fn: () => void) => { mockHide = fn }, useDidShow: (fn: () => void) => { mockShow = fn } }))
jest.mock('../runtime', () => ({ FOLLOWUP_PATH: '/admin/pages/reservation-followups/index', getFollowupApi: () => mockApi }))
const time = '2026-09-14T01:00:00Z'
const snapshot = { reservation_id: 31, kind: 'contact', eligible: true, completed: false, revision: 0, latest: null, server_now: time }
const record = { id: 1, revision: 1, outcome: 'retry', label: '待重试', note: '未接通，明日重试', operator_id: 2, created_at: time }
const page = { items: [], total: 0, page: 1, page_size: 20, pages: 0 }
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })

function input(util: ReactTestUtil, value: string) {
  const fire = util.fireEvent as unknown as (element: Element, event: Event) => void
  fire(util.queries.querySelector('.followup-panel__note')!, new CustomEvent('input', { bubbles: true, detail: { value } }))
}

describe('门店跟进表单与队列', () => {
  let util: ReactTestUtil
  beforeEach(() => {
    jest.useFakeTimers({ doNotFake: ['requestAnimationFrame', 'cancelAnimationFrame'] })
    util = new ReactTestUtil()
    mockApi.detail.mockResolvedValue(snapshot)
    mockApi.history.mockResolvedValue(page)
    mockApi.write.mockResolvedValue({ ...snapshot, revision: 1, completed: true, latest: { ...record, outcome: 'contacted' } })
    mockApi.list.mockResolvedValue(page)
    mockApi.counts.mockResolvedValue({ server_now: time, contact_pending: 2, overdue_pending: 1 })
  })
  afterEach(() => { util.unmout(); jest.resetAllMocks(); jest.useRealTimers() })

  it('读取不提交，必填说明后保存并展示完成结果', async () => {
    await util.mount(() => <FollowupPanel reservationId={31} kind='contact' />)
    await flush()
    const button = util.queries.querySelector('.followup-panel__primary')!
    expect(button.getAttribute('disabled')).not.toBeNull()
    expect(mockApi.write).not.toHaveBeenCalled()
    await act(async () => input(util, '已致电告知店休，顾客知悉'))
    await act(async () => { util.fireEvent.click(button) })
    await flush()
    expect(mockApi.write).toHaveBeenCalledWith(31, 'contact', expect.objectContaining({ expected_revision: 0, outcome: 'contacted', note: '已致电告知店休，顾客知悉' }))
    expect(util.queries.querySelector('.followup-panel__feedback')?.textContent).toContain('已完成')
  })

  it('网络结果未知时锁住草稿，重试复用完全相同请求', async () => {
    mockApi.write.mockRejectedValueOnce(new Error('network'))
    await util.mount(() => <FollowupPanel reservationId={31} kind='contact' />)
    await flush()
    await act(async () => input(util, '已经告知'))
    await act(async () => { util.fireEvent.click(util.queries.querySelector('.followup-panel__primary')!) })
    expect(util.queries.querySelector('.followup-panel__note')?.getAttribute('disabled')).not.toBeNull()
    await act(async () => { util.fireEvent.click(util.queries.querySelector('.followup-panel__primary')!) })
    expect(mockApi.write.mock.calls[0][2]).toEqual(mockApi.write.mock.calls[1][2])
  })

  it('读取失败时保护已有草稿，恢复后可以继续输入并保存', async () => {
    await util.mount(() => <FollowupPanel reservationId={31} kind='contact' />)
    await flush()
    await act(async () => input(util, '已有联系说明'))
    mockApi.detail.mockRejectedValueOnce(new Error('offline'))
    await act(async () => { jest.advanceTimersByTime(10_000) })
    await flush()
    await act(async () => input(util, '禁用期间不应修改草稿'))
    expect(util.queries.querySelector('.followup-panel__note')?.getAttribute('value')).toBe('已有联系说明')
    await act(async () => { jest.advanceTimersByTime(10_000) })
    await flush()
    await act(async () => input(util, '恢复后继续填写联系说明'))
    await act(async () => { util.fireEvent.click(util.queries.querySelector('.followup-panel__primary')!) })
    expect(mockApi.write).toHaveBeenCalledWith(31, 'contact', expect.objectContaining({ note: '恢复后继续填写联系说明' }))
  })

  it('其他管理员更新后要求核对新记录，不能悄悄覆盖；后台停止刷新', async () => {
    await util.mount(() => <FollowupPanel reservationId={31} kind='contact' />)
    await flush()
    await act(async () => input(util, '正在联系'))
    mockApi.detail.mockResolvedValue({ ...snapshot, revision: 1, latest: record })
    mockApi.history.mockResolvedValue({ ...page, items: [record], total: 1, pages: 1 })
    await act(async () => { jest.advanceTimersByTime(10_000) })
    await flush()
    expect(util.queries.querySelector('.followup-panel__primary')?.getAttribute('disabled')).not.toBeNull()
    expect(util.queries.querySelector('.followup-panel')?.textContent).toContain('其他管理员已更新')
    await act(async () => { mockHide() })
    const calls = mockApi.detail.mock.calls.length
    await act(async () => { jest.advanceTimersByTime(30_000) })
    expect(mockApi.detail).toHaveBeenCalledTimes(calls)
    await act(async () => { mockShow() })
    await flush()
    expect(mockApi.detail).toHaveBeenCalledTimes(calls + 1)
  })

  it('过期跟进没有已联系即完成选项，历史可按页查阅', async () => {
    mockApi.detail.mockResolvedValue({ ...snapshot, kind: 'overdue' })
    mockApi.history.mockResolvedValue({ ...page, total: 21, pages: 2, items: [record] })
    await util.mount(() => <FollowupPanel reservationId={31} kind='overdue' />)
    await flush()
    expect(util.queries.querySelector('.followup-panel__choices')?.textContent).not.toContain('已联系')
    const buttons = util.queries.querySelectorAll('.followup-panel__pagination .followup-panel__secondary')
    await act(async () => { util.fireEvent.click(buttons[1]) })
    expect(mockApi.history).toHaveBeenLastCalledWith(31, 'overdue', 2)
  })

  it('队列有完整显示的两组筛选，切换只读查询不完成任务', async () => {
    await util.mount(FollowupList)
    await flush()
    expect(mockApi.list).toHaveBeenCalledWith('contact', 'pending', 1)
    const tabs = util.queries.querySelectorAll('.followup-page__tab')
    expect(tabs).toHaveLength(4)
    await act(async () => { util.fireEvent.click(tabs[1]) })
    await flush()
    expect(mockApi.list).toHaveBeenLastCalledWith('overdue', 'pending', 1)
    await act(async () => { util.fireEvent.click(tabs[3]) })
    await flush()
    expect(mockApi.list).toHaveBeenLastCalledWith('overdue', 'completed', 1)
    expect(mockApi.write).not.toHaveBeenCalled()
  })

  it('首页跟进红圈按两类未完成事项相加，读取失败仍保留入口', async () => {
    const open = jest.fn(async () => undefined)
    await util.mount(() => <FollowupEntry disabled={false} open={open} />)
    await flush()
    expect(util.queries.querySelector('.attention-badge')?.textContent).toBe('3')
    mockApi.counts.mockRejectedValue(new Error('offline'))
    await act(async () => { jest.advanceTimersByTime(10_000) })
    await flush()
    expect(util.queries.querySelector('.workbench-action__meta')?.textContent).toContain('更新失败')
    await act(async () => { util.fireEvent.click(util.queries.querySelector('.workbench-action')!) })
    expect(open).toHaveBeenCalledWith({ label: '预约跟进', url: '/admin/pages/reservation-followups/index' })
  })
})
