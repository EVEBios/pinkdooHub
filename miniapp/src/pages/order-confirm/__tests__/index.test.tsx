import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import { BusinessError, TimeoutError } from '@/api'
import type { OrderDetail } from '@/api/endpoints/orders'
import type { AuthContextValue } from '@/auth'
import type {
  CartContextValue,
  OrderSubmissionState,
  UseOrderSubmissionResult,
} from '@/features/order'

import OrderConfirmPage from '../index'

let mockAuth: AuthContextValue
let mockCart: CartContextValue
let mockSubmission: UseOrderSubmissionResult
const mockSubmit = jest.fn(async () => undefined)
const mockReset = jest.fn()

jest.mock('@/auth', () => ({
  ORDER_CONFIRM_PATH: '/pages/order-confirm/index',
  ORDER_LIST_PATH: '/pages/orders/index',
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fpages%2Forder-confirm%2Findex',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/order', () => ({
  ORDER_REMARK_LIMIT: 500,
  useCart: () => mockCart,
  useOrderSubmission: () => mockSubmission,
}))

jest.mock('@/utils/format', () => ({
  formatPrice: (value: string) => value,
}))

const cartItems: CartContextValue['items'] = [
  {
    productId: 1,
    experienceOptionId: 11,
    productType: 'experience',
    productName: '周末拼豆体验',
    configurationLabel: '1小时 · 2人 · 工作日',
    unitPrice: '99.00',
    imageUrl: null,
    quantity: 1,
  },
  {
    productId: 2,
    experienceOptionId: null,
    productType: 'kit',
    productName: '基础拼豆套装',
    configurationLabel: null,
    unitPrice: '199.00',
    imageUrl: null,
    quantity: 2,
  },
]

const createdOrder: OrderDetail = {
  id: 101,
  order_no: 'OD01K2M7Y0J7A3N5Q8T4V6W9X2BC',
  total_amount: '497.00',
  status: { value: 'pending', label: '待支付' },
  remark: '服务端备注快照',
  items: [
    {
      id: 1001,
      product_id: 1,
      experience_option_id: 11,
      product_name: '服务端体验名称快照',
      option_duration_minutes: 60,
      option_participants: 1,
      option_day_type: { value: 'weekday', label: '工作日' },
      product_price: '99.00',
      quantity: 1,
      subtotal: '99.00',
    },
    {
      id: 1002,
      product_id: 2,
      experience_option_id: null,
      product_name: '服务端套装名称快照',
      option_duration_minutes: null,
      option_participants: null,
      option_day_type: null,
      product_price: '199.00',
      quantity: 2,
      subtotal: '398.00',
    },
  ],
  created_at: '2026-08-13T10:30:00Z',
  updated_at: '2026-08-13T10:30:00Z',
}

function submissionState(state: OrderSubmissionState): UseOrderSubmissionResult {
  return { state, submit: mockSubmit, reset: mockReset }
}

describe('OrderConfirmPage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'authenticated',
      user: {
        id: 7,
        username: 'alice',
        nickname: 'Alice',
        phone: '13800138000',
        avatar: null,
        role: 'user',
        status: 'normal',
        last_login_at: null,
        created_at: '2026-08-13T10:30:00Z',
        updated_at: '2026-08-13T10:30:00Z',
      },
      register: jest.fn(),
      login: jest.fn(async () => undefined),
      logout: jest.fn(async () => undefined),
      retryInitialization: jest.fn(),
    }
    mockCart = {
      status: 'ready',
      items: cartItems,
      addItem: jest.fn(async () => undefined),
      updateQuantity: jest.fn(async () => undefined),
      removeItem: jest.fn(async () => undefined),
      clear: jest.fn(async () => undefined),
      reconcileSubmittedItems: jest.fn(async () => ({
        status: 'completed' as const,
        preservedItemKeys: [],
      })),
      retryInitialization: jest.fn(),
    }
    mockSubmission = submissionState({ status: 'idle' })
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it.each([
    ['initializing', '正在准备订单…'],
    ['error', '购物清单暂不可用'],
  ] as const)('渲染购物清单 %s 状态', async (status, text) => {
    mockCart = {
      ...mockCart,
      status,
      initializationError: status === 'error' ? new Error('storage unavailable') : undefined,
    }

    await testUtils.mount(OrderConfirmPage)

    expect(testUtils.queries.querySelector('.order-confirm-page')?.textContent).toContain(text)
  })

  it('空购物清单不允许进入提交表单', async () => {
    mockCart = { ...mockCart, items: [] }

    await testUtils.mount(OrderConfirmPage)

    expect(testUtils.queries.querySelector('.order-confirm-page')?.textContent)
      .toContain('没有可以确认的商品')
    expect(testUtils.queries.querySelector('.order-confirm-page__submit')).toBeNull()
  })

  it('游客进入安全登录地址，说明登录后返回且保留购物清单', async () => {
    mockAuth = { ...mockAuth, status: 'guest', user: undefined }

    await testUtils.mount(OrderConfirmPage)

    const loginButton = testUtils.queries.querySelector('.order-confirm-state__login')
    if (!loginButton) {
      throw new Error('没有渲染登录按钮')
    }
    expect(testUtils.queries.querySelector('.order-confirm-page')?.textContent).toContain('购物清单不会被清空')
    testUtils.fireEvent.click(loginButton)
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fpages%2Forder-confirm%2Findex',
    })
  })

  it('展示 Experience/Kit 预览并把受控 remark 与 Cart 快照交给提交用例', async () => {
    await testUtils.mount(OrderConfirmPage)

    const rows = testUtils.queries.querySelectorAll('.order-confirm-item')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('1小时 · 2人 · 工作日')
    expect(rows[1].textContent).not.toContain('工作日')
    expect(testUtils.queries.querySelector('.order-confirm-page__notice')?.textContent)
      .toContain('后端重新校验')

    const remark = testUtils.queries.querySelector('.order-confirm-remark__input')
    const submit = testUtils.queries.querySelector('.order-confirm-page__submit')
    if (!remark || !submit) {
      throw new Error('确认页表单未完整渲染')
    }
    const fireCustomEvent = testUtils.fireEvent as unknown as (
      element: Element,
      event: Event,
    ) => void
    fireCustomEvent(remark, new CustomEvent('input', {
      bubbles: true,
      detail: { value: '周五晚上到店' },
    }))
    testUtils.fireEvent.click(submit)

    expect(mockSubmit).toHaveBeenCalledWith(cartItems, '周五晚上到店')
  })

  it('提交期间禁用按钮并显示明确进行中状态', async () => {
    mockSubmission = submissionState({
      status: 'submitting',
      submittedItems: cartItems,
      request: { items: [{ product_id: 1, experience_option_id: 11, quantity: 1 }] },
    })

    await testUtils.mount(OrderConfirmPage)

    const button = testUtils.queries.querySelector('.order-confirm-page__submit')
    expect(button?.textContent).toContain('正在创建订单')
    expect(button?.getAttribute('disabled')).not.toBeNull()
  })

  it('区分明确库存失败与结果未知，不把 unknown 描述为创建失败', async () => {
    const stockError = new BusinessError(
      { operation: 'orders.create', statusCode: 409 },
      40931,
      'Insufficient stock',
      { product_id: 2, requested_quantity: 2 },
    )
    mockSubmission = submissionState({
      status: 'failed',
      submittedItems: cartItems,
      request: { items: [{ product_id: 2, quantity: 2 }] },
      error: stockError,
    })
    await testUtils.mount(OrderConfirmPage)
    expect(testUtils.queries.querySelector('.order-confirm-feedback')?.textContent).toContain('库存不足')
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    mockSubmission = submissionState({
      status: 'unknown',
      submittedItems: cartItems,
      request: { items: [{ product_id: 2, quantity: 2 }] },
      error: new TimeoutError({ operation: 'orders.create' }, new Error('timeout')),
    })
    await testUtils.mount(OrderConfirmPage)
    const message = testUtils.queries.querySelector('.order-confirm-feedback')?.textContent
    expect(message).toContain('结果可能未知')
    expect(message).toContain('不要立即重复创建')
    expect(message).not.toContain('创建订单失败')
    expect(testUtils.queries.querySelector('.order-confirm-page__submit')?.getAttribute('disabled'))
      .not.toBeNull()
    const checkOrders = testUtils.queries.querySelector('.order-confirm-feedback__action')
    if (!checkOrders) throw new Error('unknown 未提供我的订单核对入口')
    testUtils.fireEvent.click(checkOrders)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/orders/index' })
  })

  it('成功后只展示服务端快照，并提示本地对账异常但不降级订单结果', async () => {
    mockCart = { ...mockCart, items: [] }
    mockSubmission = submissionState({
      status: 'succeeded',
      submittedItems: cartItems,
      request: {
        items: [
          { product_id: 1, experience_option_id: 11, quantity: 1 },
          { product_id: 2, quantity: 2 },
        ],
      },
      order: createdOrder,
      cartReconciliation: { status: 'conflict', preservedItemKeys: ['2:kit'] },
    })

    await testUtils.mount(OrderConfirmPage)

    const result = testUtils.queries.querySelector('.order-result-page')
    expect(result?.textContent).toContain('订单创建成功')
    expect(result?.textContent).toContain(createdOrder.order_no)
    expect(result?.textContent).toContain('¥497.00')
    expect(result?.textContent).toContain('服务端体验名称快照')
    expect(result?.textContent).toContain('60 分钟 · 1 人 · 工作日')
    expect(result?.textContent).not.toContain('周末拼豆体验')
    expect(result?.textContent).toContain('订单已经创建')
    expect(result?.textContent).toContain('不要重复创建')
    expect(result?.textContent).toContain('查看我的订单')
  })
})
