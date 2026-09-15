import { useCallback, useEffect, useRef, useState } from 'react'

import type { AuditLogItem, AuditLogPage } from '@/api/endpoints/audit'

import { getDefaultAuditApi } from './runtime'

const AUDIT_PAGE_SIZE = 20

export type ProductAuditListState =
  | { readonly status: 'loading' }
  | { readonly status: 'empty' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | {
      readonly status: 'content'
      readonly items: readonly AuditLogItem[]
      readonly total: number
      readonly page: number
      readonly pages: number
      readonly loadingMore: boolean
      readonly errorMessage?: string
    }

export interface ProductAuditListSource {
  listProductAuditLogs(
    productId: number,
    request?: { readonly page?: number; readonly page_size?: number },
  ): Promise<AuditLogPage>
}

export function useProductAuditList(
  productId: number,
  source: ProductAuditListSource = getDefaultAuditApi(),
) {
  const [state, setState] = useState<ProductAuditListState>({ status: 'loading' })
  const sequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)

  const loadFirstPage = useCallback(() => {
    const sequence = ++sequenceRef.current
    loadingMoreRef.current = false
    setState({ status: 'loading' })
    void source.listProductAuditLogs(productId, { page: 1, page_size: AUDIT_PAGE_SIZE })
      .then((page) => {
        if (sequence !== sequenceRef.current) return
        setState(page.items.length === 0
          ? { status: 'empty' }
          : {
              status: 'content',
              items: page.items,
              total: page.total,
              page: page.page,
              pages: page.pages,
              loadingMore: false,
            })
      })
      .catch((cause: unknown) => {
        if (sequence === sequenceRef.current) {
          setState({ status: 'error', errorMessage: toMessage(cause, '商品操作历史加载失败') })
        }
      })
  }, [productId, source])

  const loadNextPage = useCallback(() => {
    if (state.status !== 'content' || state.page >= state.pages || loadingMoreRef.current) return
    loadingMoreRef.current = true
    const sequence = ++sequenceRef.current
    setState((current) => current.status === 'content'
      ? { ...current, loadingMore: true, errorMessage: undefined }
      : current)
    void source.listProductAuditLogs(productId, {
      page: state.page + 1,
      page_size: AUDIT_PAGE_SIZE,
    }).then((page) => {
      if (sequence !== sequenceRef.current) return
      setState((current) => current.status === 'content'
        ? {
            status: 'content',
            items: [...current.items, ...page.items],
            total: page.total,
            page: page.page,
            pages: page.pages,
            loadingMore: false,
          }
        : current)
    }).catch((cause: unknown) => {
      if (sequence === sequenceRef.current) {
        setState((current) => current.status === 'content'
          ? { ...current, loadingMore: false, errorMessage: toMessage(cause, '更多操作历史加载失败') }
          : current)
      }
    }).finally(() => {
      if (sequence === sequenceRef.current) loadingMoreRef.current = false
    })
  }, [productId, source, state])

  useEffect(() => {
    loadFirstPage()
    return () => { sequenceRef.current += 1 }
  }, [loadFirstPage])

  return { state, retry: loadFirstPage, loadNextPage }
}

function toMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}
