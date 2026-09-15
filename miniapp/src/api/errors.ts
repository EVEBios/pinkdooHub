export interface ErrorContext {
  operation: string
  statusCode?: number
}

export class ApiClientError extends Error {
  readonly operation: string
  readonly statusCode?: number

  constructor(name: string, message: string, context: ErrorContext) {
    super(message)
    this.name = name
    this.operation = context.operation
    this.statusCode = context.statusCode
  }
}

export class NetworkError extends ApiClientError {
  readonly cause: unknown

  constructor(context: ErrorContext, cause: unknown) {
    super('NetworkError', '网络请求失败，请检查连接后重试', context)
    this.cause = cause
  }
}

export class TimeoutError extends ApiClientError {
  readonly cause: unknown

  constructor(context: ErrorContext, cause: unknown) {
    super('TimeoutError', '请求超时，操作结果可能未知', context)
    this.cause = cause
  }
}

export class RequestCancelledError extends ApiClientError {
  constructor(context: ErrorContext) {
    super('RequestCancelledError', '请求已取消', context)
  }
}

export class HttpError extends ApiClientError {
  readonly responseData: unknown

  constructor(context: Required<ErrorContext>, responseData: unknown) {
    super('HttpError', `HTTP 请求失败（${context.statusCode}）`, context)
    this.responseData = responseData
  }
}

export class BusinessError extends ApiClientError {
  readonly code: number
  readonly data: unknown

  constructor(
    context: Required<ErrorContext>,
    code: number,
    message: string,
    data: unknown,
  ) {
    super('BusinessError', message, context)
    this.code = code
    this.data = data
  }
}

export class ContractError extends ApiClientError {
  constructor(context: ErrorContext) {
    super('ContractError', '服务端响应不符合 API 契约', context)
  }
}

export class SessionExpiredError extends ApiClientError {
  readonly cause: unknown
  readonly cleanupCause?: unknown

  constructor(context: ErrorContext, cause: unknown, cleanupCause?: unknown) {
    super('SessionExpiredError', '登录状态已失效，请重新登录', context)
    this.cause = cause
    this.cleanupCause = cleanupCause
  }
}

/**
 * 标记请求期间会话已被退出或新登录取代。
 * 这不等于“当前会话刷新失败”，调用方不得因此清除更新的身份。
 */
export class SessionSupersededError extends Error {
  constructor() {
    super('请求期间登录会话已发生变化')
    this.name = 'SessionSupersededError'
  }
}
