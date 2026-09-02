import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type { OrderListState } from '@/features/order'

import OrdersPage, { AuthenticatedOrders } from '../index'

let mockAuth: AuthContextValue
let mockState: OrderListState
let mockStatusFilter = 'all'
const mockRetry = jest.fn()
const mockLoadNextPage = jest.fn()
const mockSetStatusFilter = jest.fn()

jest.mock('@/auth', () => ({
  ORDER_LIST_PATH: '/pages/orders/index',
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fpages%2Forders%2Findex',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/order', () => ({
  buildOrderDetailUrl: (id: number) => `/pages/order-detail/index?id=${id}`,
  useOrderList: () => ({
    state: mockState,
    statusFilter: mockStatusFilter,
    retry: mockRetry,
    loadNextPage: mockLoadNextPage,
    setStatusFilter: mockSetStatusFilter,
  }),
}))

jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('OrdersPage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'authenticated',
      register: jest.fn(),
      login: jest.fn(),
      loginWithWechat: jest.fn(),
      logout: jest.fn(),
      retryInitialization: jest.fn(),
    }
    mockState = { status: 'loading', items: [], total: 0, page: 1, pages: 0, loadingMore: false }
    mockStatusFilter = 'all'
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('Guest 使用白名单地址登录后返回我的订单', async () => {
    mockAuth = { ...mockAuth, status: 'guest' }
    await testUtils.mount(OrdersPage)
    const button = requireElement(testUtils, '.orders-state__action')
    testUtils.fireEvent.click(button)
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fpages%2Forders%2Findex',
    })
  })

  it.each([
    ['loading', '正在加载订单…'],
    ['empty', '当前筛选下没有订单'],
    ['error', '订单加载失败'],
  ] as const)('渲染 %s 四态', async (status, text) => {
    mockState = {
      ...mockState,
      status,
      errorMessage: status === 'error' ? 'offline' : undefined,
    }
    await testUtils.mount(AuthenticatedOrders)
    expect(testUtils.queries.querySelector('.orders-page')?.textContent).toContain(text)
  })

  it('展示服务端列表字段、切换筛选并进入详情', async () => {
    mockState = {
      status: 'content',
      items: [{
        id: 101,
        order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
        total_amount: '497.00',
        status: { value: 'pending', label: '待支付' },
        item_count: 2,
        created_at: '2026-08-24T08:00:00Z',
        updated_at: '2026-08-24T08:00:00Z',
      }],
      total: 1,
      page: 1,
      pages: 1,
      loadingMore: false,
    }
    await testUtils.mount(AuthenticatedOrders)
    const card = requireElement(testUtils, '.order-card')
    expect(card.textContent).toContain('2 种商品配置')
    expect(card.textContent).toContain('¥497.00')
    testUtils.fireEvent.click(requireElement(testUtils, '.orders-filters__item:nth-child(2)'))
    expect(mockSetStatusFilter).toHaveBeenCalledWith('pending')
    testUtils.fireEvent.click(card)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/order-detail/index?id=101' })
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
