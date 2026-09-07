import {
  ADMIN_RESERVATION_LIST_PATH,
  ADMIN_STORE_CLOSURE_LIST_PATH,
  RESERVATION_CREATE_PATH,
  RESERVATION_LIST_PATH,
  type ReservationCreateRedirect,
} from '@/auth/login_route'

export {
  ADMIN_RESERVATION_LIST_PATH,
  ADMIN_STORE_CLOSURE_LIST_PATH,
  RESERVATION_CREATE_PATH,
  RESERVATION_LIST_PATH,
}

export interface ReservationCreateRoute {
  readonly productId: number
  readonly experienceOptionId: number
}

export interface ReservationDetailRoute {
  readonly reservationId: number
}

export function buildReservationCreateUrl(
  productId: number,
  experienceOptionId: number,
): ReservationCreateRedirect {
  assertId(productId, 'Product ID')
  assertId(experienceOptionId, 'Experience Option ID')
  return `${RESERVATION_CREATE_PATH}?product_id=${productId}&option_id=${experienceOptionId}`
}

export function parseReservationCreateRoute(
  params: Readonly<Record<string, string | undefined>>,
): ReservationCreateRoute | undefined {
  const productId = parseId(params.product_id)
  const experienceOptionId = parseId(params.option_id)
  return productId && experienceOptionId ? { productId, experienceOptionId } : undefined
}

export function buildReservationDetailUrl(reservationId: number): string {
  assertId(reservationId, 'Reservation ID')
  return `/pages/reservation-detail/index?id=${reservationId}`
}

export function buildAdminReservationDetailUrl(reservationId: number): string {
  assertId(reservationId, 'Reservation ID')
  return `/admin/pages/reservation-detail/index?id=${reservationId}`
}

export function parseReservationDetailRoute(
  params: Readonly<Record<string, string | undefined>>,
): ReservationDetailRoute | undefined {
  const reservationId = parseId(params.id)
  return reservationId ? { reservationId } : undefined
}

function parseId(value: string | undefined): number | undefined {
  if (!value || !/^[1-9]\d*$/.test(value)) return undefined
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) ? parsed : undefined
}

function assertId(value: number, label: string): void {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${label} 必须是正安全整数`)
  }
}
