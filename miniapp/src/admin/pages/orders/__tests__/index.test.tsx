import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type { AdminOrderListState } from '@/features/order'

import AdminOrdersPage, { AuthenticatedAdminOrders } from '../index'

let mockAuth: AuthContextValue
let mockState: AdminOrderListState
const mockUseAdminOrderList = jest.fn()
const mockApplyFilters = jest.fn()

jest.mock('@/auth', () => ({
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fadmin%2Fpages%2Forders%2Findex',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/order', () => ({
  ADMIN_ORDER_LIST_PATH: '/admin/pages/orders/index',
  EMPTY_ADMIN_ORDER_FILTER_DRAFT: { status: 'all', orderNo: '', userId: '', createdFrom: '', createdTo: '' },
  buildAdminOrderDetailUrl: (id: number) => `/admin/pages/order-detail/index?id=${id}`,
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  parseAdminOrderFilters: (draft: { status: string }) => ({ filters: { status: draft.status } }),
  useAdminOrderList: () => mockUseAdminOrderList(),
}))

jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('AdminOrdersPage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'authenticated',
      user: {
        id: 2,
        username: 'dev_admin',
        nickname: '开发管理员',
        avatar: null,
        phone: '13800000000',
        role: 'admin',
        status: 'normal',
        last_login_at: null,
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-01T00:00:00Z',
      },
      login: jest.fn(),
      logout: jest.fn(),
      retryInitialization: jest.fn(),
    }
    mockState = { status: 'loading', items: [], total: 0, page: 1, pages: 0, loadingMore: false }
    mockUseAdminOrderList.mockImplementation(() => ({
      state: mockState,
      filters: { status: 'all' },
      applyFilters: mockApplyFilters,
      retry: jest.fn(),
      loadNextPage: jest.fn(),
    }))
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('普通用户在页面边界被拒绝，不挂载 ADMIN API hook', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminOrdersPage)
    expect(testUtils.queries.querySelector('.admin-orders-state')?.textContent).toContain('无管理权限')
    expect(mockUseAdminOrderList).not.toHaveBeenCalled()
  })

  it('Guest 仅跳转到固定白名单的管理列表地址', async () => {
    mockAuth = { ...mockAuth, status: 'guest', user: undefined }
    await testUtils.mount(AdminOrdersPage)
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-orders-state__action'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fadmin%2Fpages%2Forders%2Findex',
    })
    expect(mockUseAdminOrderList).not.toHaveBeenCalled()
  })

  it('展示服务端用户摘要并进入管理详情', async () => {
    mockState = {
      status: 'content',
      items: [{
        id: 101,
        order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
        user_id: 7,
        user_nickname: '开发用户',
        total_amount: '99.00',
        status: { value: 'pending', label: '待支付' },
        item_count: 1,
        created_at: '2026-08-24T08:00:00Z',
        updated_at: '2026-08-24T08:00:00Z',
      }],
      total: 1,
      page: 1,
      pages: 1,
      loadingMore: false,
    }
    await testUtils.mount(AuthenticatedAdminOrders)
    const card = requireElement(testUtils, '.admin-order-card')
    expect(card.textContent).toContain('用户 #7 · 开发用户')
    testUtils.fireEvent.click(card)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/admin/pages/order-detail/index?id=101' })
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}
