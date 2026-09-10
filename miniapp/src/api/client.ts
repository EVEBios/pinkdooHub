import {
  ApiClientError,
  BusinessError,
  HttpError,
  NetworkError,
  SessionExpiredError,
  SessionSupersededError,
} from './errors'
import { parseEnvelope } from './envelope'
import type {
  ApiRequestOptions,
  ApiResponse,
  ApiFileUploadOptions,
  AuthSession,
  FileUploadTransport,
  FileUploadTransportRequest,
  HttpTransport,
  QueryPrimitive,
  QueryValue,
  TransportRequest,
} from './types'

const DEFAULT_TIMEOUT_MS = 15_000
const TOKEN_EXPIRED_CODE = 1006
const USER_DISABLED_CODE = 1005
const USER_DELETED_CODE = 1009

export interface ApiClientOptions {
  baseUrl: string
  transport: HttpTransport
  uploadTransport?: FileUploadTransport
  authSession?: AuthSession
  defaultTimeoutMs?: number
}

interface RequestSessionIdentity {
  readonly value: unknown
}

export class ApiClient {
  private readonly baseUrl: string
  private readonly transport: HttpTransport
  private readonly uploadTransport?: FileUploadTransport
  private readonly authSession?: AuthSession
  private readonly defaultTimeoutMs: number
  private refreshPromise?: Promise<string>
  private refreshPromiseSessionIdentity?: unknown

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.transport = options.transport
    this.uploadTransport = options.uploadTransport
    this.authSession = options.authSession
    this.defaultTimeoutMs = options.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS

    if (!/^https?:\/\//.test(this.baseUrl)) {
      throw new Error('ApiClient baseUrl 必须是 HTTP(S) Origin')
    }
  }

  async request<T>(options: ApiRequestOptions): Promise<T> {
    const response = await this.execute<T>(options, false)
    return response.data
  }

  requestWithMeta<T>(options: ApiRequestOptions): Promise<ApiResponse<T>> {
    return this.execute<T>(options, false)
  }

  uploadFile<T>(options: ApiFileUploadOptions): Promise<T> {
    return this.executeUpload<T>(options, false)
  }

  private async executeUpload<T>(
    options: ApiFileUploadOptions,
    refreshed: boolean,
    accessTokenOverride?: string,
    sessionIdentityOverride?: RequestSessionIdentity,
  ): Promise<T> {
    if (!this.uploadTransport) {
      throw new Error('ApiClient 未配置文件上传 Transport')
    }
    const requestAccessToken = accessTokenOverride ?? this.authSession?.getAccessToken()
    const requestSessionIdentity = sessionIdentityOverride
      ? sessionIdentityOverride.value
      : this.getSessionIdentity(requestAccessToken)
    const request = this.buildUploadTransportRequest(options, requestAccessToken)
    let response
    try {
      response = await this.uploadTransport.upload(request)
    } catch (cause) {
      if (cause instanceof ApiClientError) throw cause
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
      requestAccessToken
    ) {
      const currentAccessToken = this.getCurrentRequestAccessToken(
        options.operation,
        requestSessionIdentity,
      )
      if (currentAccessToken !== requestAccessToken) {
        return this.executeUpload<T>(
          options,
          true,
          currentAccessToken,
          { value: requestSessionIdentity },
        )
      }
      const refreshedAccessToken = await this.refreshAccessToken(
        options.operation,
        requestSessionIdentity,
      )
      const replayAccessToken = this.getPostRefreshAccessToken(
        options.operation,
        requestSessionIdentity,
        refreshedAccessToken,
      )
      return this.executeUpload<T>(
        options,
        true,
        replayAccessToken,
        { value: requestSessionIdentity },
      )
    }

    if (
      (envelope.code === USER_DISABLED_CODE || envelope.code === USER_DELETED_CODE) &&
      options.auth !== 'none' &&
      this.authSession
    ) {
      await this.invalidateSession(options.operation, new BusinessError(
        { operation: options.operation, statusCode: response.statusCode },
        envelope.code,
        envelope.message,
        envelope.data,
      ), requestSessionIdentity)
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

  private async execute<T>(
    options: ApiRequestOptions,
    refreshed: boolean,
    accessTokenOverride?: string,
    sessionIdentityOverride?: RequestSessionIdentity,
  ): Promise<ApiResponse<T>> {
    const requestAccessToken = accessTokenOverride ?? this.authSession?.getAccessToken()
    const requestSessionIdentity = sessionIdentityOverride
      ? sessionIdentityOverride.value
      : this.getSessionIdentity(requestAccessToken)
    const request = this.buildTransportRequest(options, requestAccessToken)
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
      requestAccessToken
    ) {
      const currentAccessToken = this.getCurrentRequestAccessToken(
        options.operation,
        requestSessionIdentity,
      )
      if (currentAccessToken !== requestAccessToken) {
        return this.execute<T>(
          options,
          true,
          currentAccessToken,
          { value: requestSessionIdentity },
        )
      }
      const refreshedAccessToken = await this.refreshAccessToken(
        options.operation,
        requestSessionIdentity,
      )
      const replayAccessToken = this.getPostRefreshAccessToken(
        options.operation,
        requestSessionIdentity,
        refreshedAccessToken,
      )
      return this.execute<T>(
        options,
        true,
        replayAccessToken,
        { value: requestSessionIdentity },
      )
    }

    if (
      (envelope.code === USER_DISABLED_CODE || envelope.code === USER_DELETED_CODE) &&
      options.auth !== 'none' &&
      this.authSession
    ) {
      await this.invalidateSession(options.operation, new BusinessError(
        { operation: options.operation, statusCode: response.statusCode },
        envelope.code,
        envelope.message,
        envelope.data,
      ), requestSessionIdentity)
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

    return {
      data: envelope.data as T,
      statusCode: response.statusCode,
    }
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

  private buildUploadTransportRequest(
    options: ApiFileUploadOptions,
    accessTokenOverride?: string,
  ): FileUploadTransportRequest {
    if (!options.path.startsWith('/') || /^https?:\/\//.test(options.path)) {
      throw new Error('API path 必须是以 / 开头的相对路径')
    }
    if (!options.filePath) throw new Error('上传文件路径不能为空')

    const headers: Record<string, string> = { ...options.headers }
    const authMode = options.auth ?? 'none'
    const accessToken = accessTokenOverride ?? this.authSession?.getAccessToken()
    if (authMode === 'required' && !accessToken) {
      throw new SessionExpiredError({ operation: options.operation }, '缺少 access token')
    }
    if (authMode !== 'none' && accessToken) {
      headers.Authorization = `Bearer ${accessToken}`
    }

    return {
      operation: options.operation,
      url: `${this.baseUrl}${options.path}`,
      filePath: options.filePath,
      name: options.name ?? 'file',
      headers,
      formData: { ...options.formData },
      timeoutMs: options.timeoutMs ?? this.defaultTimeoutMs,
      signal: options.signal,
    }
  }

  private async refreshAccessToken(
    operation: string,
    expectedSessionIdentity: unknown,
  ): Promise<string> {
    if (!this.authSession) {
      throw new SessionExpiredError({ operation }, '未配置 AuthSession')
    }
    if (
      this.refreshPromise &&
      Object.is(this.refreshPromiseSessionIdentity, expectedSessionIdentity)
    ) {
      return this.refreshPromise
    }

    const activeRefresh = this.performRefresh(
      operation,
      this.authSession,
      expectedSessionIdentity,
    )
    this.refreshPromise = activeRefresh
    this.refreshPromiseSessionIdentity = expectedSessionIdentity
    try {
      return await activeRefresh
    } finally {
      if (this.refreshPromise === activeRefresh) {
        this.refreshPromise = undefined
        this.refreshPromiseSessionIdentity = undefined
      }
    }
  }

  private async performRefresh(
    operation: string,
    authSession: AuthSession,
    expectedSessionIdentity: unknown,
  ): Promise<string> {
    try {
      const accessToken = await authSession.refreshAccessToken()
      if (!accessToken) {
        throw new Error('刷新响应未返回 access token')
      }
      return accessToken
    } catch (cause) {
      if (cause instanceof SessionSupersededError) {
        throw new SessionExpiredError({ operation }, cause)
      }
      let cleanupCause: unknown
      try {
        await authSession.clearSession(expectedSessionIdentity)
      } catch (error) {
        cleanupCause = error
      }
      throw new SessionExpiredError({ operation }, cause, cleanupCause)
    }
  }

  private async invalidateSession(
    operation: string,
    cause: unknown,
    expectedSessionIdentity?: unknown,
  ): Promise<never> {
    let cleanupCause: unknown
    try {
      await this.authSession?.clearSession(expectedSessionIdentity)
    } catch (error) {
      cleanupCause = error
    }
    throw new SessionExpiredError({ operation }, cause, cleanupCause)
  }

  private getCurrentRequestAccessToken(
    operation: string,
    expectedSessionIdentity: unknown,
  ): string {
    const accessToken = this.authSession?.getAccessToken()
    if (
      !accessToken ||
      !Object.is(this.getSessionIdentity(accessToken), expectedSessionIdentity)
    ) {
      throw new SessionExpiredError({ operation }, new SessionSupersededError())
    }
    return accessToken
  }

  private getPostRefreshAccessToken(
    operation: string,
    expectedSessionIdentity: unknown,
    refreshedAccessToken: string,
  ): string {
    const accessToken = this.authSession?.getAccessToken()
    if (!accessToken) {
      throw new SessionExpiredError({ operation }, new SessionSupersededError())
    }

    if (this.authSession?.getSessionIdentity) {
      if (!Object.is(this.authSession.getSessionIdentity(), expectedSessionIdentity)) {
        throw new SessionExpiredError({ operation }, new SessionSupersededError())
      }
      return accessToken
    }

    // 兼容未实现 identity 的 AuthSession：至少要求当前 Token 仍是刚完成刷新的结果。
    // 正式 SessionManager 提供稳定 identity，因此可以严格区分 refresh 与新登录。
    if (accessToken !== refreshedAccessToken) {
      throw new SessionExpiredError({ operation }, new SessionSupersededError())
    }
    return accessToken
  }

  private getSessionIdentity(accessToken: string | undefined): unknown {
    return this.authSession?.getSessionIdentity?.() ?? accessToken
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
