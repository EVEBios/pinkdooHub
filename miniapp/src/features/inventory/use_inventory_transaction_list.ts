import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  GlobalInventoryTransactionRequest,
  InventoryTransaction,
  InventoryTransactionPage,
  ProductInventoryTransactionRequest,
} from '@/api/endpoints/inventory'

import {
  buildGlobalInventoryRequest,
  buildProductInventoryRequest,
  EMPTY_INVENTORY_FILTERS,
  type InventoryFilters,
} from './inventory_filters'
import { getDefaultInventoryApi } from './runtime'

export type InventoryTransactionScope =
  | { readonly kind: 'global' }
  | { readonly kind: 'product'; readonly productId: number }

export interface InventoryTransactionListSource {
  listProductTransactions(
    productId: number,
    request?: ProductInventoryTransactionRequest,
  ): Promise<InventoryTransactionPage>
  listTransactions(request?: GlobalInventoryTransactionRequest): Promise<InventoryTransactionPage>
}

export interface InventoryTransactionListState {
  readonly status: 'loading' | 'empty' | 'error' | 'content'
  readonly items: readonly InventoryTransaction[]
  readonly total: number
  readonly page: number
  readonly pages: number
  readonly loadingMore: boolean
  readonly errorMessage?: string
}

const INITIAL_STATE: InventoryTransactionListState = {
  status: 'loading',
  items: [],
  total: 0,
  page: 1,
  pages: 0,
  loadingMore: false,
}

export function useInventoryTransactionList(
  scope: InventoryTransactionScope,
  source: InventoryTransactionListSource = getDefaultInventoryApi(),
) {
  const [filters, setFilters] = useState<InventoryFilters>(EMPTY_INVENTORY_FILTERS)
  const [state, setState] = useState<InventoryTransactionListState>(INITIAL_STATE)
  const sequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)
  const productId = scope.kind === 'product' ? scope.productId : undefined

  const loadPage = useCallback((page: number) => productId === undefined
    ? source.listTransactions(buildGlobalInventoryRequest(filters, page))
    : source.listProductTransactions(
        productId,
        buildProductInventoryRequest(filters, page),
      ), [filters, productId, source])

  const loadFirstPage = useCallback(() => {
    const sequence = ++sequenceRef.current
    loadingMoreRef.current = false
    setState(INITIAL_STATE)
    void loadPage(1).then((page) => {
      if (sequence !== sequenceRef.current) return
      setState({
        status: page.items.length === 0 ? 'empty' : 'content',
        items: page.items,
        total: page.total,
        page: page.page,
        pages: page.pages,
        loadingMore: false,
      })
    }).catch((cause: unknown) => {
      if (sequence === sequenceRef.current) {
        setState({ ...INITIAL_STATE, status: 'error', errorMessage: toMessage(cause, '库存流水加载失败') })
      }
    })
  }, [loadPage])

  const loadNextPage = useCallback(() => {
    if (state.status !== 'content' || state.page >= state.pages || loadingMoreRef.current) return
    loadingMoreRef.current = true
    const sequence = ++sequenceRef.current
    setState((current) => ({ ...current, loadingMore: true, errorMessage: undefined }))
    void loadPage(state.page + 1).then((page) => {
      if (sequence !== sequenceRef.current) return
      setState((current) => ({
        status: 'content',
        items: [...current.items, ...page.items],
        total: page.total,
        page: page.page,
        pages: page.pages,
        loadingMore: false,
      }))
    }).catch((cause: unknown) => {
      if (sequence === sequenceRef.current) {
        setState((current) => ({ ...current, loadingMore: false, errorMessage: toMessage(cause, '更多库存流水加载失败') }))
      }
    }).finally(() => {
      if (sequence === sequenceRef.current) loadingMoreRef.current = false
    })
  }, [loadPage, state.page, state.pages, state.status])

  useEffect(() => {
    loadFirstPage()
    return () => { sequenceRef.current += 1 }
  }, [loadFirstPage])

  return { filters, state, applyFilters: setFilters, retry: loadFirstPage, loadNextPage }
}

function toMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}
