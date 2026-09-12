import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { UserProfile } from '@/api/endpoints/auth'
import type { Reservation, ReservationBookingOptions } from '@/api/endpoints/reservations'
import type { AuthContextValue } from '@/auth'

import ReservationCreatePage, { AuthenticatedReservationCreate } from '../index'

const options: ReservationBookingOptions = {
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
  dates: [{
    date: '2026-09-12',
    day_type: { value: 'holiday', label: '节假日' },
    start_times: ['14:30'],
  }],
}

const created: Reservation = {
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

const mockSubmit = jest.fn(async () => created)
let mockReservationCreateState: Record<string, unknown>
let mockAuth: AuthContextValue
const mockUseReservationCreate = jest.fn()

jest.mock('@/features/reservation', () => ({
  buildReservationCreateUrl: (productId: number, optionId: number) => `/pages/reservation-create/index?product_id=${productId}&option_id=${optionId}`,
  buildReservationDetailUrl: (id: number) => `/pages/reservation-detail/index?id=${id}`,
  formatReservationDate: (value: string) => value,
  parseReservationCreateRoute: jest.fn(),
  RESERVATION_LIST_PATH: '/pages/reservations/index',
  useReservationCreate: () => {
    mockUseReservationCreate()
    return mockReservationCreateState
  },
}))

jest.mock('@/auth', () => ({
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
  buildLoginUrl: jest.fn(),
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('AuthenticatedReservationCreate', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = authenticatedUser()
    mockSubmit.mockClear()
    mockReservationCreateState = {
      data: { status: 'ready', options },
      reservationDate: '2026-09-12',
      startTime: '14:30',
      submission: { status: 'idle' },
      retry: jest.fn(),
      selectDate: jest.fn(),
      selectStartTime: jest.fn(),
      submit: mockSubmit,
    }
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('先通过 users/me PATCH 保存手机号，再创建预约并进入详情', async () => {
    const updateProfile = jest.fn(async (): Promise<UserProfile> => ({
      id: 9,
      username: 'member_009',
      nickname: '小豆',
      phone: '13800000000',
      avatar: null,
      role: 'user',
      status: 'normal',
      last_login_at: null,
      created_at: '2026-09-06T02:00:00Z',
      updated_at: '2026-09-06T02:00:00Z',
    }))
    await testUtils.mount(AuthenticatedReservationCreate, {
      props: { experienceOptionId: 11, initialPhone: '', productId: 7, updateProfile },
    })
    const submit = required(testUtils, '.reservation-create-page__submit') as HTMLButtonElement
    expect(submit.disabled).toBe(true)

    input(testUtils, required(testUtils, '.reservation-create-contact__input'), '13800000000')
    testUtils.fireEvent.click(required(testUtils, '.reservation-create-contact__save'))
    await flush(testUtils)
    expect(updateProfile).toHaveBeenCalledWith({ phone: '13800000000' })
    expect((required(testUtils, '.reservation-create-page__submit') as HTMLButtonElement).disabled).toBe(false)

    testUtils.fireEvent.click(required(testUtils, '.reservation-create-page__submit'))
    await flush(testUtils)
    expect(mockSubmit).toHaveBeenCalledTimes(1)
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: '/pages/reservation-detail/index?id=101' })
  })

  it.each(['admin', 'super_admin'] as const)('%s 创建预约深链在业务 Hook 前进入工作台', async (role) => {
    mockAuth = {
      ...mockAuth,
      user: { ...mockAuth.user!, role },
    }
    await testUtils.mount(ReservationCreatePage)

    expect(required(testUtils, '.admin-workbench-redirect').textContent).toContain('正在进入店铺工作台')
    expect(mockUseReservationCreate).not.toHaveBeenCalled()
    await flush(testUtils)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
  })

  it('未知角色保持 fail closed，不挂载预约创建 Hook', async () => {
    mockAuth = {
      ...mockAuth,
      user: { ...mockAuth.user!, role: 'operator' as never },
    }
    await testUtils.mount(ReservationCreatePage)

    expect(required(testUtils, '.reservation-create-state__title').textContent).toContain('账户角色暂不支持')
    expect(mockUseReservationCreate).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
  })

  it('已保存手机号可直接提交，页面明确不创建订单且不主动通知', async () => {
    await testUtils.mount(AuthenticatedReservationCreate, {
      props: {
        experienceOptionId: 11,
        initialPhone: '13800000000',
        productId: 7,
        updateProfile: jest.fn(),
      },
    })
    const page = required(testUtils, '.reservation-create-page')
    expect(page.textContent).toContain('提交预约不会创建订单或扣款')
    expect(page.textContent).toContain('首版不会发送微信主动通知')
    expect((required(testUtils, '.reservation-create-page__submit') as HTMLButtonElement).disabled).toBe(false)
  })

  it('同步连点保存手机号只复用一次进行中 PATCH', async () => {
    const pending = deferred<UserProfile>()
    const updateProfile = jest.fn(() => pending.promise)
    await testUtils.mount(AuthenticatedReservationCreate, {
      props: { experienceOptionId: 11, initialPhone: '', productId: 7, updateProfile },
    })
    input(testUtils, required(testUtils, '.reservation-create-contact__input'), '13800000000')
    const save = required(testUtils, '.reservation-create-contact__save')
    testUtils.fireEvent.click(save)
    testUtils.fireEvent.click(save)
    expect(updateProfile).toHaveBeenCalledTimes(1)

    pending.resolve({
      id: 9,
      username: 'member_009',
      nickname: '小豆',
      phone: '13800000000',
      avatar: null,
      role: 'user',
      status: 'normal',
      last_login_at: null,
      created_at: '2026-09-06T02:00:00Z',
      updated_at: '2026-09-06T02:00:00Z',
    })
    await flush(testUtils)
    expect((required(testUtils, '.reservation-create-page__submit') as HTMLButtonElement).disabled).toBe(false)
  })

  it('资料响应未保存本次手机号时保持预约提交锁定', async () => {
    const updateProfile = jest.fn(async (): Promise<UserProfile> => ({
      id: 9,
      username: 'member_009',
      nickname: '小豆',
      phone: '13900009000',
      avatar: null,
      role: 'user',
      status: 'normal',
      last_login_at: null,
      created_at: '2026-09-06T02:00:00Z',
      updated_at: '2026-09-06T02:00:00Z',
    }))
    await testUtils.mount(AuthenticatedReservationCreate, {
      props: { experienceOptionId: 11, initialPhone: '', productId: 7, updateProfile },
    })
    input(testUtils, required(testUtils, '.reservation-create-contact__input'), '13800000000')
    testUtils.fireEvent.click(required(testUtils, '.reservation-create-contact__save'))
    await flush(testUtils)

    expect(required(testUtils, '.reservation-create-feedback--error').textContent).toContain('与本次保存不一致')
    expect((required(testUtils, '.reservation-create-page__submit') as HTMLButtonElement).disabled).toBe(true)
    expect(mockSubmit).not.toHaveBeenCalled()
  })

  it('预约结果未知时通过根 Tab 前往我的预约核对', async () => {
    mockReservationCreateState = {
      ...mockReservationCreateState,
      submission: { status: 'unknown', errorMessage: '预约结果可能未知' },
    }
    await testUtils.mount(AuthenticatedReservationCreate, {
      props: {
        experienceOptionId: 11,
        initialPhone: '13800000000',
        productId: 7,
        updateProfile: jest.fn(),
      },
    })

    const action = required(testUtils, '.reservation-create-feedback').lastElementChild
    if (!action) {
      throw new Error('Expected the unknown-result action')
    }
    testUtils.fireEvent.click(action)
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/reservations/index' })
  })
})

function required(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

function input(testUtils: ReactTestUtil, element: Element, value: string): void {
  const fireCustomEvent = testUtils.fireEvent as unknown as (target: Element, event: Event) => void
  fireCustomEvent(element, new CustomEvent('input', { bubbles: true, detail: { value } }))
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => { resolve = promiseResolve })
  return { promise, resolve }
}

function authenticatedUser(): AuthContextValue {
  return {
    status: 'authenticated',
    user: {
      id: 9,
      username: 'member_009',
      nickname: '小豆',
      phone: '13800000000',
      avatar: null,
      role: 'user',
      status: 'normal',
      last_login_at: null,
      created_at: '2026-09-06T02:00:00Z',
      updated_at: '2026-09-06T02:00:00Z',
    },
    register: jest.fn(),
    updateProfile: jest.fn(),
    login: jest.fn(),
    loginWithWechat: jest.fn(),
    logout: jest.fn(),
    retryInitialization: jest.fn(),
  }
}
