import ReactTestUtil from '@tarojs/test-utils-react'

import { BusinessError, TimeoutError } from '@/api'
import type { AdminOrderDetail, OrderStatusResult } from '@/api/endpoints/orders'

import {
  type AdminOrderDetailSource,
  getTransitionAction,
  useAdminOrderDetail,
} from '../use_admin_order_detail'

const pendingOrder: AdminOrderDetail = {
  id: 101,
  order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
  user_id: 7,
  user_nickname: '开发用户',
  total_amount: '99.00',
  status: { value: 'pending', label: '待支付' },
  remark: null,
  items: [{
    id: 1,
    product_id: 1,
    experience_option_id: 11,
    product_name: '拼豆体验',
    option_duration_minutes: 60,
    option_participants: 1,
    option_day_type: { value: 'weekday', label: '工作日' },
    product_price: '99.00',
    quantity: 1,
    subtotal: '99.00',
  }],
  created_at: '2026-08-24T08:00:00Z',
  updated_at: '2026-08-24T08:00:00Z',
}

const paidResult: OrderStatusResult = {
  id: 101,
  order_no: pendingOrder.order_no,
  status: { value: 'paid', label: '已支付' },
  updated_at: '2026-08-24T09:00:00Z',
}

const completedResult: OrderStatusResult = {
  ...paidResult,
  status: { value: 'completed', label: '已完成' },
  updated_at: '2026-08-24T10:00:00Z',
}

describe('getTransitionAction', () => {
  it('Cancelled/Completed 都没有管理变迁', () => {
    expect(getTransitionAction({ ...pendingOrder, status: { value: 'cancelled', label: '已取消' } })).toBeUndefined()
    expect(getTransitionAction({ ...pendingOrder, status: completedResult.status })).toBeUndefined()
  })
})

function Harness({ source }: { readonly source: AdminOrderDetailSource }) {
  const { advanceStatus, detail, transition } = useAdminOrderDetail(101, source)
  return (
    <div>
      <span className='detail-status'>{detail.status}</span>
      <span className='order-status'>{detail.status === 'content' ? detail.order.status.value : ''}</span>
      <span className='transition-status'>{transition.status}</span>
      <button className='advance' onClick={() => void advanceStatus()}>advance</button>
    </div>
  )
}

describe('useAdminOrderDetail', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('Pending 只调用 mark paid，成功后使用服务端状态并刷新', async () => {
    const paidOrder = { ...pendingOrder, status: paidResult.status, updated_at: paidResult.updated_at }
    const source: AdminOrderDetailSource = {
      getAdminOrderDetail: jest.fn().mockResolvedValueOnce(pendingOrder).mockResolvedValueOnce(paidOrder),
      markOrderPaid: jest.fn(async () => paidResult),
      completeOrder: jest.fn(async () => completedResult),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.advance'))
    await flush(testUtils)
    expect(source.markOrderPaid).toHaveBeenCalledTimes(1)
    expect(source.completeOrder).not.toHaveBeenCalled()
    expect(source.getAdminOrderDetail).toHaveBeenCalledTimes(2)
    expect(requireElement(testUtils, '.order-status').textContent).toBe('paid')
  })

  it('PATCH 成功后在权威详情刷新完成前仍保持 submitting', async () => {
    const refresh = deferred<AdminOrderDetail>()
    const paidOrder = { ...pendingOrder, status: paidResult.status, updated_at: paidResult.updated_at }
    const source: AdminOrderDetailSource = {
      getAdminOrderDetail: jest.fn()
        .mockResolvedValueOnce(pendingOrder)
        .mockReturnValueOnce(refresh.promise),
      markOrderPaid: jest.fn(async () => paidResult),
      completeOrder: jest.fn(async () => completedResult),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.advance'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.order-status').textContent).toBe('paid')
    expect(requireElement(testUtils, '.transition-status').textContent).toBe('submitting')

    refresh.resolve(paidOrder)
    await flush(testUtils)
    expect(requireElement(testUtils, '.transition-status').textContent).toBe('succeeded')
  })

  it('Paid 只调用 complete，快速重复操作只发一个 PATCH', async () => {
    const pending = deferred<OrderStatusResult>()
    const paidOrder: AdminOrderDetail = { ...pendingOrder, status: paidResult.status }
    const source: AdminOrderDetailSource = {
      getAdminOrderDetail: jest.fn(async () => paidOrder),
      markOrderPaid: jest.fn(async () => paidResult),
      completeOrder: jest.fn(() => pending.promise),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    const button = requireElement(testUtils, '.advance')
    testUtils.fireEvent.click(button)
    testUtils.fireEvent.click(button)
    expect(source.completeOrder).toHaveBeenCalledTimes(1)
    expect(source.markOrderPaid).not.toHaveBeenCalled()
    pending.resolve(completedResult)
    await flush(testUtils)
  })

  it('超时进入 unknown 且不自动重放', async () => {
    const source: AdminOrderDetailSource = {
      getAdminOrderDetail: jest.fn(async () => pendingOrder),
      markOrderPaid: jest.fn(async () => {
        throw new TimeoutError({ operation: 'orders.admin.markPaid' }, new Error('timeout'))
      }),
      completeOrder: jest.fn(async () => completedResult),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.advance'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.transition-status').textContent).toBe('unknown')
    expect(source.markOrderPaid).toHaveBeenCalledTimes(1)
  })

  it('40921 明确失败后重新读取权威状态', async () => {
    const paidOrder: AdminOrderDetail = { ...pendingOrder, status: paidResult.status }
    const source: AdminOrderDetailSource = {
      getAdminOrderDetail: jest.fn().mockResolvedValueOnce(pendingOrder).mockResolvedValueOnce(paidOrder),
      markOrderPaid: jest.fn(async () => {
        throw new BusinessError(
          { operation: 'orders.admin.markPaid', statusCode: 409 },
          40921,
          'conflict',
          { current_status: 'paid', required_status: 'pending' },
        )
      }),
      completeOrder: jest.fn(async () => completedResult),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.advance'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.transition-status').textContent).toBe('failed')
    expect(requireElement(testUtils, '.order-status').textContent).toBe('paid')
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
    await Promise.resolve()
  })
}
