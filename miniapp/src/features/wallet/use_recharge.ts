import { useCallback, useRef, useState } from 'react'

import { createWalletIdempotencyKey, type WalletIdempotencyKeyFactory } from './idempotency'
import { getWalletErrorMessage, isWalletMutationUnknown } from './mutation'
import { getDefaultWalletApi } from './runtime'

export type RechargeState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting' }
  | { readonly status: 'succeeded' }
  | { readonly status: 'failed' | 'unknown'; readonly errorMessage: string }

export interface RechargeSource {
  createRecharge(amount: string, idempotencyKey: string): Promise<void>
}

export function useRecharge(
  source: RechargeSource = getDefaultWalletApi(),
  createKey: WalletIdempotencyKeyFactory = createWalletIdempotencyKey,
) {
  const [state, setState] = useState<RechargeState>({ status: 'idle' })
  const activeRef = useRef<Promise<boolean>>()
  const keyRef = useRef<string>()
  const submit = useCallback((amount: string): Promise<boolean> => {
    if (activeRef.current) return activeRef.current
    keyRef.current ??= createKey('recharge')
    const key = keyRef.current
    const active = (async () => {
      setState({ status: 'submitting' })
      try {
        await source.createRecharge(amount, key)
        keyRef.current = undefined
        setState({ status: 'succeeded' })
        return true
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('充值请求失败')
        const unknown = isWalletMutationUnknown(error)
        if (!unknown) keyRef.current = undefined
        setState(unknown
          ? { status: 'unknown', errorMessage: '充值结果可能未知，请先核对资金明细，不要重复提交' }
          : { status: 'failed', errorMessage: getWalletErrorMessage(error, '充值请求失败') })
        return false
      }
    })()
    activeRef.current = active
    void active.finally(() => {
      if (activeRef.current === active) activeRef.current = undefined
    }).catch(() => undefined)
    return active
  }, [createKey, source])
  return { state, submit }
}
