import { useCallback, useEffect, useRef, useState } from 'react'

import { BusinessError } from '@/api'
import type { AdminReservationDetail, Reservation } from '@/api/endpoints/reservations'

import { getReservationErrorMessage, isReservationMutationUnknown } from './mutation'
import { getDefaultReservationApi } from './runtime'

export type AdminReservationAction = 'confirm' | 'reject'
export type AdminReservationDetailState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | { readonly status: 'content'; readonly reservation: AdminReservationDetail }
export type AdminReservationMutationState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly action: AdminReservationAction }
  | { readonly status: 'failed' | 'unknown'; readonly action: AdminReservationAction; readonly errorMessage: string }
  | { readonly status: 'succeeded'; readonly action: AdminReservationAction; readonly refreshErrorMessage?: string }

export interface AdminReservationDetailSource {
  getAdminReservation(reservationId: number): Promise<AdminReservationDetail>
  confirmReservation(reservationId: number): Promise<Reservation>
  rejectReservation(reservationId: number): Promise<Reservation>
}

export function useAdminReservationDetail(
  reservationId: number,
  source: AdminReservationDetailSource = getDefaultReservationApi(),
) {
  const [detail, setDetail] = useState<AdminReservationDetailState>({ status: 'loading' })
  const [mutation, setMutation] = useState<AdminReservationMutationState>({ status: 'idle' })
  const sequenceRef = useRef(0)
  const activeRef = useRef<Promise<void>>()

  const load = useCallback(() => {
    const sequence = ++sequenceRef.current
    setDetail({ status: 'loading' })
    void source.getAdminReservation(reservationId).then((reservation) => {
      if (sequence === sequenceRef.current) {
        setDetail({ status: 'content', reservation })
        setMutation((current) => current.status === 'unknown' ? { status: 'idle' } : current)
      }
    }).catch((cause: unknown) => {
      if (sequence === sequenceRef.current) {
        setDetail({ status: 'error', errorMessage: getReservationErrorMessage(cause, '管理预约详情加载失败') })
      }
    })
  }, [reservationId, source])

  useEffect(() => {
    load()
    return () => { sequenceRef.current += 1 }
  }, [load])

  const run = useCallback((action: AdminReservationAction): Promise<void> => {
    if (activeRef.current) return activeRef.current
    if (detail.status !== 'content' || mutation.status === 'unknown' ||
      detail.reservation.status.value !== 'pending') return Promise.resolve()
    const current = detail.reservation
    const active = (async () => {
      setMutation({ status: 'submitting', action })
      try {
        const result = action === 'confirm'
          ? await source.confirmReservation(reservationId)
          : await source.rejectReservation(reservationId)
        setDetail({ status: 'content', reservation: { ...current, ...result } })
        try {
          const refreshed = await source.getAdminReservation(reservationId)
          setDetail({ status: 'content', reservation: refreshed })
          setMutation({ status: 'succeeded', action })
        } catch (cause) {
          setMutation({ status: 'succeeded', action, refreshErrorMessage: getReservationErrorMessage(cause, '状态已更新，但详情刷新失败') })
        }
      } catch (cause) {
        setMutation(isReservationMutationUnknown(cause)
          ? { status: 'unknown', action, errorMessage: '处理结果可能未知，请重新加载详情核对，系统不会自动重发。' }
          : { status: 'failed', action, errorMessage: getReservationErrorMessage(cause, '预约处理失败') })
        if (cause instanceof BusinessError && (cause.code === 40951 || cause.code === 40953)) {
          try {
            const refreshed = await source.getAdminReservation(reservationId)
            setDetail({ status: 'content', reservation: refreshed })
          } catch {
            // 保留原始错误，管理员可显式重新加载。
          }
        }
      }
    })()
    activeRef.current = active
    void active.finally(() => { if (activeRef.current === active) activeRef.current = undefined }).catch(() => undefined)
    return active
  }, [detail, mutation.status, reservationId, source])

  return { detail, mutation, retry: load, confirm: () => run('confirm'), reject: () => run('reject') }
}
