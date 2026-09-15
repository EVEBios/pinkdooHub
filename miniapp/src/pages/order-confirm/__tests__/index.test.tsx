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
import type { PendingTableEntryIntent } from '@/features/table_session'

import OrderConfirmPage from '../index'

let mockAuth: AuthContextValue
let mockCart: CartContextValue
let mockSubmission: UseOrderSubmissionResult
let mockTableIntentId: string | undefined
const mockSubmit = jest.fn(async () => undefined)
const mockReset = jest.fn()
const mockUseCart = jest.fn()
const mockUseOrderSubmission = jest.fn()
const mockLoadPendingTableEntry = jest.fn<
Promise<PendingTableEntryIntent | undefined>,
[string, number]
>()
const mockClearPendingTableEntry = jest.fn<Promise<boolean>, [PendingTableEntryIntent]>()

jest.mock('@tarojs/taro', () => {
  const actual = jest.requireActual('@tarojs/taro')
  return {
    __esModule: true,
    ...actual,
    useDidShow: jest.fn(),
    default: actual.default,
    useRouter: () => ({ params: { table_intent: mockTableIntentId } }),
  }
})

jest.mock('@/auth', () => ({
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
  ORDER_CONFIRM_PATH: '/pages/order-confirm/index',
  ORDER_LIST_PATH: '/pages/orders/index',
  buildLoginUrl: (redirect?: string) => redirect
    ? `/pages/login/index?redirect=${encodeURIComponent(redirect)}`
    : '/pages/login/index',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/order', () => ({
  cartItemKey: (item: { productId: number; experienceOptionId: number | null; kitColorId: number | null }) => (
    `${item.productId}:${item.experienceOptionId ?? item.kitColorId ?? 'fixed'}`
  ),
  ORDER_REMARK_LIMIT: 500,
  useCart: () => {
    mockUseCart()
    return mockCart
  },
  useOrderSubmission: () => {
    mockUseOrderSubmission()
    return mockSubmission
  },
}))

jest.mock('@/features/table_session', () => ({
  buildTableEntryUrl: (token: string, orderId?: number, intentId?: string) => (
    `/pages/table-entry/index?token=${token}` +
    (orderId === undefined ? '' : `&order_id=${orderId}`) +
    (intentId === undefined ? '' : `&table_intent=${intentId}`)
  ),
  buildTableOrderConfirmUrl: (intentId: string) => (
    `/pages/order-confirm/index?table_intent=${intentId}`
  ),
  clearPendingTableEntry: (intent: PendingTableEntryIntent) => (
    mockClearPendingTableEntry(intent)
  ),
  loadPendingTableEntry: (intentId: string, userId: number) => (
    mockLoadPendingTableEntry(intentId, userId)
  ),
  parseTableOrderConfirmRoute: () => mockTableIntentId,
}))

jest.mock('@/utils/format', () => ({
  ...jest.requireActual('@/utils/format'),
  formatPrice: (value: string) => value,
}))

const cartItems: CartContextValue['items'] = [
  {
    productId: 1,
    experienceOptionId: 11,
    kitColorId: null,
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
    kitColorId: null,
    productType: 'kit',
    kitKind: 'fixed',
    productName: '基础拼豆套装',
    configurationLabel: null,
    unitPrice: '199.00',
    imageUrl: null,
    quantity: 2,
  },
]

const tableToken = 'Aa0123456789BbCcDdEeFfGgHhIiJjKk'
const tableIntentId = 'miniapp-table-checkout-m1234567-1-abcdefghijklmnopqrst'
const pendingTableIntent: PendingTableEntryIntent = {
  intentId: tableIntentId,
  token: tableToken,
  userId: 7,
}

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
      kit_color_id: null,
      kit_color_slot_no: null,
      kit_color_code: null,
      kit_color_name: null,
      sale_unit_grams: null,
      total_weight_grams: null,
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
      kit_color_id: null,
      kit_color_slot_no: null,
      kit_color_code: null,
      kit_color_name: null,
      sale_unit_grams: null,
      total_weight_grams: null,
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
    jest.spyOn(Taro, 'getStorage').mockRejectedValue({ errMsg: 'getStorage:fail data not found' })
    jest.spyOn(Taro, 'setStorage').mockResolvedValue({ errMsg: 'setStorage:ok' })
    testUtils = new ReactTestUtil()
    mockTableIntentId = undefined
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
      updateProfile: jest.fn(),
      login: jest.fn(async () => undefined),
      loginWithWechat: jest.fn(async () => undefined),
      logout: jest.fn(async () => undefined),
      retryInitialization: jest.fn(),
    }
    mockCart = {
      status: 'ready',
      items: cartItems,
      addItem: jest.fn(async () => undefined),
      addItems: jest.fn(async () => undefined),
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
    mockLoadPendingTableEntry.mockResolvedValue(undefined)
    mockClearPendingTableEntry.mockResolvedValue(true)
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

  it.each(['admin', 'super_admin'] as const)('%s 深链不挂载购物车或下单 Hook', async (role) => {
    mockAuth = {
      ...mockAuth,
      user: { ...mockAuth.user!, role },
    }
    await testUtils.mount(OrderConfirmPage)

    expect(requireElement(testUtils, '.admin-workbench-redirect').textContent).toContain('正在进入店铺工作台')
    expect(mockUseCart).not.toHaveBeenCalled()
    expect(mockUseOrderSubmission).not.toHaveBeenCalled()
    await flush(testUtils)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
  })

  it.each([
    ['missing', '账户信息不完整'],
    ['unknown', '账户角色暂不支持'],
  ] as const)('认证资料为 %s 时 fail closed', async (userCase, expectedText) => {
    mockAuth = {
      ...mockAuth,
      user: userCase === 'missing'
        ? undefined
        : { ...mockAuth.user!, role: 'operator' as never },
    }
    await testUtils.mount(OrderConfirmPage)

    expect(requireElement(testUtils, '.order-confirm-state__title').textContent).toContain(expectedText)
    expect(mockUseCart).not.toHaveBeenCalled()
    expect(mockUseOrderSubmission).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
  })

  it('空购物清单不允许进入提交表单', async () => {
    mockCart = { ...mockCart, items: [] }

    await testUtils.mount(OrderConfirmPage)

    expect(testUtils.queries.querySelector('.order-confirm-page')?.textContent)
      .toContain('没有可以确认的商品')
    expect(testUtils.queries.querySelector('.order-confirm-page__submit')).toBeNull()
    testUtils.fireEvent.click(requireElement(testUtils, '.order-confirm-state__action'))
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/index/index' })
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

  it('桌台确认页登录回跳保留本次结算意图', async () => {
    mockTableIntentId = tableIntentId
    mockAuth = { ...mockAuth, status: 'guest', user: undefined }
    await testUtils.mount(OrderConfirmPage)

    testUtils.fireEvent.click(requireElement(testUtils, '.order-confirm-state__login'))

    const target = `/pages/order-confirm/index?table_intent=${tableIntentId}`
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: `/pages/login/index?redirect=${encodeURIComponent(target)}`,
    })
  })

  it('展示 Experience/Kit 预览并把受控 remark 与 Cart 快照交给提交用例', async () => {
    await testUtils.mount(OrderConfirmPage)

    const rows = testUtils.queries.querySelectorAll('.order-confirm-item')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('1小时 · 2人 · 工作日')
    expect(rows[1].textContent).not.toContain('工作日')
    expect(testUtils.queries.querySelector('.order-confirm-page__notice')?.textContent)
      .toContain('实际金额和库存将在提交时确认')

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

    expect(mockSubmit).toHaveBeenCalledWith(cartItems, '周五晚上到店', undefined)
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
    const actions = requireElement(testUtils, '.order-result-actions').children
    testUtils.fireEvent.click(actions[0])
    await flush(testUtils)
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/orders/index' })
    testUtils.fireEvent.click(actions[1])
    await flush(testUtils)
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/index/index' })
  })

  it('含 Experience 的新订单会带精确 ID 自动回到扫码桌台', async () => {
    let resolveNavigation!: () => void
    mockTableIntentId = tableIntentId
    mockLoadPendingTableEntry.mockResolvedValue(pendingTableIntent)
    ;(Taro.reLaunch as jest.Mock).mockReturnValueOnce(new Promise<void>((resolve) => {
      resolveNavigation = resolve
    }))
    mockSubmission = submissionState({
      status: 'succeeded',
      submittedItems: cartItems,
      request: { items: [{ product_id: 1, experience_option_id: 11, quantity: 1 }] },
      order: createdOrder,
    })

    await testUtils.mount(OrderConfirmPage)
    await flush(testUtils)

    expect(Taro.reLaunch).toHaveBeenCalledWith({
      url: `/pages/table-entry/index?token=${tableToken}&order_id=${createdOrder.id}` +
        `&table_intent=${tableIntentId}`,
    })
    expect(mockLoadPendingTableEntry).toHaveBeenCalledWith(tableIntentId, 7)
    expect(requireElement(testUtils, '.order-result-actions__primary').textContent)
      .toContain('正在返回扫码桌台')
    const actions = requireElement(testUtils, '.order-result-actions').children
    expect(actions[1].getAttribute('disabled')).not.toBeNull()
    expect(actions[2].getAttribute('disabled')).not.toBeNull()

    await testUtils.act(async () => resolveNavigation())
    await flush(testUtils)
  })

  it('自动回桌导航失败时保留意图，并可以明确重试', async () => {
    mockTableIntentId = tableIntentId
    mockLoadPendingTableEntry.mockResolvedValue(pendingTableIntent)
    ;(Taro.reLaunch as jest.Mock)
      .mockRejectedValueOnce(new Error('navigation failed'))
      .mockResolvedValueOnce(undefined)
    mockSubmission = submissionState({
      status: 'succeeded',
      submittedItems: cartItems,
      request: { items: [{ product_id: 1, experience_option_id: 11, quantity: 1 }] },
      order: createdOrder,
    })

    await testUtils.mount(OrderConfirmPage)
    await flush(testUtils)

    expect(requireElement(testUtils, '.order-result-warning').textContent)
      .toContain('桌台信息已保留')
    const retry = requireElement(testUtils, '.order-result-actions__primary')
    expect(retry.textContent).toContain('重新返回桌台')

    testUtils.fireEvent.click(retry)
    await flush(testUtils)

    expect(Taro.reLaunch).toHaveBeenCalledTimes(2)
    expect(Taro.reLaunch).toHaveBeenLastCalledWith({
      url: `/pages/table-entry/index?token=${tableToken}&order_id=${createdOrder.id}` +
        `&table_intent=${tableIntentId}`,
    })
    expect(mockLoadPendingTableEntry).toHaveBeenCalledTimes(2)
  })

  it('自动回桌重试前重新核对意图，已被新扫码替换时不跳回旧桌', async () => {
    mockTableIntentId = tableIntentId
    mockLoadPendingTableEntry
      .mockResolvedValueOnce(pendingTableIntent)
      .mockResolvedValueOnce(undefined)
    ;(Taro.reLaunch as jest.Mock).mockRejectedValueOnce(new Error('navigation failed'))
    mockSubmission = submissionState({
      status: 'succeeded',
      submittedItems: cartItems,
      request: { items: [{ product_id: 1, experience_option_id: 11, quantity: 1 }] },
      order: createdOrder,
    })

    await testUtils.mount(OrderConfirmPage)
    await flush(testUtils)
    testUtils.fireEvent.click(requireElement(testUtils, '.order-result-actions__primary'))
    await flush(testUtils)

    expect(mockLoadPendingTableEntry).toHaveBeenCalledTimes(2)
    expect(Taro.reLaunch).toHaveBeenCalledTimes(1)
    expect(mockClearPendingTableEntry).not.toHaveBeenCalled()
  })

  it('纯 Kit 新订单不自动回桌并收口本次无法开台的意图', async () => {
    mockTableIntentId = tableIntentId
    mockLoadPendingTableEntry.mockResolvedValue(pendingTableIntent)
    mockSubmission = submissionState({
      status: 'succeeded',
      submittedItems: cartItems.slice(1),
      request: { items: [{ product_id: 2, quantity: 2 }] },
      order: { ...createdOrder, items: createdOrder.items.slice(1) },
    })

    await testUtils.mount(OrderConfirmPage)
    await flush(testUtils)

    expect(mockLoadPendingTableEntry).toHaveBeenCalledWith(tableIntentId, 7)
    expect(mockClearPendingTableEntry).toHaveBeenCalledWith(pendingTableIntent)
    expect(Taro.reLaunch).not.toHaveBeenCalled()
    expect(testUtils.queries.querySelector('.order-result-actions')?.textContent)
      .toContain('查看我的订单')
  })

  it('普通商城 Experience 订单不读取或消费设备上陈旧桌台意图', async () => {
    mockLoadPendingTableEntry.mockResolvedValue(pendingTableIntent)
    mockSubmission = submissionState({
      status: 'succeeded',
      submittedItems: cartItems,
      request: { items: [{ product_id: 1, experience_option_id: 11, quantity: 1 }] },
      order: createdOrder,
    })

    await testUtils.mount(OrderConfirmPage)
    await flush(testUtils)

    expect(mockLoadPendingTableEntry).not.toHaveBeenCalled()
    expect(mockClearPendingTableEntry).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
  })

  it('从普通购物车入口也读取扫码选桌并提交开台参数', async () => {
    jest.spyOn(Taro, 'getStorage').mockResolvedValue({ errMsg: 'getStorage:ok', data: {
      selection: { tableNo: 'T08', selectionId: 'selection-one', savedAt: Date.now() },
    } })
    await testUtils.mount(OrderConfirmPage)
    await flush(testUtils)
    expect(requireElement(testUtils, '.table-selector__title').textContent).toContain('T08')
    const submit = requireElement(testUtils, '.order-confirm-page__submit')
    expect(submit.textContent).toBe('确认订单并开台')
    testUtils.fireEvent.click(submit)
    expect(mockSubmit).toHaveBeenCalledWith(cartItems, '', { userId: 7, tableNo: 'T08' })
  })

  it('过期选桌不能静默变成普通下单', async () => {
    jest.spyOn(Taro, 'getStorage').mockResolvedValue({ errMsg: 'getStorage:ok', data: {
      selection: { tableNo: 'T08', selectionId: 'selection-one', savedAt: Date.now() - 3 * 60 * 60 * 1000 },
    } })
    await testUtils.mount(OrderConfirmPage)
    await flush(testUtils)
    expect(requireElement(testUtils, '.order-confirm-page').textContent).toContain('选桌已失效')
    testUtils.fireEvent.click(requireElement(testUtils, '.order-confirm-page__submit'))
    expect(mockSubmit).not.toHaveBeenCalled()
  })

  it('购物车已空也能找回未确认的原开台提交', async () => {
    const originalRequest = { items: [{ product_id: 1, experience_option_id: 11, quantity: 1 }],
      table_no: 'T08', table_checkout_key: 'original-key', remark: '原备注' }
    jest.spyOn(Taro, 'getStorage').mockResolvedValue({ errMsg: 'getStorage:ok', data: {
      attempt: { request: originalRequest, items: cartItems, selectionId: 'selection-one' },
    } })
    mockCart = { ...mockCart, items: [] }
    await testUtils.mount(OrderConfirmPage)
    await flush(testUtils)
    expect(requireElement(testUtils, '.order-confirm-state__title').textContent).toContain('核对上次开台订单')
    testUtils.fireEvent.click(requireElement(testUtils, '.order-confirm-state__action'))
    expect(mockSubmit).toHaveBeenCalledWith(cartItems, '原备注', { userId: 7, tableNo: 'T08' })
  })

  it('其他用户不能消费原用户的桌台意图', async () => {
    mockTableIntentId = tableIntentId
    mockAuth = {
      ...mockAuth,
      user: { ...mockAuth.user!, id: 8 },
    }
    mockLoadPendingTableEntry.mockResolvedValue(undefined)
    mockSubmission = submissionState({
      status: 'succeeded',
      submittedItems: cartItems,
      request: { items: [{ product_id: 1, experience_option_id: 11, quantity: 1 }] },
      order: createdOrder,
    })

    await testUtils.mount(OrderConfirmPage)
    await flush(testUtils)

    expect(mockLoadPendingTableEntry).toHaveBeenCalledWith(tableIntentId, 8)
    expect(Taro.reLaunch).not.toHaveBeenCalled()
    expect(mockClearPendingTableEntry).not.toHaveBeenCalled()
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
    await Promise.resolve()
    await Promise.resolve()
  })
}
