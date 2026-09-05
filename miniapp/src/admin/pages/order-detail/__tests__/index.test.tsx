import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AdminOrderDetail } from '@/api/endpoints/orders'
import type { AdminOrderDetailState, AdminOrderTransitionState } from '@/features/order'
import type { AdminRefundState, OrderFinancialState } from '@/features/wallet'
import type { AuthContextValue } from '@/auth'

import AdminOrderDetailPage, { AuthenticatedAdminOrderDetail } from '../index'

let mockDetail: AdminOrderDetailState
let mockTransition: AdminOrderTransitionState
let mockFinancialState: OrderFinancialState
let mockRefundState: AdminRefundState
let mockAuth: AuthContextValue
const mockAdvanceStatus = jest.fn(async () => undefined)
const mockUseAdminOrderDetail = jest.fn()
const mockRefundSubmit = jest.fn(async () => true)
const mockFinancialRetry = jest.fn()
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
jest.mock('@/features/wallet', () => ({
  getPaymentMethodLabel: () => '人工登记',
  getPaymentStatusLabel: () => '已支付',
  getRefundStatusLabel: () => '已退款',
  useAdminRefund: () => ({ state: mockRefundState, submit: mockRefundSubmit }),
  useOrderFinancial: () => ({
    state: mockFinancialState,
    retry: mockFinancialRetry,
  }),
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

const settledPayment = {
  id: 8,
  payment_no: `PY${'A'.repeat(26)}`,
  order_id: 101,
  recharge_order_id: null,
  purpose: 'order',
  method: 'wallet',
  amount: '99.00',
  status: 'succeeded',
  created_at: '2026-08-24T08:00:00Z',
  updated_at: '2026-08-24T08:00:00Z',
  succeeded_at: '2026-08-24T08:00:00Z',
} as const

const settledRefund = {
  id: 9,
  refund_no: `RF${'B'.repeat(26)}`,
  order_id: 101,
  method: 'wallet',
  amount: '99.00',
  status: 'succeeded',
  reason: '顾客申请整单退款',
  operator_id: 2,
  inventory_restored: true,
  created_at: '2026-08-24T08:10:00Z',
  updated_at: '2026-08-24T08:10:00Z',
  succeeded_at: '2026-08-24T08:10:00Z',
} as const

describe('AuthenticatedAdminOrderDetail', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockDetail = { status: 'content', order: pendingOrder }
    mockTransition = { status: 'idle' }
    mockFinancialState = {
      status: 'content',
      financial: {
        order_id: 101,
        order_status: { value: 'pending', label: '待支付' },
        payment: null,
        refund: null,
      },
    }
    mockRefundState = { status: 'idle' }
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
      register: jest.fn(),
      login: jest.fn(),
      loginWithWechat: jest.fn(),
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
    setPaidRefundableOrder()
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

  it('退款提交占用共享门禁，冻结完成按钮且成功后立即移除完成入口', async () => {
    setPaidRefundableOrder()
    let resolveRefund!: (succeeded: boolean) => void
    mockRefundSubmit.mockImplementationOnce(() => new Promise<boolean>((resolve) => {
      resolveRefund = resolve
    }))
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })
    input(testUtils, requireElement(testUtils, '.admin-order-financial__reason'), '顾客申请整单退款')

    testUtils.fireEvent.click(requireElement(testUtils, '.admin-order-financial__refund'))
    await flush(testUtils)

    expect(mockRefundSubmit).toHaveBeenCalledTimes(1)
    expect(requireElement(testUtils, '.admin-order-financial__refund').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-order-detail-page__transition').getAttribute('disabled')).not.toBeNull()
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-order-detail-page__transition'))
    expect(mockAdvanceStatus).not.toHaveBeenCalled()

    resolveRefund(true)
    await flush(testUtils)

    expect(mockFinancialRetry).toHaveBeenCalledTimes(1)
    expect(testUtils.queries.querySelector('.admin-order-detail-page__transition')).toBeNull()
    expect(requireElement(testUtils, '.admin-order-detail-page__terminal').textContent).toContain('已存在全额退款')
  })

  it('完成提交占用共享门禁，冻结退款原因和退款按钮', async () => {
    setPaidRefundableOrder()
    let resolveTransition!: (value: undefined) => void
    mockAdvanceStatus.mockImplementationOnce(() => new Promise<undefined>((resolve) => {
      resolveTransition = resolve
    }))
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })

    testUtils.fireEvent.click(requireElement(testUtils, '.admin-order-detail-page__transition'))
    await flush(testUtils)

    expect(mockAdvanceStatus).toHaveBeenCalledTimes(1)
    expect(requireElement(testUtils, '.admin-order-financial__reason').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-order-financial__refund').getAttribute('disabled')).not.toBeNull()

    resolveTransition(undefined)
    await flush(testUtils)
  })

  it('退款结果 unknown 时允许同意图重试，但冻结完成订单', async () => {
    setPaidRefundableOrder()
    mockRefundState = { status: 'unknown', errorMessage: '退款结果可能未知' }
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })

    expect(requireElement(testUtils, '.admin-order-financial__reason').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-order-financial__refund').textContent).toContain('重试同一笔退款')
    expect(requireElement(testUtils, '.admin-order-detail-page__transition').getAttribute('disabled')).not.toBeNull()
  })

  it('退款 submitting 时冻结完成订单', async () => {
    setPaidRefundableOrder()
    mockRefundState = { status: 'submitting' }
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })

    expect(requireElement(testUtils, '.admin-order-detail-page__transition').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-order-financial__refund').textContent).toContain('正在退款')
  })

  it('完成结果 unknown 时冻结退款动作', async () => {
    setPaidRefundableOrder()
    mockTransition = { status: 'unknown', action: 'complete', errorMessage: '完成结果可能未知' }
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })

    expect(testUtils.queries.querySelector('.admin-order-detail-page__transition')).toBeNull()
    expect(requireElement(testUtils, '.admin-order-financial__reason').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-order-financial__refund').getAttribute('disabled')).not.toBeNull()
  })

  it('完成 submitting 时冻结退款动作', async () => {
    setPaidRefundableOrder()
    mockTransition = { status: 'submitting', action: 'complete' }
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })

    expect(requireElement(testUtils, '.admin-order-financial__reason').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-order-financial__refund').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-order-detail-page__transition').textContent).toContain('正在更新')
  })

  it('权威资金事实已有退款时不再提供完成订单或重复退款', async () => {
    setPaidRefundableOrder()
    mockFinancialState = {
      status: 'content',
      financial: {
        order_id: 101,
        order_status: { value: 'paid', label: '已支付' },
        payment: settledPayment,
        refund: settledRefund,
      },
    }
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })

    expect(testUtils.queries.querySelector('.admin-order-detail-page__transition')).toBeNull()
    expect(testUtils.queries.querySelector('.admin-order-financial__refund-form')).toBeNull()
    expect(requireElement(testUtils, '.admin-order-financial__refund-record').textContent).toContain('已退款')
  })

  it('COMPLETED 且已结算订单可填写原因并执行全额退款', async () => {
    mockDetail = { status: 'content', order: { ...pendingOrder, status: { value: 'completed', label: '已完成' } } }
    mockFinancialState = {
      status: 'content',
      financial: {
        order_id: 101,
        order_status: { value: 'completed', label: '已完成' },
        payment: settledPayment,
        refund: null,
      },
    }
    await testUtils.mount(AuthenticatedAdminOrderDetail, { props: { orderId: 101 } })
    input(testUtils, requireElement(testUtils, '.admin-order-financial__reason'), '顾客申请整单退款')
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-order-financial__refund'))
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({ content: expect.stringContaining('¥99.00') }))
    expect(mockRefundSubmit).toHaveBeenCalledWith('顾客申请整单退款')
    expect(mockFinancialRetry).toHaveBeenCalled()
  })
})

function setPaidRefundableOrder(): void {
  mockDetail = {
    status: 'content',
    order: { ...pendingOrder, status: { value: 'paid', label: '已支付' } },
  }
  mockFinancialState = {
    status: 'content',
    financial: {
      order_id: 101,
      order_status: { value: 'paid', label: '已支付' },
      payment: settledPayment,
      refund: null,
    },
  }
}

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

function input(testUtils: ReactTestUtil, element: Element, value: string): void {
  const fireCustomEvent = testUtils.fireEvent as unknown as (target: Element, event: Event) => void
  fireCustomEvent(element, new CustomEvent('input', { bubbles: true, detail: { value } }))
}
