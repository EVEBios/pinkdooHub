import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  AdminOrderListItem,
  AdminOrderListPage,
  AdminOrderListRequest,
} from '@/api/endpoints/orders'

import { getDefaultOrderApi } from './runtime'

const ADMIN_ORDER_LIST_PAGE_SIZE = 20
const ORDER_NO_PATTERN = /^OD[0-9A-HJKMNP-TV-Z]{26}$/
const DATE_PATTERN = /^(\d{4})(\d{2})(\d{2})$/

export type AdminOrderStatusFilter = 'all' | NonNullable<AdminOrderListRequest['status']>

export interface AdminOrderFilterDraft {
  readonly status: AdminOrderStatusFilter
  readonly productName: string
  readonly orderNo: string
  readonly userId: string
  readonly createdFrom: string
  readonly createdTo: string
}

export interface AdminOrderFilters {
  readonly status: AdminOrderStatusFilter
  readonly productName?: string
  readonly orderNo?: string
  readonly userId?: number
  readonly createdFrom?: string
  readonly createdTo?: string
}

export type AdminOrderFilterResult =
  | { readonly filters: AdminOrderFilters; readonly error?: never }
  | { readonly filters?: never; readonly error: string }

export type AdminOrderListStatus = 'loading' | 'empty' | 'error' | 'content'

export interface AdminOrderListState {
  readonly status: AdminOrderListStatus
  readonly items: readonly AdminOrderListItem[]
  readonly total: number
  readonly page: number
  readonly pages: number
  readonly loadingMore: boolean
  readonly errorMessage?: string
}

export interface AdminOrderListSource {
  listAdminOrders(request?: AdminOrderListRequest): Promise<AdminOrderListPage>
}

export interface AdminOrderListFeature {
  readonly state: AdminOrderListState
  readonly filters: AdminOrderFilters
  applyFilters(filters: AdminOrderFilters): void
  retry(): void
  loadNextPage(): void
}

export const EMPTY_ADMIN_ORDER_FILTER_DRAFT: AdminOrderFilterDraft = {
  status: 'all',
  productName: '',
  orderNo: '',
  userId: '',
  createdFrom: '',
  createdTo: '',
}

const initialFilters: AdminOrderFilters = { status: 'all' }
const initialState: AdminOrderListState = {
  status: 'loading',
  items: [],
  total: 0,
  page: 1,
  pages: 0,
  loadingMore: false,
}

export function useAdminOrderList(
  source: AdminOrderListSource = getDefaultOrderApi(),
): AdminOrderListFeature {
  const [state, setState] = useState<AdminOrderListState>(initialState)
  const [filters, setFilters] = useState<AdminOrderFilters>(initialFilters)
  const requestSequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)

  const loadFirstPage = useCallback(() => {
    const sequence = ++requestSequenceRef.current
    loadingMoreRef.current = false
    setState(initialState)
    void source.listAdminOrders(buildRequest(filters, 1)).then((page) => {
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
      if (sequence === requestSequenceRef.current) {
        setState({ ...initialState, status: 'error', errorMessage: toMessage(cause, '管理订单加载失败') })
      }
    })
  }, [filters, source])

  const loadNextPage = useCallback(() => {
    if (state.status !== 'content' || state.page >= state.pages || loadingMoreRef.current) {
      return
    }
    loadingMoreRef.current = true
    const sequence = ++requestSequenceRef.current
    setState((current) => ({ ...current, loadingMore: true, errorMessage: undefined }))
    void source.listAdminOrders(buildRequest(filters, state.page + 1)).then((page) => {
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
      if (sequence === requestSequenceRef.current) {
        setState((current) => ({
          ...current,
          loadingMore: false,
          errorMessage: toMessage(cause, '更多管理订单加载失败'),
        }))
      }
    }).finally(() => {
      if (sequence === requestSequenceRef.current) {
        loadingMoreRef.current = false
      }
    })
  }, [filters, source, state.page, state.pages, state.status])

  useEffect(() => {
    loadFirstPage()
    return () => {
      requestSequenceRef.current += 1
    }
  }, [loadFirstPage])

  return { state, filters, applyFilters: setFilters, retry: loadFirstPage, loadNextPage }
}

export function parseAdminOrderFilters(draft: AdminOrderFilterDraft): AdminOrderFilterResult {
  const productName = draft.productName.trim()
  const orderNo = draft.orderNo.trim().toUpperCase()
  const userIdText = draft.userId.trim()
  const createdFromDate = parseDate(draft.createdFrom.trim())
  const createdToDate = parseDate(draft.createdTo.trim())

  if (productName.length > 100) {
    return { error: '商品名称不能超过 100 个字符' }
  }
  if (orderNo && !ORDER_NO_PATTERN.test(orderNo)) {
    return { error: '订单号格式不正确' }
  }
  if (userIdText && (!/^[1-9]\d*$/.test(userIdText) || !Number.isSafeInteger(Number(userIdText)))) {
    return { error: '用户 ID 必须是正整数' }
  }
  if (draft.createdFrom.trim() && !createdFromDate) {
    return { error: '开始日期必须是有效的 8 位日期，例如 20260208' }
  }
  if (draft.createdTo.trim() && !createdToDate) {
    return { error: '结束日期必须是有效的 8 位日期，例如 20260208' }
  }
  if (createdFromDate && createdToDate && createdFromDate.getTime() > createdToDate.getTime()) {
    return { error: '结束日期不能早于开始日期' }
  }

  return {
    filters: {
      status: draft.status,
      ...(productName ? { productName } : {}),
      ...(orderNo ? { orderNo } : {}),
      ...(userIdText ? { userId: Number(userIdText) } : {}),
      ...(createdFromDate ? { createdFrom: createdFromDate.toISOString() } : {}),
      ...(createdToDate ? { createdTo: addUtcDay(createdToDate).toISOString() } : {}),
    },
  }
}

function buildRequest(filters: AdminOrderFilters, page: number): AdminOrderListRequest {
  return {
    page,
    page_size: ADMIN_ORDER_LIST_PAGE_SIZE,
    ...(filters.status === 'all' ? {} : { status: filters.status }),
    ...(filters.productName ? { product_name: filters.productName } : {}),
    ...(filters.orderNo ? { order_no: filters.orderNo } : {}),
    ...(filters.userId ? { user_id: filters.userId } : {}),
    ...(filters.createdFrom ? { created_from: filters.createdFrom } : {}),
    ...(filters.createdTo ? { created_to: filters.createdTo } : {}),
  }
}

function parseDate(value: string): Date | undefined {
  if (!value) {
    return undefined
  }
  const match = DATE_PATTERN.exec(value)
  if (!match) {
    return undefined
  }
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
    ? date
    : undefined
}

function addUtcDay(date: Date): Date {
  return new Date(date.getTime() + 24 * 60 * 60 * 1000)
}

function toMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}
