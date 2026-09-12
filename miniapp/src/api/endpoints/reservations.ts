import type { ApiClient } from '@/api/client'
import { ContractError } from '@/api/errors'
import type { components, operations } from '@/api/schema'

export type ReservationStatus = components['schemas']['ReservationStatus']
export type ReservationStatusFilter = ReservationStatus | null
export type ReservationDayType = components['schemas']['DayType']
export type ReservationRejectionReason = components['schemas']['ReservationRejectionReason']
export type ReservationCancellationReason = components['schemas']['ReservationCancellationReason']
export type ReservationWeekday = components['schemas']['ReservationWeekday']

export interface LabeledValue<Value extends string> {
  readonly value: Value
  readonly label: string
}

export type ReservationCreateRequest = operations[
  'create_reservation_api_v1_reservations_post'
]['requestBody']['content']['application/json']
export type ReservationListRequest = NonNullable<operations[
  'list_reservations_api_v1_reservations_get'
]['parameters']['query']>
export type AdminReservationListRequest = NonNullable<operations[
  'list_admin_reservations_api_v1_admin_reservations_get'
]['parameters']['query']>
export type StoreClosureListRequest = NonNullable<operations[
  'list_store_closures_api_v1_admin_store_closures_get'
]['parameters']['query']>
export type Reservation = components['schemas']['ReservationOut']
export type AdminReservationListItem = components['schemas']['AdminReservationListItemOut']
export type AdminReservationDetail = components['schemas']['AdminReservationDetailOut']
export type ReservationPage = components['schemas']['Page_ReservationOut_']
export type AdminReservationPage = components['schemas']['Page_AdminReservationListItemOut_']
export type ReservationBookingDate = components['schemas']['ReservationBookingDateOut']
export type ReservationBookingOptions = components['schemas']['ReservationBookingOptionsOut']
export type StoreBusinessDay = components['schemas']['StoreBusinessDayOut']
export type StoreClosureMutation = components['schemas']['StoreClosureMutationOut']
export type StoreClosurePage = components['schemas']['Page_StoreBusinessDayOut_']
export type ReservationSettings = components['schemas']['ReservationSettingsOut']
export type WeeklyClosureMutation = components['schemas']['WeeklyClosureMutationOut']

type ReservationApiClient = Pick<ApiClient, 'request' | 'requestWithMeta'>

export class ReservationApi {
  constructor(private readonly client: ReservationApiClient) {}

  async getBookingOptions(experienceOptionId: number): Promise<ReservationBookingOptions> {
    assertPositiveId(experienceOptionId, 'Experience Option ID')
    const operation = 'reservations.bookingOptions'
    const data = await this.client.request<unknown>({
      operation,
      path: '/api/v1/reservations/booking-options',
      auth: 'required',
      query: { experience_option_id: experienceOptionId },
    })
    const parsed = parseReservationBookingOptions(data)
    if (!parsed || parsed.experience_option_id !== experienceOptionId) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async createReservation(request: ReservationCreateRequest): Promise<Reservation> {
    const operation = 'reservations.create'
    const data = await this.client.request<unknown>({
      operation,
      path: '/api/v1/reservations',
      method: 'POST',
      auth: 'required',
      body: projectCreateRequest(request),
    })
    const parsed = parseReservation(data)
    if (!parsed || parsed.status.value !== 'pending' ||
      parsed.experience_option_id !== request.experience_option_id ||
      parsed.reservation_date !== request.reservation_date || parsed.start_time !== request.start_time) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async listReservations(request: ReservationListRequest = {}): Promise<ReservationPage> {
    const operation = 'reservations.list'
    const data = await this.client.request<unknown>({
      operation,
      path: '/api/v1/reservations',
      auth: 'required',
      query: projectListRequest(request),
    })
    const parsed = parsePage(data, parseReservation)
    if (!parsed || !matchesPageRequest(parsed, request) ||
      (request.status !== undefined && request.status !== null &&
        parsed.items.some((item) => item.status.value !== request.status))) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async getReservation(reservationId: number): Promise<Reservation> {
    return this.getReservationAtPath(reservationId, false)
  }

  async cancelReservation(reservationId: number): Promise<Reservation> {
    assertPositiveId(reservationId, 'Reservation ID')
    const operation = 'reservations.cancel'
    const data = await this.client.request<unknown>({
      operation,
      path: `/api/v1/reservations/${reservationId}/cancel`,
      method: 'PATCH',
      auth: 'required',
    })
    const parsed = parseReservation(data)
    if (!parsed || parsed.id !== reservationId || parsed.status.value !== 'cancelled' ||
      parsed.cancellation_reason?.value !== 'customer_request') {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async listAdminReservations(
    request: AdminReservationListRequest = {},
  ): Promise<AdminReservationPage> {
    const operation = 'reservations.admin.list'
    const data = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/reservations',
      auth: 'required',
      query: projectAdminListRequest(request),
    })
    const parsed = parsePage(data, parseAdminReservationListItem)
    if (!parsed || !matchesPageRequest(parsed, request) || parsed.items.some((item) =>
      (request.status !== undefined && request.status !== null && item.status.value !== request.status) ||
      (request.business_date !== undefined && request.business_date !== null &&
        item.reservation_date !== request.business_date) ||
      (request.user_id !== undefined && request.user_id !== null && item.user_id !== request.user_id) ||
      (request.product_id !== undefined && request.product_id !== null && item.product_id !== request.product_id))) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async getAdminReservation(reservationId: number): Promise<AdminReservationDetail> {
    assertPositiveId(reservationId, 'Reservation ID')
    const operation = 'reservations.admin.detail'
    const data = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/reservations/${reservationId}`,
      auth: 'required',
    })
    const parsed = parseAdminReservationDetail(data)
    if (!parsed || parsed.id !== reservationId) throw new ContractError({ operation })
    return parsed
  }

  async confirmReservation(reservationId: number): Promise<Reservation> {
    return this.transitionAdminReservation(reservationId, 'confirm', 'confirmed')
  }

  async rejectReservation(reservationId: number): Promise<Reservation> {
    const reservation = await this.transitionAdminReservation(reservationId, 'reject', 'rejected')
    if (reservation.rejection_reason?.value !== 'no_capacity') {
      throw new ContractError({ operation: 'reservations.admin.reject' })
    }
    return reservation
  }

  async listStoreClosures(request: StoreClosureListRequest = {}): Promise<StoreClosurePage> {
    const operation = 'reservations.admin.storeClosures.list'
    const data = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/store-closures',
      auth: 'required',
      query: projectStoreClosureListRequest(request),
    })
    const parsed = parsePage(data, parseStoreBusinessDay)
    const expectedClosed = request.is_closed ?? true
    const isExactDateRequest = request.date_from !== undefined && request.date_from !== null &&
      request.date_from === request.date_to
    if (!parsed || !matchesPageRequest(parsed, request) || parsed.items.some((item, index) =>
      item.is_closed !== expectedClosed ||
      (request.date_from !== undefined && request.date_from !== null && item.business_date < request.date_from) ||
      (request.date_to !== undefined && request.date_to !== null && item.business_date > request.date_to) ||
      (index > 0 && item.business_date <= parsed.items[index - 1].business_date)) ||
      (isExactDateRequest && (parsed.total > 1 || parsed.items.length !== parsed.total))) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async getReservationSettings(): Promise<ReservationSettings> {
    const operation = 'reservations.admin.settings.get'
    const data = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/reservation-settings',
      auth: 'required',
    })
    const parsed = parseReservationSettings(data)
    if (!parsed) throw new ContractError({ operation })
    return parsed
  }

  async updateWeeklyClosedDay(
    weeklyClosedWeekday: ReservationWeekday,
  ): Promise<WeeklyClosureMutation> {
    const operation = 'reservations.admin.settings.weeklyClosedDay.update'
    const data = await this.client.request<unknown>({
      operation,
      path: '/api/v1/admin/reservation-settings/weekly-closed-day',
      method: 'PUT',
      auth: 'required',
      body: { weekly_closed_weekday: weeklyClosedWeekday },
    })
    const parsed = parseWeeklyClosureMutation(data)
    if (!parsed || parsed.weekly_closed_weekday.value !== weeklyClosedWeekday) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  async closeStoreDay(businessDate: string): Promise<StoreClosureMutation> {
    if (!isDate(businessDate)) throw new Error('营业日期必须使用有效的 YYYY-MM-DD')
    const operation = 'reservations.admin.storeClosures.close'
    const response = await this.client.requestWithMeta<unknown>({
      operation,
      path: `/api/v1/admin/store-closures/${businessDate}`,
      method: 'PUT',
      auth: 'required',
    })
    const parsed = parseStoreClosureMutation(response.data)
    const expectedStatus = parsed?.is_replay ? 200 : 201
    if (!parsed || parsed.business_date !== businessDate || !parsed.is_closed ||
      response.statusCode !== expectedStatus) {
      throw new ContractError({ operation, statusCode: response.statusCode })
    }
    return parsed
  }

  async reopenStoreDay(businessDate: string): Promise<StoreClosureMutation> {
    return this.mutateStoreDay(businessDate)
  }

  private async getReservationAtPath(reservationId: number, admin: boolean): Promise<Reservation> {
    assertPositiveId(reservationId, 'Reservation ID')
    const operation = admin ? 'reservations.admin.detail' : 'reservations.detail'
    const data = await this.client.request<unknown>({
      operation,
      path: admin
        ? `/api/v1/admin/reservations/${reservationId}`
        : `/api/v1/reservations/${reservationId}`,
      auth: 'required',
    })
    const parsed = parseReservation(data)
    if (!parsed || parsed.id !== reservationId) throw new ContractError({ operation })
    return parsed
  }

  private async transitionAdminReservation(
    reservationId: number,
    action: 'confirm' | 'reject',
    targetStatus: 'confirmed' | 'rejected',
  ): Promise<Reservation> {
    assertPositiveId(reservationId, 'Reservation ID')
    const operation = `reservations.admin.${action}`
    const data = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/reservations/${reservationId}/${action}`,
      method: 'PATCH',
      auth: 'required',
    })
    const parsed = parseReservation(data)
    if (!parsed || parsed.id !== reservationId || parsed.status.value !== targetStatus) {
      throw new ContractError({ operation })
    }
    return parsed
  }

  private async mutateStoreDay(
    businessDate: string,
  ): Promise<StoreClosureMutation> {
    if (!isDate(businessDate)) throw new Error('营业日期必须使用有效的 YYYY-MM-DD')
    const operation = 'reservations.admin.storeClosures.reopen'
    const data = await this.client.request<unknown>({
      operation,
      path: `/api/v1/admin/store-closures/${businessDate}`,
      method: 'DELETE',
      auth: 'required',
    })
    const parsed = parseStoreClosureMutation(data)
    if (!parsed || parsed.business_date !== businessDate || parsed.is_closed || parsed.is_replay ||
      parsed.newly_cancelled_count !== 0 ||
      parsed.cancelled_pending_count !== 0 || parsed.cancelled_confirmed_count !== 0) {
      throw new ContractError({ operation })
    }
    return parsed
  }
}

function projectCreateRequest(request: ReservationCreateRequest): ReservationCreateRequest {
  return {
    experience_option_id: request.experience_option_id,
    reservation_date: request.reservation_date,
    start_time: request.start_time,
  }
}

function projectListRequest(request: ReservationListRequest): Record<string, string | number> {
  return {
    ...(request.page === undefined ? {} : { page: request.page }),
    ...(request.page_size === undefined ? {} : { page_size: request.page_size }),
    ...(request.status === undefined || request.status === null ? {} : { status: request.status }),
  }
}

function projectAdminListRequest(request: AdminReservationListRequest): Record<string, string | number> {
  return {
    ...projectListRequest(request),
    ...(request.business_date === undefined || request.business_date === null
      ? {}
      : { business_date: request.business_date }),
    ...(request.user_id === undefined || request.user_id === null ? {} : { user_id: request.user_id }),
    ...(request.product_id === undefined || request.product_id === null
      ? {}
      : { product_id: request.product_id }),
  }
}

function projectStoreClosureListRequest(
  request: StoreClosureListRequest,
): Record<string, string | number | boolean> {
  return {
    ...(request.page === undefined ? {} : { page: request.page }),
    ...(request.page_size === undefined ? {} : { page_size: request.page_size }),
    ...(request.date_from === undefined || request.date_from === null ? {} : { date_from: request.date_from }),
    ...(request.date_to === undefined || request.date_to === null ? {} : { date_to: request.date_to }),
    ...(request.is_closed === undefined || request.is_closed === null ? {} : { is_closed: request.is_closed }),
  }
}

export function parseReservation(value: unknown): Reservation | undefined {
  if (!isRecord(value) || !(
    isPositiveInteger(value.id) &&
    isPositiveInteger(value.product_id) &&
    isPositiveInteger(value.experience_option_id) &&
    isBoundedText(value.product_name, 100) &&
    isPositiveInteger(value.duration_minutes) &&
    isPositiveInteger(value.participants) &&
    isMoney(value.price) &&
    isDate(value.reservation_date) &&
    isStartTime(value.start_time) &&
    isClockTime(value.end_time) &&
    isUtcDatetime(value.scheduled_start_at) &&
    isUtcDatetime(value.scheduled_end_at) &&
    isUtcDatetime(value.cancellation_deadline_at) &&
    isNullableUtcDatetime(value.confirmed_at) &&
    isNullableUtcDatetime(value.rejected_at) &&
    isNullableUtcDatetime(value.cancelled_at) &&
    isUtcDatetime(value.created_at) &&
    isUtcDatetime(value.updated_at)
  )) return undefined

  const dayType = parseDayType(value.day_type)
  const status = parseStatus(value.status)
  const rejectionReason = parseRejectionReason(value.rejection_reason)
  const cancellationReason = parseCancellationReason(value.cancellation_reason)
  if (!dayType || !status || rejectionReason === undefined || cancellationReason === undefined) return undefined

  const stateFieldsValid = validateStateFields({
    status: status.value,
    rejectionReason,
    cancellationReason,
    customerMessage: value.customer_message,
    confirmedAt: value.confirmed_at,
    rejectedAt: value.rejected_at,
    cancelledAt: value.cancelled_at,
  })
  const startMs = Date.parse(value.scheduled_start_at)
  const endMs = Date.parse(value.scheduled_end_at)
  const deadlineMs = Date.parse(value.cancellation_deadline_at)
  const localStart = shanghaiDateAndTime(startMs)
  const localEnd = shanghaiDateAndTime(endMs)
  if (!stateFieldsValid || endMs - startMs !== value.duration_minutes * 60_000 ||
    startMs - deadlineMs !== 3 * 60 * 60_000 ||
    localStart.date !== value.reservation_date || localStart.time !== value.start_time ||
    localEnd.date !== value.reservation_date || localEnd.time !== value.end_time) return undefined

  return {
    id: value.id,
    product_id: value.product_id,
    experience_option_id: value.experience_option_id,
    product_name: value.product_name,
    duration_minutes: value.duration_minutes,
    participants: value.participants,
    day_type: dayType,
    price: value.price,
    status,
    rejection_reason: rejectionReason,
    cancellation_reason: cancellationReason,
    customer_message: value.customer_message as string,
    reservation_date: value.reservation_date,
    start_time: value.start_time,
    end_time: value.end_time,
    scheduled_start_at: value.scheduled_start_at,
    scheduled_end_at: value.scheduled_end_at,
    cancellation_deadline_at: value.cancellation_deadline_at,
    confirmed_at: value.confirmed_at,
    rejected_at: value.rejected_at,
    cancelled_at: value.cancelled_at,
    created_at: value.created_at,
    updated_at: value.updated_at,
  }
}

export function parseReservationBookingOptions(value: unknown): ReservationBookingOptions | undefined {
  if (!isRecord(value) || !(
    isPositiveInteger(value.experience_option_id) &&
    isPositiveInteger(value.product_id) &&
    isBoundedText(value.product_name, 100) &&
    isPositiveInteger(value.duration_minutes) &&
    isPositiveInteger(value.participants) &&
    isMoney(value.price) &&
    value.timezone === 'Asia/Shanghai' &&
    isUtcDatetime(value.server_now) &&
    isDate(value.booking_window_end_date) &&
    value.minimum_lead_hours === 3 &&
    value.slot_interval_minutes === 30 &&
    value.booking_window_days === 30 &&
    value.opens_at === '11:00' &&
    value.closes_at === '20:00' &&
    Array.isArray(value.dates)
  )) return undefined
  const dayType = parseDayType(value.day_type)
  const weeklyClosedWeekday = parseWeekday(value.weekly_closed_weekday)
  const dates = value.dates.map(parseBookingDate)
  if (!dayType || !weeklyClosedWeekday || dates.some((item) => item === undefined)) return undefined
  const parsedDates = dates as ReservationBookingDate[]
  const bookingWindowEndDate = value.booking_window_end_date as string
  const durationMinutes = value.duration_minutes as number
  const serverNowMs = Date.parse(value.server_now)
  const serverBusinessDate = shanghaiDateAndTime(serverNowMs).date
  if (bookingWindowEndDate !== addDays(serverBusinessDate, 30) ||
    new Set(parsedDates.map((item) => item.date)).size !== parsedDates.length ||
    parsedDates.some((item, index) =>
      (index > 0 && item.date <= parsedDates[index - 1].date) ||
      !isLegalBookingDate(item, dayType.value, durationMinutes, serverNowMs, bookingWindowEndDate))) {
    return undefined
  }
  return {
    experience_option_id: value.experience_option_id,
    product_id: value.product_id,
    product_name: value.product_name,
    duration_minutes: durationMinutes,
    participants: value.participants,
    day_type: dayType,
    price: value.price,
    timezone: 'Asia/Shanghai',
    server_now: value.server_now,
    booking_window_end_date: bookingWindowEndDate,
    weekly_closed_weekday: weeklyClosedWeekday,
    minimum_lead_hours: 3,
    slot_interval_minutes: 30,
    booking_window_days: 30,
    opens_at: '11:00',
    closes_at: '20:00',
    dates: parsedDates,
  }
}

function parseBookingDate(value: unknown): ReservationBookingDate | undefined {
  if (!isRecord(value) || !isDate(value.date) || !Array.isArray(value.start_times) ||
    value.start_times.length === 0 || value.start_times.some((item) => !isStartTime(item))) return undefined
  const dayType = parseDayType(value.day_type)
  const startTimes = value.start_times as string[]
  if (!dayType || new Set(startTimes).size !== startTimes.length ||
    startTimes.some((item, index) => index > 0 && item <= startTimes[index - 1])) return undefined
  return { date: value.date, day_type: dayType, start_times: startTimes }
}

function parseAdminReservationListItem(value: unknown): AdminReservationListItem | undefined {
  const reservation = parseReservation(value)
  if (!reservation || !isRecord(value) || !isPositiveInteger(value.user_id) ||
    !isBoundedText(value.user_nickname, 32) ||
    !(value.user_phone_masked === null ||
      (typeof value.user_phone_masked === 'string' && /^1[3-9]\d\*{4}\d{4}$/.test(value.user_phone_masked)))) {
    return undefined
  }
  return {
    ...reservation,
    user_id: value.user_id,
    user_nickname: value.user_nickname,
    user_phone_masked: value.user_phone_masked,
  }
}

function parseAdminReservationDetail(value: unknown): AdminReservationDetail | undefined {
  const reservation = parseReservation(value)
  if (!reservation || !isRecord(value) || !isPositiveInteger(value.user_id) ||
    !isBoundedText(value.user_nickname, 32) ||
    !(value.user_phone === null ||
      (typeof value.user_phone === 'string' && /^1[3-9]\d{9}$/.test(value.user_phone)))) {
    return undefined
  }
  return {
    ...reservation,
    user_id: value.user_id,
    user_nickname: value.user_nickname,
    user_phone: value.user_phone,
  }
}

function parseStoreBusinessDay(value: unknown): StoreBusinessDay | undefined {
  if (!isRecord(value) || !isPositiveInteger(value.id) || !isDate(value.business_date) ||
    typeof value.is_closed !== 'boolean' || !isUtcDatetime(value.created_at) ||
    !isUtcDatetime(value.updated_at)) return undefined
  return {
    id: value.id,
    business_date: value.business_date,
    is_closed: value.is_closed,
    created_at: value.created_at,
    updated_at: value.updated_at,
  }
}

function parseStoreClosureMutation(value: unknown): StoreClosureMutation | undefined {
  const day = parseStoreBusinessDay(value)
  if (!day || !isRecord(value) || !isNonNegativeInteger(value.newly_cancelled_count) ||
    !isNonNegativeInteger(value.cancelled_pending_count) ||
    !isNonNegativeInteger(value.cancelled_confirmed_count) || typeof value.is_replay !== 'boolean' ||
    value.newly_cancelled_count !== value.cancelled_pending_count + value.cancelled_confirmed_count ||
    (value.is_replay && value.newly_cancelled_count !== 0)) return undefined
  return {
    ...day,
    newly_cancelled_count: value.newly_cancelled_count,
    cancelled_pending_count: value.cancelled_pending_count,
    cancelled_confirmed_count: value.cancelled_confirmed_count,
    is_replay: value.is_replay,
  }
}

function parseReservationSettings(value: unknown): ReservationSettings | undefined {
  if (!isRecord(value) || !isUtcDatetime(value.updated_at)) return undefined
  const weeklyClosedWeekday = parseWeekday(value.weekly_closed_weekday)
  if (!weeklyClosedWeekday) return undefined
  return {
    weekly_closed_weekday: weeklyClosedWeekday,
    updated_at: value.updated_at,
  }
}

function parseWeeklyClosureMutation(value: unknown): WeeklyClosureMutation | undefined {
  const settings = parseReservationSettings(value)
  if (!settings || !isRecord(value) ||
    !isNonNegativeInteger(value.newly_cancelled_count) ||
    !isNonNegativeInteger(value.cancelled_pending_count) ||
    !isNonNegativeInteger(value.cancelled_confirmed_count) ||
    typeof value.is_replay !== 'boolean' ||
    value.newly_cancelled_count !== value.cancelled_pending_count + value.cancelled_confirmed_count ||
    (value.is_replay && value.newly_cancelled_count !== 0)) return undefined
  const previous = parseWeekday(value.previous_weekly_closed_weekday)
  if (!previous) return undefined
  return {
    ...settings,
    previous_weekly_closed_weekday: previous,
    newly_cancelled_count: value.newly_cancelled_count,
    cancelled_pending_count: value.cancelled_pending_count,
    cancelled_confirmed_count: value.cancelled_confirmed_count,
    is_replay: value.is_replay,
  }
}

function parsePage<T>(
  value: unknown,
  parser: (item: unknown) => T | undefined,
): { readonly items: readonly T[]; readonly total: number; readonly page: number; readonly page_size: number; readonly pages: number } | undefined {
  if (!isRecord(value) || !Array.isArray(value.items) || !isNonNegativeInteger(value.total) ||
    !isPositiveInteger(value.page) || !isPositiveInteger(value.page_size) || value.page_size > 100 ||
    !isNonNegativeInteger(value.pages) || value.pages !== Math.ceil(value.total / value.page_size)) return undefined
  const items = value.items.map(parser)
  if (items.some((item) => item === undefined) || items.length > value.page_size ||
    items.length > value.total) return undefined
  return {
    items: items as T[],
    total: value.total,
    page: value.page,
    page_size: value.page_size,
    pages: value.pages,
  }
}

function matchesPageRequest(
  page: { readonly page: number; readonly page_size: number },
  request: { readonly page?: number; readonly page_size?: number },
): boolean {
  return page.page === (request.page ?? 1) && page.page_size === (request.page_size ?? 20)
}

function parseStatus(value: unknown): LabeledValue<ReservationStatus> | undefined {
  const labels: Record<ReservationStatus, string> = {
    pending: '待门店确认', confirmed: '已确认', rejected: '未能确认', cancelled: '已取消',
  }
  return parseLabeled(value, labels)
}

function parseDayType(value: unknown): LabeledValue<ReservationDayType> | undefined {
  return parseLabeled(value, { weekday: '工作日', holiday: '节假日' })
}

function parseWeekday(value: unknown): LabeledValue<ReservationWeekday> | undefined {
  return parseLabeled(value, {
    monday: '周一', tuesday: '周二', wednesday: '周三', thursday: '周四',
    friday: '周五', saturday: '周六', sunday: '周日',
  })
}

function parseRejectionReason(
  value: unknown,
): LabeledValue<ReservationRejectionReason> | null | undefined {
  if (value === null) return null
  return parseLabeled(value, { no_capacity: '当前时段无空位' })
}

function parseCancellationReason(
  value: unknown,
): LabeledValue<ReservationCancellationReason> | null | undefined {
  if (value === null) return null
  return parseLabeled(value, { customer_request: '顾客取消', store_closed: '门店店休' })
}

function parseLabeled<Value extends string>(
  value: unknown,
  labels: Readonly<Record<Value, string>>,
): LabeledValue<Value> | undefined {
  if (!isRecord(value) || typeof value.value !== 'string' || !(value.value in labels) ||
    value.label !== labels[value.value as Value]) return undefined
  return { value: value.value as Value, label: value.label as string }
}

function validateStateFields(input: {
  status: ReservationStatus
  rejectionReason: LabeledValue<ReservationRejectionReason> | null
  cancellationReason: LabeledValue<ReservationCancellationReason> | null
  customerMessage: unknown
  confirmedAt: unknown
  rejectedAt: unknown
  cancelledAt: unknown
}): boolean {
  const messages = {
    pending: '预约已提交，正在等待门店确认。',
    confirmed: '预约已确认，请按预约时间到店。费用以预约时价格为准，到店支付。',
    rejected: '很抱歉，您选择的时段当前已无空位，本次预约未能确认。您可以选择其他日期或时段重新预约。',
    customer_request: '本次预约已取消。您可以选择其他日期或时段重新预约。',
    store_closed: '门店当天休息，本次预约已由门店取消。给您带来不便，敬请谅解；您可以选择其他日期重新预约，如需帮助请联系门店。',
  } as const
  if (input.status === 'pending') {
    return input.rejectionReason === null && input.cancellationReason === null &&
      input.confirmedAt === null && input.rejectedAt === null && input.cancelledAt === null &&
      input.customerMessage === messages.pending
  }
  if (input.status === 'confirmed') {
    return input.rejectionReason === null && input.cancellationReason === null &&
      input.confirmedAt !== null && input.rejectedAt === null && input.cancelledAt === null &&
      input.customerMessage === messages.confirmed
  }
  if (input.status === 'rejected') {
    return input.rejectionReason?.value === 'no_capacity' && input.cancellationReason === null &&
      input.confirmedAt === null && input.rejectedAt !== null && input.cancelledAt === null &&
      input.customerMessage === messages.rejected
  }
  return input.rejectionReason === null && input.cancellationReason !== null &&
    input.rejectedAt === null && input.cancelledAt !== null &&
    input.customerMessage === messages[input.cancellationReason.value]
}

function assertPositiveId(value: number, label: string): void {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${label} 必须是正安全整数`)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function isBoundedText(value: unknown, max: number): value is string {
  return typeof value === 'string' && value.length >= 1 && value.length <= max
}

function isMoney(value: unknown): value is string {
  if (typeof value !== 'string') return false
  const match = /^(0|[1-9]\d{0,4})\.(\d{2})$/.exec(value)
  if (!match || value === '0.00') return false
  const whole = Number(match[1])
  return whole < 99_999 || match[2] === '00'
}

function isDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
}

function isStartTime(value: unknown): value is string {
  return typeof value === 'string' && /^(?:[01]\d|2[0-3]):(?:00|30)$/.test(value)
}

function isClockTime(value: unknown): value is string {
  return typeof value === 'string' && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value)
}

function isUtcDatetime(value: unknown): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value) &&
    !Number.isNaN(Date.parse(value))
}

function isNullableUtcDatetime(value: unknown): value is string | null {
  return value === null || isUtcDatetime(value)
}

function shanghaiDateAndTime(timestamp: number): { readonly date: string; readonly time: string } {
  const local = new Date(timestamp + 8 * 60 * 60 * 1_000).toISOString()
  return { date: local.slice(0, 10), time: local.slice(11, 16) }
}

function addDays(date: string, days: number): string {
  const [year, month, day] = date.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10)
}

function isLegalBookingDate(
  item: ReservationBookingDate,
  optionDayType: ReservationDayType,
  durationMinutes: number,
  serverNowMs: number,
  bookingWindowEndDate: string,
): boolean {
  if (item.date < shanghaiDateAndTime(serverNowMs).date || item.date > bookingWindowEndDate ||
    item.day_type.value !== optionDayType) return false
  const weekday = new Date(`${item.date}T00:00:00Z`).getUTCDay()
  const expectedDayType = weekday >= 2 && weekday <= 5
    ? 'weekday'
    : weekday === 0 || weekday === 6
      ? 'holiday'
      : undefined
  if (expectedDayType !== optionDayType) return false
  return item.start_times.every((time) => {
    const [hour, minute] = time.split(':').map(Number)
    const startMinute = hour * 60 + minute
    const startMs = Date.parse(`${item.date}T${time}:00+08:00`)
    return startMinute >= 11 * 60 && startMinute + durationMinutes <= 20 * 60 &&
      startMs >= serverNowMs + 3 * 60 * 60_000
  })
}
