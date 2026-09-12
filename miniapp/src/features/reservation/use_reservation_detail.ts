import { useCallback, useEffect, useRef, useState } from 'react'

import { BusinessError } from '@/api'
import type { Reservation } from '@/api/endpoints/reservations'

import { getReservationErrorMessage, isReservationMutationUnknown } from './mutation'
import { getDefaultReservationApi } from './runtime'

export type ReservationDetailState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | { readonly status: 'content'; readonly reservation: Reservation }

export type ReservationCancellationState =
  | { readonly status: 'idle' | 'submitting' }
  | { readonly status: 'failed' | 'unknown'; readonly errorMessage: string }
  | { readonly status: 'succeeded'; readonly refreshErrorMessage?: string }

export interface ReservationDetailSource {
  getReservation(reservationId: number): Promise<Reservation>
  cancelReservation(reservationId: number): Promise<Reservation>
}

export function useReservationDetail(
  reservationId: number,
  source: ReservationDetailSource = getDefaultReservationApi(),
) {
  const [detail, setDetail] = useState<ReservationDetailState>({ status: 'loading' })
  const [cancellation, setCancellation] = useState<ReservationCancellationState>({ status: 'idle' })
  const sequenceRef = useRef(0)
  const activeRef = useRef<Promise<void>>()

  const load = useCallback(() => {
    const sequence = ++sequenceRef.current
    setDetail({ status: 'loading' })
    void source.getReservation(reservationId).then((reservation) => {
      if (sequence === sequenceRef.current) {
        setDetail({ status: 'content', reservation })
        setCancellation((current) => current.status === 'unknown' ? { status: 'idle' } : current)
      }
    }).catch((cause: unknown) => {
      if (sequence === sequenceRef.current) {
        setDetail({ status: 'error', errorMessage: getReservationErrorMessage(cause, '预约详情加载失败') })
      }
    })
  }, [reservationId, source])

  useEffect(() => {
    load()
    return () => { sequenceRef.current += 1 }
  }, [load])

  const cancel = useCallback((): Promise<void> => {
    if (activeRef.current) return activeRef.current
    if (detail.status !== 'content' || cancellation.status === 'unknown' ||
      !['pending', 'confirmed'].includes(detail.reservation.status.value)) {
      return Promise.resolve()
    }
    const active = (async () => {
      setCancellation({ status: 'submitting' })
      try {
        const reservation = await source.cancelReservation(reservationId)
        setDetail({ status: 'content', reservation })
        try {
          const refreshed = await source.getReservation(reservationId)
          setDetail({ status: 'content', reservation: refreshed })
          setCancellation({ status: 'succeeded' })
        } catch (cause) {
          setCancellation({
            status: 'succeeded',
            refreshErrorMessage: getReservationErrorMessage(cause, '预约已取消，但详情刷新失败'),
          })
        }
      } catch (cause) {
        setCancellation(isReservationMutationUnknown(cause)
          ? { status: 'unknown', errorMessage: '取消结果可能未知，请重新加载详情核对，系统不会自动重发。' }
          : { status: 'failed', errorMessage: getReservationErrorMessage(cause, '取消预约失败') })
        if (cause instanceof BusinessError && (cause.code === 40951 || cause.code === 40952)) {
          try {
            const refreshed = await source.getReservation(reservationId)
            setDetail({ status: 'content', reservation: refreshed })
          } catch {
            // 保留原始业务错误，用户仍可显式重新加载。
          }
        }
      }
    })()
    activeRef.current = active
    void active.finally(() => { if (activeRef.current === active) activeRef.current = undefined }).catch(() => undefined)
    return active
  }, [cancellation.status, detail, reservationId, source])

  return { detail, cancellation, retry: load, cancel }
}
