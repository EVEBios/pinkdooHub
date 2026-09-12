import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  AdminProductListItem,
  AdminProductListPage,
  AdminProductListRequest,
} from '@/api/endpoints/admin_products'

import { getDefaultAdminProductApi } from './runtime'

const ADMIN_PRODUCT_PAGE_SIZE = 20

export type AdminProductTypeFilter = 'all' | 'experience' | 'kit'
export type AdminProductStatusFilter = 'all' | 'draft' | 'online' | 'offline'
export type AdminProductListStatus = 'loading' | 'empty' | 'error' | 'content'

export interface AdminProductFilters {
  readonly productType: AdminProductTypeFilter
  readonly status: AdminProductStatusFilter
  readonly keyword: string
  readonly includeDeleted: boolean
}

export interface AdminProductFilterDraft {
  readonly productType: AdminProductTypeFilter
  readonly status: AdminProductStatusFilter
  readonly keyword: string
  readonly includeDeleted: boolean
}

export const EMPTY_ADMIN_PRODUCT_FILTERS: AdminProductFilters = {
  productType: 'all',
  status: 'all',
  keyword: '',
  includeDeleted: false,
}

export interface AdminProductListState {
  readonly status: AdminProductListStatus
  readonly items: readonly AdminProductListItem[]
  readonly total: number
  readonly page: number
  readonly pages: number
  readonly loadingMore: boolean
  readonly errorMessage?: string
}

export interface AdminProductListSource {
  listProducts(request?: AdminProductListRequest): Promise<AdminProductListPage>
}

export interface AdminProductListFeature {
  readonly state: AdminProductListState
  readonly filters: AdminProductFilters
  applyFilters(filters: AdminProductFilterDraft): void
  retry(): void
  loadNextPage(): void
}

const initialState: AdminProductListState = {
  status: 'loading',
  items: [],
  total: 0,
  page: 1,
  pages: 0,
  loadingMore: false,
}

export function useAdminProductList(
  source: AdminProductListSource = getDefaultAdminProductApi(),
): AdminProductListFeature {
  const [state, setState] = useState(initialState)
  const [filters, setFilters] = useState<AdminProductFilters>(EMPTY_ADMIN_PRODUCT_FILTERS)
  const requestSequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)

  const loadFirstPage = useCallback(() => {
    const sequence = ++requestSequenceRef.current
    loadingMoreRef.current = false
    setState(initialState)
    void source.listProducts({
      ...toQuery(filters),
      page: 1,
      page_size: ADMIN_PRODUCT_PAGE_SIZE,
    }).then((page) => {
      if (sequence !== requestSequenceRef.current) return
      setState({
        status: page.items.length === 0 ? 'empty' : 'content',
        items: page.items,
        total: page.total,
        page: page.page,
        pages: page.pages,
        loadingMore: false,
      })
    }).catch((cause: unknown) => {
      if (sequence !== requestSequenceRef.current) return
      setState({ ...initialState, status: 'error', errorMessage: toMessage(cause) })
    })
  }, [filters, source])

  const loadNextPage = useCallback(() => {
    if (state.status !== 'content' || state.page >= state.pages || loadingMoreRef.current) return
    loadingMoreRef.current = true
    const sequence = ++requestSequenceRef.current
    setState((current) => ({ ...current, loadingMore: true, errorMessage: undefined }))
    void source.listProducts({
      ...toQuery(filters),
      page: state.page + 1,
      page_size: ADMIN_PRODUCT_PAGE_SIZE,
    }).then((page) => {
      if (sequence !== requestSequenceRef.current) return
      setState((current) => ({
        status: 'content',
        items: [...current.items, ...page.items],
        total: page.total,
        page: page.page,
        pages: page.pages,
        loadingMore: false,
      }))
    }).catch((cause: unknown) => {
      if (sequence !== requestSequenceRef.current) return
      setState((current) => ({ ...current, loadingMore: false, errorMessage: toMessage(cause) }))
    }).finally(() => {
      if (sequence === requestSequenceRef.current) loadingMoreRef.current = false
    })
  }, [filters, source, state.page, state.pages, state.status])

  useEffect(() => {
    loadFirstPage()
    return () => { requestSequenceRef.current += 1 }
  }, [loadFirstPage])

  return {
    state,
    filters,
    applyFilters: (draft) => setFilters({ ...draft, keyword: draft.keyword.trim() }),
    retry: loadFirstPage,
    loadNextPage,
  }
}

function toQuery(filters: AdminProductFilters): AdminProductListRequest {
  return {
    ...(filters.productType === 'all' ? {} : { product_type: filters.productType }),
    ...(filters.status === 'all' ? {} : { status: filters.status }),
    ...(filters.keyword ? { keyword: filters.keyword } : {}),
    include_deleted: filters.includeDeleted,
  }
}

function toMessage(cause: unknown): string {
  return cause instanceof Error && cause.message ? cause.message : '管理商品加载失败，请稍后重试'
}
