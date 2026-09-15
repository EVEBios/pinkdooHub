import { useDidShow } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  EligibleOrder,
  PublicTableCode,
  TableSession,
  TableSessionApi,
} from '@/api/endpoints/table_sessions'
import type { WalletApi, WalletPaymentResult } from '@/api/endpoints/wallet'
import {
  createWalletIdempotencyKey,
  getWalletErrorMessage,
  isWalletMutationUnknown,
} from '@/features/wallet'
import { getDefaultWalletApi } from '@/features/wallet/runtime'

import { createTableIntentKey } from './idempotency'
import { nextSessionBoundaryDelay } from './clock'
import { getDefaultTableSessionApi } from './runtime'

export interface TableEntryState {
  readonly status: 'loading' | 'ready' | 'error'
  readonly code: PublicTableCode | null
  readonly session: TableSession | null
  readonly orders: readonly EligibleOrder[]
  readonly errorMessage?: string
  readonly mutation: 'idle' | 'claiming' | 'paying' | 'unknown'
}

const INITIAL_STATE: TableEntryState = {
  status: 'loading',
  code: null,
  session: null,
  orders: [],
  mutation: 'idle',
}

export function useTableEntry(
  qrToken: string,
  authenticated: boolean,
  source: TableSessionApi = getDefaultTableSessionApi(),
  wallet: WalletApi = getDefaultWalletApi(),
) {
  const [state, setState] = useState<TableEntryState>(INITIAL_STATE)
  const sequenceRef = useRef(0)
  const activeRef = useRef<Promise<boolean>>()
  const claimKeyRef = useRef<string>()
  const paymentKeyRef = useRef<string>()

  const refresh = useCallback(async (preserve = false): Promise<void> => {
    const sequence = ++sequenceRef.current
    if (!preserve) setState(INITIAL_STATE)
    try {
      const code = await source.resolveTableCode(qrToken)
      if (sequence !== sequenceRef.current) return
      if (!authenticated) {
        setState({ ...INITIAL_STATE, status: 'ready', code })
        return
      }
      const session = await source.getCurrentSession()
      if (sequence !== sequenceRef.current) return
      if (session) {
        setState({ ...INITIAL_STATE, status: 'ready', code, session })
        return
      }
      const page = await source.listEligibleOrders()
      if (sequence !== sequenceRef.current) return
      setState({ ...INITIAL_STATE, status: 'ready', code, orders: page.items })
    } catch (cause) {
      if (sequence !== sequenceRef.current) return
      setState((current) => ({
        ...(preserve && current.status === 'ready' ? current : INITIAL_STATE),
        status: preserve && current.status === 'ready' ? 'ready' : 'error',
        errorMessage: cause instanceof Error ? cause.message : '桌台状态读取失败',
      }))
    }
  }, [authenticated, qrToken, source])

  useEffect(() => {
    void refresh()
    return () => { sequenceRef.current += 1 }
  }, [refresh])
  useDidShow(() => { void refresh(true) })

  useEffect(() => {
    if (!authenticated || state.status !== 'ready' || !state.session || state.session.status.value === 'closed') return
    const delay = state.session.status.value === 'awaiting_payment' ? 5_000 : 30_000
    const timer = setInterval(() => { void refresh(true) }, delay)
    return () => clearInterval(timer)
  }, [authenticated, refresh, state.session, state.status])

  useEffect(() => {
    if (!authenticated || state.status !== 'ready' || !state.session) return
    const delay = nextSessionBoundaryDelay(state.session)
    if (delay === undefined) return
    const timer = setTimeout(() => { void refresh(true) }, delay)
    return () => clearTimeout(timer)
  }, [authenticated, refresh, state.session, state.status])

  const claim = useCallback((orderId: number): Promise<boolean> => {
    if (activeRef.current) return activeRef.current
    claimKeyRef.current ??= createTableIntentKey('claim')
    const active = (async () => {
      setState((current) => ({ ...current, mutation: 'claiming', errorMessage: undefined }))
      try {
        const session = await source.createSession(qrToken, orderId, claimKeyRef.current!)
        claimKeyRef.current = undefined
        setState((current) => ({ ...current, session, orders: [], mutation: 'idle' }))
        return true
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('开台失败')
        const unknown = isWalletMutationUnknown(error)
        if (!unknown) claimKeyRef.current = undefined
        setState((current) => ({
          ...current,
          mutation: unknown ? 'unknown' : 'idle',
          errorMessage: unknown
            ? '开台结果可能未知，请先刷新当前会话；若仍未开台，可安全重试原操作'
            : error.message,
        }))
        return false
      }
    })()
    activeRef.current = active
    void active.finally(() => {
      if (activeRef.current === active) activeRef.current = undefined
    }).catch(() => undefined)
    return active
  }, [qrToken, source])

  const pay = useCallback((): Promise<boolean> => {
    if (activeRef.current) return activeRef.current
    const session = state.session
    if (!session || session.status.value !== 'awaiting_payment') return Promise.resolve(false)
    paymentKeyRef.current ??= createWalletIdempotencyKey('payment')
    const active = (async () => {
      setState((current) => ({ ...current, mutation: 'paying', errorMessage: undefined }))
      try {
        const result: WalletPaymentResult = await wallet.payOrderWithWallet(
          session.order_id,
          paymentKeyRef.current!,
          session.session_no,
        )
        if (result.order_id !== session.order_id) throw new Error('支付结果与当前订单不一致')
        paymentKeyRef.current = undefined
        await refresh(true)
        return true
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('余额支付失败')
        const unknown = isWalletMutationUnknown(error)
        if (!unknown) paymentKeyRef.current = undefined
        setState((current) => ({
          ...current,
          mutation: unknown ? 'unknown' : 'idle',
          errorMessage: unknown
            ? '支付结果可能未知，请先刷新当前会话；若仍待支付，再使用原操作标识重试'
            : getWalletErrorMessage(error, '余额支付失败'),
        }))
        return false
      }
    })()
    activeRef.current = active
    void active.finally(() => {
      if (activeRef.current === active) activeRef.current = undefined
    }).catch(() => undefined)
    return active
  }, [refresh, state.session, wallet])

  return { state, claim, pay, refresh: () => void refresh() }
}
