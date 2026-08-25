import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  OrderListItem,
  OrderListPage,
  OrderListRequest,
} from '@/api/endpoints/orders'

import { getDefaultOrderApi } from './runtime'

const ORDER_LIST_PAGE_SIZE = 20

export type OrderStatusFilter = 'all' | NonNullable<OrderListRequest['status']>
export type OrderListStatus = 'loading' | 'empty' | 'error' | 'content'

export interface OrderListState {
  readonly status: OrderListStatus
  readonly items: readonly OrderListItem[]
  readonly total: number
  readonly page: number
  readonly pages: number
  readonly loadingMore: boolean
  readonly errorMessage?: string
}

export interface OrderListSource {
  listOrders(request?: OrderListRequest): Promise<OrderListPage>
}

export interface OrderListFeature {
  readonly state: OrderListState
  readonly statusFilter: OrderStatusFilter
  setStatusFilter(status: OrderStatusFilter): void
  retry(): void
  loadNextPage(): void
}

const initialState: OrderListState = {
  status: 'loading',
  items: [],
  total: 0,
  page: 1,
  pages: 0,
  loadingMore: false,
}

export function useOrderList(source: OrderListSource = getDefaultOrderApi()): OrderListFeature {
  const [state, setState] = useState<OrderListState>(initialState)
  const [statusFilter, setStatusFilter] = useState<OrderStatusFilter>('all')
  const requestSequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)

  const loadFirstPage = useCallback(() => {
    const sequence = ++requestSequenceRef.current
    loadingMoreRef.current = false
    setState(initialState)
    void source.listOrders(buildRequest(statusFilter, 1)).then((page) => {
      if (sequence !== requestSequenceRef.current) {
        return
      }
      setState({
        status: page.items.length === 0 ? 'empty' : 'content',
        items: page.items,
        total: page.total,
        page: page.page,
        pages: page.pages,
        loadingMore: false,
      })
    }).catch((cause: unknown) => {
      if (sequence !== requestSequenceRef.current) {
        return
      }
      setState({ ...initialState, status: 'error', errorMessage: toMessage(cause, '订单加载失败') })
    })
  }, [source, statusFilter])

  const loadNextPage = useCallback(() => {
    if (state.status !== 'content' || state.page >= state.pages || loadingMoreRef.current) {
      return
    }
    loadingMoreRef.current = true
    const sequence = ++requestSequenceRef.current
    setState((current) => ({ ...current, loadingMore: true, errorMessage: undefined }))
    void source.listOrders(buildRequest(statusFilter, state.page + 1)).then((page) => {
      if (sequence !== requestSequenceRef.current) {
        return
      }
      setState((current) => ({
        status: 'content',
        items: [...current.items, ...page.items],
        total: page.total,
        page: page.page,
        pages: page.pages,
        loadingMore: false,
      }))
    }).catch((cause: unknown) => {
      if (sequence !== requestSequenceRef.current) {
        return
      }
      setState((current) => ({
        ...current,
        loadingMore: false,
        errorMessage: toMessage(cause, '更多订单加载失败'),
      }))
    }).finally(() => {
      if (sequence === requestSequenceRef.current) {
        loadingMoreRef.current = false
      }
    })
  }, [source, state.page, state.pages, state.status, statusFilter])

  useEffect(() => {
    loadFirstPage()
    return () => {
      requestSequenceRef.current += 1
    }
  }, [loadFirstPage])

  return { state, statusFilter, setStatusFilter, retry: loadFirstPage, loadNextPage }
}

function buildRequest(status: OrderStatusFilter, page: number): OrderListRequest {
  return {
    page,
    page_size: ORDER_LIST_PAGE_SIZE,
    ...(status === 'all' ? {} : { status }),
  }
}

function toMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}
