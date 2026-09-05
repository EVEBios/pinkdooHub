import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'

import AdminUserWalletPage, { AuthenticatedAdminUserWallet } from '../index'

let mockAuth: AuthContextValue
const mockUseDetail = jest.fn()
const mockUseLedger = jest.fn()
const mockUseAdjustment = jest.fn()
const mockSubmit = jest.fn(async () => true)
const mockRetrySameIntent = jest.fn(async () => true)
const mockDetailRetry = jest.fn()
const mockLedgerRetry = jest.fn()

jest.mock('@tarojs/taro', () => {
  const actual = jest.requireActual('@tarojs/taro')
  return { ...actual, useRouter: () => ({ params: { id: '7' } }) }
})
jest.mock('@/auth', () => ({
  ADMIN_USER_LIST_PATH: '/admin/pages/users/index',
  buildLoginUrl: () => '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fusers%2Findex',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))
jest.mock('@/features/wallet', () => ({
  buildAdminWalletOrderUrl: (userId: number) => `/admin/pages/wallet-order/index?id=${userId}`,
  getWalletTransactionLabel: () => '人工调账',
  moneyToCents: (value: string) => Math.round(Number(value) * 100),
  normalizeMoneyDraft: (value: string) => value ? `${value}.00` : undefined,
  parseAdminUserWalletRoute: () => ({ userId: 7 }),
  useAdminUserWallet: () => mockUseDetail(),
  useAdminWalletTransactions: () => mockUseLedger(),
  useAdminWalletAdjustment: () => mockUseAdjustment(),
}))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('AdminUserWalletPage', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'authenticated',
      user: {
        id: 2, username: 'admin', nickname: '管理员', phone: null, avatar: null,
        role: 'admin', status: 'normal', last_login_at: null,
        created_at: '2026-09-05T08:00:00Z', updated_at: '2026-09-05T08:00:00Z',
      },
      register: jest.fn(), login: jest.fn(), loginWithWechat: jest.fn(), logout: jest.fn(), retryInitialization: jest.fn(),
    }
    mockUseDetail.mockReturnValue({
      state: {
        status: 'content',
        wallet: {
          user: {
            id: 7, username: 'member_007', nickname: '停用会员', role: 'user', status: 'disabled',
            last_login_at: null, created_at: '2026-09-05T08:00:00Z',
          },
          wallet: {
            balance: '80.00', balance_limit: '1000.00', status: 'active',
            capabilities: { topup_enabled: false, wallet_payment_enabled: true, refund_enabled: true },
          },
        },
      },
      retry: mockDetailRetry,
    })
    mockUseLedger.mockReturnValue({
      state: { status: 'empty', items: [], total: 0, page: 1, pages: 0, loadingMore: false },
      retry: mockLedgerRetry,
      loadNextPage: jest.fn(),
    })
    mockUseAdjustment.mockReturnValue({
      state: { status: 'idle' },
      submit: mockSubmit,
      retrySameIntent: mockRetrySameIntent,
    })
    jest.spyOn(Taro, 'showModal').mockResolvedValue({ confirm: true, cancel: false, errMsg: 'showModal:ok' })
  })
  afterEach(() => { testUtils.unmout(); jest.restoreAllMocks(); jest.clearAllMocks() })

  it('非管理员在挂载资金 hooks 前被拒绝', async () => {
    mockAuth = { ...mockAuth, user: { ...mockAuth.user!, role: 'user' } }
    await testUtils.mount(AdminUserWalletPage)
    expect(requireElement(testUtils, '.admin-wallet-state').textContent).toContain('无管理权限')
    expect(mockUseDetail).not.toHaveBeenCalled()
  })

  it('ADMIN 可对 disabled 普通用户执行带原因的正向纠错', async () => {
    await testUtils.mount(AuthenticatedAdminUserWallet, { props: { currentUserId: 2, userId: 7 } })
    const page = requireElement(testUtils, '.admin-wallet-page')
    expect(page.textContent).toContain('停用会员')
    expect(page.textContent).toContain('已禁用')
    input(testUtils, requireElement(testUtils, '.admin-wallet-adjustment__input'), '20')
    input(testUtils, requireElement(testUtils, '.admin-wallet-adjustment__reason'), '线下差额纠正')
    testUtils.fireEvent.click(requireElement(testUtils, '.admin-wallet-adjustment__submit'))
    await flush(testUtils)
    expect(mockSubmit).toHaveBeenCalledWith('20.00', '线下差额纠正')
    expect(mockDetailRetry).toHaveBeenCalled()
    expect(mockLedgerRetry).toHaveBeenCalled()
    expect(requireElement(testUtils, '.admin-wallet-commerce__action').getAttribute('disabled')).not.toBeNull()
  })

  it('状态正常的普通用户可进入特定商品扣款页', async () => {
    const current = mockUseDetail()
    mockUseDetail.mockReturnValue({
      ...current,
      state: {
        ...current.state,
        wallet: {
          ...current.state.wallet,
          user: { ...current.state.wallet.user, nickname: '正常会员', status: 'normal' },
          wallet: {
            ...current.state.wallet.wallet,
            capabilities: {
              ...current.state.wallet.wallet.capabilities,
              wallet_payment_enabled: false,
            },
          },
        },
      },
    })
    await testUtils.mount(AuthenticatedAdminUserWallet, { props: { currentUserId: 2, userId: 7 } })

    testUtils.fireEvent.click(requireElement(testUtils, '.admin-wallet-commerce__action'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/admin/pages/wallet-order/index?id=7' })
  })

  it('结果未知时冻结原调账内容并只允许同一意图重试', async () => {
    mockUseAdjustment.mockReturnValue({
      state: { status: 'unknown', errorMessage: '调整结果可能未知' },
      submit: mockSubmit,
      retrySameIntent: mockRetrySameIntent,
    })
    await testUtils.mount(AuthenticatedAdminUserWallet, { props: { currentUserId: 2, userId: 7 } })

    for (const choice of testUtils.queries.querySelectorAll('.admin-wallet-adjustment__choice')) {
      expect(choice.getAttribute('disabled')).not.toBeNull()
    }
    expect(requireElement(testUtils, '.admin-wallet-adjustment__input').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-wallet-adjustment__reason').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-wallet-adjustment__submit').textContent).toContain('重试同一笔调账')

    testUtils.fireEvent.click(requireElement(testUtils, '.admin-wallet-adjustment__submit'))
    await flush(testUtils)

    expect(mockRetrySameIntent).toHaveBeenCalledTimes(1)
    expect(mockSubmit).not.toHaveBeenCalled()
    expect(Taro.showModal).not.toHaveBeenCalled()
    expect(mockDetailRetry).toHaveBeenCalledTimes(1)
    expect(mockLedgerRetry).toHaveBeenCalledTimes(1)
  })

  it('调账在途时锁定方向、金额和原因', async () => {
    mockUseAdjustment.mockReturnValue({
      state: { status: 'submitting', retrying: false },
      submit: mockSubmit,
      retrySameIntent: mockRetrySameIntent,
    })
    await testUtils.mount(AuthenticatedAdminUserWallet, { props: { currentUserId: 2, userId: 7 } })

    for (const choice of testUtils.queries.querySelectorAll('.admin-wallet-adjustment__choice')) {
      expect(choice.getAttribute('disabled')).not.toBeNull()
    }
    expect(requireElement(testUtils, '.admin-wallet-adjustment__input').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-wallet-adjustment__reason').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-wallet-adjustment__submit').getAttribute('disabled')).not.toBeNull()
    expect(requireElement(testUtils, '.admin-wallet-adjustment__submit').textContent).toContain('正在提交')
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
  })
}
