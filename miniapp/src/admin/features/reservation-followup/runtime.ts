import { createApiClient } from '@/api'
import { ReservationFollowupApi } from '@/api/endpoints/reservation_followups'
import { getDefaultAuthRuntime } from '@/auth/runtime'

export const FOLLOWUP_PATH = '/admin/pages/reservation-followups/index'
let api: ReservationFollowupApi | undefined
export function getFollowupApi(): ReservationFollowupApi {
  api ??= new ReservationFollowupApi(createApiClient(getDefaultAuthRuntime().session))
  return api
}
