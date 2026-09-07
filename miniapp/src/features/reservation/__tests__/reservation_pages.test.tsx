import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type {
  AdminReservationDetail,
  AdminReservationListItem,
  Reservation,
  StoreClosureMutation,
} from '@/api/endpoints/reservations'

import AdminReservationDetailPage, {
  AuthenticatedAdminReservationDetail,
} from '@/admin/pages/reservation-detail'
import AdminReservationsPage, {
  AuthenticatedAdminReservations,
} from '@/admin/pages/reservations'
import StoreClosuresPage, {
  AuthenticatedStoreClosures,
} from '@/admin/pages/store-closures'
import { AuthenticatedReservationDetail } from '@/pages/reservation-detail'
import ReservationsPage, { AuthenticatedReservations } from '@/pages/reservations'

let mockAuth: AuthContextValue
let mockReservationListState: Record<string, unknown>
let mockReservationDetailState: Record<string, unknown>
let mockAdminListState: Record<string, unknown>
let mockAdminDetailState: Record<string, unknown>
let mockClosureState: Record<string, unknown>
const mockUseReservationList = jest.fn()
const mockUseReservationDetail = jest.fn()
const mockUseAdminReservationList = jest.fn()
const mockUseAdminReservationDetail = jest.fn()
const mockUseStoreClosures = jest.fn()
const mockCancel = jest.fn(async () => undefined)
const mockConfirm = jest.fn(async () => undefined)
const mockReject = jest.fn(async () => undefined)
const mockClose = jest.fn(async () => undefined)
const mockReopen = jest.fn(async () => undefined)

jest.mock('@tarojs/taro', () => {
  const actual = jest.requireActual('@tarojs/taro')
  return { ...actual, useRouter: () => ({ params: { id: '31' } }) }
})

jest.mock('@/auth', () => ({
  buildLoginUrl: (redirect: string) => `/pages/login/index?redirect=${encodeURIComponent(redirect)}`,
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/reservation', () => ({
  ADMIN_RESERVATION_LIST_PATH: '/admin/pages/reservations/index',
  ADMIN_STORE_CLOSURE_LIST_PATH: '/admin/pages/store-closures/index',
  RESERVATION_LIST_PATH: '/pages/reservations/index',
  EMPTY_ADMIN_RESERVATION_FILTER_DRAFT: {
    status: 'pending', businessDate: '', userId: '', productId: '',
  },
  buildAdminReservationDetailUrl: (id: number) => `/admin/pages/reservation-detail/index?id=${id}`,
  buildReservationCreateUrl: (productId: number, optionId: number) =>
    `/pages/reservation-create/index?product_id=${productId}&option_id=${optionId}`,
  buildReservationDetailUrl: (id: number) => `/pages/reservation-detail/index?id=${id}`,
  canRequestReservationCancellation: (reservation: Reservation) =>
    reservation.status.value === 'pending' || reservation.status.value === 'confirmed',
  formatReservationDate: (value: string) => value,
  formatShanghaiUtc: (value: string) => value,
  parseAdminReservationFilters: (draft: Record<string, string>) => ({ filters: {
    status: draft.status,
  } }),
  parseReservationDetailRoute: () => ({ reservationId: 31 }),
  reservationStatusClass: (reservation: Reservation) => reservation.status.value,
  useAdminReservationDetail: () => mockUseAdminReservationDetail(),
  useAdminReservationList: () => mockUseAdminReservationList(),
  useReservationDetail: () => mockUseReservationDetail(),
  useReservationList: () => mockUseReservationList(),
  useStoreClosures: () => mockUseStoreClosures(),
}))

jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

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
  cancellation_deadline_at: '2020-01-01T00:00:00Z',
  confirmed_at: null,
  rejected_at: null,
  cancelled_at: null,
  created_at: '2026-09-06T01:00:00Z',
  updated_at: '2026-09-06T01:00:00Z',
}

const adminListItem: AdminReservationListItem = {
  ...pendingReservation,
  user_id: 9,
  user_nickname: '小豆',
  user_phone_masked: '138****8000',
}

const adminDetail: AdminReservationDetail = {
  ...pendingReservation,
  user_id: 9,
  user_nickname: '小豆',
  user_phone: '13800008000',
}

const closureResult: StoreClosureMutation = {
  id: 3,
  business_date: '2026-09-06',
  is_closed: true,
  created_at: '2026-09-06T02:00:00Z',
  updated_at: '2026-09-06T02:00:00Z',
  newly_cancelled_count: 3,
  cancelled_pending_count: 2,
  cancelled_confirmed_count: 1,
  is_replay: false,
}

describe('Reservation N1 页面集成', () => {
  let testUtils: ReactTestUtil
  const showModalSpy = jest.spyOn(Taro, 'showModal')

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = authenticated('user')
    mockReservationListState = {
      state: { status: 'content', items: [pendingReservation], total: 1, page: 1, pages: 1, loadingMore: false },
      statusFilter: 'all', setStatusFilter: jest.fn(), retry: jest.fn(), loadNextPage: jest.fn(),
    }
    mockReservationDetailState = {
      detail: { status: 'content', reservation: pendingReservation },
      cancellation: { status: 'idle' }, retry: jest.fn(), cancel: mockCancel,
    }
    mockAdminListState = {
      state: { status: 'content', items: [adminListItem], total: 1, page: 1, pages: 1, loadingMore: false },
      filters: { status: 'pending' }, applyFilters: jest.fn(), retry: jest.fn(), loadNextPage: jest.fn(),
    }
    mockAdminDetailState = {
      detail: { status: 'content', reservation: adminDetail },
      mutation: { status: 'idle' }, retry: jest.fn(), confirm: mockConfirm, reject: mockReject,
    }
    mockClosureState = {
      list: { status: 'content', items: [], total: 0, page: 1, pages: 0, loadingMore: false },
      mutation: { status: 'idle' },
      settings: { status: 'content', value: { weekly_closed_weekday: { value: 'monday', label: '周一' }, updated_at: '2026-09-06T02:00:00Z' } },
      weeklyMutation: { status: 'idle' },
      retry: jest.fn(), retrySettings: jest.fn(), loadNextPage: jest.fn(), close: mockClose,
      reopen: mockReopen, reconcile: jest.fn(), changeWeeklyClosedDay: jest.fn(), reconcileWeekly: jest.fn(),
    }
    mockUseReservationList.mockImplementation(() => mockReservationListState)
    mockUseReservationDetail.mockImplementation(() => mockReservationDetailState)
    mockUseAdminReservationList.mockImplementation(() => mockAdminListState)
    mockUseAdminReservationDetail.mockImplementation(() => mockAdminDetailState)
    mockUseStoreClosures.mockImplementation(() => mockClosureState)
    showModalSpy.mockResolvedValue({ confirm: true, cancel: false, errMsg: 'showModal:ok' })
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('我的预约只展示服务端顾客文案并进入所属详情', async () => {
    await testUtils.mount(AuthenticatedReservations)
    const card = required(testUtils, '.reservation-card')
    expect(card.textContent).toContain(pendingReservation.customer_message)
    expect(card.textContent).not.toContain('138')
    testUtils.fireEvent.click(card)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/reservation-detail/index?id=31' })
  })

  it('pending 与 confirmed 即使本地截止时间已过也显示取消按钮，unknown 时冻结', async () => {
    await testUtils.mount(AuthenticatedReservationDetail, { props: { reservationId: 31 } })
    const pendingButton = required(testUtils, '.reservation-detail-cancellation__action')
    expect(pendingButton.textContent).toContain('取消预约')
    testUtils.fireEvent.click(pendingButton)
    await flush(testUtils)
    expect(mockCancel).toHaveBeenCalledTimes(1)
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    mockReservationDetailState = {
      ...mockReservationDetailState,
      detail: {
        status: 'content',
        reservation: {
          ...pendingReservation,
          status: { value: 'confirmed', label: '已确认' },
          customer_message: '预约已确认，请按预约时间到店。费用以预约时价格为准，到店支付。',
          confirmed_at: '2026-09-06T02:00:00Z',
        },
      },
      cancellation: { status: 'unknown', errorMessage: '结果未知' },
    }
    await testUtils.mount(AuthenticatedReservationDetail, { props: { reservationId: 31 } })
    const confirmedButton = required(testUtils, '.reservation-detail-cancellation__action') as HTMLButtonElement
    expect(confirmedButton.disabled).toBe(true)
    expect(confirmedButton.textContent).toContain('先核对')
  })

  it('顾客不能挂载管理 hooks', async () => {
    await testUtils.mount(AdminReservationsPage)
    expect(required(testUtils, '.admin-reservations-state').textContent).toContain('无管理权限')
    expect(mockUseAdminReservationList).not.toHaveBeenCalled()
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    await testUtils.mount(AdminReservationDetailPage)
    expect(required(testUtils, '.admin-reservation-detail-state').textContent).toContain('无管理权限')
    expect(mockUseAdminReservationDetail).not.toHaveBeenCalled()
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    await testUtils.mount(StoreClosuresPage)
    expect(required(testUtils, '.store-closures-state').textContent).toContain('无管理权限')
    expect(mockUseStoreClosures).not.toHaveBeenCalled()
  })

  it('管理列表只显示掩码号码，详情按需显示完整号码并固定无空位拒绝', async () => {
    mockAuth = authenticated('admin')
    await testUtils.mount(AuthenticatedAdminReservations)
    const card = required(testUtils, '.admin-reservation-card')
    expect(card.textContent).toContain('138****8000')
    expect(card.textContent).not.toContain(adminDetail.user_phone ?? '')
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    await testUtils.mount(AuthenticatedAdminReservationDetail, { props: { reservationId: 31 } })
    const page = required(testUtils, '.admin-reservation-detail-page')
    expect(page.textContent).toContain(adminDetail.user_phone ?? '')
    testUtils.fireEvent.click(required(testUtils, '.admin-reservation-decision__reject'))
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({
      title: '因无空位拒绝预约？',
      content: expect.stringContaining('当前时段无空位'),
    }))
    expect(mockReject).toHaveBeenCalledTimes(1)
  })

  it('店休确认区分 store_closed，成功结果展示批量计数和人工联系边界', async () => {
    mockAuth = authenticated('admin')
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-09-06T02:00:00Z'))
    await testUtils.mount(AuthenticatedStoreClosures)
    testUtils.fireEvent.click(required(testUtils, '.store-closure-editor--single .store-closure-editor__submit'))
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({
      content: expect.stringContaining('只关闭这一天'),
    }))
    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({
      content: expect.stringContaining('暂不发送微信主动通知'),
    }))
    expect(mockClose).toHaveBeenCalledWith('2026-09-06')
    testUtils.unmout()
    nowSpy.mockRestore()

    testUtils = new ReactTestUtil()
    mockClosureState = { ...mockClosureState, mutation: { status: 'succeeded', action: 'close', result: closureResult } }
    await testUtils.mount(AuthenticatedStoreClosures)
    const feedback = required(testUtils, '.store-closure-feedback--success')
    expect(feedback.textContent).toContain('本次取消 3 条：待确认 2 条，已确认 1 条')
    expect(feedback.textContent).toContain('人工联系顾客')
    expect(feedback.textContent).not.toContain('已通知')
  })

  it('管理员账号不能挂载顾客预约列表 hook', async () => {
    mockAuth = authenticated('admin')
    await testUtils.mount(ReservationsPage)
    expect(required(testUtils, '.reservations-page').textContent).toContain('顾客账号才能查看预约')
    expect(mockUseReservationList).not.toHaveBeenCalled()
  })
})

function authenticated(role: 'user' | 'admin'): AuthContextValue {
  return {
    status: 'authenticated',
    user: {
      id: role === 'user' ? 9 : 2,
      username: role === 'user' ? 'member_009' : 'dev_admin',
      nickname: role === 'user' ? '小豆' : '开发管理员',
      phone: '13800008000',
      avatar: null,
      role,
      status: 'normal',
      last_login_at: null,
      created_at: '2026-09-06T00:00:00Z',
      updated_at: '2026-09-06T00:00:00Z',
    },
    register: jest.fn(),
    updateProfile: jest.fn(),
    login: jest.fn(),
    loginWithWechat: jest.fn(),
    logout: jest.fn(),
    retryInitialization: jest.fn(),
  }
}

function required(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}
