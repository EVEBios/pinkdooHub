import { useCallback, useRef, useState } from 'react'

import {
  ApiClientError,
  BusinessError,
  ContractError,
  HttpError,
  NetworkError,
  RequestCancelledError,
  SessionExpiredError,
  TimeoutError,
} from '@/api'
import type {
  InventoryAdjustmentRequest,
  InventoryAdjustmentResult,
} from '@/api/endpoints/inventory'

import {
  createInventoryIdempotencyKey,
  type InventoryIdempotencyKeyFactory,
} from './idempotency'
import { getDefaultInventoryApi } from './runtime'

export type InventoryAdjustmentState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly retrying: boolean }
  | { readonly status: 'created' | 'replayed'; readonly result: InventoryAdjustmentResult }
  | { readonly status: 'failed'; readonly errorMessage: string }
  | { readonly status: 'unknown'; readonly errorMessage: string }

export interface InventoryAdjustmentSource {
  adjustStock(
    productId: number,
    request: InventoryAdjustmentRequest,
    idempotencyKey: string,
  ): Promise<InventoryAdjustmentResult>
}

interface PendingIntent {
  readonly productId: number
  readonly request: InventoryAdjustmentRequest
  readonly idempotencyKey: string
}

export function useInventoryAdjustment(
  source: InventoryAdjustmentSource = getDefaultInventoryApi(),
  createKey: InventoryIdempotencyKeyFactory = createInventoryIdempotencyKey,
) {
  const [state, setState] = useState<InventoryAdjustmentState>({ status: 'idle' })
  const pendingIntentRef = useRef<PendingIntent>()
  const activeRef = useRef<Promise<InventoryAdjustmentResult | undefined>>()

  const runIntent = useCallback((intent: PendingIntent, retrying: boolean) => {
    if (activeRef.current) return activeRef.current
    const active = (async () => {
      setState({ status: 'submitting', retrying })
      try {
        const result = await source.adjustStock(
          intent.productId,
          intent.request,
          intent.idempotencyKey,
        )
        pendingIntentRef.current = undefined
        setState({ status: result.disposition, result })
        return result
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('库存调整失败')
        if (isUnknown(error)) {
          pendingIntentRef.current = intent
          setState({
            status: 'unknown',
            errorMessage: '调整结果可能未知；安全重试会复用同一个幂等键，系统不会自动重发',
          })
        } else {
          pendingIntentRef.current = undefined
          setState({ status: 'failed', errorMessage: getMessage(error) })
        }
        return undefined
      }
    })()
    activeRef.current = active
    void active.finally(() => {
      if (activeRef.current === active) activeRef.current = undefined
    }).catch(() => undefined)
    return active
  }, [source])

  const adjustStock = useCallback((
    productId: number,
    request: InventoryAdjustmentRequest,
  ): Promise<InventoryAdjustmentResult | undefined> => {
    if (activeRef.current) return activeRef.current
    if (pendingIntentRef.current) return Promise.resolve(undefined)
    const intent: PendingIntent = {
      productId,
      request: { change: request.change, reason: request.reason.trim() },
      idempotencyKey: createKey(),
    }
    return runIntent(intent, false)
  }, [createKey, runIntent])

  const retrySameIntent = useCallback(() => {
    if (activeRef.current) return activeRef.current
    const intent = pendingIntentRef.current
    return intent ? runIntent(intent, true) : Promise.resolve(undefined)
  }, [runIntent])

  const reset = useCallback(() => {
    if (!activeRef.current && !pendingIntentRef.current) setState({ status: 'idle' })
  }, [])

  return { state, adjustStock, retrySameIntent, reset }
}

function isUnknown(error: Error): boolean {
  return error instanceof NetworkError ||
    error instanceof TimeoutError ||
    error instanceof RequestCancelledError ||
    error instanceof ContractError ||
    (error instanceof HttpError && (error.statusCode ?? 0) >= 500)
}

function getMessage(error: Error): string {
  if (error instanceof BusinessError) {
    if (error.code === 40932) return '调整后库存超出 0 至 999999 的允许范围'
    if (error.code === 40933) return '本次幂等键与另一条已提交请求冲突，请重新发起调整'
    if (error.code === 40903) return '商品已删除，不能调整库存'
    if (error.code === 40001) return '目标商品不是 Kit'
    if (error.code === 40401 || error.code === 40404) return 'Kit 商品或库存扩展不存在'
  }
  if (error instanceof SessionExpiredError) return '登录状态已失效，请重新登录'
  if (error instanceof ApiClientError && error.message) return error.message
  return '库存调整失败，请检查输入后重试'
}
