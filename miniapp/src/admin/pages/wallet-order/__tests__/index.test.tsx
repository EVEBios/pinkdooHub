import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'
import type { AssistedWalletOrderState } from '@/features/wallet'

import AdminWalletOrderPage, { AuthenticatedAdminWalletOrder } from '../index'

const timestamp = '2026-09-05T08:00:00Z'
const mockCreateOrder = jest.fn()
const mockRetrySameIntent = jest.fn()
const mockReset = jest.fn()
const mockTargetRetry = jest.fn()
const mockLedgerRetry = jest.fn()
const mockUseTarget = jest.fn()
let mockAuth: AuthContextValue
let mockAssistedState: AssistedWalletOrderState

const result = {
  order: {
    id: 201,
    order_no: `OD${'D'.repeat(26)}`,
    user_id: 7,
    user_nickname: '正常会员',
    total_amount: '50.00',
    status: { value: 'paid', label: '已支付' },
    remark: '门店代客下单',
    items: [{
      id: 301, product_id: 8, experience_option_id: null, product_name: '拼豆材料套装',
      option_duration_minutes: null, option_participants: null, option_day_type: null,
      product_price: '25.00', quantity: 2, subtotal: '50.00',
    }],
    created_at: timestamp,
    updated_at: timestamp,
  },
  payment: {
    id: 18, payment_no: `PY${'C'.repeat(26)}`, order_id: 201, recharge_order_id: null,
    purpose: 'order', method: 'wallet', amount: '50.00', status: 'succeeded',
    created_at: timestamp, updated_at: timestamp, succeeded_at: timestamp,
  },
  post_payment_balance: '230.00',
} as const

jest.mock('@tarojs/taro', () => {
  const actual = jest.requireActual('@tarojs/taro')
  return { ...actual, useRouter: () => ({ params: { id: '7' } }) }
})
jest.mock('@/auth', () => ({
  ADMIN_USER_LIST_PATH: '/admin/pages/users/index',
  buildLoginUrl: () => '/pages/login/index?redirect=users',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))
jest.mock('@/features/order', () => ({
  buildAdminOrderDetailUrl: (orderId: number) => `/admin/pages/order-detail/index?id=${orderId}`,
}))
jest.mock('@/features/product/use_product_list', () => ({
  useProductList: () => ({
    state: {
      status: 'content',
      items: [{
        id: 8,
        name: '拼豆材料套装',
        cover_image: '/uploads/kit.webp',
        display_price: '25.00',
        product_type: { value: 'kit', label: '材料套装' },
      }],
      total: 1,
      page: 1,
      pages: 1,
      loadingMore: false,
    },
    productType: 'all',
    keyword: '',
    setProductType: jest.fn(),
    setKeyword: jest.fn(),
    retry: jest.fn(),
    loadNextPage: jest.fn(),
  }),
}))
jest.mock('@/features/product/use_product_detail', () => ({
  useProductDetail: () => ({
    state: {
      status: 'content',
      detail: {
        id: 8,
        name: '拼豆材料套装',
        description: '材料包',
        product_type: { value: 'kit', label: '材料套装' },
        images: [],
        price: '25.00',
        stock: 4,
        available: true,
      },
    },
    retry: jest.fn(),
  }),
}))
jest.mock('@/features/wallet', () => ({
  buildAdminUserWalletUrl: (userId: number) => `/admin/pages/user-wallet/index?id=${userId}`,
  parseAdminWalletOrderRoute: () => ({ userId: 7 }),
  useAdminUserWallet: () => mockUseTarget(),
  useAdminWalletTransactions: () => ({
    state: { status: 'empty', items: [], total: 0, page: 1, pages: 0, loadingMore: false },
    retry: mockLedgerRetry,
    loadNextPage: jest.fn(),
  }),
  useAssistedWalletOrder: () => ({
    state: mockAssistedState,
    createOrder: mockCreateOrder,
    retrySameIntent: mockRetrySameIntent,
    reset: mockReset,
  }),
}))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('AdminWalletOrderPage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'authenticated',
      user: {
        id: 2, username: 'admin', nickname: '管理员', phone: null, avatar: null,
        role: 'admin', status: 'normal', last_login_at: null,
        created_at: timestamp, updated_at: timestamp,
      },
      register: jest.fn(), login: jest.fn(), loginWithWechat: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
    }
    mockAssistedState = { status: 'idle' }
    mockCreateOrder.mockResolvedValue(result)
    mockUseTarget.mockReturnValue({
      state: {
        status: 'content',
        wallet: {
          user: {
            id: 7, username: 'member_007', nickname: '正常会员', role: 'user', status: 'normal',
            last_login_at: null, created_at: timestamp,
          },
          wallet: {
            balance: '280.00', balance_limit: '1000.00', status: 'active',
            capabilities: { topup_enabled: false, wallet_payment_enabled: false, refund_enabled: true },
          },
        },
      },
      retry: mockTargetRetry,
    })
    jest.spyOn(Taro, 'showModal').mockResolvedValue({ confirm: true, cancel: false, errMsg: 'showModal:ok' })
  })

  afterEach(() => {
    testUtils.unmout()
    jest.restoreAllMocks()
    jest.clearAllMocks()
  })

  it('非管理员在挂载资金和商品 hooks 前被拒绝', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminWalletOrderPage)

    expect(requireElement(testUtils, '.wallet-order-state').textContent).toContain('无管理权限')
    expect(mockUseTarget).not.toHaveBeenCalled()
  })

  it('自助余额支付关闭时仍可选择权威 Kit 并确认管理员代客扣款', async () => {
    await testUtils.mount(AuthenticatedAdminWalletOrder, { props: { currentUserId: 2, userId: 7 } })
    testUtils.fireEvent.click(requireElement(testUtils, '.wallet-order-product'))
    testUtils.fireEvent.click(requireElement(testUtils, '.wallet-order-quantity__increase'))
    input(testUtils, requireElement(testUtils, '.wallet-order-form__remark'), '门店代客下单')
    testUtils.fireEvent.click(requireElement(testUtils, '.wallet-order-form__submit'))
    await flush(testUtils)

    expect(Taro.showModal).toHaveBeenCalledWith(expect.objectContaining({
      content: expect.stringContaining('预计扣款：¥50.00'),
    }))
    expect(mockCreateOrder).toHaveBeenCalledWith({
      items: [{ product_id: 8, quantity: 2 }],
      remark: '门店代客下单',
    })
    expect(mockTargetRetry).toHaveBeenCalled()
    expect(mockLedgerRetry).toHaveBeenCalled()
  })

  it('disabled 用户不能创建消费订单', async () => {
    const target = mockUseTarget()
    mockUseTarget.mockReturnValue({
      ...target,
      state: {
        ...target.state,
        wallet: { ...target.state.wallet, user: { ...target.state.wallet.user, status: 'disabled' } },
      },
    })
    await testUtils.mount(AuthenticatedAdminWalletOrder, { props: { currentUserId: 2, userId: 7 } })

    expect(requireElement(testUtils, '.wallet-order-state').textContent).toContain('不可代客消费')
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  it('成功态展示真实订单、支付单号与扣款后余额', async () => {
    mockAssistedState = { status: 'succeeded', result }
    await testUtils.mount(AuthenticatedAdminWalletOrder, { props: { currentUserId: 2, userId: 7 } })

    const page = requireElement(testUtils, '.wallet-order-result')
    expect(page.textContent).toContain(result.order.order_no)
    expect(page.textContent).toContain(result.payment.payment_no)
    expect(page.textContent).toContain('扣款后余额 ¥230.00')
    expect(page.textContent).toContain('真实订单与扣款已完成')
  })
})

function input(testUtils: ReactTestUtil, element: Element, value: string): void {
  const fireCustomEvent = testUtils.fireEvent as unknown as (target: Element, event: Event) => void
  fireCustomEvent(element, new CustomEvent('input', { bubbles: true, detail: { value } }))
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
    await Promise.resolve()
  })
}
