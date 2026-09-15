import { useCallback, useRef, useState } from 'react'

import type { RefundRecord } from '@/api/endpoints/wallet'

import { createWalletIdempotencyKey, type WalletIdempotencyKeyFactory } from './idempotency'
import { getWalletErrorMessage, isWalletMutationUnknown } from './mutation'
import { getDefaultWalletApi } from './runtime'

export type AdminRefundState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting' }
  | { readonly status: 'succeeded'; readonly refund: RefundRecord }
  | { readonly status: 'failed' | 'unknown'; readonly errorMessage: string }

export interface AdminRefundSource {
  refundAdminOrder(orderId: number, reason: string, idempotencyKey: string): Promise<RefundRecord>
}

export function useAdminRefund(
  orderId: number,
  source: AdminRefundSource = getDefaultWalletApi(),
  createKey: WalletIdempotencyKeyFactory = createWalletIdempotencyKey,
) {
  const [state, setState] = useState<AdminRefundState>({ status: 'idle' })
  const activeRef = useRef<Promise<boolean>>()
  const intentRef = useRef<{ reason: string; key: string }>()
  const submit = useCallback((reason: string): Promise<boolean> => {
    if (activeRef.current) return activeRef.current
    const previous = intentRef.current
    const intent = previous && previous.reason === reason
      ? previous
      : { reason, key: createKey('refund') }
    intentRef.current = intent
    const active = (async () => {
      setState({ status: 'submitting' })
      try {
        const refund = await source.refundAdminOrder(orderId, intent.reason, intent.key)
        intentRef.current = undefined
        setState({ status: 'succeeded', refund })
        return true
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('退款失败')
        const unknown = isWalletMutationUnknown(error)
        if (!unknown) intentRef.current = undefined
        setState(unknown
          ? { status: 'unknown', errorMessage: '退款结果可能未知；再次提交相同原因会复用原操作标识' }
          : { status: 'failed', errorMessage: getWalletErrorMessage(error, '退款失败') })
        return false
      }
    })()
    activeRef.current = active
    void active.finally(() => {
      if (activeRef.current === active) activeRef.current = undefined
    }).catch(() => undefined)
    return active
  }, [createKey, orderId, source])
  return { state, submit }
}
