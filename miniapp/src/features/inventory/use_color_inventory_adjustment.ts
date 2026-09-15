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
  InventoryColorAdjustmentResult,
} from '@/api/endpoints/inventory'

import {
  createInventoryIdempotencyKey,
  type InventoryIdempotencyKeyFactory,
} from './idempotency'
import { getDefaultInventoryApi } from './runtime'

export type ColorInventoryAdjustmentState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly retrying: boolean }
  | { readonly status: 'created' | 'replayed'; readonly result: InventoryColorAdjustmentResult }
  | { readonly status: 'failed'; readonly errorMessage: string }
  | { readonly status: 'unknown'; readonly errorMessage: string }

export interface ColorInventoryAdjustmentSource {
  adjustColorStock(
    productId: number,
    kitColorId: number,
    request: InventoryAdjustmentRequest,
    idempotencyKey: string,
  ): Promise<InventoryColorAdjustmentResult>
}

interface PendingColorIntent {
  readonly productId: number
  readonly kitColorId: number
  readonly request: InventoryAdjustmentRequest
  readonly idempotencyKey: string
}

export function useColorInventoryAdjustment(
  source: ColorInventoryAdjustmentSource = getDefaultInventoryApi(),
  createKey: InventoryIdempotencyKeyFactory = createInventoryIdempotencyKey,
) {
  const [state, setState] = useState<ColorInventoryAdjustmentState>({ status: 'idle' })
  const pendingIntentRef = useRef<PendingColorIntent>()
  const activeRef = useRef<Promise<InventoryColorAdjustmentResult | undefined>>()

  const runIntent = useCallback((intent: PendingColorIntent, retrying: boolean) => {
    if (activeRef.current) return activeRef.current
    const active = (async () => {
      setState({ status: 'submitting', retrying })
      try {
        const result = await source.adjustColorStock(
          intent.productId,
          intent.kitColorId,
          intent.request,
          intent.idempotencyKey,
        )
        pendingIntentRef.current = undefined
        setState({ status: result.disposition, result })
        return result
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('颜色库存调整失败')
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

  const adjustColorStock = useCallback((
    productId: number,
    kitColorId: number,
    request: InventoryAdjustmentRequest,
  ): Promise<InventoryColorAdjustmentResult | undefined> => {
    if (activeRef.current) return activeRef.current
    if (pendingIntentRef.current) return Promise.resolve(undefined)
    const intent: PendingColorIntent = {
      productId,
      kitColorId,
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

  return { state, adjustColorStock, retrySameIntent, reset }
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
    if (error.code === 40932) return '调整后颜色库存超出 0 至 999999 个 10g 单位的允许范围'
    if (error.code === 40933) return '本次幂等键与另一条已提交请求冲突，请重新发起调整'
    if (error.code === 40903) return '商品已删除，不能调整库存'
    if (error.code === 40001 || error.code === 40031) return '目标商品或库存形态不匹配'
    if (error.code === 40401 || error.code === 40404 || error.code === 40406) return '商品颜色或库存扩展不存在'
  }
  if (error instanceof SessionExpiredError) return '登录状态已失效，请重新登录'
  if (error instanceof ApiClientError && error.message) return error.message
  return '颜色库存调整失败，请检查输入后重试'
}
