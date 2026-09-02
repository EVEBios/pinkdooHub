import ReactTestUtil from '@tarojs/test-utils-react'

import type { ProductListPage } from '@/api/endpoints/products'

import { type ProductListSource, useProductList } from '../use_product_list'

const firstPage: ProductListPage = {
  items: [{
    id: 1,
    name: '体验 A',
    product_type: { value: 'experience', label: '拼豆体验' },
    cover_image: '/uploads/products/a.webp',
    display_price: '100.00',
  }],
  total: 2,
  page: 1,
  page_size: 10,
  pages: 2,
}

const secondPage: ProductListPage = {
  items: [{
    id: 2,
    name: '套装 B',
    product_type: { value: 'kit', label: '拼豆套装' },
    cover_image: '/uploads/products/b.webp',
    display_price: '200.00',
  }],
  total: 2,
  page: 2,
  page_size: 10,
  pages: 2,
}

function ProductListHarness({ source }: { source: ProductListSource }) {
  const {
    loadNextPage,
    retry,
    setKeyword,
    setProductType,
    state,
  } = useProductList(source)
  return (
    <div>
      <span className='status'>{state.status}</span>
      <span className='ids'>{state.items.map((item) => item.id).join(',')}</span>
      <span className='page'>{state.page}</span>
      <button className='next' onClick={loadNextPage}>next</button>
      <button className='retry' onClick={retry}>retry</button>
      <button className='kit' onClick={() => setProductType('kit')}>kit</button>
      <button className='keyword' onClick={() => setKeyword('  套装  ')}>keyword</button>
    </div>
  )
}

describe('useProductList', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
  })

  afterEach(() => {
    testUtils.unmout()
  })

  it('加载第一页并按服务端分页加载下一页', async () => {
    const source: ProductListSource = {
      listProducts: jest.fn()
        .mockResolvedValueOnce(firstPage)
        .mockResolvedValueOnce(secondPage),
    }
    await testUtils.mount(ProductListHarness, { props: { source } })
    await flush(testUtils)

    expect(testUtils.queries.querySelector('.status')?.textContent).toBe('content')
    expect(testUtils.queries.querySelector('.ids')?.textContent).toBe('1')
    expect(source.listProducts).toHaveBeenNthCalledWith(1, { page: 1, page_size: 10 })

    const next = testUtils.queries.querySelector('.next')
    if (!next) {
      throw new Error('next button not found')
    }
    testUtils.fireEvent.click(next)
    await flush(testUtils)

    expect(source.listProducts).toHaveBeenNthCalledWith(2, { page: 2, page_size: 10 })
    expect(testUtils.queries.querySelector('.ids')?.textContent).toBe('1,2')
    expect(testUtils.queries.querySelector('.page')?.textContent).toBe('2')
  })

  it('重试后忽略更早请求的迟到响应', async () => {
    const oldRequest = deferred<ProductListPage>()
    const newRequest = deferred<ProductListPage>()
    const source: ProductListSource = {
      listProducts: jest.fn()
        .mockReturnValueOnce(oldRequest.promise)
        .mockReturnValueOnce(newRequest.promise),
    }
    await testUtils.mount(ProductListHarness, { props: { source } })

    const retry = testUtils.queries.querySelector('.retry')
    if (!retry) {
      throw new Error('retry button not found')
    }
    testUtils.fireEvent.click(retry)

    newRequest.resolve(secondPage)
    await flush(testUtils)
    oldRequest.resolve(firstPage)
    await flush(testUtils)

    expect(testUtils.queries.querySelector('.ids')?.textContent).toBe('2')
    expect(testUtils.queries.querySelector('.page')?.textContent).toBe('2')
  })

  it('类型立即生效，keyword 防抖后组合查询并重置第一页', async () => {
    const source: ProductListSource = {
      listProducts: jest.fn().mockResolvedValue(firstPage),
    }
    await testUtils.mount(ProductListHarness, { props: { source } })
    await flush(testUtils)

    testUtils.fireEvent.click(requireElement(testUtils, '.kit'))
    await flush(testUtils)
    expect(source.listProducts).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 10,
      product_type: 'kit',
    })

    testUtils.fireEvent.click(requireElement(testUtils, '.keyword'))
    await flush(testUtils)
    expect(source.listProducts).toHaveBeenCalledTimes(2)

    await testUtils.act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 350))
    })
    await flush(testUtils)
    expect(source.listProducts).toHaveBeenLastCalledWith({
      keyword: '套装',
      page: 1,
      page_size: 10,
      product_type: 'kit',
    })
  })

  it('加载下一页时保留当前筛选条件', async () => {
    const filteredFirstPage = { ...firstPage, page: 1, pages: 2 }
    const source: ProductListSource = {
      listProducts: jest.fn()
        .mockResolvedValueOnce(firstPage)
        .mockResolvedValueOnce(filteredFirstPage)
        .mockResolvedValueOnce(secondPage),
    }
    await testUtils.mount(ProductListHarness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.kit'))
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.next'))
    await flush(testUtils)

    expect(source.listProducts).toHaveBeenLastCalledWith({
      page: 2,
      page_size: 10,
      product_type: 'kit',
    })
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) {
    throw new Error(`${selector} not found`)
  }
  return element
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve
  })
  return { promise, resolve }
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}
