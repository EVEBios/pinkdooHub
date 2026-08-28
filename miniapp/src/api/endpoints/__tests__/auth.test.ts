import { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { AuthSession, HttpTransport, TransportRequest, TransportResponse } from '@/api/types'

import { AuthApi, type UserProfile } from '../auth'

const user: UserProfile = {
  id: 7,
  username: 'alice',
  nickname: 'Alice',
  phone: '13800138000',
  avatar: null,
  role: 'user',
  status: 'normal',
  last_login_at: '2026-08-20T08:00:00Z',
  created_at: '2026-08-01T08:00:00Z',
  updated_at: '2026-08-20T08:00:00Z',
}

class FakeTransport implements HttpTransport {
  readonly requests: TransportRequest[] = []

  constructor(private readonly data: unknown) {}

  async request(request: TransportRequest): Promise<TransportResponse> {
    this.requests.push(request)
    return {
      statusCode: 200,
      headers: {},
      data: { code: 0, message: 'success', data: this.data },
    }
  }
}

describe('AuthApi', () => {
  it('注册请求不携带认证，并对白名单用户响应做运行时投影', async () => {
    const transport = new FakeTransport({ ...user, password: 'must-not-cross-endpoint' })
    const api = new AuthApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport,
    }))

    await expect(api.register({
      username: 'alice',
      password: 'secret-password',
      nickname: 'Alice',
      phone: '13800138000',
    })).resolves.toEqual(user)
    expect(transport.requests[0]).toMatchObject({
      operation: 'auth.register',
      method: 'POST',
      url: 'https://api.example.com/api/v1/auth/register',
      body: {
        username: 'alice',
        password: 'secret-password',
        nickname: 'Alice',
        phone: '13800138000',
      },
    })
    expect(transport.requests[0].headers).not.toHaveProperty('Authorization')
  })

  it('拒绝形状错误的注册成功响应', async () => {
    const api = new AuthApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport: new FakeTransport({ id: 7, username: 'alice' }),
    }))

    await expect(api.register({
      username: 'alice',
      password: 'secret-password',
      nickname: 'Alice',
      phone: '13800138000',
    })).rejects.toBeInstanceOf(ContractError)
  })

  it('按生成请求类型调用登录端点，并校验返回数据', async () => {
    const transport = new FakeTransport({
      access_token: 'access-token',
      refresh_token: 'refresh-token',
      token_type: 'Bearer',
      expires_in: 7200,
      user: { ...user, password: 'must-not-cross-endpoint' },
    })
    const api = new AuthApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport,
    }))

    const result = await api.login({ username: 'alice', password: 'secret' })
    expect(result).toMatchObject({ user })
    expect(result.user).not.toHaveProperty('password')
    expect(transport.requests[0]).toMatchObject({
      operation: 'auth.login',
      method: 'POST',
      url: 'https://api.example.com/api/v1/auth/login',
      body: { username: 'alice', password: 'secret' },
    })
    expect(transport.requests[0].headers).not.toHaveProperty('Authorization')
  })

  it('拒绝 HTTP 信封内形状错误的登录数据', async () => {
    const transport = new FakeTransport({ access_token: 'only-one-field' })
    const api = new AuthApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport,
    }))

    await expect(api.login({ username: 'alice', password: 'secret' }))
      .rejects.toBeInstanceOf(ContractError)
  })

  it('GET me 携带 access token，logout 接受 null data', async () => {
    const authSession: AuthSession = {
      getAccessToken: () => 'access-token',
      refreshAccessToken: async () => undefined,
      clearSession: jest.fn(),
    }
    const meTransport = new FakeTransport(user)
    const meApi = new AuthApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport: meTransport,
      authSession,
    }))

    await expect(meApi.getMe()).resolves.toEqual(user)
    expect(meTransport.requests[0].headers.Authorization).toBe('Bearer access-token')

    const logoutTransport = new FakeTransport(null)
    const logoutApi = new AuthApi(new ApiClient({
      baseUrl: 'https://api.example.com',
      transport: logoutTransport,
      authSession,
    }))
    await expect(logoutApi.logout()).resolves.toBeUndefined()
  })
})
