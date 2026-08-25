import ReactTestUtil from '@tarojs/test-utils-react'

import type { OrderListPage } from '@/api/endpoints/orders'

import { type OrderListSource, useOrderList } from '../use_order_list'

const firstPage: OrderListPage = {
  items: [{
    id: 1,
    order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
    total_amount: '99.00',
    status: { value: 'pending', label: '待支付' },
    item_count: 1,
    created_at: '2026-08-24T08:00:00Z',
    updated_at: '2026-08-24T08:00:00Z',
  }],
  total: 2,
  page: 1,
  page_size: 20,
  pages: 2,
}

const secondPage: OrderListPage = {
  items: [{
    ...firstPage.items[0],
    id: 2,
    order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BD',
    status: { value: 'paid', label: '已支付' },
  }],
  total: 2,
  page: 2,
  page_size: 20,
  pages: 2,
}

function Harness({ source }: { readonly source: OrderListSource }) {
  const { loadNextPage, retry, setStatusFilter, state } = useOrderList(source)
  return (
    <div>
      <span className='status'>{state.status}</span>
      <span className='ids'>{state.items.map((item) => item.id).join(',')}</span>
      <span className='page'>{state.page}</span>
      <button className='next' onClick={loadNextPage}>next</button>
      <button className='retry' onClick={retry}>retry</button>
      <button className='paid' onClick={() => setStatusFilter('paid')}>paid</button>
    </div>
  )
}

describe('useOrderList', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
  })

  afterEach(() => testUtils.unmout())

  it('加载第一页并按服务端分页追加下一页', async () => {
    const source: OrderListSource = {
      listOrders: jest.fn().mockResolvedValueOnce(firstPage).mockResolvedValueOnce(secondPage),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    expect(source.listOrders).toHaveBeenNthCalledWith(1, { page: 1, page_size: 20 })
    expect(requireElement(testUtils, '.ids').textContent).toBe('1')

    testUtils.fireEvent.click(requireElement(testUtils, '.next'))
    await flush(testUtils)
    expect(source.listOrders).toHaveBeenNthCalledWith(2, { page: 2, page_size: 20 })
    expect(requireElement(testUtils, '.ids').textContent).toBe('1,2')
  })

  it('状态筛选立即重置第一页并保留到下一页', async () => {
    const source: OrderListSource = {
      listOrders: jest.fn()
        .mockResolvedValueOnce(firstPage)
        .mockResolvedValueOnce(firstPage)
        .mockResolvedValueOnce(secondPage),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.paid'))
    await flush(testUtils)
    expect(source.listOrders).toHaveBeenLastCalledWith({ page: 1, page_size: 20, status: 'paid' })
    testUtils.fireEvent.click(requireElement(testUtils, '.next'))
    await flush(testUtils)
    expect(source.listOrders).toHaveBeenLastCalledWith({ page: 2, page_size: 20, status: 'paid' })
  })

  it('忽略旧请求的迟到响应', async () => {
    const oldRequest = deferred<OrderListPage>()
    const newRequest = deferred<OrderListPage>()
    const source: OrderListSource = {
      listOrders: jest.fn().mockReturnValueOnce(oldRequest.promise).mockReturnValueOnce(newRequest.promise),
    }
    await testUtils.mount(Harness, { props: { source } })
    testUtils.fireEvent.click(requireElement(testUtils, '.retry'))
    newRequest.resolve(secondPage)
    await flush(testUtils)
    oldRequest.resolve(firstPage)
    await flush(testUtils)
    expect(requireElement(testUtils, '.ids').textContent).toBe('2')
  })

  it('首屏错误进入 error', async () => {
    const source: OrderListSource = { listOrders: jest.fn(async () => { throw new Error('offline') }) }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('error')
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => { resolve = promiseResolve })
  return { promise, resolve }
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}
