import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  Reservation,
  ReservationBookingOptions,
  ReservationCreateRequest,
} from '@/api/endpoints/reservations'

import { getReservationErrorMessage, isReservationMutationUnknown } from './mutation'
import { getDefaultReservationApi } from './runtime'

export type ReservationCreateDataState =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly errorMessage: string }
  | { readonly status: 'empty'; readonly options: ReservationBookingOptions }
  | { readonly status: 'ready'; readonly options: ReservationBookingOptions }

export type ReservationSubmissionState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting' }
  | { readonly status: 'failed'; readonly errorMessage: string }
  | { readonly status: 'unknown'; readonly errorMessage: string }
  | { readonly status: 'succeeded'; readonly reservation: Reservation }

export interface ReservationCreateSource {
  getBookingOptions(experienceOptionId?: number | null): Promise<ReservationBookingOptions>
  createReservation(request: ReservationCreateRequest): Promise<Reservation>
}

export function useReservationCreate(
  initialProductId?: number,
  initialExperienceOptionId?: number,
  source: ReservationCreateSource = getDefaultReservationApi(),
) {
  const [productId, setProductId] = useState(initialProductId)
  const [experienceOptionId, setExperienceOptionId] = useState(initialExperienceOptionId)
  const scheduleRef = useRef({ date: '', time: '', initialized: false })
  const [data, setData] = useState<ReservationCreateDataState>({ status: 'loading' })
  const [reservationDate, setReservationDate] = useState('')
  const [startTime, setStartTime] = useState('')
  const [submission, setSubmission] = useState<ReservationSubmissionState>({ status: 'idle' })
  const sequenceRef = useRef(0)
  const activeSubmissionRef = useRef<Promise<Reservation | undefined>>()

  const load = useCallback(() => {
    const sequence = ++sequenceRef.current
    setData({ status: 'loading' })
    setSubmission((current) => current.status === 'unknown' || current.status === 'succeeded' ? current : { status: 'idle' })
    void source.getBookingOptions(experienceOptionId).then((options) => {
      if (sequence !== sequenceRef.current) return
      if (options.product_id !== (productId ?? null) || options.experience_option_id !== (experienceOptionId ?? null)) {
        setData({ status: 'error', errorMessage: '服务端返回的体验配置与当前页面不一致' })
        return
      }
      const firstDate = options.dates[0]
      if (!scheduleRef.current.initialized) {
        scheduleRef.current = { date: firstDate?.date ?? '', time: firstDate?.start_times[0] ?? '', initialized: true }
        setReservationDate(scheduleRef.current.date)
        setStartTime(scheduleRef.current.time)
      }
      setData(options.dates.length === 0 ? { status: 'empty', options } : { status: 'ready', options })
    }).catch((cause: unknown) => {
      if (sequence === sequenceRef.current) {
        setData({ status: 'error', errorMessage: getReservationErrorMessage(cause, '预约时间加载失败') })
      }
    })
  }, [experienceOptionId, productId, source])

  useEffect(() => {
    load()
    return () => { sequenceRef.current += 1 }
  }, [load])

  const selectDate = useCallback((date: string) => {
    if (data.status !== 'ready' || submission.status === 'submitting' ||
      submission.status === 'unknown' || submission.status === 'succeeded') return
    const bookingDate = data.options.dates.find((item) => item.date === date)
    if (!bookingDate) return
    const currentTime = scheduleRef.current.time
    const nextTime = bookingDate.start_times.includes(currentTime) ? currentTime : ''
    scheduleRef.current = { date, time: nextTime, initialized: true }
    setReservationDate(date)
    setStartTime(nextTime)
    setSubmission({ status: 'idle' })
  }, [data, submission.status])

  const selectStartTime = useCallback((time: string) => {
    if (data.status !== 'ready' || submission.status === 'submitting' ||
      submission.status === 'unknown' || submission.status === 'succeeded') return
    const bookingDate = data.options.dates.find((item) => item.date === reservationDate)
    if (bookingDate?.start_times.includes(time)) {
      scheduleRef.current.time = time
      setStartTime(time)
      setSubmission({ status: 'idle' })
    }
  }, [data, reservationDate, submission.status])

  const selectPackage = useCallback((selection?: { productId: number; experienceOptionId: number }) => {
    if (activeSubmissionRef.current || submission.status === 'unknown' || submission.status === 'succeeded') return
    if (productId === selection?.productId && experienceOptionId === selection?.experienceOptionId) return
    setData({ status: 'loading' })
    setProductId(selection?.productId)
    setExperienceOptionId(selection?.experienceOptionId)
  }, [experienceOptionId, productId, submission.status])

  const scheduleIsValid = data.status === 'ready' &&
    data.options.dates.some((day) => day.date === reservationDate && day.start_times.includes(startTime))

  const submit = useCallback((): Promise<Reservation | undefined> => {
    if (activeSubmissionRef.current) return activeSubmissionRef.current
    if (!scheduleIsValid || submission.status === 'unknown' || submission.status === 'succeeded') {
      return Promise.resolve(undefined)
    }
    const active = (async () => {
      setSubmission({ status: 'submitting' })
      try {
        const reservation = await source.createReservation({
          ...(experienceOptionId === undefined ? {} : { experience_option_id: experienceOptionId }),
          reservation_date: reservationDate,
          start_time: startTime,
        })
        setSubmission({ status: 'succeeded', reservation })
        return reservation
      } catch (cause) {
        setSubmission(isReservationMutationUnknown(cause)
          ? { status: 'unknown', errorMessage: '预约结果可能未知，请前往“我的预约”核对，系统不会自动重发。' }
          : { status: 'failed', errorMessage: getReservationErrorMessage(cause, '预约提交失败') })
        return undefined
      }
    })()
    activeSubmissionRef.current = active
    void active.finally(() => {
      if (activeSubmissionRef.current === active) activeSubmissionRef.current = undefined
    }).catch(() => undefined)
    return active
  }, [scheduleIsValid, experienceOptionId, reservationDate, source, startTime, submission.status])

  return {
    data,
    productId,
    experienceOptionId,
    selectPackage,
    scheduleIsValid,
    reservationDate,
    startTime,
    submission,
    retry: load,
    selectDate,
    selectStartTime,
    submit,
  }
}
