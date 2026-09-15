import type { Reservation } from '@/api/endpoints/reservations'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'] as const

export function formatReservationDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return value
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
  return `${match[1]}年${Number(match[2])}月${Number(match[3])}日 ${WEEKDAYS[date.getUTCDay()]}`
}

export function formatShanghaiUtc(value: string): string {
  const timestamp = Date.parse(value)
  if (Number.isNaN(timestamp)) return value
  const date = new Date(timestamp + 8 * 60 * 60 * 1_000)
  return `${date.getUTCFullYear()}年${date.getUTCMonth() + 1}月${date.getUTCDate()}日 ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
}

export function isReservationOverdue(reservation: Reservation, now = Date.now()): boolean {
  return reservation.status.value === 'pending' && Date.parse(reservation.scheduled_start_at) <= now
}

export function reservationStatusLabel(reservation: Reservation, now = Date.now()): string {
  return isReservationOverdue(reservation, now) ? '已过期未处理' : reservation.status.label
}

export function reservationMessage(reservation: Reservation, now = Date.now()): string {
  return isReservationOverdue(reservation, now)
    ? '预约时间已过，门店未能及时确认。请联系门店确认安排。'
    : reservation.customer_message
}

export function reservationStatusClass(reservation: Reservation, now = Date.now()): string {
  if (isReservationOverdue(reservation, now)) return 'overdue'
  if (reservation.status.value === 'cancelled' &&
    reservation.cancellation_reason?.value === 'store_closed') return 'store-closed'
  return reservation.status.value
}

export function canRequestReservationCancellation(reservation: Reservation): boolean {
  return reservation.status.value === 'pending' || reservation.status.value === 'confirmed'
}

function pad(value: number): string {
  return value.toString().padStart(2, '0')
}
