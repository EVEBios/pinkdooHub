import {
  ApiClientError,
  BusinessError,
  HttpError,
  NetworkError,
  SessionExpiredError,
} from './errors'
import { parseEnvelope } from './envelope'
import type {
  ApiRequestOptions,
  AuthSession,
  HttpTransport,
  QueryPrimitive,
  QueryValue,
  TransportRequest,
} from './types'

const DEFAULT_TIMEOUT_MS = 15_000
const TOKEN_EXPIRED_CODE = 1006

export interface ApiClientOptions {
  baseUrl: string
  transport: HttpTransport
  authSession?: AuthSession
  defaultTimeoutMs?: number
}

export class ApiClient {
  private readonly baseUrl: string
  private readonly transport: HttpTransport
  private readonly authSession?: AuthSession
  private readonly defaultTimeoutMs: number
  private refreshPromise?: Promise<string>

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.transport = options.transport
    this.authSession = options.authSession
    this.defaultTimeoutMs = options.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS

    if (!/^https?:\/\//.test(this.baseUrl)) {
      throw new Error('ApiClient baseUrl 必须是 HTTP(S) Origin')
    }
  }

  request<T>(options: ApiRequestOptions): Promise<T> {
    return this.execute<T>(options, false)
  }

  private async execute<T>(
    options: ApiRequestOptions,
    refreshed: boolean,
    accessTokenOverride?: string,
  ): Promise<T> {
    const request = this.buildTransportRequest(options, accessTokenOverride)
    let response
    try {
      response = await this.transport.request(request)
    } catch (cause) {
      if (cause instanceof ApiClientError) {
        throw cause
      }
      throw new NetworkError({ operation: options.operation }, cause)
    }

    const successStatus = response.statusCode >= 200 && response.statusCode < 300
    let envelope
    try {
      envelope = parseEnvelope(response, options.operation)
    } catch (cause) {
      if (!successStatus) {
        throw new HttpError(
          { operation: options.operation, statusCode: response.statusCode },
          response.data,
        )
      }
      throw cause
    }

    if (
      envelope.code === TOKEN_EXPIRED_CODE &&
      !refreshed &&
      options.auth !== 'none' &&
      this.authSession?.getAccessToken()
    ) {
      const newAccessToken = await this.refreshAccessToken(options.operation)
      return this.execute<T>(options, true, newAccessToken)
    }

    if (envelope.code !== 0) {
      throw new BusinessError(
        { operation: options.operation, statusCode: response.statusCode },
        envelope.code,
        envelope.message,
        envelope.data,
      )
    }

    if (!successStatus) {
      throw new HttpError(
        { operation: options.operation, statusCode: response.statusCode },
        response.data,
      )
    }

    return envelope.data as T
  }

  private buildTransportRequest(
    options: ApiRequestOptions,
    accessTokenOverride?: string,
  ): TransportRequest {
    if (!options.path.startsWith('/') || /^https?:\/\//.test(options.path)) {
      throw new Error('API path 必须是以 / 开头的相对路径')
    }

    const headers: Record<string, string> = { ...options.headers }
    const authMode = options.auth ?? 'none'
    const accessToken = accessTokenOverride ?? this.authSession?.getAccessToken()
    if (authMode === 'required' && !accessToken) {
      throw new SessionExpiredError({ operation: options.operation }, '缺少 access token')
    }
    if (authMode !== 'none' && accessToken) {
      headers.Authorization = `Bearer ${accessToken}`
    }
    if (options.body !== undefined && !hasHeader(headers, 'content-type')) {
      headers['Content-Type'] = 'application/json'
    }

    return {
      operation: options.operation,
      url: `${this.baseUrl}${options.path}${encodeQuery(options.query)}`,
      method: options.method ?? 'GET',
      headers,
      body: options.body,
      timeoutMs: options.timeoutMs ?? this.defaultTimeoutMs,
      signal: options.signal,
    }
  }

  private async refreshAccessToken(operation: string): Promise<string> {
    if (!this.authSession) {
      throw new SessionExpiredError({ operation }, '未配置 AuthSession')
    }
    if (this.refreshPromise) {
      return this.refreshPromise
    }

    const activeRefresh = this.performRefresh(operation, this.authSession)
    this.refreshPromise = activeRefresh
    try {
      return await activeRefresh
    } finally {
      if (this.refreshPromise === activeRefresh) {
        this.refreshPromise = undefined
      }
    }
  }

  private async performRefresh(operation: string, authSession: AuthSession): Promise<string> {
    try {
      const accessToken = await authSession.refreshAccessToken()
      if (!accessToken) {
        throw new Error('刷新响应未返回 access token')
      }
      return accessToken
    } catch (cause) {
      let cleanupCause: unknown
      try {
        await authSession.clearSession()
      } catch (error) {
        cleanupCause = error
      }
      throw new SessionExpiredError({ operation }, cause, cleanupCause)
    }
  }
}

function hasHeader(headers: Readonly<Record<string, string>>, name: string): boolean {
  const normalizedName = name.toLowerCase()
  return Object.keys(headers).some((key) => key.toLowerCase() === normalizedName)
}

function encodeQuery(query: Readonly<Record<string, QueryValue>> | undefined): string {
  if (!query) {
    return ''
  }

  const parts: string[] = []
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null) {
      return
    }
    if (Array.isArray(value)) {
      value.forEach((item) => parts.push(encodeQueryPart(key, item)))
      return
    }
    parts.push(encodeQueryPart(key, value as QueryPrimitive))
  })
  return parts.length > 0 ? `?${parts.join('&')}` : ''
}

function encodeQueryPart(key: string, value: QueryPrimitive): string {
  return `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`
}
