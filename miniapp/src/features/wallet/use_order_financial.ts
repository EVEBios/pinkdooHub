import { useCallback, useEffect, useRef, useState } from 'react'

import type { OrderFinancial } from '@/api/endpoints/wallet'

import { getWalletErrorMessage } from './mutation'
import { getDefaultWalletApi } from './runtime'

export type OrderFinancialState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | { readonly status: 'content'; readonly financial: OrderFinancial }

export interface OrderFinancialSource {
  getOrderFinancials(orderId: number): Promise<OrderFinancial>
  getAdminOrderFinancials(orderId: number): Promise<OrderFinancial>
}

export function useOrderFinancial(
  orderId: number,
  admin = false,
  source: OrderFinancialSource = getDefaultWalletApi(),
) {
  const [state, setState] = useState<OrderFinancialState>({ status: 'loading' })
  const sequenceRef = useRef(0)
  const load = useCallback(() => {
    const sequence = ++sequenceRef.current
    setState({ status: 'loading' })
    const request = admin ? source.getAdminOrderFinancials(orderId) : source.getOrderFinancials(orderId)
    void request.then((financial) => {
      if (sequence === sequenceRef.current) setState({ status: 'content', financial })
    }).catch((cause: unknown) => {
      if (sequence !== sequenceRef.current) return
      const error = cause instanceof Error ? cause : new Error('订单资金状态加载失败')
      setState({ status: 'error', errorMessage: getWalletErrorMessage(error, '订单资金状态加载失败') })
    })
  }, [admin, orderId, source])

  useEffect(() => {
    load()
    return () => { sequenceRef.current += 1 }
  }, [load])
  return { state, retry: load }
}
