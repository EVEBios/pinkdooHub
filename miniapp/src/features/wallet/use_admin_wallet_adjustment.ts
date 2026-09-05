import { useCallback, useRef, useState } from 'react'

import type { WalletAdjustmentResult } from '@/api/endpoints/wallet'

import { createWalletIdempotencyKey, type WalletIdempotencyKeyFactory } from './idempotency'
import { getWalletErrorMessage, isWalletMutationUnknown } from './mutation'
import { getDefaultWalletApi } from './runtime'

export type AdminWalletAdjustmentState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly retrying: boolean }
  | { readonly status: 'succeeded'; readonly result: WalletAdjustmentResult }
  | { readonly status: 'failed' | 'unknown'; readonly errorMessage: string }

export interface AdminWalletAdjustmentSource {
  adjustAdminUserWallet(
    userId: number,
    request: { readonly change: string; readonly reason: string },
    idempotencyKey: string,
  ): Promise<WalletAdjustmentResult>
}

interface PendingAdjustmentIntent {
  readonly userId: number
  readonly request: {
    readonly change: string
    readonly reason: string
  }
  readonly idempotencyKey: string
}

export function useAdminWalletAdjustment(
  userId: number,
  source: AdminWalletAdjustmentSource = getDefaultWalletApi(),
  createKey: WalletIdempotencyKeyFactory = createWalletIdempotencyKey,
) {
  const [state, setState] = useState<AdminWalletAdjustmentState>({ status: 'idle' })
  const activeRef = useRef<Promise<boolean>>()
  const pendingIntentRef = useRef<PendingAdjustmentIntent>()

  const runIntent = useCallback((intent: PendingAdjustmentIntent, retrying: boolean): Promise<boolean> => {
    if (activeRef.current) return activeRef.current
    const active = (async () => {
      setState({ status: 'submitting', retrying })
      try {
        const result = await source.adjustAdminUserWallet(
          intent.userId,
          intent.request,
          intent.idempotencyKey,
        )
        pendingIntentRef.current = undefined
        setState({ status: 'succeeded', result })
        return true
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('余额调整失败')
        const unknown = isWalletMutationUnknown(error)
        if (unknown) pendingIntentRef.current = intent
        else pendingIntentRef.current = undefined
        setState(unknown
          ? {
              status: 'unknown',
              errorMessage: '调整结果可能未知；安全重试会原样复用同一方向、金额、原因和操作标识，系统不会自动重发',
            }
          : { status: 'failed', errorMessage: getWalletErrorMessage(error, '余额调整失败') })
        return false
      }
    })()
    activeRef.current = active
    void active.finally(() => {
      if (activeRef.current === active) activeRef.current = undefined
    }).catch(() => undefined)
    return active
  }, [source])

  const submit = useCallback((change: string, reason: string): Promise<boolean> => {
    if (activeRef.current) return activeRef.current
    if (pendingIntentRef.current) return Promise.resolve(false)
    const intent: PendingAdjustmentIntent = {
      userId,
      request: { change, reason },
      idempotencyKey: createKey('adjustment'),
    }
    pendingIntentRef.current = intent
    return runIntent(intent, false)
  }, [createKey, runIntent, userId])

  const retrySameIntent = useCallback((): Promise<boolean> => {
    if (activeRef.current) return activeRef.current
    const intent = pendingIntentRef.current
    return intent ? runIntent(intent, true) : Promise.resolve(false)
  }, [runIntent])

  return { state, submit, retrySameIntent }
}
