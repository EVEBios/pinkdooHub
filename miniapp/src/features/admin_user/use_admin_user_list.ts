import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  AdminUserListItem,
  AdminUserListPage,
  AdminUserListRequest,
} from '@/api/endpoints/admin_users'

import { getDefaultAdminUserApi } from './runtime'

const ADMIN_USER_PAGE_SIZE = 20

export type AdminUserRoleFilter = 'all' | NonNullable<AdminUserListRequest['role']>
export type AdminUserStatusFilter = 'all' | NonNullable<AdminUserListRequest['status']>
export interface AdminUserFilters {
  readonly role: AdminUserRoleFilter
  readonly status: AdminUserStatusFilter
}
export interface AdminUserListState {
  readonly status: 'loading' | 'empty' | 'error' | 'content'
  readonly items: readonly AdminUserListItem[]
  readonly total: number
  readonly page: number
  readonly pages: number
  readonly loadingMore: boolean
  readonly errorMessage?: string
}
export interface AdminUserListSource {
  listUsers(request?: AdminUserListRequest): Promise<AdminUserListPage>
}

const INITIAL_FILTERS: AdminUserFilters = { role: 'all', status: 'all' }
const INITIAL_STATE: AdminUserListState = {
  status: 'loading', items: [], total: 0, page: 1, pages: 0, loadingMore: false,
}

export function useAdminUserList(
  source: AdminUserListSource = getDefaultAdminUserApi(),
) {
  const [filters, setFilters] = useState<AdminUserFilters>(INITIAL_FILTERS)
  const [state, setState] = useState<AdminUserListState>(INITIAL_STATE)
  const sequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)

  const loadFirstPage = useCallback(() => {
    const sequence = ++sequenceRef.current
    loadingMoreRef.current = false
    setState(INITIAL_STATE)
    void source.listUsers(buildRequest(filters, 1)).then((page) => {
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
        setState({ ...INITIAL_STATE, status: 'error', errorMessage: toMessage(cause, '管理用户加载失败') })
      }
    })
  }, [filters, source])

  const loadNextPage = useCallback(() => {
    if (state.status !== 'content' || state.page >= state.pages || loadingMoreRef.current) return
    loadingMoreRef.current = true
    const sequence = ++sequenceRef.current
    setState((current) => ({ ...current, loadingMore: true, errorMessage: undefined }))
    void source.listUsers(buildRequest(filters, state.page + 1)).then((page) => {
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
          errorMessage: toMessage(cause, '更多管理用户加载失败'),
        }))
      }
    }).finally(() => {
      if (sequence === sequenceRef.current) loadingMoreRef.current = false
    })
  }, [filters, source, state.page, state.pages, state.status])

  useEffect(() => {
    loadFirstPage()
    return () => { sequenceRef.current += 1 }
  }, [loadFirstPage])

  return { filters, state, applyFilters: setFilters, retry: loadFirstPage, loadNextPage }
}

function buildRequest(filters: AdminUserFilters, page: number): AdminUserListRequest {
  return {
    page,
    page_size: ADMIN_USER_PAGE_SIZE,
    ...(filters.role === 'all' ? {} : { role: filters.role }),
    ...(filters.status === 'all' ? {} : { status: filters.status }),
  }
}

function toMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}
