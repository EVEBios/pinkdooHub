import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { ProductListItem } from '@/api/endpoints/products'
import type { EligibleOrder, PublicTableCode, TableSession } from '@/api/endpoints/table_sessions'
import type { AuthContextValue } from '@/auth'
import type { CartContextValue } from '@/features/order'
import type { PendingTableEntryIntent, TableEntryState } from '@/features/table_session'

import TableEntryPage from '../index'

const token = 'Aa0123456789BbCcDdEeFfGgHhIiJjKk'
const mockRefresh = jest.fn()
const mockClaim = jest.fn(async () => true)
const mockPay = jest.fn(async () => true)
const mockGetOrderDetail = jest.fn()
const mockGetOrderSession = jest.fn()
let mockAuth: AuthContextValue
let mockEntryState: TableEntryState
let mockIntentId: string | undefined
let mockOrderId: number | undefined
let mockCart: CartContextValue
let mockProductType: 'experience' | 'kit'

const mockSetProductType = jest.fn((value: 'experience' | 'kit') => {
  mockProductType = value
})
const tableIntentId = 'miniapp-table-checkout-m1234567-1-abcdefghijklmnopqrst'
const pendingIntent: PendingTableEntryIntent = { intentId: tableIntentId, token, userId: 7 }
const mockSavePendingTableEntry = jest.fn<Promise<PendingTableEntryIntent>, [string, number]>(
  () => Promise.resolve(pendingIntent),
)
const mockClearPendingTableEntry = jest.fn<Promise<boolean>, [PendingTableEntryIntent]>(
  () => Promise.resolve(true),
)

const product: ProductListItem = {
  id: 13,
  name: '标准拼豆体验',
  product_type: { value: 'experience', label: '拼豆体验' },
  cover_image: '/uploads/products/experience.png',
  display_price: '59.00',
  kit_kind: null,
  sale_unit_grams: null,
}

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    navigateTo: jest.fn(() => Promise.resolve()),
    redirectTo: jest.fn(() => Promise.resolve()),
    showModal: jest.fn(() => Promise.resolve({ confirm: true, cancel: false })),
    showToast: jest.fn(() => Promise.resolve()),
    switchTab: jest.fn(() => Promise.resolve()),
  },
  useRouter: () => ({ params: { token } }),
}))

jest.mock('@/auth', () => ({
  ORDER_LIST_PATH: '/pages/orders/index',
  buildLoginUrl: (redirect: string) => `/pages/login/index?redirect=${encodeURIComponent(redirect)}`,
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/table_session', () => ({
  buildTableEntryUrl: (value: string, orderId?: number, intentId?: string) => (
    `/pages/table-entry/index?token=${value}` +
    (orderId === undefined ? '' : `&order_id=${orderId}`) +
    (intentId === undefined ? '' : `&table_intent=${intentId}`)
  ),
  buildTableOrderConfirmUrl: (intentId: string) => (
    `/pages/order-confirm/index?table_intent=${intentId}`
  ),
  clearPendingTableEntry: (intent: PendingTableEntryIntent) => mockClearPendingTableEntry(intent),
  parseTableCheckoutIntentId: () => mockIntentId,
  parseTableEntryOrderId: () => mockOrderId,
  parseTableEntryRoute: () => token,
  savePendingTableEntry: (value: string, userId: number) => (
    mockSavePendingTableEntry(value, userId)
  ),
  timerPhaseAt: () => 'experience',
  timerPhaseLabel: () => '体验中',
  useTableEntry: () => ({
    state: mockEntryState,
    refresh: mockRefresh,
    claim: mockClaim,
    pay: mockPay,
  }),
}))

jest.mock('@/features/order', () => ({
  useCart: () => mockCart,
}))

jest.mock('@/features/order/runtime', () => ({
  getDefaultOrderApi: () => ({ getOrderDetail: mockGetOrderDetail }),
}))

jest.mock('@/features/table_session/runtime', () => ({
  getDefaultTableSessionApi: () => ({ getOrderSession: mockGetOrderSession }),
}))

jest.mock('@/features/product/use_product_list', () => ({
  useProductList: () => ({
    keyword: '',
    loadNextPage: jest.fn(),
    productType: mockProductType,
    retry: jest.fn(),
    setKeyword: jest.fn(),
    setProductType: mockSetProductType,
    state: {
      status: 'content',
      items: [product],
      total: 1,
      page: 1,
      pages: 1,
      loadingMore: false,
    },
  }),
}))

jest.mock('@/navigation/admin_workbench_redirect', () => ({
  AdminWorkbenchRedirect: () => <div className='admin-workbench-redirect' />,
}))

jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

jest.mock('@/utils/asset_url', () => ({ resolveAssetUrl: (value: string) => value }))

const code: PublicTableCode = {
  table_no: 'T01',
  display_name: 'T01号桌',
  is_enabled: true,
  is_available: true,
}

const order: EligibleOrder = {
  id: 9,
  order_no: 'OD01M29PHQ7GY5A0FY28975SCRB6',
  total_amount: '148.00',
  created_at: '2026-09-12T02:00:00Z',
  experience_item_count: 2,
  kit_item_count: 0,
  duration_groups: [
    { duration_minutes: 60, buffer_minutes: 10, experience_item_count: 1, total_quantity: 1 },
    { duration_minutes: 120, buffer_minutes: 10, experience_item_count: 1, total_quantity: 1 },
  ],
}

describe('扫码开台页面视觉状态', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockIntentId = undefined
    mockOrderId = undefined
    mockProductType = 'experience'
    mockAuth = createAuth('authenticated')
    mockCart = createCart()
    mockEntryState = {
      status: 'ready',
      code,
      session: null,
      orders: [order],
      mutation: 'idle',
    }
    mockClaim.mockResolvedValue(true)
    mockGetOrderDetail.mockResolvedValue({ status: { value: 'pending' } })
    mockGetOrderSession.mockResolvedValue(null)
    mockSavePendingTableEntry.mockResolvedValue(pendingIntent)
    mockClearPendingTableEntry.mockResolvedValue(true)
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('使用方案 3 的桌台商品目录并在页头展示可开台胶囊', async () => {
    await testUtils.mount(TableEntryPage)

    expect(required(testUtils, '.table-hero__title').textContent).toBe('T01号桌')
    expect(required(testUtils, '.table-status--success').textContent).toBe('可开台')
    expect(required(testUtils, '.table-journey').textContent).toContain('选商品')
    expect(required(testUtils, '.table-journey').textContent).toContain('支付')
    expect(required(testUtils, '.table-journey').textContent).toContain('开始计时')
    const journeySteps = testUtils.queries.querySelectorAll('.table-journey__step')
    expect(journeySteps[0].getAttribute('aria-label')).toBe('选商品，当前步骤')
    expect(journeySteps[1].getAttribute('aria-label')).toBe('支付，未开始')
    expect(required(testUtils, '.table-catalog__title').textContent).toBe('为本桌选择项目')
    const activeTab = required(testUtils, '.table-catalog-tabs__item--active')
    expect(activeTab.textContent).toBe('体验项目')
    expect(activeTab.getAttribute('aria-role')).toBe('tab')
    expect(activeTab.getAttribute('aria-label')).toBe('体验项目，当前分类')
    const productCard = required(testUtils, '.table-product')
    expect(productCard.textContent).toContain('标准拼豆体验')
    expect(productCard.getAttribute('aria-label'))
      .toBe('选择标准拼豆体验，59.00元起，选择时长与人数')
    expect(required(testUtils, '.table-existing-orders__toggle').textContent).toBe('查看 1 笔')
  })

  it('页头房子入口返回商城而不更改订单、付款或开台意图', async () => {
    mockIntentId = tableIntentId
    mockOrderId = order.id
    await testUtils.mount(TableEntryPage)

    const home = required(testUtils, '.table-hero__home')
    expect(home.getAttribute('aria-label')).toBe('返回商城首页')
    expect(home.textContent).toBe('返回商城首页')
    testUtils.fireEvent.click(home)
    await flush(testUtils)

    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/index/index' })
    expect(mockClaim).not.toHaveBeenCalled()
    expect(mockPay).not.toHaveBeenCalled()
    expect(mockClearPendingTableEntry).not.toHaveBeenCalled()
  })

  it.each(['loading', 'error'] as const)('%s 状态也保留返回商城入口', async (status) => {
    mockEntryState = { ...mockEntryState, status }
    await testUtils.mount(TableEntryPage)

    const home = required(testUtils, '.table-hero__home')
    testUtils.fireEvent.click(home)
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/index/index' })
  })

  it('无既有订单时仍直接展示可选商品而不是要求先去商城建单', async () => {
    mockEntryState = { ...mockEntryState, orders: [] }
    await testUtils.mount(TableEntryPage)

    expect(required(testUtils, '.table-catalog__title').textContent).toBe('为本桌选择项目')
    expect(testUtils.queries.querySelector('.table-empty')).toBeNull()
    expect(required(testUtils, '.table-cart-bar__action').textContent).toBe('先选择体验')
  })

  it('从商品卡进入配置时不武装可被普通商城订单消费的桌台意图', async () => {
    mockEntryState = { ...mockEntryState, orders: [] }
    await testUtils.mount(TableEntryPage)

    testUtils.fireEvent.click(required(testUtils, '.table-product'))
    await flush(testUtils)

    expect(mockSavePendingTableEntry).not.toHaveBeenCalled()
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/product-detail/index?id=13&type=experience',
    })
  })

  it('购物车含体验项目后允许确认本桌订单并保留桌台上下文', async () => {
    mockEntryState = { ...mockEntryState, orders: [] }
    mockCart = createCart([{
      productId: 13,
      productName: '标准拼豆体验',
      productType: 'experience',
      experienceOptionId: 21,
      kitColorId: null,
      configurationLabel: '60 分钟 · 1 人 · 工作日',
      unitPrice: '59.00',
      imageUrl: '/uploads/products/experience.png',
      quantity: 1,
    }])
    await testUtils.mount(TableEntryPage)

    expect(required(testUtils, '.table-cart-bar__total').textContent).toBe('合计 ¥59.00')
    const action = required(testUtils, '.table-cart-bar__action')
    expect(action.textContent).toBe('确认本桌订单')
    testUtils.fireEvent.click(action)
    await flush(testUtils)

    expect(mockSavePendingTableEntry).toHaveBeenCalledWith(token, 7)
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: `/pages/order-confirm/index?table_intent=${tableIntentId}`,
    })
  })

  it('桌台确认页导航失败时精确清理未交付的意图', async () => {
    mockEntryState = { ...mockEntryState, orders: [] }
    mockCart = createCart([{
      productId: 13,
      productName: '标准拼豆体验',
      productType: 'experience',
      experienceOptionId: 21,
      kitColorId: null,
      configurationLabel: '60 分钟 · 1 人 · 工作日',
      unitPrice: '59.00',
      imageUrl: '/uploads/products/experience.png',
      quantity: 1,
    }])
    ;(Taro.navigateTo as jest.Mock).mockRejectedValueOnce(new Error('navigation failed'))
    await testUtils.mount(TableEntryPage)

    testUtils.fireEvent.click(required(testUtils, '.table-cart-bar__action'))
    await flush(testUtils)

    expect(mockClearPendingTableEntry).toHaveBeenCalledWith(pendingIntent)
    expect(Taro.showToast).toHaveBeenCalledWith({
      title: '无法保存桌台，请重新扫码',
      icon: 'none',
    })
  })

  it('新建订单回到桌台后聚焦该订单且 claim 成功才清除桌台意图', async () => {
    mockIntentId = tableIntentId
    mockOrderId = order.id
    await testUtils.mount(TableEntryPage)

    expect(required(testUtils, '.table-ready__title').textContent).toBe('确认绑定本桌')
    expect(required(testUtils, '.table-order__number').textContent).toBe(order.order_no)
    testUtils.fireEvent.click(required(testUtils, '.table-ready > .table-action'))
    await flush(testUtils)

    expect(mockClaim).toHaveBeenCalledWith(order.id)
    expect(mockClearPendingTableEntry).toHaveBeenCalledWith(pendingIntent)
  })

  it('聚焦新建订单后 claim 失败保留桌台意图供原订单重试', async () => {
    mockIntentId = tableIntentId
    mockOrderId = order.id
    mockClaim.mockResolvedValueOnce(false)
    await testUtils.mount(TableEntryPage)

    testUtils.fireEvent.click(required(testUtils, '.table-ready > .table-action'))
    await flush(testUtils)

    expect(mockClaim).toHaveBeenCalledWith(order.id)
    expect(mockClearPendingTableEntry).not.toHaveBeenCalled()
  })

  it('携带新订单意图重新登录时保留精确聚焦路由', async () => {
    mockIntentId = tableIntentId
    mockOrderId = order.id
    mockAuth = createAuth('guest')
    await testUtils.mount(TableEntryPage)

    testUtils.fireEvent.click(required(testUtils, '.table-state .table-action'))

    const target = `/pages/table-entry/index?token=${token}&order_id=${order.id}` +
      `&table_intent=${tableIntentId}`
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: `/pages/login/index?redirect=${encodeURIComponent(target)}`,
    })
  })

  it('聚焦订单不在 eligible 列表时阻止重复下单并提供恢复入口', async () => {
    mockIntentId = tableIntentId
    mockOrderId = order.id
    mockEntryState = { ...mockEntryState, orders: [] }
    await testUtils.mount(TableEntryPage)
    await flush(testUtils)

    expect(testUtils.queries.querySelector('.table-catalog')).toBeNull()
    expect(required(testUtils, '.table-ready').textContent).toContain('暂时无法开台')
    expect(required(testUtils, '.table-ready').textContent).toContain('避免重复下单')
    const actions = testUtils.queries.querySelectorAll('.table-ready > .table-action')
    testUtils.fireEvent.click(actions[0])
    expect(mockRefresh).toHaveBeenCalledTimes(1)
    testUtils.fireEvent.click(actions[1])
    await flush(testUtils)

    expect(mockClearPendingTableEntry).toHaveBeenCalledWith(pendingIntent)
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/orders/index' })
  })

  it('历史聚焦订单已支付且桌台到时结束时，展示重新选商品而非新订单失败', async () => {
    mockIntentId = tableIntentId
    mockOrderId = order.id
    mockEntryState = { ...mockEntryState, orders: [] }
    mockGetOrderDetail.mockResolvedValue({ status: { value: 'paid' } })
    mockGetOrderSession.mockResolvedValue(createSession('closed'))
    await testUtils.mount(TableEntryPage)
    await flush(testUtils)

    expect(mockGetOrderDetail).toHaveBeenCalledWith(order.id)
    expect(mockGetOrderSession).toHaveBeenCalledWith(order.id)
    expect(required(testUtils, '.table-ready__eyebrow').textContent).toBe('上次体验已结束')
    expect(required(testUtils, '.table-ready__title').textContent).toBe('这张桌台可以再次开台')
    expect(required(testUtils, '.table-journey__step--current').textContent).toContain('选商品')
    testUtils.fireEvent.click(required(testUtils, '.table-ready > .table-action'))
    await flush(testUtils)

    expect(mockClearPendingTableEntry).toHaveBeenCalledWith(pendingIntent)
    expect(Taro.redirectTo).toHaveBeenCalledWith({ url: `/pages/table-entry/index?token=${token}` })
    expect(required(testUtils, '.table-catalog')).toBeTruthy()
  })

  it('已取消的历史聚焦订单不再阻塞重新选商品', async () => {
    mockOrderId = order.id
    mockEntryState = { ...mockEntryState, orders: [] }
    mockGetOrderDetail.mockResolvedValue({ status: { value: 'cancelled' } })
    await testUtils.mount(TableEntryPage)
    await flush(testUtils)

    expect(required(testUtils, '.table-ready__eyebrow').textContent).toBe('订单已取消')
    expect(required(testUtils, '.table-ready__title').textContent).toBe('这笔订单不能再次开台')
    expect(mockGetOrderSession).not.toHaveBeenCalled()
  })

  it('聚焦订单详情读取失败时仍阻止重复下单', async () => {
    mockOrderId = order.id
    mockEntryState = { ...mockEntryState, orders: [] }
    mockGetOrderDetail.mockRejectedValue(new Error('network unavailable'))
    await testUtils.mount(TableEntryPage)
    await flush(testUtils)

    expect(testUtils.queries.querySelector('.table-catalog')).toBeNull()
    expect(required(testUtils, '.table-ready').textContent).toContain('避免重复下单')
    expect(required(testUtils, '.table-ready').textContent).not.toContain('重新选择商品')
  })

  it('直接选择既有订单 claim 成功不清理无关桌台意图', async () => {
    await testUtils.mount(TableEntryPage)

    testUtils.fireEvent.click(required(testUtils, '.table-existing-orders__toggle'))
    testUtils.fireEvent.click(required(testUtils, '.table-existing-order'))
    await flush(testUtils)

    expect(mockClaim).toHaveBeenCalledWith(order.id)
    expect(mockClearPendingTableEntry).not.toHaveBeenCalled()
  })

  it('退出新订单聚焦后改选既有订单，claim 成功也不误清原意图', async () => {
    mockIntentId = tableIntentId
    mockOrderId = order.id
    await testUtils.mount(TableEntryPage)

    const focusedActions = testUtils.queries.querySelectorAll('.table-ready > .table-action')
    testUtils.fireEvent.click(focusedActions[1])
    testUtils.fireEvent.click(required(testUtils, '.table-existing-orders__toggle'))
    testUtils.fireEvent.click(required(testUtils, '.table-existing-order'))
    await flush(testUtils)

    expect(mockClaim).toHaveBeenCalledWith(order.id)
    expect(mockClearPendingTableEntry).not.toHaveBeenCalled()
  })

  it('读取失败时复用状态票据并提供重新读取', async () => {
    mockEntryState = {
      status: 'error',
      code: null,
      session: null,
      orders: [],
      mutation: 'idle',
      errorMessage: '网络连接失败',
    }
    await testUtils.mount(TableEntryPage)

    expect(required(testUtils, '.table-status--danger').textContent).toBe('读取失败')
    expect(required(testUtils, '.table-state').textContent).toContain('网络连接失败')
    testUtils.fireEvent.click(required(testUtils, '.table-state .table-action'))
    expect(mockRefresh).toHaveBeenCalledTimes(1)
  })

  it('读取失败时不向顾客展示后端英文错误', async () => {
    mockEntryState = {
      status: 'error',
      code: null,
      session: null,
      orders: [],
      mutation: 'idle',
      errorMessage: 'Table code not found',
    }
    await testUtils.mount(TableEntryPage)

    expect(required(testUtils, '.table-state__description').textContent)
      .toBe('没有找到对应桌台，请确认二维码来自门店并保持完整。')
  })

  it.each([
    ['awaiting_payment', '待付款', '使用会员余额付款'],
    ['active', '计时中', '校准计时'],
    ['closed', '已结束', '返回订单'],
  ] as const)('会话 %s 状态沿用统一页头与操作层级', async (status, label, action) => {
    mockEntryState = { ...mockEntryState, session: createSession(status), orders: [] }
    await testUtils.mount(TableEntryPage)

    expect(required(testUtils, '.table-status').textContent).toBe(label)
    expect(required(testUtils, '.table-session').textContent).toContain(action)
    expect(required(testUtils, '.table-hero__home').getAttribute('aria-label')).toBe('返回商城首页')
  })
})

function createAuth(status: AuthContextValue['status']): AuthContextValue {
  return {
    status,
    user: status === 'authenticated' ? {
      id: 7,
      username: 'member_007',
      nickname: '拼豆伙伴',
      phone: null,
      avatar: null,
      role: 'user',
      status: 'normal',
      last_login_at: null,
      created_at: '2026-09-01T08:00:00Z',
      updated_at: '2026-09-05T08:00:00Z',
    } : undefined,
    register: jest.fn(),
    updateProfile: jest.fn(),
    login: jest.fn(),
    loginWithWechat: jest.fn(),
    logout: jest.fn(),
    retryInitialization: jest.fn(),
  }
}

function createCart(items: CartContextValue['items'] = []): CartContextValue {
  return {
    status: 'ready',
    items,
    addItem: jest.fn(),
    addItems: jest.fn(),
    updateQuantity: jest.fn(),
    removeItem: jest.fn(),
    clear: jest.fn(),
    reconcileSubmittedItems: jest.fn(),
    retryInitialization: jest.fn(),
  }
}

function createSession(status: 'active' | 'awaiting_payment' | 'closed'): TableSession {
  return {
    session_no: `TS${'1'.repeat(26)}`,
    table: { id: 1, table_no: 'T01', display_name: 'T01号桌', is_enabled: true },
    order_id: order.id,
    order_no: order.order_no,
    status: { value: status, label: status },
    claimed_at: '2026-09-12T02:00:00Z',
    payment_deadline_at: '2026-09-12T03:00:00Z',
    started_at: status === 'active' ? '2026-09-12T02:01:00Z' : null,
    table_release_at: status === 'active' ? '2026-09-12T04:11:00Z' : null,
    closed_at: status === 'closed' ? '2026-09-12T02:30:00Z' : null,
    close_reason: status === 'closed' ? { value: 'completed', label: '正常结束' } : null,
    timers: status === 'active' ? [{
      id: 1,
      duration_minutes: 60,
      buffer_minutes: 10,
      started_at: '2026-09-12T02:01:00Z',
      service_ends_at: '2026-09-12T03:01:00Z',
      grace_ends_at: '2026-09-12T03:11:00Z',
      ended_at: null,
      phase: { value: 'experience', label: '体验中' },
      experience_items: [{
        order_item_id: 1,
        product_id: 13,
        product_name: '双人拼豆体验',
        quantity: 1,
        participants_per_unit: 2,
        total_participants: 2,
      }],
    }] : [],
    server_now: '2026-09-12T02:05:00Z',
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
