import ReactTestUtil from '@tarojs/test-utils-react'

import type { AdminProductListPage } from '@/api/endpoints/admin_products'

import { type AdminProductListSource, useAdminProductList } from '../use_admin_product_list'

const page: AdminProductListPage = {
  items: [{
    id: 1,
    name: '草稿体验',
    product_type: { value: 'experience', label: '拼豆体验' },
    status: { value: 'draft', label: '草稿' },
    cover_image: null,
    display_price: null,
    updated_at: '2026-08-25T08:00:00Z',
    is_deleted: false,
  }],
  total: 2,
  page: 1,
  page_size: 20,
  pages: 2,
}

function Harness({ source }: { readonly source: AdminProductListSource }) {
  const { applyFilters, loadNextPage, state } = useAdminProductList(source)
  return (
    <div>
      <span className='status'>{state.status}</span>
      <span className='ids'>{state.items.map((item) => item.id).join(',')}</span>
      <button
        className='apply'
        onClick={() => applyFilters({
          productType: 'experience', status: 'draft', keyword: ' 草稿 ', includeDeleted: true,
        })}
      >apply</button>
      <button className='next' onClick={loadNextPage}>next</button>
    </div>
  )
}

describe('useAdminProductList', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('筛选换页时保留规范化条件并使用服务端分页', async () => {
    const secondPage = { ...page, items: [{ ...page.items[0], id: 2 }], page: 2 }
    const source: AdminProductListSource = {
      listProducts: jest.fn().mockResolvedValueOnce(page).mockResolvedValueOnce(page).mockResolvedValueOnce(secondPage),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.apply'))
    await flush(testUtils)
    const query = {
      page: 1, page_size: 20, product_type: 'experience', status: 'draft', keyword: '草稿', include_deleted: true,
    }
    expect(source.listProducts).toHaveBeenLastCalledWith(query)
    testUtils.fireEvent.click(requireElement(testUtils, '.next'))
    await flush(testUtils)
    expect(source.listProducts).toHaveBeenLastCalledWith({ ...query, page: 2 })
    expect(requireElement(testUtils, '.ids').textContent).toBe('1,2')
  })

  it('首屏失败进入 error', async () => {
    const source: AdminProductListSource = { listProducts: jest.fn(async () => { throw new Error('offline') }) }
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

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
  })
}
