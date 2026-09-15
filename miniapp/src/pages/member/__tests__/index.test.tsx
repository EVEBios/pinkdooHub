import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { UserProfile } from '@/api/endpoints/auth'
import { type AuthContextValue, SessionPersistenceClearError } from '@/auth'

import MemberPage from '../index'

const mockRetry = jest.fn()
const mockUseMemberWallet = jest.fn()
const mockUseRootTabSelection = jest.fn()
const mockShowToast = jest.spyOn(Taro, 'showToast').mockResolvedValue({ errMsg: 'showToast:ok' })
let mockAuth: AuthContextValue

jest.mock('@/auth', () => ({
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
  MEMBER_PATH: '/pages/member/index',
  WALLET_RECHARGE_PATH: '/pages/wallet-recharge/index',
  WALLET_TRANSACTION_LIST_PATH: '/pages/wallet-transactions/index',
  buildLoginUrl: (redirect: string) => `/pages/login/index?redirect=${encodeURIComponent(redirect)}`,
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  SessionPersistenceClearError: class MockSessionPersistenceClearError extends Error {
    constructor() {
      super('设备会话未能安全清除，请清理小程序数据')
    }
  },
  useAuth: () => mockAuth,
}))

jest.mock('@/features/wallet', () => ({
  useMemberWallet: () => mockUseMemberWallet(),
}))

jest.mock('@/navigation/root_tabs', () => ({
  ROOT_TAB_INDEX: { mall: 0, reservations: 1, orders: 2, member: 3 },
  useRootTabSelection: (index: number) => mockUseRootTabSelection(index),
}))

jest.mock('@/utils/asset_url', () => ({
  resolveAssetUrl: (value: string) => `https://api.example.com${value}`,
}))
jest.mock('@/utils/format', () => ({ formatPrice: (value: string) => value }))

describe('MemberPage', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = createAuth('user')
    mockUseMemberWallet.mockReturnValue({
      state: createWalletState(),
      retry: mockRetry,
    })
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('登录状态初始化时不挂载钱包', async () => {
    mockAuth = { ...mockAuth, status: 'initializing', user: undefined }
    await testUtils.mount(MemberPage)

    expect(requireElement(testUtils, '.member-state__title').textContent).toContain('正在确认会员身份')
    expect(mockUseMemberWallet).not.toHaveBeenCalled()
    expect(mockUseRootTabSelection).toHaveBeenCalledWith(3)
  })

  it('登录状态错误时不挂载钱包，并允许重新检查', async () => {
    mockAuth = {
      ...mockAuth,
      status: 'error',
      user: undefined,
      initializationError: new Error('storage unavailable'),
    }
    await testUtils.mount(MemberPage)

    expect(requireElement(testUtils, '.member-state__title').textContent).toContain('登录状态暂不可用')
    expect(requireElement(testUtils, '.member-state__description').textContent).toContain('storage unavailable')
    expect(mockUseMemberWallet).not.toHaveBeenCalled()
    testUtils.fireEvent.click(requireElement(testUtils, '.member-state__action'))
    expect(mockAuth.retryInitialization).toHaveBeenCalledTimes(1)
  })

  it('游客只显示安全登录引导，不挂载钱包', async () => {
    mockAuth = { ...mockAuth, status: 'guest', user: undefined }
    await testUtils.mount(MemberPage)

    expect(requireElement(testUtils, '.member-state__title').textContent).toContain('登录后进入会员中心')
    expect(mockUseMemberWallet).not.toHaveBeenCalled()
    testUtils.fireEvent.click(requireElement(testUtils, '.member-state__action'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fpages%2Fmember%2Findex',
    })
  })

  it('已认证但缺少用户资料时保持 fail closed，不挂载钱包', async () => {
    mockAuth = { ...mockAuth, user: undefined }
    await testUtils.mount(MemberPage)

    expect(requireElement(testUtils, '.member-state__title').textContent).toContain('账户信息不完整')
    expect(mockUseMemberWallet).not.toHaveBeenCalled()
    expect(mockUseRootTabSelection).not.toHaveBeenCalled()
  })

  it('已认证但角色未知时保持 fail closed，不误入工作台或挂载钱包', async () => {
    mockAuth = {
      ...mockAuth,
      user: { ...mockAuth.user!, role: 'operator' as never },
    }
    await testUtils.mount(MemberPage)

    expect(requireElement(testUtils, '.member-state__title').textContent).toContain('账户角色暂不支持')
    expect(mockUseMemberWallet).not.toHaveBeenCalled()
    expect(mockUseRootTabSelection).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
  })

  it('普通会员展示资料、权威余额、充值状态与退出入口', async () => {
    await testUtils.mount(MemberPage)

    const page = requireElement(testUtils, '.member-page')
    expect(page.textContent).toContain('拼豆会员')
    expect(page.textContent).toContain('¥280.00')
    expect(page.textContent).toContain('¥1000.00')
    expect(page.textContent).toContain('pinkdooHub 自有商品与服务')
    expect(page.textContent).toContain('充值暂未开通')
    expect(page.textContent).toContain('个人资料')
    expect(page.textContent).toContain('未绑定手机号')
    expect(page.textContent).toContain('2026-09-01T08:00:00Z')
    expect(page.textContent).toContain('退出当前账号')
    expect(requireElement(testUtils, '.member-profile__avatar').getAttribute('src'))
      .toBe('https://api.example.com/uploads/avatars/member.webp')
    expect(mockUseMemberWallet).toHaveBeenCalledTimes(1)

    testUtils.fireEvent.click(requireElement(testUtils, '.member-actions__primary'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/wallet-transactions/index' })
    testUtils.fireEvent.click(requireElement(testUtils, '.member-actions__secondary'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: '/pages/wallet-recharge/index' })
    testUtils.fireEvent.click(requireElement(testUtils, '.member-logout__button'))
    await flush(testUtils)
    expect(mockAuth.logout).toHaveBeenCalledTimes(1)
  })

  it('钱包读取失败时提供原位重试', async () => {
    mockUseMemberWallet.mockReturnValue({
      state: { status: 'error', errorMessage: '钱包服务暂不可用' },
      retry: mockRetry,
    })
    await testUtils.mount(MemberPage)

    expect(requireElement(testUtils, '.member-state__description').textContent)
      .toContain('钱包服务暂不可用')
    testUtils.fireEvent.click(requireElement(testUtils, '.member-state__action'))
    expect(mockRetry).toHaveBeenCalledTimes(1)
    expect(requireElement(testUtils, '.member-logout__button').textContent).toContain('退出当前账号')
  })

  it('静默刷新失败时保留余额并提供明确的重新加载动作', async () => {
    mockUseMemberWallet.mockReturnValue({
      state: { ...createWalletState(), refreshErrorMessage: '网络连接不可用' },
      retry: mockRetry,
    })
    await testUtils.mount(MemberPage)

    expect(requireElement(testUtils, '.member-balance').textContent).toContain('¥280.00')
    expect(requireElement(testUtils, '.member-refresh__message').textContent)
      .toContain('当前仍显示上次数据。网络连接不可用')
    testUtils.fireEvent.click(requireElement(testUtils, '.member-refresh__action'))
    expect(mockRetry).toHaveBeenCalledTimes(1)
  })

  it('无头像时使用带独立居中样式的昵称首字母', async () => {
    mockUseMemberWallet.mockReturnValue({
      state: createWalletState({ avatar: null, nickname: 'peter' }),
      retry: mockRetry,
    })
    await testUtils.mount(MemberPage)

    expect(requireElement(testUtils, '.member-profile__avatar--fallback').textContent).toBe('p')
    expect(requireElement(testUtils, '.member-profile__avatar-initial').textContent).toBe('p')
  })

  it.each(['admin', 'super_admin'] as const)('%s 不挂载普通钱包并自动进入独立工作台', async (role) => {
    mockAuth = createAuth(role)
    await testUtils.mount(MemberPage)

    const page = requireElement(testUtils, '.admin-workbench-redirect')
    expect(page.textContent).toContain('正在进入店铺工作台')
    expect(page.textContent).not.toContain('可用余额')
    expect(page.textContent).not.toContain('资金明细')
    expect(mockUseMemberWallet).not.toHaveBeenCalled()
    expect(mockUseRootTabSelection).not.toHaveBeenCalled()
    await flush(testUtils)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
  })

  it('登出服务端未确认时通过跨页面 Toast 说明本机会话已经清除', async () => {
    ;(mockAuth.logout as jest.Mock).mockRejectedValueOnce(new Error('offline'))
    await testUtils.mount(MemberPage)

    testUtils.fireEvent.click(requireElement(testUtils, '.member-logout__button'))
    await flush(testUtils)

    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
      title: '服务端登出未确认，本机会话已清除',
      icon: 'none',
    }))
  })

  it('持久会话无法安全清除时不误报本机会话已清除', async () => {
    ;(mockAuth.logout as jest.Mock).mockRejectedValueOnce(new SessionPersistenceClearError())
    await testUtils.mount(MemberPage)

    testUtils.fireEvent.click(requireElement(testUtils, '.member-logout__button'))
    await flush(testUtils)

    expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
      title: '设备会话未能安全清除，请清理小程序数据',
      icon: 'none',
    }))
    expect(mockShowToast).not.toHaveBeenCalledWith(expect.objectContaining({
      title: expect.stringContaining('本机会话已清除'),
    }))
  })
})

function createAuth(role: UserProfile['role']): AuthContextValue {
  return {
    status: 'authenticated',
    user: createUser(role),
    register: jest.fn(),
    updateProfile: jest.fn(),
    login: jest.fn(),
    loginWithWechat: jest.fn(),
    logout: jest.fn(),
    retryInitialization: jest.fn(),
  }
}

function createUser(role: UserProfile['role']): UserProfile {
  return {
    id: role === 'user' ? 7 : 2,
    username: role === 'user' ? 'member_007' : 'store_staff',
    nickname: role === 'user' ? '拼豆会员' : '门店伙伴',
    phone: null,
    avatar: role === 'user' ? '/uploads/avatars/member.webp' : null,
    role,
    status: 'normal',
    last_login_at: null,
    created_at: '2026-09-01T08:00:00Z',
    updated_at: '2026-09-05T08:00:00Z',
  }
}

function createWalletState(userOverrides: Partial<UserProfile> = {}) {
  return {
    status: 'content' as const,
    member: {
      user: { ...createUser('user'), ...userOverrides },
      wallet: {
        balance: '280.00',
        balance_limit: '1000.00',
        status: 'active' as const,
        capabilities: {
          topup_enabled: false,
          wallet_payment_enabled: true,
          refund_enabled: true,
        },
      },
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
    await Promise.resolve()
  })
}
