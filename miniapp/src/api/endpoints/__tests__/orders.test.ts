import { ApiClient } from '@/api/client'
import { ContractError, SessionExpiredError, TimeoutError } from '@/api/errors'
import type {
  AuthSession,
  HttpTransport,
  TransportRequest,
  TransportResponse,
} from '@/api/types'

import {
  OrderApi,
  type AdminOrderDetail,
  type AdminOrderListPage,
  type OrderCreateRequest,
  type OrderDetail,
  type OrderListPage,
  type OrderStatusResult,
} from '../orders'

const orderDetail: OrderDetail = {
  id: 101,
  order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
  total_amount: '497.00',
  status: { value: 'pending', label: '待支付' },
  remark: '周五晚上到店',
  items: [
    {
      id: 1001,
      product_id: 1,
      experience_option_id: 10,
      product_name: '拼豆体验',
      option_duration_minutes: 60,
      option_participants: 1,
      option_day_type: { value: 'weekday', label: '工作日' },
      product_price: '99.00',
      quantity: 1,
      subtotal: '99.00',
    },
    {
      id: 1002,
      product_id: 5,
      experience_option_id: null,
      product_name: '拼豆材料包',
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

const orderListPage: OrderListPage = {
  items: [{
    id: orderDetail.id,
    order_no: orderDetail.order_no,
    total_amount: orderDetail.total_amount,
    status: orderDetail.status,
    item_count: orderDetail.items.length,
    created_at: orderDetail.created_at,
    updated_at: orderDetail.updated_at,
  }],
  total: 1,
  page: 1,
  page_size: 20,
  pages: 1,
}

const cancelledStatus: OrderStatusResult = {
  id: orderDetail.id,
  order_no: orderDetail.order_no,
  status: { value: 'cancelled', label: '已取消' },
  updated_at: '2026-08-13T11:00:00Z',
}

const adminOrderDetail: AdminOrderDetail = {
  ...orderDetail,
  user_id: 7,
  user_nickname: '开发用户',
}

const adminOrderListPage: AdminOrderListPage = {
  ...orderListPage,
  items: orderListPage.items.map((item) => ({
    ...item,
    user_id: adminOrderDetail.user_id,
    user_nickname: adminOrderDetail.user_nickname,
  })),
}

const paidStatus: OrderStatusResult = {
  ...cancelledStatus,
  status: { value: 'paid', label: '已支付' },
}

const completedStatus: OrderStatusResult = {
  ...cancelledStatus,
  status: { value: 'completed', label: '已完成' },
}

class FakeTransport implements HttpTransport {
  readonly requests: TransportRequest[] = []

  constructor(
    private readonly data: unknown,
    private readonly statusCode = 200,
    private readonly code = 0,
  ) {}

  async request(request: TransportRequest): Promise<TransportResponse> {
    this.requests.push(request)
    return {
      statusCode: this.statusCode,
      headers: {},
      data: { code: this.code, message: this.code === 0 ? 'success' : 'error', data: this.data },
    }
  }
}

function createAuthSession(): AuthSession {
  return {
    getAccessToken: () => 'access-token',
    refreshAccessToken: jest.fn(async () => 'refreshed-token'),
    clearSession: jest.fn(),
  }
}

function createOrderApi(transport: HttpTransport, authSession: AuthSession = createAuthSession()): OrderApi {
  return new OrderApi(new ApiClient({
    baseUrl: 'https://api.example.com',
    transport,
    authSession,
  }))
}

describe('OrderApi.createOrder', () => {
  it('使用 Bearer POST Experience/Kit 最小白名单请求并省略 Kit option', async () => {
    const transport = new FakeTransport(orderDetail)
    const api = createOrderApi(transport)
    const request: OrderCreateRequest = {
      items: [
        { product_id: 1, experience_option_id: 10, quantity: 1 },
        { product_id: 5, quantity: 2 },
      ],
      remark: '周五晚上到店',
    }

    await expect(api.createOrder(request)).resolves.toEqual(orderDetail)

    expect(transport.requests).toHaveLength(1)
    expect(transport.requests[0]).toEqual(expect.objectContaining({
      operation: 'orders.create',
      method: 'POST',
      url: 'https://api.example.com/api/v1/orders',
      headers: {
        Authorization: 'Bearer access-token',
        'Content-Type': 'application/json',
      },
      body: request,
    }))
    expect((transport.requests[0].body as OrderCreateRequest).items[1]).not.toHaveProperty(
      'experience_option_id',
    )
  })

  it('请求与响应都执行白名单投影', async () => {
    const transport = new FakeTransport({
      ...orderDetail,
      user_id: 7,
      internal_note: '不应进入用户端结果',
      items: orderDetail.items.map((item) => ({ ...item, internal_cost: '1.00' })),
    })
    const api = createOrderApi(transport)
    const request = {
      items: [
        {
          product_id: 5,
          experience_option_id: null,
          quantity: 2,
          product_name: '不应发送',
        },
      ],
      remark: null,
      total_amount: '1.00',
    } as unknown as OrderCreateRequest

    await expect(api.createOrder(request)).resolves.toEqual(orderDetail)
    expect(transport.requests[0].body).toEqual({
      items: [{ product_id: 5, quantity: 2 }],
      remark: null,
    })
  })

  it('没有 access token 时在发出请求前失败', async () => {
    const transport = new FakeTransport(orderDetail)
    const api = createOrderApi(transport, {
      getAccessToken: () => undefined,
      refreshAccessToken: jest.fn(async () => undefined),
      clearSession: jest.fn(),
    })

    await expect(api.createOrder({
      items: [{ product_id: 5, quantity: 1 }],
    })).rejects.toBeInstanceOf(SessionExpiredError)
    expect(transport.requests).toHaveLength(0)
  })

  it.each([
    { ...orderDetail, order_no: 'OD-invalid' },
    { ...orderDetail, status: { value: 'pending', label: '错误文案' } },
    { ...orderDetail, total_amount: '496.00' },
    { ...orderDetail, created_at: '2026-08-13T18:30:00+08:00' },
    { ...orderDetail, items: [] },
    {
      ...orderDetail,
      items: [
        { ...orderDetail.items[0], option_day_type: null },
        orderDetail.items[1],
      ],
    },
    {
      ...orderDetail,
      items: [
        orderDetail.items[0],
        { ...orderDetail.items[1], option_participants: 1 },
      ],
    },
  ])('拒绝不符合 Order 创建响应契约的数据：%p', async (data) => {
    const api = createOrderApi(new FakeTransport(data))

    await expect(api.createOrder({
      items: [{ product_id: 5, quantity: 1 }],
    })).rejects.toBeInstanceOf(ContractError)
  })

  it('超时结果未知时只调用一次且不刷新、不重试 POST', async () => {
    const requests: TransportRequest[] = []
    const transport: HttpTransport = {
      request: jest.fn(async (request: TransportRequest) => {
        requests.push(request)
        throw new TimeoutError({ operation: request.operation }, { errMsg: 'request:fail timeout' })
      }),
    }
    const authSession = createAuthSession()
    const api = createOrderApi(transport, authSession)

    await expect(api.createOrder({
      items: [{ product_id: 5, quantity: 1 }],
    })).rejects.toBeInstanceOf(TimeoutError)
    expect(requests).toHaveLength(1)
    expect(authSession.refreshAccessToken).not.toHaveBeenCalled()
  })
})

describe('OrderApi query and cancel', () => {
  it('分页查询使用认证 GET、白名单 Query 并解析列表页', async () => {
    const transport = new FakeTransport(orderListPage)
    const api = createOrderApi(transport)

    await expect(api.listOrders({
      page: 2,
      page_size: 20,
      status: 'pending',
      ignored: 'field',
    } as never)).resolves.toEqual(orderListPage)

    expect(transport.requests[0]).toEqual(expect.objectContaining({
      operation: 'orders.list',
      method: 'GET',
      url: 'https://api.example.com/api/v1/orders?page=2&page_size=20&status=pending',
      headers: { Authorization: 'Bearer access-token' },
    }))
    expect(transport.requests[0].body).toBeUndefined()
  })

  it('列表省略 null status 并对白名单响应投影', async () => {
    const transport = new FakeTransport({
      ...orderListPage,
      internal: 'hidden',
      items: orderListPage.items.map((item) => ({ ...item, user_id: 7 })),
    })
    const api = createOrderApi(transport)

    await expect(api.listOrders({ status: null })).resolves.toEqual(orderListPage)
    expect(transport.requests[0].url).toBe('https://api.example.com/api/v1/orders')
  })

  it.each([
    { ...orderListPage, pages: 2 },
    { ...orderListPage, total: -1 },
    { ...orderListPage, items: [{ ...orderListPage.items[0], item_count: 0 }] },
    { ...orderListPage, items: [{ ...orderListPage.items[0], total_amount: '1' }] },
    { ...orderListPage, items: [{ ...orderListPage.items[0], status: { value: 'pending', label: '错误' } }] },
  ])('拒绝坏列表分页或列表项：%p', async (data) => {
    await expect(createOrderApi(new FakeTransport(data)).listOrders())
      .rejects.toBeInstanceOf(ContractError)
  })

  it('详情使用 owner-only 认证 GET 并复用详情 Guard', async () => {
    const transport = new FakeTransport(orderDetail)
    const api = createOrderApi(transport)

    await expect(api.getOrderDetail(101)).resolves.toEqual(orderDetail)
    expect(transport.requests[0]).toEqual(expect.objectContaining({
      operation: 'orders.detail',
      method: 'GET',
      url: 'https://api.example.com/api/v1/orders/101',
      headers: { Authorization: 'Bearer access-token' },
    }))
  })

  it('取消发送完全没有 body 的认证 PATCH，并只接受 cancelled', async () => {
    const transport = new FakeTransport(cancelledStatus)
    const api = createOrderApi(transport)

    await expect(api.cancelOrder(101)).resolves.toEqual(cancelledStatus)
    expect(transport.requests[0]).toEqual(expect.objectContaining({
      operation: 'orders.cancel',
      method: 'PATCH',
      url: 'https://api.example.com/api/v1/orders/101/cancel',
      headers: { Authorization: 'Bearer access-token' },
    }))
    expect(transport.requests[0].body).toBeUndefined()

    await expect(createOrderApi(new FakeTransport({
      ...cancelledStatus,
      status: { value: 'pending', label: '待支付' },
    })).cancelOrder(101)).rejects.toBeInstanceOf(ContractError)
  })

  it('拒绝非法 Order ID，且不发送请求', async () => {
    const transport = new FakeTransport(orderDetail)
    const api = createOrderApi(transport)

    await expect(api.getOrderDetail(0)).rejects.toThrow('Order ID 必须是正整数')
    await expect(api.cancelOrder(Number.NaN)).rejects.toThrow('Order ID 必须是正整数')
    expect(transport.requests).toHaveLength(0)
  })

  it('40411 与 40921 保持结构化业务错误', async () => {
    const notFound = createOrderApi(new FakeTransport(null, 404, 40411))
    const conflict = createOrderApi(new FakeTransport({
      operation: 'cancel',
      current_status: 'paid',
      required_status: 'pending',
    }, 409, 40921))

    await expect(notFound.getOrderDetail(101)).rejects.toMatchObject({
      code: 40411,
      statusCode: 404,
    })
    await expect(conflict.cancelOrder(101)).rejects.toMatchObject({
      code: 40921,
      statusCode: 409,
    })
  })
})

describe('OrderApi admin query and transitions', () => {
  it('管理端列表仅发送完整白名单筛选参数', async () => {
    const transport = new FakeTransport(adminOrderListPage)
    const api = createOrderApi(transport)

    await expect(api.listAdminOrders({
      page: 2,
      page_size: 20,
      status: 'paid',
      order_no: orderDetail.order_no,
      user_id: 7,
      created_from: '2026-08-01T00:00:00Z',
      created_to: '2026-09-01T00:00:00Z',
      ignored: 'hidden',
    } as never)).resolves.toEqual(adminOrderListPage)

    expect(transport.requests[0]).toEqual(expect.objectContaining({
      operation: 'orders.admin.list',
      method: 'GET',
      url: `https://api.example.com/api/v1/admin/orders?page=2&page_size=20&status=paid&order_no=${orderDetail.order_no}&user_id=7&created_from=2026-08-01T00%3A00%3A00Z&created_to=2026-09-01T00%3A00%3A00Z`,
      headers: { Authorization: 'Bearer access-token' },
    }))
    expect(transport.requests[0].body).toBeUndefined()
  })

  it('管理端列表和详情都执行响应白名单投影', async () => {
    const listTransport = new FakeTransport({
      ...adminOrderListPage,
      internal: 'hidden',
      items: adminOrderListPage.items.map((item) => ({ ...item, private_phone: 'hidden' })),
    })
    const detailTransport = new FakeTransport({
      ...adminOrderDetail,
      private_phone: 'hidden',
    })

    await expect(createOrderApi(listTransport).listAdminOrders()).resolves.toEqual(adminOrderListPage)
    await expect(createOrderApi(detailTransport).getAdminOrderDetail(101)).resolves.toEqual(adminOrderDetail)
  })

  it.each([
    { ...adminOrderListPage, items: [{ ...adminOrderListPage.items[0], user_id: 0 }] },
    { ...adminOrderListPage, items: [{ ...adminOrderListPage.items[0], user_nickname: '' }] },
    { ...adminOrderDetail, user_id: 0 },
    { ...adminOrderDetail, user_nickname: 'x'.repeat(33) },
  ])('拒绝不符合管理端输出契约的数据：%p', async (data) => {
    const api = createOrderApi(new FakeTransport(data))
    const action = 'items' in data
      ? api.listAdminOrders()
      : api.getAdminOrderDetail(101)

    await expect(action).rejects.toBeInstanceOf(ContractError)
  })

  it.each([
    ['markOrderPaid', paidStatus, '/api/v1/admin/orders/101/paid', 'orders.admin.markPaid'],
    ['completeOrder', completedStatus, '/api/v1/admin/orders/101/complete', 'orders.admin.complete'],
  ] as const)('%s 发送无 body PATCH 并校验目标状态', async (method, result, path, operation) => {
    const transport = new FakeTransport(result)
    const api = createOrderApi(transport)

    await expect(api[method](101)).resolves.toEqual(result)
    expect(transport.requests[0]).toEqual(expect.objectContaining({
      operation,
      method: 'PATCH',
      url: `https://api.example.com${path}`,
      headers: { Authorization: 'Bearer access-token' },
    }))
    expect(transport.requests[0].body).toBeUndefined()

    await expect(createOrderApi(new FakeTransport(cancelledStatus))[method](101))
      .rejects.toBeInstanceOf(ContractError)
  })

  it('ADMIN 端点保留 403/40411/40921 结构化错误', async () => {
    const forbidden = createOrderApi(new FakeTransport(null, 403, 40301))
    const notFound = createOrderApi(new FakeTransport(null, 404, 40411))
    const conflict = createOrderApi(new FakeTransport({
      operation: 'mark_paid',
      current_status: 'paid',
      required_status: 'pending',
    }, 409, 40921))

    await expect(forbidden.listAdminOrders()).rejects.toMatchObject({ statusCode: 403 })
    await expect(notFound.getAdminOrderDetail(101)).rejects.toMatchObject({ code: 40411 })
    await expect(conflict.markOrderPaid(101)).rejects.toMatchObject({ code: 40921 })
  })
})
