export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export type QueryPrimitive = string | number | boolean
export type QueryValue = QueryPrimitive | readonly QueryPrimitive[] | null | undefined

export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
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

export interface AuthSession {
  getAccessToken(): string | undefined
  refreshAccessToken(): Promise<string | undefined>
  clearSession(): void | Promise<void>
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
