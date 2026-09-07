import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { ExperienceProductDetail } from '@/api/endpoints/products'
import type { AuthContextValue } from '@/auth'

import { ReservationAction } from '../index'

let mockAuth: AuthContextValue

jest.mock('@/auth', () => ({
  buildLoginUrl: (redirect: string) => `/pages/login/index?redirect=${encodeURIComponent(redirect)}`,
  useAuth: () => mockAuth,
}))

jest.mock('@/features/reservation', () => ({
  buildReservationCreateUrl: (productId: number, optionId: number) =>
    `/pages/reservation-create/index?product_id=${productId}&option_id=${optionId}`,
}))

const detail: ExperienceProductDetail = {
  id: 7,
  name: '周末拼豆体验',
  product_type: { value: 'experience', label: '拼豆体验' },
  description: '一起完成一幅拼豆作品',
  dimensions: {
    durations: [{ value: 120, label: '2小时' }],
    participants: [{ value: 2, label: '2人' }],
    day_types: [{ value: 'holiday', label: '节假日' }],
  },
  options: [{
    id: 11,
    duration: { value: 120, label: '2小时' },
    participants: { value: 2, label: '2人' },
    day_type: { value: 'holiday', label: '节假日' },
    price: '199.00',
    images: [],
  }],
  images: [],
}

describe('商品详情预约入口', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = authValue('guest')
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('Guest 使用严格动态回跳登录，顾客登录后直接携带 Option ID 进入创建页', async () => {
    await testUtils.mount(ReservationAction, { props: { detail, option: detail.options[0] } })
    testUtils.fireEvent.click(required(testUtils, '.product-detail__reservation-action'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fpages%2Freservation-create%2Findex%3Fproduct_id%3D7%26option_id%3D11',
    })
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    mockAuth = authValue('authenticated')
    await testUtils.mount(ReservationAction, { props: { detail, option: detail.options[0] } })
    testUtils.fireEvent.click(required(testUtils, '.product-detail__reservation-action'))
    expect(Taro.navigateTo).toHaveBeenLastCalledWith({
      url: '/pages/reservation-create/index?product_id=7&option_id=11',
    })
  })
})

function authValue(status: 'guest' | 'authenticated'): AuthContextValue {
  return {
    status,
    ...(status === 'authenticated' ? {
      user: {
        id: 9,
        username: 'member_009',
        nickname: '小豆',
        phone: '13800000000',
        avatar: null,
        role: 'user' as const,
        status: 'normal' as const,
        last_login_at: null,
        created_at: '2026-09-06T02:00:00Z',
        updated_at: '2026-09-06T02:00:00Z',
      },
    } : {}),
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
