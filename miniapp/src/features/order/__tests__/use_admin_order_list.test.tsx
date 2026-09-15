import ReactTestUtil from '@tarojs/test-utils-react'

import type { AdminOrderListPage } from '@/api/endpoints/orders'

import {
  type AdminOrderListSource,
  parseAdminOrderFilters,
  useAdminOrderList,
} from '../use_admin_order_list'

const firstPage: AdminOrderListPage = {
  items: [{
    id: 1,
    order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
    user_id: 7,
    user_nickname: '开发用户',
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

const secondPage: AdminOrderListPage = {
  ...firstPage,
  items: [{ ...firstPage.items[0], id: 2, order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BD' }],
  page: 2,
}

function Harness({ source }: { readonly source: AdminOrderListSource }) {
  const { applyFilters, loadNextPage, state } = useAdminOrderList(source)
  return (
    <div>
      <span className='status'>{state.status}</span>
      <span className='ids'>{state.items.map((item) => item.id).join(',')}</span>
      <button className='apply' onClick={() => applyFilters({
        status: 'paid',
        productName: '星空拼豆',
        orderNo: firstPage.items[0].order_no,
        userId: 7,
        createdFrom: '2026-08-01T00:00:00.000Z',
        createdTo: '2026-09-01T00:00:00.000Z',
      })}
      >apply</button>
      <button className='next' onClick={loadNextPage}>next</button>
    </div>
  )
}

describe('useAdminOrderList', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('筛选后重置第一页，并将全部筛选保留到下一页', async () => {
    const source: AdminOrderListSource = {
      listAdminOrders: jest.fn()
        .mockResolvedValueOnce(firstPage)
        .mockResolvedValueOnce(firstPage)
        .mockResolvedValueOnce(secondPage),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.apply'))
    await flush(testUtils)
    const filterQuery = {
      page: 1,
      page_size: 20,
      status: 'paid',
      product_name: '星空拼豆',
      order_no: firstPage.items[0].order_no,
      user_id: 7,
      created_from: '2026-08-01T00:00:00.000Z',
      created_to: '2026-09-01T00:00:00.000Z',
    }
    expect(source.listAdminOrders).toHaveBeenLastCalledWith(filterQuery)
    testUtils.fireEvent.click(requireElement(testUtils, '.next'))
    await flush(testUtils)
    expect(source.listAdminOrders).toHaveBeenLastCalledWith({ ...filterQuery, page: 2 })
    expect(requireElement(testUtils, '.ids').textContent).toBe('1,2')
  })

  it('首屏错误进入 error', async () => {
    const source: AdminOrderListSource = {
      listAdminOrders: jest.fn(async () => { throw new Error('offline') }),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    expect(requireElement(testUtils, '.status').textContent).toBe('error')
  })
})

describe('parseAdminOrderFilters', () => {
  it('规范化订单号/用户 ID，并将结束日转为次日排他上界', () => {
    expect(parseAdminOrderFilters({
      status: 'completed',
      productName: ' 星空拼豆 ',
      orderNo: ' od01k2m7y0j7a3n5q8t4v6w9x2bc ',
      userId: '7',
      createdFrom: '20260801',
      createdTo: '20260831',
    })).toEqual({ filters: {
      status: 'completed',
      productName: '星空拼豆',
      orderNo: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
      userId: 7,
      createdFrom: '2026-08-01T00:00:00.000Z',
      createdTo: '2026-09-01T00:00:00.000Z',
    } })
  })

  it('接受紧凑闰日并拒绝不足 8 位的日期', () => {
    expect(parseAdminOrderFilters({
      status: 'all',
      productName: '',
      orderNo: '',
      userId: '',
      createdFrom: '20280229',
      createdTo: '',
    })).toEqual({ filters: {
      status: 'all',
      createdFrom: '2028-02-29T00:00:00.000Z',
    } })
    expect(parseAdminOrderFilters({
      status: 'all',
      productName: '',
      orderNo: '',
      userId: '',
      createdFrom: '2026020',
      createdTo: '',
    }).error).toContain('8 位日期')
  })

  it.each([
    [{ status: 'all', productName: '拼'.repeat(101), orderNo: '', userId: '', createdFrom: '', createdTo: '' }, '商品名称'],
    [{ status: 'all', productName: '', orderNo: 'bad', userId: '', createdFrom: '', createdTo: '' }, '订单号格式'],
    [{ status: 'all', productName: '', orderNo: '', userId: '0', createdFrom: '', createdTo: '' }, '用户 ID'],
    [{ status: 'all', productName: '', orderNo: '', userId: '', createdFrom: '20260230', createdTo: '' }, '开始日期'],
    [{ status: 'all', productName: '', orderNo: '', userId: '', createdFrom: '20260901', createdTo: '20260801' }, '不能早于'],
  ] as const)('拒绝非法筛选：%p', (draft, expected) => {
    expect(parseAdminOrderFilters(draft).error).toContain(expected)
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
