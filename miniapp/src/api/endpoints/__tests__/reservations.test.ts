import { ApiClient } from '@/api/client'
import { ContractError, TimeoutError } from '@/api/errors'
import type {
  AuthSession,
  HttpTransport,
  TransportRequest,
  TransportResponse,
} from '@/api/types'

import {
  ReservationApi,
  type Reservation,
  type ReservationBookingOptions,
} from '../reservations'

const pendingReservation: Reservation = {
  id: 31,
  product_id: 7,
  experience_option_id: 12,
  product_name: '周末拼豆体验',
  duration_minutes: 60,
  participants: 2,
  day_type: { value: 'holiday', label: '节假日' },
  price: '299.00',
  status: { value: 'pending', label: '待门店确认' },
  rejection_reason: null,
  cancellation_reason: null,
  customer_message: '预约已提交，正在等待门店确认。',
  reservation_date: '2026-09-06',
  start_time: '15:00',
  end_time: '16:00',
  scheduled_start_at: '2026-09-06T07:00:00Z',
  scheduled_end_at: '2026-09-06T08:00:00Z',
  cancellation_deadline_at: '2026-09-06T04:00:00Z',
  confirmed_at: null,
  rejected_at: null,
  cancelled_at: null,
  created_at: '2026-09-06T01:00:00Z',
  updated_at: '2026-09-06T01:00:00Z',
}

const bookingOptions: ReservationBookingOptions = {
  experience_option_id: 12,
  product_id: 7,
  product_name: '周末拼豆体验',
  duration_minutes: 60,
  participants: 2,
  day_type: { value: 'holiday', label: '节假日' },
  price: '299.00',
  timezone: 'Asia/Shanghai',
  server_now: '2026-09-06T03:05:00Z',
  booking_window_end_date: '2026-10-06',
  weekly_closed_weekday: { value: 'monday', label: '周一' },
  minimum_lead_hours: 3,
  slot_interval_minutes: 30,
  booking_window_days: 30,
  opens_at: '11:00',
  closes_at: '20:00',
  dates: [{
    date: '2026-09-06',
    day_type: { value: 'holiday', label: '节假日' },
    start_times: ['14:30', '15:00'],
  }],
}

class FakeTransport implements HttpTransport {
  readonly requests: TransportRequest[] = []

  constructor(private readonly data: unknown, private readonly statusCode = 200) {}

  async request(request: TransportRequest): Promise<TransportResponse> {
    this.requests.push(request)
    return {
      statusCode: this.statusCode,
      headers: {},
      data: { code: 0, message: 'success', data: this.data },
    }
  }
}

function createApi(transport: HttpTransport): ReservationApi {
  const authSession: AuthSession = {
    getAccessToken: () => 'access-token',
    refreshAccessToken: jest.fn(async () => undefined),
    clearSession: jest.fn(),
  }
  return new ReservationApi(new ApiClient({
    baseUrl: 'https://api.example.com',
    transport,
    authSession,
  }))
}

describe('ReservationApi customer endpoints', () => {
  it('读取服务端生成的半小时时段并严格校验固定规则', async () => {
    const transport = new FakeTransport(bookingOptions)
    await expect(createApi(transport).getBookingOptions(12)).resolves.toEqual(bookingOptions)
    expect(transport.requests[0]).toMatchObject({
      operation: 'reservations.bookingOptions',
      method: 'GET',
      url: 'https://api.example.com/api/v1/reservations/booking-options?experience_option_id=12',
      headers: { Authorization: 'Bearer access-token' },
    })

    await expect(createApi(new FakeTransport({
      ...bookingOptions,
      slot_interval_minutes: 15,
    })).getBookingOptions(12)).rejects.toBeInstanceOf(ContractError)

    await expect(createApi(new FakeTransport({
      ...bookingOptions,
      booking_window_end_date: '2026-10-05',
    })).getBookingOptions(12)).rejects.toBeInstanceOf(ContractError)

    await expect(createApi(new FakeTransport({
      ...bookingOptions,
      dates: [{
        ...bookingOptions.dates[0],
        start_times: ['14:00'],
      }],
    })).getBookingOptions(12)).rejects.toBeInstanceOf(ContractError)

    await expect(createApi(new FakeTransport({
      ...bookingOptions,
      dates: [
        { ...bookingOptions.dates[0], date: '2026-09-12' },
        bookingOptions.dates[0],
      ],
    })).getBookingOptions(12)).rejects.toBeInstanceOf(ContractError)
  })

  it('创建预约只发送 Option、本地日期和开始时间', async () => {
    const transport = new FakeTransport({ ...pendingReservation, internal_note: 'hidden' }, 201)
    await expect(createApi(transport).createReservation({
      experience_option_id: 12,
      reservation_date: '2026-09-06',
      start_time: '15:00',
      price: '1.00',
    } as never)).resolves.toEqual(pendingReservation)
    expect(transport.requests[0]).toMatchObject({
      method: 'POST',
      url: 'https://api.example.com/api/v1/reservations',
      body: {
        experience_option_id: 12,
        reservation_date: '2026-09-06',
        start_time: '15:00',
      },
    })
  })

  it('取消发送无 body PATCH 并只接受 customer_request', async () => {
    const cancelled: Reservation = {
      ...pendingReservation,
      status: { value: 'cancelled', label: '已取消' },
      cancellation_reason: { value: 'customer_request', label: '顾客取消' },
      customer_message: '本次预约已取消。您可以选择其他日期或时段重新预约。',
      cancelled_at: '2026-09-06T02:00:00Z',
      updated_at: '2026-09-06T02:00:00Z',
    }
    const transport = new FakeTransport(cancelled)
    await expect(createApi(transport).cancelReservation(31)).resolves.toEqual(cancelled)
    expect(transport.requests[0]).toMatchObject({
      method: 'PATCH',
      url: 'https://api.example.com/api/v1/reservations/31/cancel',
    })
    expect(transport.requests[0].body).toBeUndefined()
  })

  it('拒绝状态与原因、时间或顾客文案不一致的响应', async () => {
    await expect(createApi(new FakeTransport({
      ...pendingReservation,
      status: { value: 'rejected', label: '未能确认' },
      rejection_reason: null,
      customer_message: '随意文案',
    })).getReservation(31)).rejects.toBeInstanceOf(ContractError)
  })

  it('把选项、创建和详情响应关联回本次请求', async () => {
    await expect(createApi(new FakeTransport({
      ...bookingOptions,
      experience_option_id: 13,
    })).getBookingOptions(12)).rejects.toBeInstanceOf(ContractError)

    await expect(createApi(new FakeTransport({
      ...pendingReservation,
      reservation_date: '2026-09-12',
      scheduled_start_at: '2026-09-12T07:00:00Z',
      scheduled_end_at: '2026-09-12T08:00:00Z',
      cancellation_deadline_at: '2026-09-12T04:00:00Z',
    })).createReservation({
      experience_option_id: 12,
      reservation_date: '2026-09-06',
      start_time: '15:00',
    })).rejects.toBeInstanceOf(ContractError)

    await expect(createApi(new FakeTransport({
      ...pendingReservation,
      id: 32,
    })).getReservation(31)).rejects.toBeInstanceOf(ContractError)
  })

  it('列表响应必须匹配本次分页和状态筛选', async () => {
    const page = {
      items: [pendingReservation],
      total: 1,
      page: 1,
      page_size: 20,
      pages: 1,
    }
    await expect(createApi(new FakeTransport(page)).listReservations({
      page: 2,
      page_size: 20,
    })).rejects.toBeInstanceOf(ContractError)
    await expect(createApi(new FakeTransport(page)).listReservations({
      status: 'confirmed',
    })).rejects.toBeInstanceOf(ContractError)
  })

  it('创建请求超时只发送一次，不盲目重试', async () => {
    const requests: TransportRequest[] = []
    const transport: HttpTransport = {
      request: jest.fn(async (request) => {
        requests.push(request)
        throw new TimeoutError({ operation: request.operation }, new Error('timeout'))
      }),
    }
    await expect(createApi(transport).createReservation({
      experience_option_id: 12,
      reservation_date: '2026-09-06',
      start_time: '15:00',
    })).rejects.toBeInstanceOf(TimeoutError)
    expect(requests).toHaveLength(1)
  })
})

describe('ReservationApi admin endpoints', () => {
  it('管理列表使用筛选白名单，列表只接受掩码手机号', async () => {
    const page = {
      items: [{
        ...pendingReservation,
        user_id: 9,
        user_nickname: '拼豆顾客',
        user_phone_masked: '138****8000',
        user_phone: '13800138000',
      }],
      total: 1,
      page: 1,
      page_size: 20,
      pages: 1,
    }
    const transport = new FakeTransport(page)
    const result = await createApi(transport).listAdminReservations({
      status: 'pending',
      business_date: '2026-09-06',
      user_id: 9,
      product_id: 7,
      ignored: 'hidden',
    } as never)
    expect(result.items[0].user_phone_masked).toBe('138****8000')
    expect(result.items[0]).not.toHaveProperty('user_phone')
    expect(transport.requests[0].url).toContain('status=pending')
    expect(transport.requests[0].url).toContain('business_date=2026-09-06')
    expect(transport.requests[0].url).not.toContain('ignored')

    await expect(createApi(new FakeTransport(page)).listAdminReservations({ user_id: 10 }))
      .rejects.toBeInstanceOf(ContractError)
  })

  it('确认与拒绝发送无 body PATCH 并检查目标状态', async () => {
    const confirmed: Reservation = {
      ...pendingReservation,
      status: { value: 'confirmed', label: '已确认' },
      customer_message: '预约已确认，请按预约时间到店。费用以预约时价格为准，到店支付。',
      confirmed_at: '2026-09-06T02:00:00Z',
    }
    const rejected: Reservation = {
      ...pendingReservation,
      status: { value: 'rejected', label: '未能确认' },
      rejection_reason: { value: 'no_capacity', label: '当前时段无空位' },
      customer_message: '很抱歉，您选择的时段当前已无空位，本次预约未能确认。您可以选择其他日期或时段重新预约。',
      rejected_at: '2026-09-06T02:00:00Z',
    }
    const confirmTransport = new FakeTransport(confirmed)
    const rejectTransport = new FakeTransport(rejected)
    await createApi(confirmTransport).confirmReservation(31)
    await createApi(rejectTransport).rejectReservation(31)
    expect(confirmTransport.requests[0].body).toBeUndefined()
    expect(rejectTransport.requests[0].body).toBeUndefined()

    await expect(createApi(new FakeTransport({ ...confirmed, id: 32 })).confirmReservation(31))
      .rejects.toBeInstanceOf(ContractError)
    await expect(createApi(new FakeTransport({
      ...pendingReservation,
      id: 32,
      user_id: 9,
      user_nickname: '拼豆顾客',
      user_phone: '13800138000',
    })).getAdminReservation(31)).rejects.toBeInstanceOf(ContractError)
  })

  it('店休写入无 body，校验批量计数并区分关闭与恢复', async () => {
    const closed = {
      id: 3,
      business_date: '2026-09-08',
      is_closed: true,
      created_at: '2026-09-06T02:00:00Z',
      updated_at: '2026-09-06T02:00:00Z',
      newly_cancelled_count: 3,
      cancelled_pending_count: 2,
      cancelled_confirmed_count: 1,
      is_replay: false,
    }
    const transport = new FakeTransport(closed, 201)
    await expect(createApi(transport).closeStoreDay('2026-09-08')).resolves.toEqual(closed)
    expect(transport.requests[0]).toMatchObject({
      method: 'PUT',
      url: 'https://api.example.com/api/v1/admin/store-closures/2026-09-08',
    })
    expect(transport.requests[0].body).toBeUndefined()

    const replay = {
      ...closed,
      newly_cancelled_count: 0,
      cancelled_pending_count: 0,
      cancelled_confirmed_count: 0,
      is_replay: true,
    }
    await expect(createApi(new FakeTransport(replay, 200)).closeStoreDay('2026-09-08'))
      .resolves.toEqual(replay)
    await expect(createApi(new FakeTransport(closed, 200)).closeStoreDay('2026-09-08'))
      .rejects.toBeInstanceOf(ContractError)

    await expect(createApi(new FakeTransport({
      ...closed,
      newly_cancelled_count: 2,
    })).closeStoreDay('2026-09-08')).rejects.toBeInstanceOf(ContractError)

    const reopened = {
      ...closed,
      is_closed: false,
      newly_cancelled_count: 0,
      cancelled_pending_count: 0,
      cancelled_confirmed_count: 0,
      is_replay: false,
    }
    const reopenTransport = new FakeTransport(reopened)
    await expect(createApi(reopenTransport).reopenStoreDay('2026-09-08')).resolves.toEqual(reopened)
    expect(reopenTransport.requests[0].method).toBe('DELETE')
    expect(reopenTransport.requests[0].body).toBeUndefined()
    await expect(createApi(new FakeTransport({
      ...reopened,
      newly_cancelled_count: 1,
      cancelled_pending_count: 1,
    })).reopenStoreDay('2026-09-08')).rejects.toBeInstanceOf(ContractError)
    await expect(createApi(new FakeTransport({
      ...reopened,
      is_replay: true,
    })).reopenStoreDay('2026-09-08')).rejects.toBeInstanceOf(ContractError)
    await expect(createApi(new FakeTransport({
      ...closed,
      business_date: '2026-09-09',
    }, 201)).closeStoreDay('2026-09-08')).rejects.toBeInstanceOf(ContractError)
  })

  it('店休日筛选响应必须与请求的 is_closed 一致', async () => {
    const page = {
      items: [{
        id: 3,
        business_date: '2026-09-08',
        is_closed: false,
        created_at: '2026-09-06T02:00:00Z',
        updated_at: '2026-09-06T02:00:00Z',
      }],
      total: 1,
      page: 1,
      page_size: 20,
      pages: 1,
    }
    await expect(createApi(new FakeTransport(page)).listStoreClosures({ is_closed: true }))
      .rejects.toBeInstanceOf(ContractError)

    await expect(createApi(new FakeTransport({
      ...page,
      items: [{ ...page.items[0], is_closed: true }],
      total: 2,
      pages: 1,
    })).listStoreClosures({
      date_from: '2026-09-08',
      date_to: '2026-09-08',
      is_closed: true,
    })).rejects.toBeInstanceOf(ContractError)
  })
})
