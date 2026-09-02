import {
  BusinessError,
  ContractError,
  HttpError,
  NetworkError,
  RequestCancelledError,
  TimeoutError,
} from '@/api'
import type { OrderDetail } from '@/api/endpoints/orders'

import type { ExperienceCartItem, KitCartItem } from '../cart'
import {
  normalizeOrderRemark,
  OrderSubmissionStore,
  OrderSubmissionValidationError,
  type OrderCreator,
} from '../submission'

const experienceItem: ExperienceCartItem = {
  productId: 1,
  experienceOptionId: 11,
  productType: 'experience',
  productName: '周末拼豆体验',
  configurationLabel: '1小时 · 2人 · 工作日',
  unitPrice: '99.00',
  imageUrl: null,
  quantity: 1,
}

const kitItem: KitCartItem = {
  productId: 2,
  experienceOptionId: null,
  productType: 'kit',
  productName: '基础拼豆套装',
  configurationLabel: null,
  unitPrice: '199.00',
  imageUrl: null,
  quantity: 2,
}

const order: OrderDetail = {
  id: 101,
  order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
  total_amount: '497.00',
  status: { value: 'pending', label: '待支付' },
  remark: '周五晚上到店',
  items: [
    {
      id: 1001,
      product_id: 1,
      experience_option_id: 11,
      product_name: '周末拼豆体验',
      option_duration_minutes: 60,
      option_participants: 1,
      option_day_type: { value: 'weekday', label: '工作日' },
      product_price: '99.00',
      quantity: 1,
      subtotal: '99.00',
    },
    {
      id: 1002,
      product_id: 2,
      experience_option_id: null,
      product_name: '基础拼豆套装',
      option_duration_minutes: null,
      option_participants: null,
      option_day_type: null,
      product_price: '199.00',
      quantity: 2,
      subtotal: '398.00',
    },
  ],
  created_at: '2026-08-13T10:30:00Z',
  updated_at: '2026-08-13T10:30:00Z',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (cause: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

describe('OrderSubmissionStore', () => {
  it('复制 Cart 快照、规范化 remark 并构造 Experience/Kit 最小请求', async () => {
    const creator: OrderCreator = { createOrder: jest.fn(async () => order) }
    const store = new OrderSubmissionStore(creator)
    const mutableItems = [{ ...experienceItem }, { ...kitItem }]

    await store.submit(mutableItems, '  周五晚上到店  ')
    mutableItems[0].quantity = 9

    expect(creator.createOrder).toHaveBeenCalledWith({
      items: [
        { product_id: 1, experience_option_id: 11, quantity: 1 },
        { product_id: 2, quantity: 2 },
      ],
      remark: '周五晚上到店',
    })
    expect(store.getState()).toMatchObject({
      status: 'succeeded',
      order,
      submittedItems: [experienceItem, kitItem],
    })
  })

  it('提交期间复用同一 Promise，避免重复 POST', async () => {
    const pending = deferred<OrderDetail>()
    const creator: OrderCreator = { createOrder: jest.fn(() => pending.promise) }
    const store = new OrderSubmissionStore(creator)

    const first = store.submit([kitItem])
    const second = store.submit([kitItem])

    expect(second).toBe(first)
    expect(creator.createOrder).toHaveBeenCalledTimes(1)
    expect(store.getState().status).toBe('submitting')
    pending.resolve(order)
    await first
    expect(store.getState().status).toBe('succeeded')
  })

  it('明确业务失败进入 failed，允许 reset 后重新提交', async () => {
    const error = new BusinessError(
      { operation: 'orders.create', statusCode: 409 },
      40931,
      'Insufficient stock',
      { product_id: 2, requested_quantity: 2 },
    )
    const creator: OrderCreator = { createOrder: jest.fn(async () => { throw error }) }
    const store = new OrderSubmissionStore(creator)

    await store.submit([kitItem])

    expect(store.getState()).toMatchObject({ status: 'failed', error })
    store.reset()
    expect(store.getState()).toEqual({ status: 'idle' })
  })

  it.each([
    new TimeoutError({ operation: 'orders.create' }, new Error('timeout')),
    new NetworkError({ operation: 'orders.create' }, new Error('offline')),
    new RequestCancelledError({ operation: 'orders.create' }),
    new ContractError({ operation: 'orders.create', statusCode: 201 }),
    new HttpError({ operation: 'orders.create', statusCode: 500 }, { code: 500 }),
  ])('无法确认服务端未提交的 %s 进入 unknown，且不自动重试', async (error) => {
    const creator: OrderCreator = { createOrder: jest.fn(async () => { throw error }) }
    const store = new OrderSubmissionStore(creator)

    await store.submit([kitItem])

    expect(store.getState()).toMatchObject({ status: 'unknown', error })
    expect(creator.createOrder).toHaveBeenCalledTimes(1)
  })

  it('明确的非 5xx HTTP 拒绝仍进入 failed', async () => {
    const error = new HttpError(
      { operation: 'orders.create', statusCode: 400 },
      { message: 'bad request' },
    )
    const creator: OrderCreator = { createOrder: jest.fn(async () => { throw error }) }
    const store = new OrderSubmissionStore(creator)

    await store.submit([kitItem])

    expect(store.getState()).toMatchObject({ status: 'failed', error })
    expect(creator.createOrder).toHaveBeenCalledTimes(1)
  })

  it('拒绝空购物清单和超长 remark，并且不调用 API', () => {
    const creator: OrderCreator = { createOrder: jest.fn(async () => order) }
    const store = new OrderSubmissionStore(creator)

    expect(() => store.submit([])).toThrow(OrderSubmissionValidationError)
    expect(() => store.submit([kitItem], 'x'.repeat(501))).toThrow(OrderSubmissionValidationError)
    expect(creator.createOrder).not.toHaveBeenCalled()
  })

  it('服务端成功后对账 Cart；清理失败仍保持 succeeded 且不重复创建', async () => {
    const creator: OrderCreator = { createOrder: jest.fn(async () => order) }
    const reconcileError = new Error('storage unavailable')
    const reconciler = {
      reconcileSubmittedItems: jest.fn(async () => { throw reconcileError }),
    }
    const store = new OrderSubmissionStore(creator, reconciler)

    await store.submit([kitItem])

    expect(reconciler.reconcileSubmittedItems).toHaveBeenCalledWith([kitItem])
    expect(store.getState()).toMatchObject({
      status: 'succeeded',
      order,
      cartReconciliationError: reconcileError,
    })
    expect(creator.createOrder).toHaveBeenCalledTimes(1)
  })
})

describe('normalizeOrderRemark', () => {
  it('省略空白备注并保留 500 字边界', () => {
    expect(normalizeOrderRemark('   ')).toBeUndefined()
    expect(normalizeOrderRemark(null)).toBeUndefined()
    expect(normalizeOrderRemark('x'.repeat(500))).toBe('x'.repeat(500))
  })
})
