import { useCallback, useEffect, useRef, useState } from 'react'

import type { CartItem } from './cart'
import { getDefaultCartRuntime, getDefaultOrderCreator } from './runtime'
import {
  type OrderCreator,
  type OrderSubmissionState,
  OrderSubmissionStore,
} from './submission'

export interface UseOrderSubmissionResult {
  readonly state: OrderSubmissionState
  submit(items: readonly CartItem[], remark?: string | null): Promise<void>
  reset(): void
}

export function useOrderSubmission(orderCreator?: OrderCreator): UseOrderSubmissionResult {
  const storeRef = useRef<OrderSubmissionStore>()
  storeRef.current ??= new OrderSubmissionStore(
    orderCreator ?? getDefaultOrderCreator(),
    getDefaultCartRuntime().store,
  )
  const store = storeRef.current
  const [state, setState] = useState<OrderSubmissionState>(store.getState())

  useEffect(() => store.subscribe(setState), [store])

  const submit = useCallback((items: readonly CartItem[], remark?: string | null) => (
    store.submit(items, remark)
  ), [store])
  const reset = useCallback(() => store.reset(), [store])

  return { state, submit, reset }
}
