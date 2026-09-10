import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import { type AuthContextValue, SessionPersistenceClearError } from '@/auth'

import AdminWorkbenchPage from '../index'

let mockAuth: AuthContextValue

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    navigateTo: jest.fn(() => Promise.resolve()),
    reLaunch: jest.fn(() => Promise.resolve()),
    showToast: jest.fn(() => Promise.resolve()),
    switchTab: jest.fn(() => Promise.resolve()),
  },
}))

jest.mock('@/auth', () => ({
  ADMIN_INVENTORY_LIST_PATH: '/admin/pages/inventory-transactions/index',
  ADMIN_ORDER_LIST_PATH: '/admin/pages/orders/index',
  ADMIN_PRODUCT_LIST_PATH: '/admin/pages/products/index',
  ADMIN_RESERVATION_LIST_PATH: '/admin/pages/reservations/index',
  ADMIN_STORE_CLOSURE_LIST_PATH: '/admin/pages/store-closures/index',
  ADMIN_USER_LIST_PATH: '/admin/pages/users/index',
  ADMIN_WORKBENCH_PATH: '/admin/pages/workbench/index',
  MALL_PATH: '/pages/index/index',
  buildLoginUrl: (redirect?: string) => redirect
    ? `/pages/login/index?redirect=${encodeURIComponent(redirect)}`
    : '/pages/login/index',
  isAdminRole: (role?: string) => role === 'admin' || role === 'super_admin',
  SessionPersistenceClearError: class MockSessionPersistenceClearError extends Error {
    constructor() {
      super('设备会话未能安全清除，请清理小程序数据')
    }
  },
  useAuth: () => mockAuth,
}))

describe('店铺工作台', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = createAuth('admin')
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it.each([
    ['admin', '管理员'],
    ['super_admin', '超级管理员'],
  ] as const)('%s 展示紧凑身份与三组六项入口', async (role, roleLabel) => {
    mockAuth = createAuth(role)
    await testUtils.mount(AdminWorkbenchPage)

    const page = required(testUtils, '.workbench-page')
    expect(page.textContent).toContain('店铺工作台')
    expect(page.textContent).toContain(`门店伙伴 · @store_staff · ${roleLabel}`)
    expect(page.textContent).not.toContain('工作人员 ID')
    expect(page.textContent).not.toContain('可用余额')
    expect(page.textContent).not.toMatch(/待处理\s*\d/)

    const groups = Array.from(testUtils.queries.querySelectorAll('.workbench-group'))
    expect(groups).toHaveLength(3)
    expect(groups.map((group) => group.querySelector('.workbench-group__title')?.textContent))
      .toEqual(['今日处理', '商品与库存', '门店与权限'])
    expect(groups.map((group) => group.className)).toEqual([
      'workbench-group workbench-group--ink',
      'workbench-group workbench-group--berry',
      'workbench-group workbench-group--rose',
    ])

    const actions = Array.from(testUtils.queries.querySelectorAll('.workbench-action'))
    expect(actions).toHaveLength(6)
    expect(actions.map((action) => [
      action.querySelector('.workbench-action__label')?.textContent,
      action.querySelector('.workbench-action__meta')?.textContent,
    ])).toEqual([
      ['预约审核', '确认、拒绝与联系顾客'],
      ['订单处理', '支付确认与履约'],
      ['商品管理', '商品、价格与配置'],
      ['库存流水', '变动记录与来源'],
      ['营业日历', '固定店休与单日店休'],
      ['用户与权限', '账号状态与资金入口'],
    ])

    const urls = [
      '/admin/pages/reservations/index',
      '/admin/pages/orders/index',
      '/admin/pages/products/index',
      '/admin/pages/inventory-transactions/index',
      '/admin/pages/store-closures/index',
      '/admin/pages/users/index',
    ]
    for (const action of actions) {
      testUtils.fireEvent.click(action)
      await flush(testUtils)
    }
    urls.forEach((url, index) => {
      expect(Taro.navigateTo).toHaveBeenNthCalledWith(index + 1, { url })
    })
    expect(Taro.switchTab).not.toHaveBeenCalled()
  })

  it('工作入口合并重复点击，失败后提供原目标重试', async () => {
    let resolveNavigation!: () => void
    ;(Taro.navigateTo as jest.Mock).mockReturnValueOnce(new Promise<void>((resolve) => {
      resolveNavigation = resolve
    }))
    await testUtils.mount(AdminWorkbenchPage)
    const action = required(testUtils, '.workbench-action')

    testUtils.fireEvent.click(action)
    testUtils.fireEvent.click(action)
    expect(Taro.navigateTo).toHaveBeenCalledTimes(1)
    await testUtils.act(async () => resolveNavigation())

    ;(Taro.navigateTo as jest.Mock).mockRejectedValueOnce(new Error('route busy'))
    testUtils.fireEvent.click(action)
    await flush(testUtils)
    expect(required(testUtils, '.workbench-navigation-error').textContent)
      .toContain('预约审核暂时无法打开')

    testUtils.fireEvent.click(required(testUtils, '.workbench-navigation-error__action'))
    await flush(testUtils)
    expect(Taro.navigateTo).toHaveBeenCalledTimes(3)
    expect(Taro.navigateTo).toHaveBeenLastCalledWith({
      url: '/admin/pages/reservations/index',
    })
  })

  it('工作入口使用局部按压态，导航中也只改变当前入口胶囊', async () => {
    let resolveNavigation!: () => void
    ;(Taro.navigateTo as jest.Mock).mockReturnValueOnce(new Promise<void>((resolve) => {
      resolveNavigation = resolve
    }))
    await testUtils.mount(AdminWorkbenchPage)

    const actions = Array.from(testUtils.queries.querySelectorAll('.workbench-action'))
    expect(actions.every(
      (action) => action.getAttribute('hover-class') === 'workbench-action--pressed',
    )).toBe(true)
    testUtils.fireEvent.click(actions[0])

    expect(actions.every((action) => action.getAttribute('disabled') !== 'true')).toBe(true)
    expect(actions[0].classList.contains('workbench-action--pending')).toBe(true)
    expect(actions.slice(1).every(
      (action) => !action.classList.contains('workbench-action--pending'),
    )).toBe(true)

    await testUtils.act(async () => resolveNavigation())
    expect(actions.every((action) => action.getAttribute('disabled') !== 'true')).toBe(true)
    expect(actions.every(
      (action) => !action.classList.contains('workbench-action--pending'),
    )).toBe(true)
  })

  it('工作入口导航与退出互斥，避免迟到导航覆盖最终页面', async () => {
    let resolveAction!: () => void
    ;(Taro.navigateTo as jest.Mock).mockReturnValueOnce(new Promise<void>((resolve) => {
      resolveAction = resolve
    }))
    await testUtils.mount(AdminWorkbenchPage)

    testUtils.fireEvent.click(required(testUtils, '.workbench-action'))
    const logoutButton = required(testUtils, '.workbench-logout__button')
    expect(logoutButton.hasAttribute('disabled')).toBe(true)
    testUtils.fireEvent.click(logoutButton)
    expect(mockAuth.logout).not.toHaveBeenCalled()
    await testUtils.act(async () => resolveAction())

    let resolveLogout!: () => void
    ;(mockAuth.logout as jest.Mock).mockReturnValueOnce(new Promise<void>((resolve) => {
      resolveLogout = resolve
    }))
    testUtils.fireEvent.click(required(testUtils, '.workbench-logout__button'))
    const actionButton = required(testUtils, '.workbench-action')
    expect(actionButton.hasAttribute('disabled')).toBe(false)
    expect(actionButton.classList.contains('workbench-action--pending')).toBe(false)
    testUtils.fireEvent.click(actionButton)
    expect(Taro.navigateTo).toHaveBeenCalledTimes(1)
    await testUtils.act(async () => resolveLogout())
    await flush(testUtils)
  })

  it('初始化、错误、缺失资料与普通用户都保持 fail closed', async () => {
    mockAuth = { ...createAuth('admin'), status: 'initializing', user: undefined }
    await testUtils.mount(AdminWorkbenchPage)
    expect(required(testUtils, '.workbench-state').textContent).toContain('正在确认工作人员身份')
    expect(testUtils.queries.querySelectorAll('.workbench-action')).toHaveLength(0)
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    mockAuth = {
      ...createAuth('admin'),
      status: 'error',
      user: undefined,
      initializationError: new Error('storage unavailable'),
    }
    await testUtils.mount(AdminWorkbenchPage)
    testUtils.fireEvent.click(required(testUtils, '.workbench-state__action'))
    expect(mockAuth.retryInitialization).toHaveBeenCalledTimes(1)
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    mockAuth = { ...createAuth('admin'), user: undefined }
    await testUtils.mount(AdminWorkbenchPage)
    expect(required(testUtils, '.workbench-state').textContent).toContain('账户信息不完整')
    testUtils.unmout()

    testUtils = new ReactTestUtil()
    mockAuth = createAuth('user')
    await testUtils.mount(AdminWorkbenchPage)
    expect(required(testUtils, '.workbench-state').textContent).toContain('无管理权限')
    expect(testUtils.queries.querySelectorAll('.workbench-action')).toHaveLength(0)
    testUtils.fireEvent.click(required(testUtils, '.workbench-state__action'))
    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/index/index' })
  })

  it('游客通过安全白名单目标登录', async () => {
    mockAuth = { ...createAuth('admin'), status: 'guest', user: undefined }
    await testUtils.mount(AdminWorkbenchPage)

    testUtils.fireEvent.click(required(testUtils, '.workbench-state__action'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fworkbench%2Findex',
    })
    expect(testUtils.queries.querySelectorAll('.workbench-action')).toHaveLength(0)
  })

  it('退出成功后清理管理栈并返回裸登录页', async () => {
    await testUtils.mount(AdminWorkbenchPage)
    testUtils.fireEvent.click(required(testUtils, '.workbench-logout__button'))
    await flush(testUtils)

    expect(mockAuth.logout).toHaveBeenCalledTimes(1)
    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/pages/login/index' })
    expect(Taro.showToast).not.toHaveBeenCalled()
  })

  it('服务端退出未确认时仍返回登录页并说明本机会话已清除', async () => {
    ;(mockAuth.logout as jest.Mock).mockRejectedValueOnce(new Error('offline'))
    await testUtils.mount(AdminWorkbenchPage)
    testUtils.fireEvent.click(required(testUtils, '.workbench-logout__button'))
    await flush(testUtils)

    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/pages/login/index' })
    expect(Taro.showToast).toHaveBeenCalledWith(expect.objectContaining({
      title: '服务端登出未确认，本机会话已清除',
      icon: 'none',
    }))
  })

  it('设备持久会话无法安全清除时不声称本机会话已清除', async () => {
    ;(mockAuth.logout as jest.Mock).mockRejectedValueOnce(new SessionPersistenceClearError())
    await testUtils.mount(AdminWorkbenchPage)
    testUtils.fireEvent.click(required(testUtils, '.workbench-logout__button'))
    await flush(testUtils)

    expect(Taro.reLaunch).not.toHaveBeenCalled()
    expect(Taro.showToast).toHaveBeenCalledWith(expect.objectContaining({
      title: '设备会话未能安全清除，请清理小程序数据',
      icon: 'none',
    }))
    expect(Taro.showToast).not.toHaveBeenCalledWith(expect.objectContaining({
      title: expect.stringContaining('本机会话已清除'),
    }))
  })
})

function createAuth(role: 'user' | 'admin' | 'super_admin'): AuthContextValue {
  return {
    status: 'authenticated',
    user: {
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
    },
    register: jest.fn(),
    updateProfile: jest.fn(),
    login: jest.fn(),
    loginWithWechat: jest.fn(),
    logout: jest.fn(() => Promise.resolve()),
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
