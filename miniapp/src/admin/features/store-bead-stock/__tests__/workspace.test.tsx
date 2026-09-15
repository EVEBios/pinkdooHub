import ReactTestUtil from '@tarojs/test-utils-react'
import { act } from 'react'
import { StoreStockWorkspace } from '@/admin/pages/store-bead-stock'
import { BusinessError } from '@/api/errors'

const mockApi = { list: jest.fn(), write: jest.fn(), byRequest: jest.fn(), history: jest.fn(), detail: jest.fn() }
jest.mock('../runtime', () => ({ getStoreStockApi: () => mockApi, STORE_STOCK_PATH: '/admin/pages/store-bead-stock/index' }))
jest.mock('@/features/attention/hooks', () => ({ usePageVisibility: () => ({ visible: true }) }))
const rows = [
  { bead_color_id: 1, slot_no: 1, color_code: 'A1', color_name: 'A1', packs: null, revision: 0 },
  { bead_color_id: 2, slot_no: 2, color_code: 'B1', color_name: 'B1', packs: 1, revision: 1 },
  { bead_color_id: 3, slot_no: 3, color_code: 'M1', color_name: 'M1', packs: 3, revision: 1 },
]
const flush = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) }) }
describe('门店库存批量界面', () => {
  let util: ReactTestUtil
  beforeEach(() => { util = new ReactTestUtil(); mockApi.list.mockResolvedValue(rows) })
  afterEach(() => { util.unmout(); jest.resetAllMocks() })
  const click = async (selector: string) => { await act(async () => { util.fireEvent.click(util.queries.querySelector(selector)!) }); await flush() }
  const edit = async () => { await click('.bead-stock__header-action') }
  const type = async (value: string) => { await act(async () => { (util.fireEvent as unknown as (element: Element, event: Event) => void)(util.queries.querySelector('.bead-stock__input')!, new CustomEvent('input', { bubbles: true, detail: { value } })) }); await flush() }

  it('浏览不显示加减，二次确认前不写；首次盘点0列入清单', async () => {
    await util.mount(() => <StoreStockWorkspace />); await flush()
    expect(util.queries.querySelector('.bead-stock__step')).toBeNull()
    expect(util.queries.querySelector('.bead-stock__header-copy')?.textContent).toContain('用豆库存')
    await edit(); await type('0')
    await click('.bead-stock__primary')
    expect(mockApi.write).not.toHaveBeenCalled()
    expect(util.queries.querySelector('.bead-stock__changes')?.textContent).toContain('未盘点')
    expect(util.queries.querySelector('.bead-stock__changes')?.textContent).toContain('0 包')
    await click('.bead-stock__secondary')
    expect(util.queries.querySelector('.bead-stock__input')?.getAttribute('value')).toBe('0')
  })
  it('跨颜色筛选保留隐藏草稿，确认列出全部变动', async () => {
    await util.mount(() => <StoreStockWorkspace />); await flush(); await edit(); await type('2')
    const group = Array.from(util.queries.querySelectorAll('.bead-stock__groups .bead-stock__filter')).find(e => e.textContent === 'B')!
    await act(async () => { util.fireEvent.click(group) }); await flush(); await type('4')
    await click('.bead-stock__primary')
    expect(util.queries.querySelectorAll('.bead-stock__change')).toHaveLength(2)
    expect(util.queries.querySelector('.bead-stock__changes')?.textContent).toContain('A1')
    expect(util.queries.querySelector('.bead-stock__changes')?.textContent).toContain('B1')
  })
  it('确认清单同时展示增减包数和修改前后的数量，返回后仍保留草稿', async () => {
    mockApi.list.mockResolvedValue([{ ...rows[0], packs: 1, revision: 1 }, ...rows.slice(1)])
    await util.mount(() => <StoreStockWorkspace />); await flush(); await edit(); await type('0')
    const group = Array.from(util.queries.querySelectorAll('.bead-stock__groups .bead-stock__filter')).find(e => e.textContent === 'B')!
    await act(async () => { util.fireEvent.click(group) }); await flush(); await type('4')
    await click('.bead-stock__primary')
    const items = util.queries.querySelectorAll('.bead-stock__change')
    expect(items[0].querySelector('.bead-stock__change-note')?.textContent).toBe('减少 1 包')
    expect(items[0].querySelector('.bead-stock__change-value')?.textContent).toBe('1 包 → 0 包')
    expect(items[1].querySelector('.bead-stock__change-note')?.textContent).toBe('增加 3 包')
    expect(items[1].querySelector('.bead-stock__change-value')?.textContent).toBe('1 包 → 4 包')
    expect(util.queries.querySelector('.bead-stock__totals')?.textContent).toContain('增加 3 包 · 减少 1 包')
    expect(mockApi.write).not.toHaveBeenCalled()
    await click('.bead-stock__secondary')
    expect(util.queries.querySelector('.bead-stock__input')?.getAttribute('value')).toBe('4')
  })
  it('未知结果先核查原批次，未查到时原样重试，不生成新key', async () => {
    mockApi.write.mockRejectedValue(new Error('network'))
    mockApi.byRequest.mockRejectedValue(new BusinessError({ operation: 'read', statusCode: 404 }, 404, 'missing', null))
    await util.mount(() => <StoreStockWorkspace />); await flush(); await edit(); await type('0'); await click('.bead-stock__primary'); await click('.bead-stock__primary')
    expect(mockApi.write).toHaveBeenCalledTimes(1)
    expect(util.queries.querySelector('.bead-stock__primary')?.textContent).toContain('核查本次结果')
    await click('.bead-stock__primary')
    expect(mockApi.byRequest).toHaveBeenCalledWith(mockApi.write.mock.calls[0][0].request_key)
    expect(mockApi.write.mock.calls[0][0]).toEqual(mockApi.write.mock.calls[1][0])
  })
  it('冲突保留目标数量，刷新原值后必须再次确认', async () => {
    mockApi.write.mockRejectedValue(new BusinessError({ operation: 'write', statusCode: 409 }, 40973, '库存变化', null))
    await util.mount(() => <StoreStockWorkspace />); await flush(); await edit(); await type('2'); await click('.bead-stock__primary'); await click('.bead-stock__primary')
    mockApi.list.mockResolvedValue([{ ...rows[0], packs: 5, revision: 1 }, ...rows.slice(1)])
    await click('.bead-stock__primary')
    expect(util.queries.querySelector('.bead-stock__input')?.getAttribute('value')).toBe('2')
    expect(util.queries.querySelector('.bead-stock__draft')?.textContent).toContain('原 5 包')
    expect(mockApi.write).toHaveBeenCalledTimes(1)
  })
  it('首次读取失败明确结束加载，刷新成功后可编辑', async () => {
    mockApi.list.mockRejectedValueOnce(new Error('technical contract error'))
    await util.mount(() => <StoreStockWorkspace />); await flush()
    expect(util.queries.querySelector('.bead-stock__meta')?.textContent).toContain('库存暂不可用')
    expect(util.queries.querySelector('.bead-stock__meta')?.textContent).not.toContain('正在读取')
    expect(util.queries.querySelector('.bead-stock__message')?.textContent).toContain('库存读取失败，请刷新重试')
    expect(util.queries.querySelector('.bead-stock__message')?.textContent).not.toContain('technical')
    await click('.bead-stock__message .bead-stock__text-action')
    expect(util.queries.querySelectorAll('.bead-stock__card')).toHaveLength(3)
  })
  it('历史详情失败后重试同一详情，不误重载列表', async () => {
    const batch = { id: 7, operator_id: 1, operator_name: '测试店员', created_at: '2026-09-15T00:00:00Z', reason: 'stocktake', note: '', changed_colors: 1, items: [{ ...rows[0], before_packs: null, after_packs: 0, revision: 1 }] }
    mockApi.history.mockResolvedValue({ items: [batch], page: 1, page_size: 20, pages: 1, total: 1 })
    mockApi.detail.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(batch)
    await util.mount(() => <StoreStockWorkspace />); await flush()
    await click('.bead-stock__meta .bead-stock__text-action')
    await click('.bead-stock__history-item')
    expect(util.queries.querySelector('.bead-stock__message')?.textContent).toContain('记录详情读取失败')
    const retry = Array.from(util.queries.querySelectorAll('taro-button-core')).find(el => el.textContent === '重试')!
    await act(async () => { util.fireEvent.click(retry) }); await flush()
    expect(mockApi.history).toHaveBeenCalledTimes(1)
    expect(mockApi.detail.mock.calls).toEqual([[7], [7]])
    expect(util.queries.querySelector('.bead-stock__title')?.textContent).toBe('库存调整记录')
    expect(util.queries.querySelector('.bead-stock__changes')?.textContent).toContain('未盘点')
  })

})
