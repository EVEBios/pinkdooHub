import { ApiClient } from '@/api/client'
import { OrderApi, type AdminOrderDetail, type AdminOrderListPage } from '@/api/endpoints/orders'
import type { AuthSession, HttpTransport, TransportRequest, TransportResponse } from '@/api/types'

const pendingDetail: AdminOrderDetail = {
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
    product_name: '体验快照',
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

describe('Admin Order vertical slice', () => {
  it('列表→详情→Paid→核对→Completed→核对全程使用认证契约', async () => {
    const paidStatus = {
      id: 101,
      order_no: pendingDetail.order_no,
      status: { value: 'paid', label: '已支付' } as const,
      updated_at: '2026-08-24T09:00:00Z',
    }
    const completedStatus = {
      ...paidStatus,
      status: { value: 'completed', label: '已完成' } as const,
      updated_at: '2026-08-24T10:00:00Z',
    }
    const listPage: AdminOrderListPage = {
      items: [{
        id: 101,
        order_no: pendingDetail.order_no,
        user_id: 7,
        user_nickname: '开发用户',
        total_amount: '99.00',
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
    const paidDetail = { ...pendingDetail, status: paidStatus.status, updated_at: paidStatus.updated_at }
    const completedDetail = { ...pendingDetail, status: completedStatus.status, updated_at: completedStatus.updated_at }
    const transport = new SequencedTransport([
      success(listPage),
      success(pendingDetail),
      success(paidStatus),
      success(paidDetail),
      success(completedStatus),
      success(completedDetail),
    ])
    const authSession: AuthSession = {
      getAccessToken: () => 'admin-access-token',
      refreshAccessToken: jest.fn(async () => 'refreshed-token'),
      clearSession: jest.fn(),
    }
    const api = new OrderApi(new ApiClient({ baseUrl: 'https://api.example.com', transport, authSession }))

    await api.listAdminOrders({ page: 1, page_size: 20, status: 'pending', user_id: 7 })
    await api.getAdminOrderDetail(101)
    await api.markOrderPaid(101)
    await api.getAdminOrderDetail(101)
    await api.completeOrder(101)
    await api.getAdminOrderDetail(101)

    expect(transport.requests.map((request) => [request.method, request.url])).toEqual([
      ['GET', 'https://api.example.com/api/v1/admin/orders?page=1&page_size=20&status=pending&user_id=7'],
      ['GET', 'https://api.example.com/api/v1/admin/orders/101'],
      ['PATCH', 'https://api.example.com/api/v1/admin/orders/101/paid'],
      ['GET', 'https://api.example.com/api/v1/admin/orders/101'],
      ['PATCH', 'https://api.example.com/api/v1/admin/orders/101/complete'],
      ['GET', 'https://api.example.com/api/v1/admin/orders/101'],
    ])
    expect(transport.requests[2].body).toBeUndefined()
    expect(transport.requests[4].body).toBeUndefined()
    expect(transport.requests.every((request) => request.headers.Authorization === 'Bearer admin-access-token')).toBe(true)
  })
})

function success(data: unknown): TransportResponse {
  return { statusCode: 200, headers: {}, data: { code: 0, message: 'success', data } }
}
