export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export type QueryPrimitive = string | number | boolean
export type QueryValue = QueryPrimitive | readonly QueryPrimitive[] | null | undefined

export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

export interface ApiResponse<T> {
  data: T
  statusCode: number
}

export interface TransportRequest {
  operation: string
  url: string
  method: HttpMethod
  headers: Record<string, string>
  body?: unknown
  timeoutMs: number
  signal?: AbortSignal
}

export interface TransportResponse {
  statusCode: number
  data: unknown
  headers: Record<string, unknown>
}

export interface HttpTransport {
  request(request: TransportRequest): Promise<TransportResponse>
}

export interface FileUploadTransportRequest {
  operation: string
  url: string
  filePath: string
  name: string
  headers: Record<string, string>
  formData: Record<string, string>
  timeoutMs: number
  signal?: AbortSignal
}

export interface FileUploadTransport {
  upload(request: FileUploadTransportRequest): Promise<TransportResponse>
}

export interface AuthSession {
  getAccessToken(): string | undefined
  /** 同一登录周期内保持不变的身份；Token refresh 不改变，退出/新登录改变。 */
  getSessionIdentity?(): unknown
  refreshAccessToken(): Promise<string | undefined>
  /** 传入身份时只清除仍属于该请求的会话，避免迟到响应清除新登录。 */
  clearSession(expectedSessionIdentity?: unknown): void | Promise<void>
}

export type AuthMode = 'none' | 'optional' | 'required'

export interface ApiRequestOptions {
  operation: string
  path: string
  method?: HttpMethod
  query?: Readonly<Record<string, QueryValue>>
  body?: unknown
  headers?: Readonly<Record<string, string>>
  auth?: AuthMode
  timeoutMs?: number
  signal?: AbortSignal
}

export interface ApiFileUploadOptions {
  operation: string
  path: string
  filePath: string
  name?: string
  formData?: Readonly<Record<string, string>>
  headers?: Readonly<Record<string, string>>
  auth?: AuthMode
  timeoutMs?: number
  signal?: AbortSignal
}
