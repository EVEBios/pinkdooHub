import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  StoreClosureListRequest,
  StoreClosureMutation,
  StoreClosurePage,
} from '@/api/endpoints/reservations'

import { getReservationErrorMessage, isReservationMutationUnknown } from './mutation'
import { getDefaultReservationApi } from './runtime'

const PAGE_SIZE = 20
export type StoreClosureListState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | {
      readonly status: 'content'
      readonly items: StoreClosurePage['items']
      readonly total: number
      readonly page: number
      readonly pages: number
      readonly loadingMore: boolean
      readonly errorMessage?: string
    }

export type StoreClosureMutationState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly action: 'close' | 'reopen'; readonly businessDate: string }
  | { readonly status: 'failed' | 'unknown'; readonly action: 'close' | 'reopen'; readonly businessDate: string; readonly errorMessage: string }
  | { readonly status: 'succeeded'; readonly action: 'close' | 'reopen'; readonly result: StoreClosureMutation }
  | { readonly status: 'reconciled'; readonly action: 'close' | 'reopen'; readonly businessDate: string; readonly isClosed: boolean }

export interface StoreClosureSource {
  listStoreClosures(request?: StoreClosureListRequest): Promise<StoreClosurePage>
  closeStoreDay(businessDate: string): Promise<StoreClosureMutation>
  reopenStoreDay(businessDate: string): Promise<StoreClosureMutation>
}

export function useStoreClosures(source: StoreClosureSource = getDefaultReservationApi()) {
  const [list, setList] = useState<StoreClosureListState>({ status: 'loading' })
  const [mutation, setMutation] = useState<StoreClosureMutationState>({ status: 'idle' })
  const sequenceRef = useRef(0)
  const loadingMoreRef = useRef(false)
  const activeRef = useRef<Promise<StoreClosureMutation | undefined>>()

  const load = useCallback(() => {
    const sequence = ++sequenceRef.current
    loadingMoreRef.current = false
    setList({ status: 'loading' })
    void source.listStoreClosures({ page: 1, page_size: PAGE_SIZE, is_closed: true }).then((page) => {
      if (sequence === sequenceRef.current) {
        setList({ status: 'content', items: page.items, total: page.total, page: page.page, pages: page.pages, loadingMore: false })
      }
    }).catch((cause: unknown) => {
      if (sequence === sequenceRef.current) {
        setList({ status: 'error', errorMessage: getReservationErrorMessage(cause, '店休日期加载失败') })
      }
    })
  }, [source])

  useEffect(() => {
    load()
    return () => { sequenceRef.current += 1 }
  }, [load])

  const loadNextPage = useCallback(() => {
    if (list.status !== 'content' || list.page >= list.pages || loadingMoreRef.current) return
    loadingMoreRef.current = true
    const sequence = ++sequenceRef.current
    setList({ ...list, loadingMore: true, errorMessage: undefined })
    void source.listStoreClosures({ page: list.page + 1, page_size: PAGE_SIZE, is_closed: true }).then((page) => {
      if (sequence === sequenceRef.current && list.status === 'content') {
        setList({ status: 'content', items: [...list.items, ...page.items], total: page.total, page: page.page, pages: page.pages, loadingMore: false })
      }
    }).catch((cause: unknown) => {
      if (sequence === sequenceRef.current && list.status === 'content') {
        setList({ ...list, loadingMore: false, errorMessage: getReservationErrorMessage(cause, '更多店休日期加载失败') })
      }
    }).finally(() => {
      if (sequence === sequenceRef.current) loadingMoreRef.current = false
    })
  }, [list, source])

  const mutate = useCallback((action: 'close' | 'reopen', businessDate: string) => {
    if (activeRef.current) return activeRef.current
    if (mutation.status === 'unknown') return Promise.resolve(undefined)
    const active = (async () => {
      setMutation({ status: 'submitting', action, businessDate })
      try {
        const result = action === 'close'
          ? await source.closeStoreDay(businessDate)
          : await source.reopenStoreDay(businessDate)
        setMutation({ status: 'succeeded', action, result })
        load()
        return result
      } catch (cause) {
        setMutation(isReservationMutationUnknown(cause)
          ? { status: 'unknown', action, businessDate, errorMessage: '营业状态结果可能未知，请重新加载店休列表核对，系统不会自动重发。' }
          : { status: 'failed', action, businessDate, errorMessage: getReservationErrorMessage(cause, '营业状态更新失败') })
        return undefined
      }
    })()
    activeRef.current = active
    void active.finally(() => { if (activeRef.current === active) activeRef.current = undefined }).catch(() => undefined)
    return active
  }, [load, mutation.status, source])

  const reconcile = useCallback(() => {
    if (activeRef.current) return activeRef.current
    if (mutation.status !== 'unknown') {
      load()
      return Promise.resolve(undefined)
    }

    const { action, businessDate } = mutation
    const active = (async () => {
      try {
        const page = await source.listStoreClosures({
          page: 1,
          page_size: PAGE_SIZE,
          date_from: businessDate,
          date_to: businessDate,
          is_closed: true,
        })
        const isClosed = page.total === 1 && page.items.length === 1 &&
          page.items[0].business_date === businessDate
        setMutation((current) => current.status === 'unknown' &&
          current.action === action && current.businessDate === businessDate
          ? { status: 'reconciled', action, businessDate, isClosed }
          : current)
        load()
      } catch (cause) {
        setMutation((current) => current.status === 'unknown' &&
          current.action === action && current.businessDate === businessDate
          ? {
              ...current,
              errorMessage: getReservationErrorMessage(cause, '店休状态核对失败，请稍后重试'),
            }
          : current)
      }
      return undefined
    })()
    activeRef.current = active
    void active.finally(() => { if (activeRef.current === active) activeRef.current = undefined }).catch(() => undefined)
    return active
  }, [load, mutation, source])

  return {
    list,
    mutation,
    retry: load,
    loadNextPage,
    close: (date: string) => mutate('close', date),
    reopen: (date: string) => mutate('reopen', date),
    reconcile,
  }
}
