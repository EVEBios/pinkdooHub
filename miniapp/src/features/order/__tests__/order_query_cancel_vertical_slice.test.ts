import { ApiClient } from '@/api/client'
import type {
  AuthSession,
  HttpTransport,
  TransportRequest,
  TransportResponse,
} from '@/api/types'
import { OrderApi, type OrderDetail, type OrderListPage } from '@/api/endpoints/orders'

const pendingDetail: OrderDetail = {
  id: 101,
  order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
  total_amount: '199.00',
  status: { value: 'pending', label: '待支付' },
  remark: null,
  items: [{
    id: 1,
    product_id: 5,
    experience_option_id: null,
    product_name: '材料包快照',
    option_duration_minutes: null,
    option_participants: null,
    option_day_type: null,
    product_price: '199.00',
    quantity: 1,
    subtotal: '199.00',
  }],
  created_at: '2026-08-24T08:00:00Z',
  updated_at: '2026-08-24T08:00:00Z',
}

const listPage: OrderListPage = {
  items: [{
    id: pendingDetail.id,
    order_no: pendingDetail.order_no,
    total_amount: pendingDetail.total_amount,
    status: pendingDetail.status,
    item_count: 1,
    created_at: pendingDetail.created_at,
    updated_at: pendingDetail.updated_at,
  }],
  total: 1,
  page: 1,
  page_size: 20,
  pages: 1,
}

class SequencedTransport implements HttpTransport {
  readonly requests: TransportRequest[] = []

  constructor(private readonly responses: readonly TransportResponse[]) {}

  async request(request: TransportRequest): Promise<TransportResponse> {
    this.requests.push(request)
    const response = this.responses[this.requests.length - 1]
    if (!response) throw new Error('unexpected request')
    return response
  }
}

describe('Order query/cancel vertical slice', () => {
  it('列表→详情→empty-body 取消→详情核对全程使用认证服务端事实', async () => {
    const cancelled = {
      id: pendingDetail.id,
      order_no: pendingDetail.order_no,
      status: { value: 'cancelled', label: '已取消' } as const,
      updated_at: '2026-08-24T09:00:00Z',
    }
    const cancelledDetail: OrderDetail = {
      ...pendingDetail,
      status: cancelled.status,
      updated_at: cancelled.updated_at,
    }
    const transport = new SequencedTransport([
      success(listPage),
      success(pendingDetail),
      success(cancelled),
      success(cancelledDetail),
    ])
    const authSession: AuthSession = {
      getAccessToken: () => 'access-token',
      refreshAccessToken: jest.fn(async () => 'refreshed-token'),
      clearSession: jest.fn(),
    }
    const api = new OrderApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport,
      authSession,
    }))

    await expect(api.listOrders({ page: 1, page_size: 20 })).resolves.toEqual(listPage)
    await expect(api.getOrderDetail(101)).resolves.toEqual(pendingDetail)
    await expect(api.cancelOrder(101)).resolves.toEqual(cancelled)
    await expect(api.getOrderDetail(101)).resolves.toEqual(cancelledDetail)

    expect(transport.requests.map((request) => [request.method, request.url])).toEqual([
      ['GET', 'https://api.example.com/api/v1/orders?page=1&page_size=20'],
      ['GET', 'https://api.example.com/api/v1/orders/101'],
      ['PATCH', 'https://api.example.com/api/v1/orders/101/cancel'],
      ['GET', 'https://api.example.com/api/v1/orders/101'],
    ])
    expect(transport.requests[2].body).toBeUndefined()
    expect(transport.requests.every((request) => (
      request.headers.Authorization === 'Bearer access-token'
    ))).toBe(true)
  })
})

function success(data: unknown): TransportResponse {
  return { statusCode: 200, headers: {}, data: { code: 0, message: 'success', data } }
}
