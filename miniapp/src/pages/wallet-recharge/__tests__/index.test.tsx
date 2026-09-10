import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'

import WalletTransactionsPage from '../../wallet-transactions'
import WalletRechargePage, { AuthenticatedRecharge } from '../index'

const mockSubmit = jest.fn()
let mockTopupEnabled = false
let mockAuth: AuthContextValue
const mockUseMemberWallet = jest.fn()
const mockUseRecharge = jest.fn()
const mockUseWalletTransactions = jest.fn()

jest.mock('@/auth', () => ({
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
  WALLET_RECHARGE_PATH: '/pages/wallet-recharge/index',
  WALLET_TRANSACTION_LIST_PATH: '/pages/wallet-transactions/index',
  buildLoginUrl: (redirect: string) => `/pages/login/index?redirect=${encodeURIComponent(redirect)}`,
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

jest.mock('@/features/wallet', () => ({
  getWalletTransactionLabel: () => '余额变动',
  moneyToCents: (value: string) => Math.round(Number(value) * 100),
  normalizeMoneyDraft: (value: string) => value ? `${value}.00` : undefined,
  useMemberWallet: () => {
    mockUseMemberWallet()
    return {
      state: {
        status: 'content',
        member: {
          user: { status: 'normal' },
          wallet: {
            balance: '280.00', balance_limit: '1000.00', status: 'active',
            capabilities: { topup_enabled: mockTopupEnabled },
          },
        },
      },
      retry: jest.fn(),
    }
  },
  useRecharge: () => {
    mockUseRecharge()
    return { state: { status: 'idle' }, submit: mockSubmit }
  },
  useWalletTransactions: () => {
    mockUseWalletTransactions()
    return {
      state: { status: 'loading', items: [], total: 0, page: 1, pages: 0, loadingMore: false },
      retry: jest.fn(),
      loadNextPage: jest.fn(),
    }
  },
}))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('AuthenticatedRecharge', () => {
  let testUtils: ReactTestUtil
  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockTopupEnabled = false
    mockAuth = authenticatedUser()
  })
  afterEach(() => { testUtils.unmout(); jest.clearAllMocks() })

  it('Provider 未就绪时展示范围并硬禁用提交，不制造成功', async () => {
    await testUtils.mount(AuthenticatedRecharge)
    const page = requireElement(testUtils, '.recharge-page')
    expect(page.textContent).toContain('微信支付暂未开通')
    expect(page.textContent).toContain('商户号、小程序 AppID 关联、HTTPS 通知')
    expect(requireElement(testUtils, '.recharge-form__input').getAttribute('placeholder')).toBe('1.00–1000.00')
    expect(requireElement(testUtils, '.recharge-form__submit').getAttribute('disabled')).not.toBeNull()
    expect(mockSubmit).not.toHaveBeenCalled()
  })

  it('服务端能力先开放时仍由客户端支付确认门禁保持禁用', async () => {
    mockTopupEnabled = true
    await testUtils.mount(AuthenticatedRecharge)

    expect(requireElement(testUtils, '.recharge-provider').textContent).toContain('客户端支付确认能力')
    expect(requireElement(testUtils, '.recharge-form__submit').getAttribute('disabled')).not.toBeNull()
    expect(mockSubmit).not.toHaveBeenCalled()
  })

  it.each(['admin', 'super_admin'] as const)('%s 不挂载充值与资金明细 Hook，并进入工作台', async (role) => {
    mockAuth = {
      ...mockAuth,
      user: { ...mockAuth.user!, role },
    }
    await testUtils.mount(WalletRechargePage)
    expect(requireElement(testUtils, '.admin-workbench-redirect').textContent).toContain('正在进入店铺工作台')
    expect(mockUseMemberWallet).not.toHaveBeenCalled()
    expect(mockUseRecharge).not.toHaveBeenCalled()
    await flush(testUtils)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })

    testUtils.unmout()
    testUtils = new ReactTestUtil()
    await testUtils.mount(WalletTransactionsPage)
    expect(requireElement(testUtils, '.admin-workbench-redirect').textContent).toContain('正在进入店铺工作台')
    expect(mockUseWalletTransactions).not.toHaveBeenCalled()
  })

  it('资金明细未知角色保持 fail closed，不挂载列表 Hook', async () => {
    mockAuth = {
      ...mockAuth,
      user: { ...mockAuth.user!, role: 'operator' as never },
    }
    await testUtils.mount(WalletTransactionsPage)

    expect(requireElement(testUtils, '.wallet-ledger-state__title').textContent).toContain('账户角色暂不支持')
    expect(mockUseWalletTransactions).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
  })
})

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`${selector} not found`)
  return element
}

function authenticatedUser(): AuthContextValue {
  return {
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
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}
