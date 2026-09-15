import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  AdminReservationListRequest,
  AdminReservationPage,
  ReservationStatus,
} from '@/api/endpoints/reservations'

import { getReservationErrorMessage } from './mutation'
import { getDefaultReservationApi } from './runtime'

const PAGE_SIZE = 20
export type AdminReservationStatusFilter = 'all' | ReservationStatus

export interface AdminReservationFilterDraft {
  readonly status: AdminReservationStatusFilter
  readonly businessDate: string
  readonly userId: string
  readonly productId: string
}

export interface AdminReservationFilters {
  readonly status: AdminReservationStatusFilter
  readonly businessDate?: string
  readonly userId?: number
  readonly productId?: number
}

export const EMPTY_ADMIN_RESERVATION_FILTER_DRAFT: AdminReservationFilterDraft = {
  status: 'pending', businessDate: '', userId: '', productId: '',
}

export type AdminReservationFilterParseResult =
  | { readonly filters: AdminReservationFilters; readonly error?: never }
  | { readonly filters?: never; readonly error: string }

export type AdminReservationListState = {
  readonly status: 'loading' | 'empty' | 'error' | 'content'
  readonly items: AdminReservationPage['items']
  readonly total: number
  readonly page: number
  readonly pages: number
  readonly loadingMore: boolean
  readonly errorMessage?: string
}

export interface AdminReservationListSource {
  listAdminReservations(request?: AdminReservationListRequest): Promise<AdminReservationPage>
}

const initialState: AdminReservationListState = {
  status: 'loading', items: [], total: 0, page: 1, pages: 0, loadingMore: false,
}

export function useAdminReservationList(
  source: AdminReservationListSource = getDefaultReservationApi(),
) {
  const [filters, setFilters] = useState<AdminReservationFilters>({ status: 'pending' })
  const [state, setState] = useState(initialState)
  const sequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)

  const loadFirstPage = useCallback(() => {
    const sequence = ++sequenceRef.current
    loadingMoreRef.current = false
    setState(initialState)
    void source.listAdminReservations(buildRequest(filters, 1)).then((page) => {
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
        setState({ ...initialState, status: 'error', errorMessage: getReservationErrorMessage(cause, '管理预约加载失败') })
      }
    })
  }, [filters, source])

  const loadNextPage = useCallback(() => {
    if (state.status !== 'content' || state.page >= state.pages || loadingMoreRef.current) return
    loadingMoreRef.current = true
    const sequence = ++sequenceRef.current
    setState((current) => ({ ...current, loadingMore: true, errorMessage: undefined }))
    void source.listAdminReservations(buildRequest(filters, state.page + 1)).then((page) => {
      if (sequence !== sequenceRef.current) return
      setState((current) => ({
        status: 'content', items: [...current.items, ...page.items], total: page.total,
        page: page.page, pages: page.pages, loadingMore: false,
      }))
    }).catch((cause: unknown) => {
      if (sequence === sequenceRef.current) {
        setState((current) => ({ ...current, loadingMore: false, errorMessage: getReservationErrorMessage(cause, '更多管理预约加载失败') }))
      }
    }).finally(() => {
      if (sequence === sequenceRef.current) loadingMoreRef.current = false
    })
  }, [filters, source, state.page, state.pages, state.status])

  useEffect(() => {
    loadFirstPage()
    return () => { sequenceRef.current += 1 }
  }, [loadFirstPage])

  return { state, filters, applyFilters: setFilters, retry: loadFirstPage, loadNextPage }
}

export function parseAdminReservationFilters(
  draft: AdminReservationFilterDraft,
): AdminReservationFilterParseResult {
  const businessDate = normalizeDate(draft.businessDate)
  const userId = parseOptionalId(draft.userId)
  const productId = parseOptionalId(draft.productId)
  if (draft.businessDate.trim() && !businessDate) return { error: '预约日期必须是有效的 8 位日期，例如 20260908' }
  if (draft.userId.trim() && !userId) return { error: '用户 ID 必须是正整数' }
  if (draft.productId.trim() && !productId) return { error: '商品 ID 必须是正整数' }
  return {
    filters: {
      status: draft.status,
      ...(businessDate ? { businessDate } : {}),
      ...(userId ? { userId } : {}),
      ...(productId ? { productId } : {}),
    },
  }
}

function buildRequest(filters: AdminReservationFilters, page: number): AdminReservationListRequest {
  return {
    page,
    page_size: PAGE_SIZE,
    ...(filters.status === 'all' ? {} : { status: filters.status }),
    ...(filters.businessDate ? { business_date: filters.businessDate } : {}),
    ...(filters.userId ? { user_id: filters.userId } : {}),
    ...(filters.productId ? { product_id: filters.productId } : {}),
  }
}

function normalizeDate(value: string): string | undefined {
  const digits = value.trim()
  const match = /^(\d{4})(\d{2})(\d{2})$/.exec(digits)
  if (!match) return undefined
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const date = new Date(Date.UTC(year, month - 1, day))
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return undefined
  return `${match[1]}-${match[2]}-${match[3]}`
}

function parseOptionalId(value: string): number | undefined {
  const normalized = value.trim()
  if (!/^[1-9]\d*$/.test(normalized)) return undefined
  const parsed = Number(normalized)
  return Number.isSafeInteger(parsed) ? parsed : undefined
}
