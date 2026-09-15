import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import { TableSelector } from '../table_selector'

const mockApi = { resolveTableNumber: jest.fn(), resolveTableCode: jest.fn() }
jest.mock('../runtime', () => ({ getDefaultTableSessionApi: () => mockApi }))

function required(util: ReactTestUtil, selector: string): Element {
  const element = util.queries.querySelector(selector)
  if (!element) throw new Error(`missing ${selector}`)
  return element
}
async function flush(util: ReactTestUtil) {
  await util.act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() })
}
function input(util: ReactTestUtil, value: string) {
  const fire = util.fireEvent as unknown as (element: Element, event: Event) => void
  fire(required(util, '.table-selector__input'), new CustomEvent('input', { bubbles: true, detail: { value } }))
}

describe('统一选桌控件', () => {
  let util: ReactTestUtil
  const changed = jest.fn(async (_tableNo?: string) => undefined)
  beforeEach(() => {
    util = new ReactTestUtil()
    mockApi.resolveTableNumber.mockResolvedValue({ table_no: 'T08', display_name: '8号桌', is_available: true, is_enabled: true })
    mockApi.resolveTableCode.mockResolvedValue({ table_no: 'T08' })
    jest.spyOn(Taro, 'showModal').mockResolvedValue({ confirm: true, cancel: false, errMsg: 'showModal:ok' })
  })
  afterEach(() => { util.unmout(); jest.restoreAllMocks(); jest.clearAllMocks() })
  it('输入桌号规范化后经服务端校验和顾客确认才选中', async () => {
    await util.mount(() => <TableSelector onChange={changed} />)
    util.fireEvent.click(required(util, '.table-selector__edit'))
    input(util, '8')
    util.fireEvent.click(required(util, '.table-selector__confirm'))
    await flush(util)
    expect(mockApi.resolveTableNumber).toHaveBeenCalledWith('T08')
    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({ title: '确认选择 T08？', confirmText: '确认选桌' }))
    expect(changed).toHaveBeenCalledWith('T08')
  })
  it.each(['31', 'abc'])('无效桌号 %s 不请求也不改变选择', async (value) => {
    await util.mount(() => <TableSelector value='T08' onChange={changed} />)
    util.fireEvent.click(required(util, '.table-selector__edit'))
    input(util, value)
    util.fireEvent.click(required(util, '.table-selector__confirm'))
    await flush(util)
    expect(required(util, '.table-selector__error').textContent).toContain('1–30')
    expect(mockApi.resolveTableNumber).not.toHaveBeenCalled()
    expect(changed).not.toHaveBeenCalled()
  })
  it('占用的桌台明确提示，保留现有选择', async () => {
    mockApi.resolveTableNumber.mockResolvedValue({ table_no: 'T08', is_available: false, is_enabled: true })
    await util.mount(() => <TableSelector value='T09' onChange={changed} />)
    util.fireEvent.click(required(util, '.table-selector__edit'))
    input(util, '8')
    util.fireEvent.click(required(util, '.table-selector__confirm'))
    await flush(util)
    expect(required(util, '.table-selector__error').textContent).toContain('暂不可用')
    expect(required(util, '.table-selector__title').textContent).toContain('T09')
    expect(changed).not.toHaveBeenCalled()
  })
  it('顾客取消选桌确认后不绑定桌台', async () => {
    jest.spyOn(Taro, 'showModal').mockResolvedValue({ confirm: false, cancel: true, errMsg: 'showModal:ok' })
    await util.mount(() => <TableSelector onChange={changed} />)
    util.fireEvent.click(required(util, '.table-selector__edit'))
    input(util, '8')
    util.fireEvent.click(required(util, '.table-selector__confirm'))
    await flush(util)
    expect(changed).not.toHaveBeenCalled()
  })
})
