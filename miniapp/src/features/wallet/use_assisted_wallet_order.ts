import { useCallback, useRef, useState } from 'react'

import type { OrderCreateRequest } from '@/api/endpoints/orders'
import type { AssistedWalletOrderResult } from '@/api/endpoints/wallet'

import { createWalletIdempotencyKey, type WalletIdempotencyKeyFactory } from './idempotency'
import { getWalletErrorMessage, isWalletMutationUnknown } from './mutation'
import { getDefaultWalletApi } from './runtime'

export type AssistedWalletOrderState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly retrying: boolean }
  | { readonly status: 'succeeded'; readonly result: AssistedWalletOrderResult }
  | { readonly status: 'failed' | 'unknown'; readonly errorMessage: string }

export interface AssistedWalletOrderSource {
  createAssistedWalletOrder(
    userId: number,
    request: OrderCreateRequest,
    idempotencyKey: string,
  ): Promise<AssistedWalletOrderResult>
}

interface PendingIntent {
  readonly request: OrderCreateRequest
  readonly idempotencyKey: string
}

export function useAssistedWalletOrder(
  userId: number,
  source: AssistedWalletOrderSource = getDefaultWalletApi(),
  createKey: WalletIdempotencyKeyFactory = createWalletIdempotencyKey,
) {
  const [state, setState] = useState<AssistedWalletOrderState>({ status: 'idle' })
  const pendingIntentRef = useRef<PendingIntent>()
  const activeRef = useRef<Promise<AssistedWalletOrderResult | undefined>>()

  const runIntent = useCallback((intent: PendingIntent, retrying: boolean) => {
    if (activeRef.current) return activeRef.current
    const active = (async () => {
      setState({ status: 'submitting', retrying })
      try {
        const result = await source.createAssistedWalletOrder(
          userId,
          intent.request,
          intent.idempotencyKey,
        )
        pendingIntentRef.current = undefined
        setState({ status: 'succeeded', result })
        return result
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('代客钱包订单创建失败')
        if (isWalletMutationUnknown(error)) {
          pendingIntentRef.current = intent
          setState({
            status: 'unknown',
            errorMessage: '扣款结果可能未知；安全重试会原样复用同一订单内容与操作标识，系统不会自动重发',
          })
        } else {
          pendingIntentRef.current = undefined
          setState({ status: 'failed', errorMessage: getWalletErrorMessage(error, '代客钱包订单创建失败') })
        }
        return undefined
      }
    })()
    activeRef.current = active
    void active.finally(() => {
      if (activeRef.current === active) activeRef.current = undefined
    }).catch(() => undefined)
    return active
  }, [source, userId])

  const createOrder = useCallback((request: OrderCreateRequest) => {
    if (activeRef.current) return activeRef.current
    if (pendingIntentRef.current) return Promise.resolve(undefined)
    const intent: PendingIntent = {
      request: copyRequest(request),
      idempotencyKey: createKey('assisted-order'),
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

  return { state, createOrder, retrySameIntent, reset }
}

function copyRequest(request: OrderCreateRequest): OrderCreateRequest {
  const remark = request.remark?.trim()
  return {
    items: request.items.map((item) => ({
      product_id: item.product_id,
      quantity: item.quantity,
      ...(item.experience_option_id === undefined || item.experience_option_id === null
        ? {}
        : { experience_option_id: item.experience_option_id }),
    })),
    ...(remark ? { remark } : {}),
  }
}
