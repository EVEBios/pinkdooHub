import {
  ContractError,
  HttpError,
  NetworkError,
  RequestCancelledError,
  TimeoutError,
} from '@/api'
import type { OrderCreateRequest, OrderDetail } from '@/api/endpoints/orders'

import {
  buildOrderItems,
  type CartItem,
  type CartReconciliationResult,
} from './cart'

export const ORDER_REMARK_LIMIT = 500

export interface OrderCreator {
  createOrder(request: OrderCreateRequest): Promise<OrderDetail>
}

export interface CartSubmissionReconciler {
  reconcileSubmittedItems(items: readonly CartItem[]): Promise<CartReconciliationResult>
}

interface SubmissionSnapshot {
  readonly submittedItems: readonly CartItem[]
  readonly request: OrderCreateRequest
}

export type OrderSubmissionState =
  | { readonly status: 'idle' }
  | ({ readonly status: 'submitting' } & SubmissionSnapshot)
  | ({
      readonly status: 'succeeded'
      readonly order: OrderDetail
      readonly cartReconciliation?: CartReconciliationResult
      readonly cartReconciliationError?: Error
    } & SubmissionSnapshot)
  | ({ readonly status: 'failed'; readonly error: Error } & SubmissionSnapshot)
  | ({ readonly status: 'unknown'; readonly error: OrderSubmissionUnknownError } & SubmissionSnapshot)

export type OrderSubmissionUnknownError =
  | NetworkError
  | TimeoutError
  | RequestCancelledError
  | ContractError
  | HttpError

export type OrderSubmissionListener = (state: OrderSubmissionState) => void

export class OrderSubmissionValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'OrderSubmissionValidationError'
  }
}

export class OrderSubmissionStore {
  private state: OrderSubmissionState = { status: 'idle' }
  private readonly listeners = new Set<OrderSubmissionListener>()
  private activeSubmission?: Promise<void>

  constructor(
    private readonly orderCreator: OrderCreator,
    private readonly cartReconciler?: CartSubmissionReconciler,
  ) {}

  getState(): OrderSubmissionState {
    return copyState(this.state)
  }

  subscribe(listener: OrderSubmissionListener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  submit(items: readonly CartItem[], remark?: string | null): Promise<void> {
    if (this.activeSubmission) {
      return this.activeSubmission
    }

    const snapshot = buildSubmissionSnapshot(items, remark)
    const submission = this.performSubmission(snapshot)
    this.activeSubmission = submission
    void submission.finally(() => {
      if (this.activeSubmission === submission) {
        this.activeSubmission = undefined
      }
    }).catch(() => undefined)
    return submission
  }

  reset(): void {
    if (this.activeSubmission) {
      return
    }
    this.setState({ status: 'idle' })
  }

  private async performSubmission(snapshot: SubmissionSnapshot): Promise<void> {
    this.setState({ status: 'submitting', ...snapshot })
    try {
      const order = await this.orderCreator.createOrder(snapshot.request)
      let cartReconciliation: CartReconciliationResult | undefined
      let cartReconciliationError: Error | undefined
      try {
        cartReconciliation = await this.cartReconciler?.reconcileSubmittedItems(
          snapshot.submittedItems,
        )
      } catch (cause) {
        // Order 已由服务端创建成功；本地清理失败只能作为成功结果的附加警告。
        cartReconciliationError = toError(cause)
      }
      this.setState({
        status: 'succeeded',
        ...snapshot,
        order,
        cartReconciliation,
        cartReconciliationError,
      })
    } catch (cause) {
      const error = toError(cause)
      this.setState(isOrderCommandUnknownError(error)
        ? { status: 'unknown', ...snapshot, error }
        : { status: 'failed', ...snapshot, error })
    }
  }

  private setState(state: OrderSubmissionState): void {
    this.state = copyState(state)
    const snapshot = this.getState()
    this.listeners.forEach((listener) => listener(snapshot))
  }
}

export function normalizeOrderRemark(remark?: string | null): string | undefined {
  if (remark === undefined || remark === null) {
    return undefined
  }
  const normalized = remark.trim()
  if (normalized.length === 0) {
    return undefined
  }
  if (normalized.length > ORDER_REMARK_LIMIT) {
    throw new OrderSubmissionValidationError(`订单备注最多 ${ORDER_REMARK_LIMIT} 个字符`)
  }
  return normalized
}

function buildSubmissionSnapshot(
  items: readonly CartItem[],
  remark?: string | null,
): SubmissionSnapshot {
  if (items.length < 1 || items.length > 10) {
    throw new OrderSubmissionValidationError('购物清单必须包含 1 至 10 种商品配置')
  }
  const submittedItems = items.map((item) => ({ ...item }))
  const normalizedRemark = normalizeOrderRemark(remark)
  const request: OrderCreateRequest = {
    items: buildOrderItems(submittedItems),
    ...(normalizedRemark === undefined ? {} : { remark: normalizedRemark }),
  }
  return { submittedItems, request }
}

function copyState(state: OrderSubmissionState): OrderSubmissionState {
  if (state.status === 'idle') {
    return state
  }
  const snapshot = {
    submittedItems: state.submittedItems.map((item) => ({ ...item })),
    request: {
      ...state.request,
      items: state.request.items.map((item) => ({ ...item })),
    },
  }
  if (state.status === 'succeeded') {
    return {
      status: state.status,
      ...snapshot,
      order: state.order,
      cartReconciliation: state.cartReconciliation && {
        ...state.cartReconciliation,
        preservedItemKeys: [...state.cartReconciliation.preservedItemKeys],
      },
      cartReconciliationError: state.cartReconciliationError,
    }
  }
  if (state.status === 'failed') {
    return { status: state.status, ...snapshot, error: state.error }
  }
  if (state.status === 'unknown') {
    return { status: state.status, ...snapshot, error: state.error }
  }
  return { status: state.status, ...snapshot }
}

export function isOrderCommandUnknownError(error: Error): error is OrderSubmissionUnknownError {
  return error instanceof NetworkError ||
    error instanceof TimeoutError ||
    error instanceof RequestCancelledError ||
    error instanceof ContractError ||
    (error instanceof HttpError && (error.statusCode ?? 0) >= 500)
}

function toError(cause: unknown): Error {
  return cause instanceof Error ? cause : new Error('创建订单失败')
}
