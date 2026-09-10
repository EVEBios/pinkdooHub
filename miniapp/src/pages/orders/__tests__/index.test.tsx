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
const mockUseOrderList = jest.fn()
const mockUseRootTabSelection = jest.fn()

jest.mock('@/auth', () => ({
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
  ORDER_LIST_PATH: '/pages/orders/index',
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fpages%2Forders%2Findex',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/order', () => ({
  buildOrderDetailUrl: (id: number) => `/pages/order-detail/index?id=${id}`,
  useOrderList: () => mockUseOrderList.mockReturnValue({
    state: mockState,
    statusFilter: mockStatusFilter,
    retry: mockRetry,
    loadNextPage: mockLoadNextPage,
    setStatusFilter: mockSetStatusFilter,
  })(),
}))

jest.mock('@/navigation/root_tabs', () => ({
  ROOT_TAB_INDEX: { orders: 2 },
  useRootTabSelection: (index: number) => mockUseRootTabSelection(index),
}))

jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('OrdersPage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'authenticated',
      user: {
        id: 7,
        username: 'member_007',
        nickname: '拼豆会员',
        phone: null,
        avatar: null,
        role: 'user',
        status: 'normal',
        last_login_at: null,
        created_at: '2026-09-01T08:00:00Z',
        updated_at: '2026-09-05T08:00:00Z',
      },
      register: jest.fn(),
      updateProfile: jest.fn(),
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
    mockAuth = { ...mockAuth, status: 'guest', user: undefined }
    await testUtils.mount(OrdersPage)
    const button = requireElement(testUtils, '.orders-state__action')
    testUtils.fireEvent.click(button)
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fpages%2Forders%2Findex',
    })
    expect(mockUseRootTabSelection).toHaveBeenCalledWith(2)
  })

  it('ADMIN+ 不挂载顾客订单 hook，并自动进入店铺工作台', async () => {
    mockAuth = {
      ...mockAuth,
      user: { ...mockAuth.user!, role: 'admin' },
    }
    await testUtils.mount(OrdersPage)

    const state = requireElement(testUtils, '.admin-workbench-redirect')
    expect(state.textContent).toContain('正在进入店铺工作台')
    expect(mockUseOrderList).not.toHaveBeenCalled()
    expect(mockUseRootTabSelection).not.toHaveBeenCalled()
    await testUtils.act(async () => { await Promise.resolve() })
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
    expect(Taro.switchTab).not.toHaveBeenCalled()
  })

  it.each([
    ['缺少用户资料', 'missing', '账户信息不完整'],
    ['未知角色', 'unknown', '账户角色暂不支持'],
  ] as const)('已认证但%s时 fail closed', async (_caseName, userCase, expectedText) => {
    mockAuth = {
      ...mockAuth,
      user: userCase === 'missing'
        ? undefined
        : { ...mockAuth.user!, role: 'operator' as never },
    }
    await testUtils.mount(OrdersPage)

    expect(requireElement(testUtils, '.orders-page--state').textContent).toContain(expectedText)
    expect(mockUseOrderList).not.toHaveBeenCalled()
    expect(mockUseRootTabSelection).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
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
    expect(testUtils.queries.querySelector('.orders-inline-state')).not.toBeNull()
    expect(testUtils.queries.querySelector('.orders-page--state')).toBeNull()
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
