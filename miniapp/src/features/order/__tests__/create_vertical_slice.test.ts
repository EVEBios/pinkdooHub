import { ApiClient, TimeoutError } from '@/api'
import { OrderApi, type OrderDetail } from '@/api/endpoints/orders'
import type {
  AuthSession,
  HttpTransport,
  TransportRequest,
  TransportResponse,
} from '@/api/types'
import type { StoragePort } from '@/platform/storage'

import { CartStore, type ExperienceCartItem, type KitCartItem } from '../cart'
import { OrderSubmissionStore } from '../submission'

class FakeStorage implements StoragePort {
  value: unknown

  async get(): Promise<unknown> {
    return this.value
  }

  async set(_key: string, value: unknown): Promise<void> {
    this.value = value
  }

  async remove(): Promise<void> {
    this.value = undefined
  }
}

class SequencedTransport implements HttpTransport {
  readonly requests: TransportRequest[] = []

  constructor(private readonly responses: Array<TransportResponse | Error>) {}

  async request(request: TransportRequest): Promise<TransportResponse> {
    this.requests.push(request)
    const response = this.responses.shift()
    if (response instanceof Error) {
      throw response
    }
    if (!response) {
      throw new Error('FakeTransport 没有更多响应')
    }
    return response
  }
}

const experienceItem: ExperienceCartItem = {
  productId: 1,
  experienceOptionId: 11,
  productType: 'experience',
  productName: '本地体验预览',
  configurationLabel: '1小时 · 1人 · 工作日',
  unitPrice: '88.00',
  imageUrl: null,
  quantity: 1,
}

const kitItem: KitCartItem = {
  productId: 2,
  experienceOptionId: null,
  productType: 'kit',
  productName: '本地套装预览',
  configurationLabel: null,
  unitPrice: '188.00',
  imageUrl: null,
  quantity: 2,
}

const createdOrder: OrderDetail = {
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
      product_name: '服务端体验快照',
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
      product_name: '服务端套装快照',
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

function envelope(statusCode: number, code: number, data: unknown): TransportResponse {
  return {
    statusCode,
    headers: {},
    data: { code, message: code === 0 ? 'Order created' : 'error', data },
  }
}

function authSession(): AuthSession {
  return {
    getAccessToken: () => 'access-token',
    refreshAccessToken: jest.fn(async () => 'new-token'),
    clearSession: jest.fn(),
  }
}

async function readyCart(): Promise<CartStore> {
  const cart = new CartStore(new FakeStorage())
  await cart.restore()
  await cart.addItem(experienceItem)
  await cart.addItem(kitItem)
  return cart
}

describe('创建订单前端 vertical slice', () => {
  it('Cart → Submission → ApiClient → OrderApi 成功后展示服务端快照并清理已提交 Cart', async () => {
    const cart = await readyCart()
    const transport = new SequencedTransport([envelope(201, 0, createdOrder)])
    const api = new OrderApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport,
      authSession: authSession(),
    }))
    const submission = new OrderSubmissionStore(api, cart)

    await submission.submit(cart.getSnapshot().items, '  周五晚上到店  ')

    expect(transport.requests).toHaveLength(1)
    expect(transport.requests[0]).toMatchObject({
      method: 'POST',
      url: 'https://api.example.com/api/v1/orders',
      headers: {
        Authorization: 'Bearer access-token',
        'Content-Type': 'application/json',
      },
      body: {
        items: [
          { product_id: 1, experience_option_id: 11, quantity: 1 },
          { product_id: 2, quantity: 2 },
        ],
        remark: '周五晚上到店',
      },
    })
    expect(submission.getState()).toMatchObject({
      status: 'succeeded',
      order: createdOrder,
      cartReconciliation: { status: 'completed' },
    })
    expect(cart.getSnapshot().items).toEqual([])
  })

  it('明确库存失败保留 Cart，且不会产生第二次 POST', async () => {
    const cart = await readyCart()
    const transport = new SequencedTransport([
      envelope(409, 40931, { product_id: 2, requested_quantity: 2 }),
    ])
    const api = new OrderApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport,
      authSession: authSession(),
    }))
    const submission = new OrderSubmissionStore(api, cart)

    await submission.submit(cart.getSnapshot().items)

    expect(submission.getState()).toMatchObject({ status: 'failed' })
    expect(cart.getSnapshot().items).toEqual([experienceItem, kitItem])
    expect(transport.requests).toHaveLength(1)
  })

  it('Timeout 进入 unknown、保留 Cart 且不自动重试', async () => {
    const cart = await readyCart()
    const transport = new SequencedTransport([
      new TimeoutError({ operation: 'orders.create' }, new Error('timeout')),
    ])
    const api = new OrderApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport,
      authSession: authSession(),
    }))
    const submission = new OrderSubmissionStore(api, cart)

    await submission.submit(cart.getSnapshot().items)

    expect(submission.getState()).toMatchObject({ status: 'unknown' })
    expect(cart.getSnapshot().items).toEqual([experienceItem, kitItem])
    expect(transport.requests).toHaveLength(1)
  })
})
