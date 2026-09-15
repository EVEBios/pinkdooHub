import { createApiClient } from '@/api'
import { ReservationApi } from '@/api/endpoints/reservations'
import { getDefaultAuthRuntime } from '@/auth/runtime'

let defaultReservationApi: ReservationApi | undefined

export function getDefaultReservationApi(): ReservationApi {
  defaultReservationApi ??= new ReservationApi(createApiClient(getDefaultAuthRuntime().session))
  return defaultReservationApi
}
