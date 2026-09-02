import ReactTestUtil from '@tarojs/test-utils-react'

import type { InventoryTransactionPage } from '@/api/endpoints/inventory'

import {
  type InventoryTransactionListSource,
  useInventoryTransactionList,
} from '../use_inventory_transaction_list'

const emptyPage: InventoryTransactionPage = {
  items: [], total: 0, page: 1, page_size: 20, pages: 0,
}

function Harness({
  source,
  productId,
}: {
  readonly source: InventoryTransactionListSource
  readonly productId?: number
}) {
  const inventory = useInventoryTransactionList(
    productId === undefined ? { kind: 'global' } : { kind: 'product', productId },
    source,
  )
  return (
    <div>
      <span className='status'>{inventory.state.status}</span>
      <span className='page'>{inventory.state.page}</span>
      <button
        className='filter'
        onClick={() => inventory.applyFilters({
          transactionType: 'order_deduction',
          sourceType: 'order',
          sourceId: 9,
          productId: 7,
          createdFrom: '2026-08-01T00:00:00.000Z',
          createdTo: '2026-08-29T00:00:00.000Z',
        })}
      >filter</button>
      <button className='next' onClick={inventory.loadNextPage}>next</button>
    </div>
  )
}

describe('useInventoryTransactionList', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('全局列表在筛选变化后从第一页重查并保留精确条件', async () => {
    const source = createSource(emptyPage)
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    expect(source.listTransactions).toHaveBeenLastCalledWith({ page: 1, page_size: 20 })

    testUtils.fireEvent.click(requireElement(testUtils, '.filter'))
    await flush(testUtils)
    expect(source.listTransactions).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 20,
      type: 'order_deduction',
      source_type: 'order',
      source_id: 9,
      product_id: 7,
      created_from: '2026-08-01T00:00:00.000Z',
      created_to: '2026-08-29T00:00:00.000Z',
    })
    expect(source.listProductTransactions).not.toHaveBeenCalled()
  })

  it('Kit 作用域只调用商品流水端点，并在加载下一页时保持筛选', async () => {
    const firstPage = {
      ...emptyPage,
      items: [transaction(1)],
      total: 2,
      pages: 2,
    }
    const secondPage = {
      ...emptyPage,
      items: [transaction(2)],
      total: 2,
      page: 2,
      pages: 2,
    }
    const source = createSource(firstPage)
    ;(source.listProductTransactions as jest.Mock).mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(secondPage)
    await testUtils.mount(Harness, { props: { source, productId: 7 } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.filter'))
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.next'))
    testUtils.fireEvent.click(requireElement(testUtils, '.next'))
    await flush(testUtils)

    expect(source.listTransactions).not.toHaveBeenCalled()
    expect(source.listProductTransactions).toHaveBeenLastCalledWith(7, {
      page: 2,
      page_size: 20,
      type: 'order_deduction',
      source_type: 'order',
      source_id: 9,
      created_from: '2026-08-01T00:00:00.000Z',
      created_to: '2026-08-29T00:00:00.000Z',
    })
    expect(source.listProductTransactions).toHaveBeenCalledTimes(3)
  })
})

function createSource(page: InventoryTransactionPage): InventoryTransactionListSource {
  return {
    listProductTransactions: jest.fn(async () => page),
    listTransactions: jest.fn(async () => page),
  }
}

function transaction(id: number) {
  return {
    id,
    product_id: 7,
    transaction_type: 'admin_adjustment' as const,
    change_quantity: 1,
    before_quantity: id - 1,
    after_quantity: id,
    reason: '补录',
    source_type: 'admin' as const,
    source_id: null,
    source_order_no: null,
    operator_id: 2,
    operator_nickname: '管理员',
    created_at: '2026-08-28T08:00:00Z',
  }
}

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
