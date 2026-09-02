import ReactTestUtil from '@tarojs/test-utils-react'

import { BusinessError, TimeoutError } from '@/api'
import type { OrderDetail, OrderStatusResult } from '@/api/endpoints/orders'

import { type OrderDetailSource, useOrderDetail } from '../use_order_detail'

const pendingOrder: OrderDetail = {
  id: 101,
  order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
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

const cancelledResult: OrderStatusResult = {
  id: 101,
  order_no: pendingOrder.order_no,
  status: { value: 'cancelled', label: '已取消' },
  updated_at: '2026-08-24T09:00:00Z',
}

function Harness({ source }: { readonly source: OrderDetailSource }) {
  const { cancel, cancellation, detail, retry } = useOrderDetail(101, source)
  return (
    <div>
      <span className='detail-status'>{detail.status}</span>
      <span className='order-status'>{detail.status === 'content' ? detail.order.status.value : ''}</span>
      <span className='cancel-status'>{cancellation.status}</span>
      <span className='cancel-message'>{
        cancellation.status === 'failed' || cancellation.status === 'unknown'
          ? cancellation.errorMessage
          : cancellation.status === 'succeeded'
            ? cancellation.refreshErrorMessage
            : ''
      }</span>
      <button className='cancel' onClick={() => void cancel()}>cancel</button>
      <button className='retry' onClick={retry}>retry</button>
    </div>
  )
}

describe('useOrderDetail', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('加载详情，成功取消后使用服务端状态并刷新详情', async () => {
    const cancelledOrder = { ...pendingOrder, status: cancelledResult.status, updated_at: cancelledResult.updated_at }
    const source: OrderDetailSource = {
      getOrderDetail: jest.fn().mockResolvedValueOnce(pendingOrder).mockResolvedValueOnce(cancelledOrder),
      cancelOrder: jest.fn(async () => cancelledResult),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.cancel'))
    await flush(testUtils)
    expect(source.cancelOrder).toHaveBeenCalledTimes(1)
    expect(source.getOrderDetail).toHaveBeenCalledTimes(2)
    expect(requireElement(testUtils, '.order-status').textContent).toBe('cancelled')
    expect(requireElement(testUtils, '.cancel-status').textContent).toBe('succeeded')
  })

  it('快速重复取消只发一个 PATCH', async () => {
    const pending = deferred<OrderStatusResult>()
    const source: OrderDetailSource = {
      getOrderDetail: jest.fn(async () => pendingOrder),
      cancelOrder: jest.fn(() => pending.promise),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    const button = requireElement(testUtils, '.cancel')
    testUtils.fireEvent.click(button)
    testUtils.fireEvent.click(button)
    expect(source.cancelOrder).toHaveBeenCalledTimes(1)
    pending.resolve(cancelledResult)
    await flush(testUtils)
  })

  it('取消 timeout 进入 unknown，不自动重放', async () => {
    const error = new TimeoutError({ operation: 'orders.cancel' }, new Error('timeout'))
    const source: OrderDetailSource = {
      getOrderDetail: jest.fn(async () => pendingOrder),
      cancelOrder: jest.fn(async () => { throw error }),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.cancel'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.cancel-status').textContent).toBe('unknown')
    expect(source.cancelOrder).toHaveBeenCalledTimes(1)
  })

  it('40921 明确失败并重新读取权威详情', async () => {
    const paidOrder: OrderDetail = { ...pendingOrder, status: { value: 'paid', label: '已支付' } }
    const error = new BusinessError(
      { operation: 'orders.cancel', statusCode: 409 },
      40921,
      'conflict',
      { operation: 'cancel', current_status: 'paid', required_status: 'pending' },
    )
    const source: OrderDetailSource = {
      getOrderDetail: jest.fn().mockResolvedValueOnce(pendingOrder).mockResolvedValueOnce(paidOrder),
      cancelOrder: jest.fn(async () => { throw error }),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.cancel'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.cancel-status').textContent).toBe('failed')
    expect(requireElement(testUtils, '.order-status').textContent).toBe('paid')
  })

  it('取消成功但详情刷新失败时保留 succeeded', async () => {
    const source: OrderDetailSource = {
      getOrderDetail: jest.fn()
        .mockResolvedValueOnce(pendingOrder)
        .mockRejectedValueOnce(new Error('refresh offline')),
      cancelOrder: jest.fn(async () => cancelledResult),
    }
    await testUtils.mount(Harness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.cancel'))
    await flush(testUtils)
    expect(requireElement(testUtils, '.cancel-status').textContent).toBe('succeeded')
    expect(requireElement(testUtils, '.order-status').textContent).toBe('cancelled')
    expect(requireElement(testUtils, '.cancel-message').textContent).toContain('refresh offline')
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
