import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  Reservation,
  ReservationListRequest,
  ReservationPage,
  ReservationStatus,
} from '@/api/endpoints/reservations'

import { getReservationErrorMessage } from './mutation'
import { getDefaultReservationApi } from './runtime'

const PAGE_SIZE = 20
export type ReservationListStatusFilter = 'all' | ReservationStatus
export type ReservationListState = {
  readonly status: 'loading' | 'empty' | 'error' | 'content'
  readonly items: readonly Reservation[]
  readonly total: number
  readonly page: number
  readonly pages: number
  readonly loadingMore: boolean
  readonly errorMessage?: string
}

export interface ReservationListSource {
  listReservations(request?: ReservationListRequest): Promise<ReservationPage>
}

const initialState: ReservationListState = {
  status: 'loading', items: [], total: 0, page: 1, pages: 0, loadingMore: false,
}

export function useReservationList(source: ReservationListSource = getDefaultReservationApi()) {
  const [state, setState] = useState(initialState)
  const [statusFilter, setStatusFilter] = useState<ReservationListStatusFilter>('all')
  const sequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)

  const loadFirstPage = useCallback(() => {
    const sequence = ++sequenceRef.current
    loadingMoreRef.current = false
    setState(initialState)
    void source.listReservations(buildRequest(statusFilter, 1)).then((page) => {
      if (sequence !== sequenceRef.current) return
      setState({
        status: page.items.length ? 'content' : 'empty',
        items: page.items,
        total: page.total,
        page: page.page,
        pages: page.pages,
        loadingMore: false,
      })
    }).catch((cause: unknown) => {
      if (sequence === sequenceRef.current) {
        setState({ ...initialState, status: 'error', errorMessage: getReservationErrorMessage(cause, '预约加载失败') })
      }
    })
  }, [source, statusFilter])

  const loadNextPage = useCallback(() => {
    if (state.status !== 'content' || state.page >= state.pages || loadingMoreRef.current) return
    loadingMoreRef.current = true
    const sequence = ++sequenceRef.current
    setState((current) => ({ ...current, loadingMore: true, errorMessage: undefined }))
    void source.listReservations(buildRequest(statusFilter, state.page + 1)).then((page) => {
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
        setState((current) => ({
          ...current,
          loadingMore: false,
          errorMessage: getReservationErrorMessage(cause, '更多预约加载失败'),
        }))
      }
    }).finally(() => {
      if (sequence === sequenceRef.current) loadingMoreRef.current = false
    })
  }, [source, state.page, state.pages, state.status, statusFilter])

  useEffect(() => {
    loadFirstPage()
    return () => { sequenceRef.current += 1 }
  }, [loadFirstPage])

  return { state, statusFilter, setStatusFilter, retry: loadFirstPage, loadNextPage }
}

function buildRequest(status: ReservationListStatusFilter, page: number): ReservationListRequest {
  return { page, page_size: PAGE_SIZE, ...(status === 'all' ? {} : { status }) }
}
