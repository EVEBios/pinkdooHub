import { useCallback, useEffect, useRef, useState } from 'react'

import type { WalletTransaction, WalletTransactionPage } from '@/api/endpoints/wallet'

import { getWalletErrorMessage } from './mutation'
import { getDefaultWalletApi } from './runtime'

const PAGE_SIZE = 20

export interface WalletTransactionState {
  readonly status: 'loading' | 'empty' | 'error' | 'content'
  readonly items: readonly WalletTransaction[]
  readonly total: number
  readonly page: number
  readonly pages: number
  readonly loadingMore: boolean
  readonly errorMessage?: string
}

export interface WalletTransactionSource {
  listWalletTransactions(request?: { page?: number; page_size?: number }): Promise<WalletTransactionPage>
  listAdminUserWalletTransactions(
    userId: number,
    request?: { page?: number; page_size?: number },
  ): Promise<WalletTransactionPage>
}

const INITIAL_STATE: WalletTransactionState = {
  status: 'loading', items: [], total: 0, page: 1, pages: 0, loadingMore: false,
}

export function useWalletTransactions(source: WalletTransactionSource = getDefaultWalletApi()) {
  return useTransactionList(
    'current-user',
    (page) => source.listWalletTransactions({ page, page_size: PAGE_SIZE }),
  )
}

export function useAdminWalletTransactions(
  userId: number,
  source: WalletTransactionSource = getDefaultWalletApi(),
) {
  return useTransactionList(
    `admin-user:${userId}`,
    (page) => source.listAdminUserWalletTransactions(
      userId,
      { page, page_size: PAGE_SIZE },
    ),
  )
}

interface ScopedTransactionState {
  readonly scope: string
  readonly state: WalletTransactionState
}

function useTransactionList(
  scope: string,
  loadPage: (page: number) => Promise<WalletTransactionPage>,
) {
  const [scopedState, setScopedState] = useState<ScopedTransactionState>({
    scope,
    state: INITIAL_STATE,
  })
  const sequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)
  const loadPageRef = useRef(loadPage)
  loadPageRef.current = loadPage
  const state = scopedState.scope === scope ? scopedState.state : INITIAL_STATE

  const loadFirstPage = useCallback(() => {
    const sequence = ++sequenceRef.current
    loadingMoreRef.current = false
    setScopedState({ scope, state: INITIAL_STATE })
    void loadPageRef.current(1).then((page) => {
      if (sequence !== sequenceRef.current) return
      setScopedState({
        scope,
        state: {
          status: page.items.length === 0 ? 'empty' : 'content',
          items: page.items,
          total: page.total,
          page: page.page,
          pages: page.pages,
          loadingMore: false,
        },
      })
    }).catch((cause: unknown) => {
      if (sequence !== sequenceRef.current) return
      const error = cause instanceof Error ? cause : new Error('资金明细加载失败')
      setScopedState({
        scope,
        state: {
          ...INITIAL_STATE,
          status: 'error',
          errorMessage: getWalletErrorMessage(error, '资金明细加载失败'),
        },
      })
    })
  }, [scope])

  const loadNextPage = useCallback(() => {
    if (state.status !== 'content' || state.page >= state.pages || loadingMoreRef.current) return
    loadingMoreRef.current = true
    const sequence = ++sequenceRef.current
    const nextPage = state.page + 1
    setScopedState((current) => current.scope === scope
      ? {
          scope,
          state: { ...current.state, loadingMore: true, errorMessage: undefined },
        }
      : current)
    void loadPageRef.current(nextPage).then((page) => {
      if (sequence !== sequenceRef.current) return
      setScopedState((current) => current.scope === scope
        ? {
            scope,
            state: {
              status: 'content',
              items: [...current.state.items, ...page.items],
              total: page.total,
              page: page.page,
              pages: page.pages,
              loadingMore: false,
            },
          }
        : current)
    }).catch((cause: unknown) => {
      if (sequence !== sequenceRef.current) return
      const error = cause instanceof Error ? cause : new Error('更多资金明细加载失败')
      setScopedState((current) => current.scope === scope
        ? {
            scope,
            state: {
              ...current.state,
              loadingMore: false,
              errorMessage: getWalletErrorMessage(error, '更多资金明细加载失败'),
            },
          }
        : current)
    }).finally(() => {
      if (sequence === sequenceRef.current) loadingMoreRef.current = false
    })
  }, [scope, state.page, state.pages, state.status])

  useEffect(() => {
    loadFirstPage()
    return () => { sequenceRef.current += 1 }
  }, [loadFirstPage])

  return { state, retry: loadFirstPage, loadNextPage }
}
