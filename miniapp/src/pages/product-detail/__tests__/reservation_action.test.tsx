import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { ExperienceProductDetail } from '@/api/endpoints/products'
import type { AuthContextValue } from '@/auth'

import ProductDetailPage, { ReservationAction } from '../index'

let mockAuth: AuthContextValue
const mockUseProductDetail = jest.fn()

jest.mock('@/auth', () => ({
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
  buildLoginUrl: (redirect: string) => `/pages/login/index?redirect=${encodeURIComponent(redirect)}`,
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/product/use_product_detail', () => ({
  useProductDetail: (...args: unknown[]) => mockUseProductDetail(...args),
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

  it.each(['admin', 'super_admin'] as const)('%s 商品深链在商品 Hook 前进入工作台', async (role) => {
    mockAuth = {
      ...authValue('authenticated'),
      user: { ...authValue('authenticated').user!, role },
    }
    await testUtils.mount(ProductDetailPage)

    expect(required(testUtils, '.admin-workbench-redirect').textContent).toContain('正在进入店铺工作台')
    expect(mockUseProductDetail).not.toHaveBeenCalled()
    await flush(testUtils)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
  })

  it('未知角色保持 fail closed，不挂载商品 Hook', async () => {
    mockAuth = {
      ...authValue('authenticated'),
      user: { ...authValue('authenticated').user!, role: 'operator' as never },
    }
    await testUtils.mount(ProductDetailPage)

    expect(required(testUtils, '.product-detail__state-title').textContent).toContain('账户角色暂不支持')
    expect(mockUseProductDetail).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
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

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}
