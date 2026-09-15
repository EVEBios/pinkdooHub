import { useCallback, useRef, useState } from 'react'

import type { WalletPaymentResult } from '@/api/endpoints/wallet'

import { createWalletIdempotencyKey, type WalletIdempotencyKeyFactory } from './idempotency'
import { getWalletErrorMessage, isWalletMutationUnknown } from './mutation'
import { getDefaultWalletApi } from './runtime'

export type OrderPaymentState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting' }
  | { readonly status: 'succeeded'; readonly result: WalletPaymentResult }
  | { readonly status: 'failed' | 'unknown'; readonly errorMessage: string }

export interface OrderPaymentSource {
  payOrderWithWallet(orderId: number, idempotencyKey: string): Promise<WalletPaymentResult>
}

export function useOrderPayment(
  orderId: number,
  source: OrderPaymentSource = getDefaultWalletApi(),
  createKey: WalletIdempotencyKeyFactory = createWalletIdempotencyKey,
) {
  const [state, setState] = useState<OrderPaymentState>({ status: 'idle' })
  const activeRef = useRef<Promise<boolean>>()
  const keyRef = useRef<string>()

  const payWithWallet = useCallback((): Promise<boolean> => {
    if (activeRef.current) return activeRef.current
    keyRef.current ??= createKey('payment')
    const key = keyRef.current
    const active = (async () => {
      setState({ status: 'submitting' })
      try {
        const result = await source.payOrderWithWallet(orderId, key)
        keyRef.current = undefined
        setState({ status: 'succeeded', result })
        return true
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('余额支付失败')
        const unknown = isWalletMutationUnknown(error)
        if (!unknown) keyRef.current = undefined
        setState(unknown
          ? { status: 'unknown', errorMessage: '支付结果可能未知，请重新读取订单资金状态后再操作' }
          : { status: 'failed', errorMessage: getWalletErrorMessage(error, '余额支付失败') })
        return false
      }
    })()
    activeRef.current = active
    void active.finally(() => {
      if (activeRef.current === active) activeRef.current = undefined
    }).catch(() => undefined)
    return active
  }, [createKey, orderId, source])

  const reset = useCallback(() => {
    if (!activeRef.current) setState({ status: 'idle' })
  }, [])
  return { state, payWithWallet, reset }
}
