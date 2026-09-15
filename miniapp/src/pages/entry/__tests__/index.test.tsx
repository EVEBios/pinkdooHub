import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import type { AuthContextValue } from '@/auth'

import EntryPage, { resolveEntryDestination } from '../index'

let mockAuth: AuthContextValue

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    reLaunch: jest.fn(() => Promise.resolve()),
    switchTab: jest.fn(() => Promise.resolve()),
  },
}))

jest.mock('@/auth', () => ({
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
  MALL_PATH: '/pages/index/index',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  useAuth: () => mockAuth,
}))

describe('启动身份分流', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = createAuth('initializing')
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('认证完成前保持在无底栏状态且不导航', async () => {
    await testUtils.mount(EntryPage)

    expect(required(testUtils, '.entry-state').textContent).toContain('正在确认本次使用身份')
    expect(Taro.switchTab).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
  })

  it('初始化失败时提供原位重试', async () => {
    mockAuth = {
      ...mockAuth,
      status: 'error',
      initializationError: new Error('storage unavailable'),
    }
    await testUtils.mount(EntryPage)

    expect(required(testUtils, '.entry-state').textContent).toContain('storage unavailable')
    expect(required(testUtils, '.entry-state__description').getAttribute('aria-role')).toBe('alert')
    testUtils.fireEvent.click(required(testUtils, '.entry-state__action'))
    expect(mockAuth.retryInitialization).toHaveBeenCalledTimes(1)
    expect(Taro.switchTab).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
  })

  it.each([
    ['guest', undefined],
    ['authenticated', 'user'],
  ] as const)('%s 进入顾客商城', async (status, role) => {
    mockAuth = createAuth(status, role)
    await testUtils.mount(EntryPage)
    await flush(testUtils)

    expect(Taro.switchTab).toHaveBeenCalledTimes(1)
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/index/index' })
    expect(Taro.reLaunch).not.toHaveBeenCalled()
  })

  it.each(['admin', 'super_admin'] as const)('%s 直接进入独立店铺工作台', async (role) => {
    mockAuth = createAuth('authenticated', role)
    await testUtils.mount(EntryPage)
    await flush(testUtils)

    expect(Taro.reLaunch).toHaveBeenCalledTimes(1)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
    expect(Taro.switchTab).not.toHaveBeenCalled()
  })

  it('角色与认证状态组合解析保持 fail closed', async () => {
    await testUtils.mount(EntryPage)
    expect(resolveEntryDestination('initializing', 'admin')).toBeUndefined()
    expect(resolveEntryDestination('error', 'admin')).toBeUndefined()
    expect(resolveEntryDestination('authenticated', undefined)).toBeUndefined()
    // @ts-expect-error 未知角色既不属于公开参数类型，也不得在运行时降级为顾客身份。
    expect(resolveEntryDestination('authenticated', 'store_owner')).toBeUndefined()
    expect(resolveEntryDestination('guest', undefined)).toEqual({
      method: 'switchTab',
      url: '/pages/index/index',
    })
    expect(resolveEntryDestination('authenticated', 'admin')).toEqual({
      method: 'reLaunch',
      url: '/admin/pages/workbench/index',
    })
  })

  it('导航失败后显示可恢复动作并允许重试', async () => {
    ;(Taro.reLaunch as jest.Mock)
      .mockRejectedValueOnce(new Error('navigation failed'))
      .mockResolvedValueOnce(undefined)
    mockAuth = createAuth('authenticated', 'admin')
    await testUtils.mount(EntryPage)
    await flush(testUtils)

    const navigationError = required(testUtils, '.entry-state__error')
    expect(navigationError.textContent).toContain('页面暂时无法打开')
    expect(navigationError.getAttribute('aria-role')).toBe('alert')
    expect(Taro.reLaunch).toHaveBeenCalledTimes(1)
    testUtils.fireEvent.click(required(testUtils, '.entry-state__action'))
    await flush(testUtils)
    expect(Taro.reLaunch).toHaveBeenCalledTimes(2)
  })

  it('运行时出现未知角色时保持 fail closed 并提供重新检查', async () => {
    const auth = createAuth('authenticated', 'user')
    mockAuth = {
      ...auth,
      user: auth.user ? { ...auth.user, role: 'store_owner' as never } : undefined,
    }
    await testUtils.mount(EntryPage)
    await flush(testUtils)

    expect(required(testUtils, '.entry-state').textContent).toContain('账户角色无法识别')
    expect(required(testUtils, '.entry-state__description').getAttribute('aria-role')).toBe('alert')
    expect(Taro.switchTab).not.toHaveBeenCalled()
    expect(Taro.reLaunch).not.toHaveBeenCalled()
    testUtils.fireEvent.click(required(testUtils, '.entry-state__action'))
    expect(mockAuth.retryInitialization).toHaveBeenCalledTimes(1)
  })
})

function createAuth(
  status: AuthContextValue['status'],
  role?: 'user' | 'admin' | 'super_admin',
): AuthContextValue {
  return {
    status,
    user: role ? {
      id: 2,
      username: 'store_staff',
      nickname: '门店伙伴',
      phone: null,
      avatar: null,
      role,
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

function required(testUtils: ReactTestUtil, selector: string): Element {
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
