import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AdminOrderDetail } from '@/api/endpoints/orders'
import type { AdminOrderDetailState, AdminOrderTransitionState } from '@/features/order'
import type { AuthContextValue } from '@/auth'

import AdminOrderDetailPage, { AuthenticatedAdminOrderDetail } from '../index'

let mockDetail: AdminOrderDetailState
let mockTransition: AdminOrderTransitionState
let mockAuth: AuthContextValue
const mockAdvanceStatus = jest.fn(async () => undefined)
const mockUseAdminOrderDetail = jest.fn()
const showModalSpy = jest.spyOn(Taro, 'showModal')

jest.mock('@tarojs/taro', () => {
  const actual = jest.requireActual('@tarojs/taro')
  return { ...actual, useRouter: () => ({ params: { id: '101' } }) }
})

jest.mock('@/auth', () => ({ buildLoginUrl: jest.fn(), useAuth: () => mockAuth }))
jest.mock('@/features/order', () => ({
  ADMIN_ORDER_LIST_PATH: '/admin/pages/orders/index',
  getTransitionAction: (order: AdminOrderDetail) => order.status.value === 'pending'
    ? 'mark_paid'
    : order.status.value === 'paid' ? 'complete' : undefined,
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  parseAdminOrderDetailRoute: () => ({ orderId: 101 }),
  useAdminOrderDetail: () => mockUseAdminOrderDetail(),
}))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

const pendingOrder: AdminOrderDetail = {
  id: 101,
  order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
  user_id: 7,
  user_nickname: '开发用户',
  total_amount: '99.00',
  status: { value: 'pending', label: '待支付' },
  remark: null,
  items: [{
    id: 1,
    product_id: 1,
    experience_option_id: 11,
    product_name: '体验快照',
    option_duration_minutes: 60,
    option_participants: 1,
    option_day_type: { value: 'weekday', label: '工作日' },
    product_price: '99.00',
    quantity: 1,
    subtotal: '99.00',
  }],
  created_at: '2026-08-24T08:00:00Z',
  updated_at: '2026-08-24T08:00:00Z',
}

describe('AuthenticatedAdminOrderDetail', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockDetail = { status: 'content', order: pendingOrder }
    mockTransition = { status: 'idle' }
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
    mockUseAdminOrderDetail.mockImplementation(() => ({
      detail: mockDetail,
      transition: mockTransition,
      advanceStatus: mockAdvanceStatus,
      retry: jest.fn(),
    }))
    showModalSpy.mockResolvedValue({ confirm: true, cancel: false, errMsg: 'showModal:ok' })
  })

  it('普通用户不挂载 ADMIN 详情 hook', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminOrderDetailPage)
    expect(testUtils.queries.querySelector('.admin-detail-state')?.textContent).toContain('无管理权限')
    expect(mockUseAdminOrderDetail).not.toHaveBeenCalled()
  })
  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('Pending 只显示标记已支付，确认框明示不改库存', async () => {
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })
    const page = requireElement(testUtils, '.admin-order-detail-page')
    expect(page.textContent).toContain('用户：#7 · 开发用户')
    expect(page.textContent).toContain('标记为已支付')
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-order-detail-page__transition'))
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({ content: expect.stringContaining('不改变库存') }))
    expect(mockAdvanceStatus).toHaveBeenCalledTimes(1)
  })

  it('Paid 只显示完成订单', async () => {
    mockDetail = { status: 'content', order: { ...pendingOrder, status: { value: 'paid', label: '已支付' } } }
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })
    expect(requireElement(testUtils, '.admin-order-detail-page__transition').textContent).toContain('完成订单')
  })

  it.each([
    ['cancelled', '已取消'],
    ['completed', '已完成'],
  ] as const)('%s 终态不显示变迁按钮', async (value, label) => {
    mockDetail = { status: 'content', order: { ...pendingOrder, status: { value, label } } }
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })
    expect(testUtils.queries.querySelector('.admin-order-detail-page__transition')).toBeNull()
    expect(testUtils.queries.querySelector('.admin-order-detail-page__terminal')).not.toBeNull()
  })

  it('unknown 不允许立即重放命令', async () => {
    mockTransition = { status: 'unknown', action: 'mark_paid', errorMessage: '结果未知' }
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })
    expect(testUtils.queries.querySelector('.admin-order-detail-page__transition')).toBeNull()
    expect(testUtils.queries.querySelector('.admin-transition-feedback')?.textContent).toContain('结果未知')
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
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
