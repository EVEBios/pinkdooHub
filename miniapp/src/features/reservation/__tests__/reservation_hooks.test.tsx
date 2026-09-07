import ReactTestUtil from '@tarojs/test-utils-react'

import { BusinessError, TimeoutError } from '@/api'
import type {
  AdminReservationDetail,
  Reservation,
  ReservationBookingOptions,
  StoreClosureMutation,
  StoreClosurePage,
} from '@/api/endpoints/reservations'

import { type AdminReservationDetailSource, useAdminReservationDetail } from '../use_admin_reservation_detail'
import { type AdminReservationListSource, useAdminReservationList } from '../use_admin_reservation_list'
import { type ReservationCreateSource, useReservationCreate } from '../use_reservation_create'
import { type ReservationDetailSource, useReservationDetail } from '../use_reservation_detail'
import { type ReservationListSource, useReservationList } from '../use_reservation_list'
import { type StoreClosureSource, useStoreClosures } from '../use_store_closures'

const pendingReservation: Reservation = {
  id: 101,
  product_id: 7,
  experience_option_id: 11,
  product_name: '周末拼豆体验',
  duration_minutes: 120,
  participants: 2,
  day_type: { value: 'holiday', label: '节假日' },
  price: '199.00',
  status: { value: 'pending', label: '待门店确认' },
  rejection_reason: null,
  cancellation_reason: null,
  customer_message: '预约已提交，正在等待门店确认。',
  reservation_date: '2026-09-12',
  start_time: '14:30',
  end_time: '16:30',
  scheduled_start_at: '2026-09-12T06:30:00Z',
  scheduled_end_at: '2026-09-12T08:30:00Z',
  cancellation_deadline_at: '2026-09-12T03:30:00Z',
  confirmed_at: null,
  rejected_at: null,
  cancelled_at: null,
  created_at: '2026-09-06T02:00:00Z',
  updated_at: '2026-09-06T02:00:00Z',
}

const bookingOptions: ReservationBookingOptions = {
  experience_option_id: 11,
  product_id: 7,
  product_name: '周末拼豆体验',
  duration_minutes: 120,
  participants: 2,
  day_type: { value: 'holiday', label: '节假日' },
  price: '199.00',
  timezone: 'Asia/Shanghai',
  server_now: '2026-09-06T02:00:00Z',
  booking_window_end_date: '2026-10-06',
  weekly_closed_weekday: { value: 'monday', label: '周一' },
  minimum_lead_hours: 3,
  slot_interval_minutes: 30,
  booking_window_days: 30,
  opens_at: '11:00',
  closes_at: '20:00',
  dates: [
    { date: '2026-09-12', day_type: { value: 'holiday', label: '节假日' }, start_times: ['14:30', '15:00'] },
  ],
}

const adminPending: AdminReservationDetail = {
  ...pendingReservation,
  user_id: 9,
  user_nickname: '小豆',
  user_phone: '13800000000',
}

function CreateHarness({ source }: { readonly source: ReservationCreateSource }) {
  const hook = useReservationCreate(7, 11, source)
  return (
    <div>
      <span className='data'>{hook.data.status}</span>
      <span className='date'>{hook.reservationDate}</span>
      <span className='time'>{hook.startTime}</span>
      <span className='submission'>{hook.submission.status}</span>
      <button className='later' onClick={() => hook.selectStartTime('15:00')}>later</button>
      <button className='submit' onClick={() => void hook.submit()}>submit</button>
    </div>
  )
}

function DetailHarness({ source }: { readonly source: ReservationDetailSource }) {
  const hook = useReservationDetail(101, source)
  return (
    <div>
      <span className='detail'>{hook.detail.status}</span>
      <span className='status'>{hook.detail.status === 'content' ? hook.detail.reservation.status.value : ''}</span>
      <span className='mutation'>{hook.cancellation.status}</span>
      <span className='message'>{hook.cancellation.status === 'failed' || hook.cancellation.status === 'unknown' ? hook.cancellation.errorMessage : ''}</span>
      <button className='cancel' onClick={() => void hook.cancel()}>cancel</button>
      <button className='retry' onClick={hook.retry}>retry</button>
    </div>
  )
}

function AdminDetailHarness({ source }: { readonly source: AdminReservationDetailSource }) {
  const hook = useAdminReservationDetail(101, source)
  return (
    <div>
      <span className='detail'>{hook.detail.status}</span>
      <span className='status'>{hook.detail.status === 'content' ? hook.detail.reservation.status.value : ''}</span>
      <span className='mutation'>{hook.mutation.status}</span>
      <span className='message'>{hook.mutation.status === 'failed' || hook.mutation.status === 'unknown' ? hook.mutation.errorMessage : ''}</span>
      <button className='confirm' onClick={() => void hook.confirm()}>confirm</button>
      <button className='reject' onClick={() => void hook.reject()}>reject</button>
      <button className='retry' onClick={hook.retry}>retry</button>
    </div>
  )
}

function ClosuresHarness({ source }: { readonly source: StoreClosureSource }) {
  const hook = useStoreClosures(source)
  return (
    <div>
      <span className='list'>{hook.list.status}</span>
      <span className='mutation'>{hook.mutation.status}</span>
      <span className='count'>{hook.mutation.status === 'succeeded' ? hook.mutation.result.newly_cancelled_count : ''}</span>
      <button className='close' onClick={() => void hook.close('2026-09-09')}>close</button>
      <button className='reconcile' onClick={hook.reconcile}>reconcile</button>
      <button className='next' onClick={hook.loadNextPage}>next</button>
    </div>
  )
}

function ListHarness({ source }: { readonly source: ReservationListSource }) {
  const hook = useReservationList(source)
  return (
    <div>
      <span className='status'>{hook.state.status}</span>
      <span className='ids'>{hook.state.items.map((item) => item.id).join(',')}</span>
      <button className='confirmed' onClick={() => hook.setStatusFilter('confirmed')}>confirmed</button>
      <button className='next' onClick={hook.loadNextPage}>next</button>
    </div>
  )
}

function AdminListHarness({ source }: { readonly source: AdminReservationListSource }) {
  const hook = useAdminReservationList(source)
  return (
    <div>
      <span className='status'>{hook.state.status}</span>
      <button
        className='apply'
        onClick={() => hook.applyFilters({
          status: 'confirmed', businessDate: '2026-09-12', userId: 9, productId: 7,
        })}
      >apply</button>
    </div>
  )
}

describe('预约 hooks', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => { testUtils = new ReactTestUtil() })
  afterEach(() => testUtils.unmout())

  it('加载服务端时间默认值、切换时段并防止重复创建', async () => {
    const pending = deferred<Reservation>()
    const source: ReservationCreateSource = {
      getBookingOptions: jest.fn(async () => bookingOptions),
      createReservation: jest.fn(() => pending.promise),
    }
    await testUtils.mount(CreateHarness, { props: { source } })
    await flush(testUtils)
    expect(text(testUtils, '.date')).toBe('2026-09-12')
    expect(text(testUtils, '.time')).toBe('14:30')
    testUtils.fireEvent.click(required(testUtils, '.later'))
    expect(text(testUtils, '.time')).toBe('15:00')
    const submit = required(testUtils, '.submit')
    testUtils.fireEvent.click(submit)
    testUtils.fireEvent.click(submit)
    expect(source.createReservation).toHaveBeenCalledTimes(1)
    expect(source.createReservation).toHaveBeenCalledWith({
      experience_option_id: 11,
      reservation_date: '2026-09-12',
      start_time: '15:00',
    })
    pending.resolve(pendingReservation)
    await flush(testUtils)
    expect(text(testUtils, '.submission')).toBe('succeeded')
  })

  it('创建超时进入 unknown 且不自动或手动重复发起', async () => {
    const source: ReservationCreateSource = {
      getBookingOptions: jest.fn(async () => bookingOptions),
      createReservation: jest.fn(async () => {
        throw new TimeoutError({ operation: 'reservations.create' }, new Error('timeout'))
      }),
    }
    await testUtils.mount(CreateHarness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.submit'))
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.later'))
    testUtils.fireEvent.click(required(testUtils, '.submit'))
    await flush(testUtils)
    expect(text(testUtils, '.submission')).toBe('unknown')
    expect(text(testUtils, '.time')).toBe('14:30')
    expect(source.createReservation).toHaveBeenCalledTimes(1)
  })

  it('顾客取消成功后刷新；40952 明确冲突后也重拉权威详情', async () => {
    const cancelled: Reservation = {
      ...pendingReservation,
      status: { value: 'cancelled', label: '已取消' },
      cancellation_reason: { value: 'customer_request', label: '顾客取消' },
      customer_message: '本次预约已取消。您可以选择其他日期或时段重新预约。',
      cancelled_at: '2026-09-06T03:00:00Z',
    }
    const successSource: ReservationDetailSource = {
      getReservation: jest.fn().mockResolvedValueOnce(pendingReservation).mockResolvedValueOnce(cancelled),
      cancelReservation: jest.fn(async () => cancelled),
    }
    await testUtils.mount(DetailHarness, { props: { source: successSource } })
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.cancel'))
    await flush(testUtils)
    expect(text(testUtils, '.status')).toBe('cancelled')
    expect(text(testUtils, '.mutation')).toBe('succeeded')
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    const conflict = new BusinessError(
      { operation: 'reservations.cancel', statusCode: 409 },
      40952,
      'window closed',
      {},
    )
    const conflictSource: ReservationDetailSource = {
      getReservation: jest.fn().mockResolvedValue(pendingReservation),
      cancelReservation: jest.fn(async () => { throw conflict }),
    }
    await testUtils.mount(DetailHarness, { props: { source: conflictSource } })
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.cancel'))
    await flush(testUtils)
    expect(text(testUtils, '.mutation')).toBe('failed')
    expect(text(testUtils, '.message')).toContain('不足预约开始前三小时')
    expect(conflictSource.getReservation).toHaveBeenCalledTimes(2)
  })

  it('管理员确认后刷新；预约已开始的 40953 不在客户端伪成功', async () => {
    const confirmed: Reservation = {
      ...pendingReservation,
      status: { value: 'confirmed', label: '已确认' },
      customer_message: '预约已确认，请按预约时间到店。费用以预约时价格为准，到店支付。',
      confirmed_at: '2026-09-06T03:00:00Z',
    }
    const adminConfirmed: AdminReservationDetail = { ...adminPending, ...confirmed }
    const successSource: AdminReservationDetailSource = {
      getAdminReservation: jest.fn().mockResolvedValueOnce(adminPending).mockResolvedValueOnce(adminConfirmed),
      confirmReservation: jest.fn(async () => confirmed),
      rejectReservation: jest.fn(),
    }
    await testUtils.mount(AdminDetailHarness, { props: { source: successSource } })
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.confirm'))
    await flush(testUtils)
    expect(text(testUtils, '.status')).toBe('confirmed')
    expect(text(testUtils, '.mutation')).toBe('succeeded')
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    const expired = new BusinessError(
      { operation: 'reservations.admin.reject', statusCode: 409 },
      40953,
      'expired',
      {},
    )
    const expiredSource: AdminReservationDetailSource = {
      getAdminReservation: jest.fn().mockResolvedValue(adminPending),
      confirmReservation: jest.fn(),
      rejectReservation: jest.fn(async () => { throw expired }),
    }
    await testUtils.mount(AdminDetailHarness, { props: { source: expiredSource } })
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.reject'))
    await flush(testUtils)
    expect(text(testUtils, '.mutation')).toBe('failed')
    expect(text(testUtils, '.message')).toContain('预约已经开始')
    expect(expiredSource.getAdminReservation).toHaveBeenCalledTimes(2)
  })

  it('取消或审核结果未知时先冻结写操作，显式重拉成功后才允许新意图', async () => {
    const timeout = new TimeoutError({ operation: 'reservations.cancel' }, new Error('timeout'))
    const detailSource: ReservationDetailSource = {
      getReservation: jest.fn(async () => pendingReservation),
      cancelReservation: jest.fn(async () => { throw timeout }),
    }
    await testUtils.mount(DetailHarness, { props: { source: detailSource } })
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.cancel'))
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.cancel'))
    await flush(testUtils)
    expect(text(testUtils, '.mutation')).toBe('unknown')
    expect(detailSource.cancelReservation).toHaveBeenCalledTimes(1)
    testUtils.fireEvent.click(required(testUtils, '.retry'))
    await flush(testUtils)
    expect(text(testUtils, '.mutation')).toBe('idle')
    expect(detailSource.getReservation).toHaveBeenCalledTimes(2)
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    const adminTimeout = new TimeoutError({ operation: 'reservations.admin.confirm' }, new Error('timeout'))
    const adminSource: AdminReservationDetailSource = {
      getAdminReservation: jest.fn(async () => adminPending),
      confirmReservation: jest.fn(async () => { throw adminTimeout }),
      rejectReservation: jest.fn(),
    }
    await testUtils.mount(AdminDetailHarness, { props: { source: adminSource } })
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.confirm'))
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.confirm'))
    await flush(testUtils)
    expect(text(testUtils, '.mutation')).toBe('unknown')
    expect(adminSource.confirmReservation).toHaveBeenCalledTimes(1)
    testUtils.fireEvent.click(required(testUtils, '.retry'))
    await flush(testUtils)
    expect(text(testUtils, '.mutation')).toBe('idle')
    expect(adminSource.getAdminReservation).toHaveBeenCalledTimes(2)
  })

  it('设置店休展示批量取消计数，超时后冻结写操作直到显式核对', async () => {
    const page: StoreClosurePage = { items: [], total: 0, page: 1, page_size: 20, pages: 0 }
    const result: StoreClosureMutation = {
      id: 1,
      business_date: '2026-09-09',
      is_closed: true,
      created_at: '2026-09-06T03:00:00Z',
      updated_at: '2026-09-06T03:00:00Z',
      newly_cancelled_count: 3,
      cancelled_pending_count: 2,
      cancelled_confirmed_count: 1,
      is_replay: false,
    }
    const source: StoreClosureSource = {
      listStoreClosures: jest.fn(async () => page),
      closeStoreDay: jest.fn(async () => result),
      reopenStoreDay: jest.fn(),
      getReservationSettings: jest.fn(async () => ({ weekly_closed_weekday: { value: 'monday' as const, label: '周一' }, updated_at: '2026-09-06T03:00:00Z' })),
      updateWeeklyClosedDay: jest.fn(),
    }
    await testUtils.mount(ClosuresHarness, { props: { source } })
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.close'))
    await flush(testUtils)
    expect(text(testUtils, '.mutation')).toBe('succeeded')
    expect(text(testUtils, '.count')).toBe('3')
    expect(source.listStoreClosures).toHaveBeenCalledTimes(2)
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    const listStoreClosures = jest.fn(async () => page)
    const timeoutSource: StoreClosureSource = {
      listStoreClosures,
      closeStoreDay: jest.fn(async () => {
        throw new TimeoutError({ operation: 'reservations.admin.storeClosures.close' }, new Error('timeout'))
      }),
      reopenStoreDay: jest.fn(),
      getReservationSettings: jest.fn(async () => ({ weekly_closed_weekday: { value: 'monday' as const, label: '周一' }, updated_at: '2026-09-06T03:00:00Z' })),
      updateWeeklyClosedDay: jest.fn(),
    }
    await testUtils.mount(ClosuresHarness, { props: { source: timeoutSource } })
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.close'))
    await flush(testUtils)
    testUtils.fireEvent.click(required(testUtils, '.close'))
    await flush(testUtils)
    expect(text(testUtils, '.mutation')).toBe('unknown')
    expect(timeoutSource.closeStoreDay).toHaveBeenCalledTimes(1)
    listStoreClosures.mockRejectedValueOnce(new Error('offline'))
    testUtils.fireEvent.click(required(testUtils, '.reconcile'))
    await flush(testUtils)
    expect(text(testUtils, '.mutation')).toBe('unknown')
    listStoreClosures.mockResolvedValueOnce(page)
    testUtils.fireEvent.click(required(testUtils, '.reconcile'))
    await flush(testUtils)
    expect(text(testUtils, '.mutation')).toBe('reconciled')
    expect(listStoreClosures).toHaveBeenNthCalledWith(2, {
      page: 1,
      page_size: 20,
      date_from: '2026-09-09',
      date_to: '2026-09-09',
      is_closed: true,
    })
    expect(listStoreClosures).toHaveBeenNthCalledWith(3, {
      page: 1,
      page_size: 20,
      date_from: '2026-09-09',
      date_to: '2026-09-09',
      is_closed: true,
    })
  })

  it('店休列表同步点击加载更多只发出一个下一页请求', async () => {
    const secondPage = deferred<StoreClosurePage>()
    const firstPage: StoreClosurePage = {
      items: [{
        id: 1,
        business_date: '2026-09-09',
        is_closed: true,
        created_at: '2026-09-06T03:00:00Z',
        updated_at: '2026-09-06T03:00:00Z',
      }],
      total: 21,
      page: 1,
      page_size: 20,
      pages: 2,
    }
    const source: StoreClosureSource = {
      listStoreClosures: jest.fn()
        .mockResolvedValueOnce(firstPage)
        .mockImplementationOnce(() => secondPage.promise),
      closeStoreDay: jest.fn(),
      reopenStoreDay: jest.fn(),
      getReservationSettings: jest.fn(async () => ({ weekly_closed_weekday: { value: 'monday' as const, label: '周一' }, updated_at: '2026-09-06T03:00:00Z' })),
      updateWeeklyClosedDay: jest.fn(),
    }
    await testUtils.mount(ClosuresHarness, { props: { source } })
    await flush(testUtils)
    const next = required(testUtils, '.next')
    testUtils.fireEvent.click(next)
    testUtils.fireEvent.click(next)
    expect(source.listStoreClosures).toHaveBeenCalledTimes(2)
    secondPage.resolve({ items: [], total: 21, page: 2, page_size: 20, pages: 2 })
    await flush(testUtils)
  })

  it('我的预约分页同步防重，并隔离切换状态前的迟到响应', async () => {
    const oldSecondPage = deferred<{
      readonly items: readonly Reservation[]
      readonly total: number
      readonly page: number
      readonly page_size: number
      readonly pages: number
    }>()
    const confirmed: Reservation = {
      ...pendingReservation,
      id: 202,
      status: { value: 'confirmed', label: '已确认' },
      customer_message: '预约已确认，请按预约时间到店。费用以预约时价格为准，到店支付。',
      confirmed_at: '2026-09-06T03:00:00Z',
    }
    const source: ReservationListSource = {
      listReservations: jest.fn((request = {}) => {
        if (request.status === 'confirmed') {
          return Promise.resolve({ items: [confirmed], total: 1, page: 1, page_size: 20, pages: 1 })
        }
        if (request.page === 2) return oldSecondPage.promise
        return Promise.resolve({ items: [pendingReservation], total: 21, page: 1, page_size: 20, pages: 2 })
      }),
    }
    await testUtils.mount(ListHarness, { props: { source } })
    await flush(testUtils)
    const next = required(testUtils, '.next')
    testUtils.fireEvent.click(next)
    testUtils.fireEvent.click(next)
    expect(source.listReservations).toHaveBeenCalledTimes(2)
    testUtils.fireEvent.click(required(testUtils, '.confirmed'))
    await flush(testUtils)
    expect(text(testUtils, '.ids')).toBe('202')
    oldSecondPage.resolve({ items: [pendingReservation], total: 21, page: 2, page_size: 20, pages: 2 })
    await flush(testUtils)
    expect(text(testUtils, '.ids')).toBe('202')
    expect(source.listReservations).toHaveBeenLastCalledWith({ page: 1, page_size: 20, status: 'confirmed' })
  })

  it('管理预约默认只查 pending，组合筛选从第一页重新请求', async () => {
    const page = {
      items: [{ ...adminPending, user_phone_masked: '138****0000' }],
      total: 1,
      page: 1,
      page_size: 20,
      pages: 1,
    }
    const source: AdminReservationListSource = {
      listAdminReservations: jest.fn(async () => page),
    }
    await testUtils.mount(AdminListHarness, { props: { source } })
    await flush(testUtils)
    expect(source.listAdminReservations).toHaveBeenNthCalledWith(1, {
      page: 1, page_size: 20, status: 'pending',
    })
    testUtils.fireEvent.click(required(testUtils, '.apply'))
    await flush(testUtils)
    expect(source.listAdminReservations).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 20,
      status: 'confirmed',
      business_date: '2026-09-12',
      user_id: 9,
      product_id: 7,
    })
  })
})

function required(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

function text(testUtils: ReactTestUtil, selector: string): string | null {
  return required(testUtils, selector).textContent
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => { resolve = promiseResolve })
  return { promise, resolve }
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}
