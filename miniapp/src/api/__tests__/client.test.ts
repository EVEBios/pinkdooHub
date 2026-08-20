import { ApiClient } from '../client'
import {
  BusinessError,
  ContractError,
  HttpError,
  SessionExpiredError,
  TimeoutError,
} from '../errors'
import type {
  AuthSession,
  HttpTransport,
  TransportRequest,
  TransportResponse,
} from '../types'

class FakeTransport implements HttpTransport {
  readonly requests: TransportRequest[] = []

  constructor(
    private readonly responder: (
      request: TransportRequest,
      index: number,
    ) => TransportResponse | Promise<TransportResponse>,
  ) {}

  async request(request: TransportRequest): Promise<TransportResponse> {
    this.requests.push(request)
    return this.responder(request, this.requests.length - 1)
  }
}

function response(statusCode: number, data: unknown): TransportResponse {
  return { statusCode, data, headers: {} }
}

describe('ApiClient', () => {
  it('解析成功信封并编码 query', async () => {
    const transport = new FakeTransport(() => response(200, {
      code: 0,
      message: 'success',
      data: { id: 7 },
    }))
    const client = new ApiClient({ baseUrl: 'https://api.example.com/', transport })

    await expect(client.request<{ id: number }>({
      operation: 'listProducts',
      path: '/api/v1/products',
      query: { page: 1, status: ['online', 'offline'], ignored: undefined },
    })).resolves.toEqual({ id: 7 })

    expect(transport.requests[0].url).toBe(
      'https://api.example.com/api/v1/products?page=1&status=online&status=offline',
    )
  })

  it('把后端业务错误保留为 BusinessError', async () => {
    const transport = new FakeTransport(() => response(403, {
      code: 403,
      message: '权限不足',
      data: null,
    }))
    const client = new ApiClient({ baseUrl: 'https://api.example.com', transport })

    await expect(client.request({
      operation: 'adminListUsers',
      path: '/api/v1/admin/users',
    })).rejects.toMatchObject<Partial<BusinessError>>({
      name: 'BusinessError',
      code: 403,
      statusCode: 403,
      data: null,
    })
  })

  it('拒绝成功状态下的不合法信封', async () => {
    const transport = new FakeTransport(() => response(200, { result: 'unexpected' }))
    const client = new ApiClient({ baseUrl: 'https://api.example.com', transport })

    await expect(client.request({ operation: 'health', path: '/api/v1/health' }))
      .rejects.toBeInstanceOf(ContractError)
  })

  it('把非信封 HTTP 失败映射为 HttpError', async () => {
    const transport = new FakeTransport(() => response(502, '<html>bad gateway</html>'))
    const client = new ApiClient({ baseUrl: 'https://api.example.com', transport })

    await expect(client.request({ operation: 'health', path: '/api/v1/health' }))
      .rejects.toBeInstanceOf(HttpError)
  })

  it('三个并发 1006 只刷新一次并各重放一次', async () => {
    let accessToken = 'expired-token'
    let refreshCount = 0
    const authSession: AuthSession = {
      getAccessToken: () => accessToken,
      refreshAccessToken: async () => {
        refreshCount += 1
        await Promise.resolve()
        accessToken = 'new-token'
        return accessToken
      },
      clearSession: jest.fn(),
    }
    const transport = new FakeTransport((request) => {
      if (request.headers.Authorization === 'Bearer expired-token') {
        return response(400, { code: 1006, message: 'Token 已失效', data: null })
      }
      return response(200, { code: 0, message: 'success', data: request.operation })
    })
    const client = new ApiClient({
      baseUrl: 'https://api.example.com',
      transport,
      authSession,
    })

    const requests = ['first', 'second', 'third'].map((operation) => client.request<string>({
      operation,
      path: '/api/v1/users/me',
      auth: 'required',
    }))

    await expect(Promise.all(requests)).resolves.toEqual(['first', 'second', 'third'])
    expect(refreshCount).toBe(1)
    expect(transport.requests).toHaveLength(6)
  })

  it('403 不触发 refresh', async () => {
    const authSession: AuthSession = {
      getAccessToken: () => 'valid-token',
      refreshAccessToken: jest.fn(),
      clearSession: jest.fn(),
    }
    const transport = new FakeTransport(() => response(403, {
      code: 403,
      message: '权限不足',
      data: null,
    }))
    const client = new ApiClient({ baseUrl: 'https://api.example.com', transport, authSession })

    await expect(client.request({
      operation: 'adminListUsers',
      path: '/api/v1/admin/users',
      auth: 'required',
    })).rejects.toBeInstanceOf(BusinessError)
    expect(authSession.refreshAccessToken).not.toHaveBeenCalled()
  })

  it('refresh 失败时清理会话并返回 SessionExpiredError', async () => {
    const clearSession = jest.fn()
    const authSession: AuthSession = {
      getAccessToken: () => 'expired-token',
      refreshAccessToken: async () => {
        throw new Error('refresh failed')
      },
      clearSession,
    }
    const transport = new FakeTransport(() => response(400, {
      code: 1006,
      message: 'Token 已失效',
      data: null,
    }))
    const client = new ApiClient({ baseUrl: 'https://api.example.com', transport, authSession })

    await expect(client.request({
      operation: 'getMe',
      path: '/api/v1/users/me',
      auth: 'required',
    })).rejects.toBeInstanceOf(SessionExpiredError)
    expect(clearSession).toHaveBeenCalledTimes(1)
  })

  it('empty-body PATCH 不添加 data 与 Content-Type', async () => {
    const transport = new FakeTransport(() => response(200, {
      code: 0,
      message: 'success',
      data: { status: 'cancelled' },
    }))
    const client = new ApiClient({ baseUrl: 'https://api.example.com', transport })

    await client.request({
      operation: 'cancelOrder',
      path: '/api/v1/orders/1/cancel',
      method: 'PATCH',
    })

    expect(transport.requests[0].body).toBeUndefined()
    expect(transport.requests[0].headers).not.toHaveProperty('Content-Type')
  })

  it('不包装 Transport 已分类的超时错误', async () => {
    const timeout = new TimeoutError({ operation: 'createOrder' }, 'timeout')
    const transport = new FakeTransport(async () => {
      throw timeout
    })
    const client = new ApiClient({ baseUrl: 'https://api.example.com', transport })

    await expect(client.request({
      operation: 'createOrder',
      path: '/api/v1/orders',
      method: 'POST',
      body: { items: [] },
    })).rejects.toBe(timeout)
    expect(transport.requests).toHaveLength(1)
  })
})
