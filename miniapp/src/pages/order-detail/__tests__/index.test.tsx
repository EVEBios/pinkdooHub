import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { OrderDetail } from '@/api/endpoints/orders'
import type { OrderCancellationState, OrderDetailState } from '@/features/order'
import type { OrderFinancialState, OrderPaymentState } from '@/features/wallet'

import { AuthenticatedOrderDetail } from '../index'

let mockDetail: OrderDetailState
let mockCancellation: OrderCancellationState
let mockFinancialState: OrderFinancialState
let mockPaymentState: OrderPaymentState
let mockMemberBalance = '500.00'
const mockCancel = jest.fn(async () => undefined)
const mockRetry = jest.fn()
const mockFinancialRetry = jest.fn()
const mockMemberRetry = jest.fn()
const mockPaymentReset = jest.fn()
const mockPayWithWallet = jest.fn(async () => false)
const showModalSpy = jest.spyOn(Taro, 'showModal')

jest.mock('@/auth', () => ({
  ORDER_LIST_PATH: '/pages/orders/index',
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fpages%2Forders%2Findex',
  useAuth: jest.fn(),
}))

jest.mock('@/features/order', () => ({
  parseOrderDetailRoute: jest.fn(),
  useOrderDetail: () => ({
    detail: mockDetail,
    cancellation: mockCancellation,
    cancel: mockCancel,
    retry: mockRetry,
  }),
}))

jest.mock('@/features/wallet', () => ({
  getPaymentMethodLabel: () => '余额支付',
  getPaymentStatusLabel: () => '已支付',
  moneyToCents: (value: string) => Math.round(Number(value) * 100),
  useMemberWallet: () => ({
    state: {
      status: 'content',
      member: {
        user: { status: 'normal' },
        wallet: {
          balance: mockMemberBalance, status: 'active',
          capabilities: { wallet_payment_enabled: true },
        },
      },
    },
    retry: mockMemberRetry,
  }),
  useOrderFinancial: () => ({
    state: mockFinancialState,
    retry: mockFinancialRetry,
  }),
  useOrderPayment: () => ({
    state: mockPaymentState,
    payWithWallet: mockPayWithWallet,
    reset: mockPaymentReset,
  }),
}))

jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

const pendingOrder: OrderDetail = {
  id: 101,
  order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
  total_amount: '298.00',
  status: { value: 'pending', label: '待支付' },
  remark: '服务端备注',
  items: [
    {
      id: 1,
      product_id: 1,
      experience_option_id: 11,
      kit_color_id: null,
      kit_color_slot_no: null,
      kit_color_code: null,
      kit_color_name: null,
      sale_unit_grams: null,
      total_weight_grams: null,
      product_name: '体验快照',
      option_duration_minutes: 60,
      option_participants: 1,
      option_day_type: { value: 'weekday', label: '工作日' },
      product_price: '99.00',
      quantity: 1,
      subtotal: '99.00',
    },
    {
      id: 2,
      product_id: 2,
      experience_option_id: null,
      kit_color_id: null,
      kit_color_slot_no: null,
      kit_color_code: null,
      kit_color_name: null,
      sale_unit_grams: null,
      total_weight_grams: null,
      product_name: '套装快照',
      option_duration_minutes: null,
      option_participants: null,
      option_day_type: null,
      product_price: '199.00',
      quantity: 1,
      subtotal: '199.00',
    },
  ],
  created_at: '2026-08-24T08:00:00Z',
  updated_at: '2026-08-24T08:00:00Z',
}

describe('AuthenticatedOrderDetail', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockDetail = { status: 'content', order: pendingOrder }
    mockCancellation = { status: 'idle' }
    mockFinancialState = {
      status: 'content',
      financial: {
        order_id: 101,
        order_status: { value: 'pending', label: '待支付' },
        payment: null,
        refund: null,
      },
    }
    mockPaymentState = { status: 'idle' }
    mockMemberBalance = '500.00'
    showModalSpy.mockResolvedValue({
      confirm: true,
      cancel: false,
      errMsg: 'showModal:ok',
    })
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('只显示服务端详情快照，Pending 经确认后取消', async () => {
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    const page = requireElement(testUtils, '.order-detail-page')
    expect(page.textContent).toContain('体验快照')
    expect(page.textContent).toContain('60 分钟 · 1 人 · 工作日')
    expect(page.textContent).toContain('套装快照')
    expect(page.textContent).toContain('¥298.00')
    expect(page.textContent).toContain('会员余额')
    expect(page.textContent).toContain('微信支付')
    expect(page.textContent).toContain('暂未开通')
    testUtils.fireEvent.click(requireElement(testUtils, '.order-detail-page__cancel'))
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalled()
    expect(mockCancel).toHaveBeenCalledTimes(1)
  })

  it('取消确认框打开起即锁住余额支付，不能并发发起两种命令', async () => {
    let resolveConfirmation!: (value: { confirm: boolean; cancel: boolean; errMsg: string }) => void
    showModalSpy.mockImplementationOnce(() => new Promise((resolve) => {
      resolveConfirmation = resolve
    }))
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })

    testUtils.fireEvent.click(requireElement(testUtils, '.order-detail-page__cancel'))
    await flush(testUtils)

    const paymentButton = requireElement(testUtils, '.order-payment__submit')
    expect(paymentButton.getAttribute('disabled')).not.toBeNull()
    testUtils.fireEvent.click(paymentButton)
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalledTimes(1)
    expect(mockPayWithWallet).not.toHaveBeenCalled()

    resolveConfirmation({ confirm: false, cancel: true, errMsg: 'showModal:ok' })
    await flush(testUtils)
  })

  it('支付确认框打开起即锁住取消，不能并发发起两种命令', async () => {
    let resolveConfirmation!: (value: { confirm: boolean; cancel: boolean; errMsg: string }) => void
    showModalSpy.mockImplementationOnce(() => new Promise((resolve) => {
      resolveConfirmation = resolve
    }))
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })

    testUtils.fireEvent.click(requireElement(testUtils, '.order-payment__submit'))
    await flush(testUtils)

    const cancelButton = requireElement(testUtils, '.order-detail-page__cancel')
    expect(cancelButton.getAttribute('disabled')).not.toBeNull()
    testUtils.fireEvent.click(cancelButton)
    await flush(testUtils)
    expect(Taro.showModal).toHaveBeenCalledTimes(1)
    expect(mockCancel).not.toHaveBeenCalled()

    resolveConfirmation({ confirm: false, cancel: true, errMsg: 'showModal:ok' })
    await flush(testUtils)
  })

  it.each([
    ['paid', '已支付'],
    ['cancelled', '已取消'],
    ['completed', '已完成'],
  ] as const)('%s 状态不显示取消入口', async (value, label) => {
    mockDetail = { status: 'content', order: { ...pendingOrder, status: { value, label } } }
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    expect(testUtils.queries.querySelector('.order-detail-page__cancel')).toBeNull()
  })

  it('余额不足时禁用余额支付，微信支付保持未开通且不发起请求', async () => {
    mockMemberBalance = '20.00'
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    expect(requireElement(testUtils, '.order-payment').textContent).toContain('余额不足')
    expect(requireElement(testUtils, '.order-payment__submit').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.order-payment__method--unavailable').getAttribute('disabled')).not.toBeNull()
  })

  it.each([
    [{ status: 'submitting' } as const, '支付处理中，暂不能取消'],
    [{ status: 'unknown', errorMessage: '支付结果可能未知' } as const, '请先核对支付结果'],
  ])('余额支付为 $status 时禁用取消订单', async (paymentState, cancelLabel) => {
    mockPaymentState = paymentState
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })

    const cancelButton = requireElement(testUtils, '.order-detail-page__cancel')
    expect(cancelButton.getAttribute('disabled')).not.toBeNull()
    expect(cancelButton.textContent).toContain(cancelLabel)
    testUtils.fireEvent.click(cancelButton)
    await flush(testUtils)
    expect(Taro.showModal).not.toHaveBeenCalled()
    expect(mockCancel).not.toHaveBeenCalled()
  })

  it('支付结果未知时同时重读订单与资金，未收敛前不 reset 或开放取消', async () => {
    mockPaymentState = { status: 'unknown', errorMessage: '支付结果可能未知' }
    mockFinancialState = { status: 'loading' }
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })

    testUtils.fireEvent.click(requireElement(testUtils, '.order-payment__reconcile'))
    await flush(testUtils)

    expect(mockRetry).toHaveBeenCalledTimes(1)
    expect(mockFinancialRetry).toHaveBeenCalledTimes(1)
    expect(mockPaymentReset).not.toHaveBeenCalled()
    expect(requireElement(testUtils, '.order-detail-page__cancel').getAttribute('disabled')).not.toBeNull()
  })

  it('订单与资金重读结果一致后才结束支付 unknown 锁定', async () => {
    mockPaymentState = { status: 'unknown', errorMessage: '支付结果可能未知' }
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })

    testUtils.fireEvent.click(requireElement(testUtils, '.order-payment__reconcile'))
    await flush(testUtils)

    expect(mockRetry).toHaveBeenCalledTimes(1)
    expect(mockFinancialRetry).toHaveBeenCalledTimes(1)
    expect(mockPaymentReset).toHaveBeenCalledTimes(1)
  })

  it('订单与资金状态不一致时保持锁定但允许再次重读', async () => {
    mockPaymentState = { status: 'unknown', errorMessage: '支付结果可能未知' }
    mockFinancialState = {
      status: 'content',
      financial: {
        order_id: 101,
        order_status: { value: 'paid', label: '已支付' },
        payment: null,
        refund: null,
      },
    }
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })

    const reconcile = requireElement(testUtils, '.order-payment__reconcile')
    testUtils.fireEvent.click(reconcile)
    await flush(testUtils)
    expect(mockPaymentReset).not.toHaveBeenCalled()
    expect(requireElement(testUtils, '.order-detail-page__cancel').getAttribute('disabled')).not.toBeNull()

    testUtils.fireEvent.click(requireElement(testUtils, '.order-payment__reconcile'))
    await flush(testUtils)
    expect(mockRetry).toHaveBeenCalledTimes(2)
    expect(mockFinancialRetry).toHaveBeenCalledTimes(2)
  })

  it('取消提交中不挂载支付入口', async () => {
    mockCancellation = { status: 'submitting' }
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })

    expect(testUtils.queries.querySelector('.order-payment')).toBeNull()
    const cancelButton = requireElement(testUtils, '.order-detail-page__cancel')
    expect(cancelButton.getAttribute('disabled')).not.toBeNull()
    expect(cancelButton.textContent).toContain('正在取消')
    expect(mockPayWithWallet).not.toHaveBeenCalled()
  })

  it('unknown 不提供重复取消入口，并引导回我的订单核对', async () => {
    mockCancellation = { status: 'unknown', errorMessage: '取消结果可能未知，请从我的订单重新核对' }
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    expect(testUtils.queries.querySelector('.order-cancel-feedback')?.textContent).toContain('结果可能未知')
    expect(testUtils.queries.querySelector('.order-payment')).toBeNull()
    expect(testUtils.queries.querySelector('.order-detail-page__cancel')).toBeNull()
    testUtils.fireEvent.click(requireElement(testUtils, '.order-detail-page__back'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/orders/index' })
  })

  it('取消成功和详情刷新失败同时可见', async () => {
    mockDetail = {
      status: 'content',
      order: { ...pendingOrder, status: { value: 'cancelled', label: '已取消' } },
    }
    mockCancellation = {
      status: 'succeeded',
      result: {
        id: 101,
        order_no: pendingOrder.order_no,
        status: { value: 'cancelled', label: '已取消' },
        updated_at: pendingOrder.updated_at,
      },
      refreshErrorMessage: '订单已取消，但详情刷新失败',
    }
    await testUtils.mount(AuthenticatedOrderDetail, { props: { orderId: 101 } })
    expect(testUtils.queries.querySelector('.order-cancel-feedback')?.textContent)
      .toContain('订单已取消，但详情刷新失败')
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
