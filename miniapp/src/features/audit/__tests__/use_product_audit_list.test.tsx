import ReactTestUtil from '@tarojs/test-utils-react'

import type { AuditLogPage } from '@/api/endpoints/audit'

import { type ProductAuditListSource, useProductAuditList } from '../use_product_audit_list'

const firstPage: AuditLogPage = {
  items: [{
    id: 2, operator_id: 1, action: 'UPDATE_PRODUCT', target_type: 'product', target_id: 7,
    description: null, ip_address: '127.0.0.1', created_at: '2026-08-28T08:00:00Z',
  }],
  total: 2, page: 1, page_size: 20, pages: 2,
}
const secondPage: AuditLogPage = {
  ...firstPage,
  items: [{ ...firstPage.items[0], id: 1, action: 'CREATE_PRODUCT' }],
  page: 2,
}

function Harness({ source }: { readonly source: ProductAuditListSource }) {
  const { loadNextPage, state } = useProductAuditList(7, source)
  return (
    <div>
      <span className='status'>{state.status}</span>
      <span className='ids'>{state.status === 'content' ? state.items.map((item) => item.id).join(',') : ''}</span>
      <button className='next' onClick={loadNextPage}>next</button>
    </div>
  )
}

describe('useProductAuditList', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('固定 Product ID 分页追加操作历史', async () => {
    const source: ProductAuditListSource = {
      listProductAuditLogs: jest.fn()
        .mockResolvedValueOnce(firstPage)
        .mockResolvedValueOnce(secondPage),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.next'))
    await flush(testUtils)
    expect(source.listProductAuditLogs).toHaveBeenNthCalledWith(1, 7, { page: 1, page_size: 20 })
    expect(source.listProductAuditLogs).toHaveBeenNthCalledWith(2, 7, { page: 2, page_size: 20 })
    expect(requireElement(testUtils, '.ids').textContent).toBe('2,1')
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}
