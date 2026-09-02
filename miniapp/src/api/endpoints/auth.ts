import { ContractError } from '@/api/errors'
import type { ApiClient } from '@/api/client'
import type { components } from '@/api/schema'

export type LoginRequest = components['schemas']['LoginRequest']
export type RegistrationRequest = components['schemas']['UserCreate']
export type RefreshRequest = components['schemas']['RefreshRequest']
export type LoginResult = components['schemas']['TokenOut']
export type RefreshResult = components['schemas']['RefreshOut']
export type UserProfile = components['schemas']['UserOut']
export type WeChatLoginRequest = components['schemas']['WeChatCodeRequest']

type AuthApiClient = Pick<ApiClient, 'request'>

export class AuthApi {
  constructor(private readonly client: AuthApiClient) {}

  async register(data: RegistrationRequest): Promise<UserProfile> {
    const result = await this.client.request<unknown>({
      operation: 'auth.register',
      path: '/api/v1/auth/register',
      method: 'POST',
      body: data,
      auth: 'none',
    })
    const parsed = parseUserProfile(result)
    if (!parsed) {
      throw new ContractError({ operation: 'auth.register' })
    }
    return parsed
  }

  async login(data: LoginRequest): Promise<LoginResult> {
    const result = await this.client.request<unknown>({
      operation: 'auth.login',
      path: '/api/v1/auth/login',
      method: 'POST',
      body: data,
      auth: 'none',
    })
    const parsed = parseLoginResult(result)
    if (!parsed) {
      throw new ContractError({ operation: 'auth.login' })
    }
    return parsed
  }

  async loginWithWechat(code: string): Promise<LoginResult> {
    const data: WeChatLoginRequest = { code }
    const result = await this.client.request<unknown>({
      operation: 'auth.wechatLogin',
      path: '/api/v1/auth/wechat/login',
      method: 'POST',
      body: data,
      auth: 'none',
    })
    const parsed = parseLoginResult(result)
    if (!parsed) {
      throw new ContractError({ operation: 'auth.wechatLogin' })
    }
    return parsed
  }

  async refresh(refreshToken: string): Promise<RefreshResult> {
    const data: RefreshRequest = { refresh_token: refreshToken }
    const result = await this.client.request<unknown>({
      operation: 'auth.refresh',
      path: '/api/v1/auth/refresh',
      method: 'POST',
      body: data,
      auth: 'none',
    })
    const parsed = parseRefreshResult(result)
    if (!parsed) {
      throw new ContractError({ operation: 'auth.refresh' })
    }
    return parsed
  }

  async logout(): Promise<void> {
    const result = await this.client.request<unknown>({
      operation: 'auth.logout',
      path: '/api/v1/auth/logout',
      method: 'POST',
      auth: 'required',
    })
    if (result !== null) {
      throw new ContractError({ operation: 'auth.logout' })
    }
  }

  async getMe(): Promise<UserProfile> {
    const result = await this.client.request<unknown>({
      operation: 'users.getMe',
      path: '/api/v1/users/me',
      auth: 'required',
    })
    const parsed = parseUserProfile(result)
    if (!parsed) {
      throw new ContractError({ operation: 'users.getMe' })
    }
    return parsed
  }
}

export function parseUserProfile(value: unknown): UserProfile | undefined {
  if (!isRecord(value)) {
    return undefined
  }
  if (!(
    isPositiveInteger(value.id) &&
    isNonEmptyString(value.username) &&
    isNonEmptyString(value.nickname) &&
    (value.phone === null || typeof value.phone === 'string') &&
    (value.avatar === null || typeof value.avatar === 'string') &&
    (value.role === 'user' || value.role === 'admin' || value.role === 'super_admin') &&
    (value.status === 'normal' || value.status === 'disabled' || value.status === 'deleted') &&
    (value.last_login_at === null || typeof value.last_login_at === 'string') &&
    typeof value.created_at === 'string' &&
    typeof value.updated_at === 'string'
  )) {
    return undefined
  }
  return {
    id: value.id,
    username: value.username,
    nickname: value.nickname,
    phone: value.phone,
    avatar: value.avatar,
    role: value.role,
    status: value.status,
    last_login_at: value.last_login_at,
    created_at: value.created_at,
    updated_at: value.updated_at,
  }
}

function parseLoginResult(value: unknown): LoginResult | undefined {
  if (!isRecord(value)) {
    return undefined
  }
  const user = parseUserProfile(value.user)
  if (!(
    isNonEmptyString(value.access_token) &&
    isNonEmptyString(value.refresh_token) &&
    value.token_type === 'Bearer' &&
    isPositiveInteger(value.expires_in) &&
    user
  )) {
    return undefined
  }
  return {
    access_token: value.access_token,
    refresh_token: value.refresh_token,
    token_type: value.token_type,
    expires_in: value.expires_in,
    user,
  }
}

function parseRefreshResult(value: unknown): RefreshResult | undefined {
  if (!isRecord(value)) {
    return undefined
  }
  if (!(
    isNonEmptyString(value.access_token) &&
    isNonEmptyString(value.refresh_token) &&
    value.token_type === 'Bearer' &&
    isPositiveInteger(value.expires_in)
  )) {
    return undefined
  }
  return {
    access_token: value.access_token,
    refresh_token: value.refresh_token,
    token_type: value.token_type,
    expires_in: value.expires_in,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}
