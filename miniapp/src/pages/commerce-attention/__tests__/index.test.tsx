import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'
import { CommerceList } from '../index'

const mockApi = { myTableSessions: jest.fn(), commerceList: jest.fn(), read: jest.fn() }
const mockRefresh = jest.fn()
jest.mock('@/features/attention/runtime', () => ({ getAttentionApi: () => mockApi }))
jest.mock('@/features/attention/hooks', () => ({
  usePageVisibility: () => ({ visible: true }),
  useAttentionSummary: () => ({ summary: { server_now: '2026-09-14T12:00:00Z', table_total: 0 }, refresh: mockRefresh }),
}))
const sessionNo = `TS${'1'.repeat(26)}`
const page = { items: [{ id: 1, scope: 'tables', reference: sessionNo, title: 'T01号桌', status_label: '体验中', order_id: 42, session_no: sessionNo, unread: false, created_at: '2026-09-14T11:00:00Z', payment_deadline_at: null }], total: 1, page: 1, page_size: 20, pages: 1 }

describe('顾客固定桌台列表', () => {
  let util: ReactTestUtil
  beforeEach(() => {
    util = new ReactTestUtil()
    mockApi.myTableSessions.mockResolvedValue(page)
    mockApi.commerceList.mockResolvedValue({ ...page, items: [], total: 0, pages: 0 })
  })
  afterEach(() => { util.unmout(); jest.clearAllMocks() })

  it('无提醒时仍加载进行中桌台，点击按精确会话进入详情', async () => {
    await util.mount(() => <CommerceList admin={false} scope='tables' />)
    expect(mockApi.myTableSessions).toHaveBeenCalledWith(1)
    expect(mockApi.commerceList).not.toHaveBeenCalled()
    expect(util.queries.querySelector('.attention-page__title')?.textContent).toBe('我的桌台')
    expect(util.queries.querySelector('.attention-page__item')?.textContent).toContain('体验中')
    expect(util.queries.querySelector('.attention-badge')).toBeNull()
    util.fireEvent.click(util.queries.querySelector('.attention-page__item')!)
    expect(Taro.navigateTo).toHaveBeenLastCalledWith({ url: `/pages/table-history/index?sessionNo=${sessionNo}` })
    expect(mockApi.read).not.toHaveBeenCalled()
  })

  it('待付款与新结果仍使用提醒集合，返回全部桌台加载完整列表', async () => {
    await util.mount(() => <CommerceList admin={false} scope='tables' />)
    const tabs = util.queries.querySelectorAll('.attention-page__filter')
    expect(tabs[0].textContent).toBe('全部桌台')
    for (const [index, view] of [[1, 'pending'], [2, 'unread']] as const) {
      await util.act(async () => { util.fireEvent.click(tabs[index]) })
      expect(mockApi.commerceList).toHaveBeenLastCalledWith(false, 'tables', view, 1)
    }
    await util.act(async () => { util.fireEvent.click(tabs[0]) })
    expect(mockApi.myTableSessions).toHaveBeenCalledTimes(2)
  })

  it('管理员桌台仍只查询待付款集合', async () => {
    await util.mount(() => <CommerceList admin scope='tables' />)
    expect(mockApi.myTableSessions).not.toHaveBeenCalled()
    expect(mockApi.commerceList).toHaveBeenCalledWith(true, 'tables', 'pending', 1)
    expect(util.queries.querySelectorAll('.attention-page__filter')).toHaveLength(1)
  })

  it('余额变动只展示两类筛选并打开精确结果，列表不清未读', async () => {
    mockApi.commerceList.mockResolvedValue({ ...page, items: [{ ...page.items[0], id: 22, scope: 'wallet', session_no: null, order_id: null, unread: true, title: '余额增加 ¥10.00' }] })
    await util.mount(() => <CommerceList admin={false} scope='wallet' />)
    expect(mockApi.commerceList).toHaveBeenCalledWith(false, 'wallet', 'unread', 1)
    expect(Array.from(util.queries.querySelectorAll('.attention-page__filter')).map((node) => node.textContent)).toEqual(['全部调整', '新结果'])
    expect(util.queries.querySelector('.attention-page__title')?.textContent).toBe('余额变动')
    util.fireEvent.click(util.queries.querySelector('.attention-page__item')!)
    expect(Taro.navigateTo).toHaveBeenLastCalledWith({ url: '/pages/wallet-result/index?id=22' })
    expect(mockApi.read).not.toHaveBeenCalled()
  })

  it('完整桌台加载失败可重试，不显示为没有记录', async () => {
    mockApi.myTableSessions.mockRejectedValueOnce(new Error('offline'))
    await util.mount(() => <CommerceList admin={false} scope='tables' />)
    expect(util.queries.querySelector('.attention-page__state')?.textContent).toContain('加载失败')
    await util.act(async () => { util.fireEvent.click(util.queries.querySelector('.attention-page__retry')!) })
    expect(util.queries.querySelector('.attention-page__item')?.textContent).toContain('T01号桌')
  })
})
