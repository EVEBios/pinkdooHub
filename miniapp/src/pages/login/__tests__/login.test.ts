import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import { BusinessError, NetworkError } from '@/api'
import type { AuthContextValue } from '@/auth'

import LoginPage, { getLoginErrorMessage, validateLogin } from '../index'

let mockAuth: AuthContextValue
let mockRedirect: string | undefined

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    redirectTo: jest.fn(() => Promise.resolve()),
    reLaunch: jest.fn(() => Promise.resolve()),
    showToast: jest.fn(() => Promise.resolve()),
    switchTab: jest.fn(),
  },
  useRouter: () => ({ params: { redirect: '%2Fpages%2Forders%2Findex' } }),
}))

jest.mock('@/auth', () => ({
  buildRegisterUrl: (redirect?: string) => redirect
    ? `/pages/register/index?redirect=${encodeURIComponent(redirect)}`
    : '/pages/register/index',
  parseLoginRedirect: () => mockRedirect,
  resolveAuthenticatedLanding: (role?: string, redirect?: string) => {
    if (role === 'admin' || role === 'super_admin') {
      return redirect?.startsWith('/admin/') ? redirect : '/admin/pages/workbench/index'
    }
    if (role === 'user') {
      return redirect?.startsWith('/admin/') ? '/pages/index/index' : redirect ?? '/pages/index/index'
    }
    return undefined
  },
  useAuth: () => mockAuth,
}))

jest.mock('@/config/env', () => ({
  resolveEnv: () => ({ authMode: 'password' }),
}))

describe('登录表单规则', () => {
  it('只做与当前登录契约一致的必填校验', () => {
    expect(validateLogin('', 'secret')).toBe('请输入用户名')
    expect(validateLogin('alice', '')).toBe('请输入密码')
    expect(validateLogin('alice', 'secret')).toBe('')
  })

  it('避免向界面区分用户不存在和密码错误', () => {
    const missing = new BusinessError(
      { operation: 'auth.login', statusCode: 400 },
      1002,
      'User not found',
      null,
    )
    const incorrect = new BusinessError(
      { operation: 'auth.login', statusCode: 400 },
      1003,
      'Incorrect password',
      null,
    )

    expect(getLoginErrorMessage(missing)).toBe('用户名或密码错误')
    expect(getLoginErrorMessage(incorrect)).toBe('用户名或密码错误')
  })

  it('保留网络层给用户的安全提示', () => {
    const error = new NetworkError({ operation: 'auth.login' }, new Error('secret cause'))
    expect(getLoginErrorMessage(error)).toBe('网络请求失败，请检查连接后重试')
  })
})

describe('登录页注册入口', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'guest',
      register: jest.fn(),
      updateProfile: jest.fn(),
      login: jest.fn(),
      loginWithWechat: jest.fn(),
      logout: jest.fn(),
      retryInitialization: jest.fn(),
    }
    mockRedirect = '/pages/orders/index'
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('进入注册页时保留原固定登录返回目标', async () => {
    await testUtils.mount(LoginPage)
    const inputs = testUtils.queries.querySelectorAll('.login-form__input')
    expect(inputs).toHaveLength(2)
    const registerButton = testUtils.queries.querySelector('.login-card__register')
    if (!registerButton) {
      throw new Error('未渲染注册入口')
    }
    testUtils.fireEvent.click(registerButton)
    expect(Taro.redirectTo).toHaveBeenCalledWith({
      url: '/pages/register/index?redirect=%2Fpages%2Forders%2Findex',
    })
  })

  it('登录按钮使用自定义莓果按压态，不交给原生 primary 绿色反馈', async () => {
    await testUtils.mount(LoginPage)
    const submit = requireElement(testUtils, '.login-form__submit')

    expect(submit.getAttribute('type')).not.toBe('primary')
    expect(submit.getAttribute('hover-class')).toBe('login-form__submit--pressed')
  })

  it('注册页导航失败时保留当前登录页并提供原目标重试', async () => {
    ;(Taro.redirectTo as jest.Mock)
      .mockRejectedValueOnce(new Error('navigation failed'))
      .mockResolvedValueOnce(undefined)
    await testUtils.mount(LoginPage)

    testUtils.fireEvent.click(requireElement(testUtils, '.login-card__register'))
    await flush(testUtils)
    const error = requireElement(testUtils, '.login-navigation__error')
    expect(error.textContent).toContain('注册页暂时无法打开')
    expect(error.getAttribute('aria-role')).toBe('alert')

    testUtils.fireEvent.click(requireElement(testUtils, '.login-card__register'))
    await flush(testUtils)
    expect(Taro.redirectTo).toHaveBeenCalledTimes(2)
  })

  it('登录完成后以 switchTab 打开顾客根页白名单目标', async () => {
    mockAuth = { ...mockAuth, status: 'authenticated', user: createUser('user') }
    await testUtils.mount(LoginPage)
    await flush(testUtils)

    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/orders/index' })
    expect(Taro.reLaunch).not.toHaveBeenCalled()

    input(testUtils, requireElement(testUtils, '.login-form__input'), 'rerender only')
    await flush(testUtils)
    expect(Taro.switchTab).toHaveBeenCalledTimes(1)
  })

  it('顾客二级白名单目标仍以 reLaunch 清理认证页面栈', async () => {
    mockRedirect = '/pages/order-confirm/index'
    mockAuth = { ...mockAuth, status: 'authenticated', user: createUser('user') }
    await testUtils.mount(LoginPage)
    await flush(testUtils)

    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/pages/order-confirm/index' })
    expect(Taro.switchTab).not.toHaveBeenCalled()
  })

  it.each(['admin', 'super_admin'] as const)('%s 无显式回跳时进入店铺工作台', async (role) => {
    mockRedirect = undefined
    mockAuth = { ...mockAuth, status: 'authenticated', user: createUser(role) }
    await testUtils.mount(LoginPage)
    await testUtils.act(async () => { await Promise.resolve() })

    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
  })

  it('落点导航失败后只通过明确动作重试导航，不重新登录', async () => {
    ;(Taro.switchTab as jest.Mock)
      .mockRejectedValueOnce(new Error('navigation failed'))
      .mockResolvedValueOnce(undefined)
    mockAuth = { ...mockAuth, status: 'authenticated', user: createUser('user') }
    await testUtils.mount(LoginPage)
    await flush(testUtils)

    const navigationError = requireElement(testUtils, '.login-navigation__error')
    expect(navigationError.textContent).toContain('页面暂时无法打开')
    expect(navigationError.getAttribute('aria-role')).toBe('alert')
    expect(Taro.switchTab).toHaveBeenCalledTimes(1)

    testUtils.fireEvent.click(requireElement(testUtils, '.login-navigation__retry'))
    await flush(testUtils)

    expect(Taro.switchTab).toHaveBeenCalledTimes(2)
    expect(mockAuth.login).not.toHaveBeenCalled()
    expect(mockAuth.loginWithWechat).not.toHaveBeenCalled()
  })

  it.each([
    ['缺少用户资料', undefined, '账户信息不完整'],
    ['角色未知', { ...createUser('user'), role: 'operator' as never }, '账户角色暂不支持'],
  ] as const)('已认证但%s时保持 fail closed 并提供重试与退出', async (_case, user, message) => {
    mockAuth = { ...mockAuth, status: 'authenticated', user }
    await testUtils.mount(LoginPage)
    await testUtils.act(async () => { await Promise.resolve() })

    expect(Taro.reLaunch).not.toHaveBeenCalled()
    expect(Taro.switchTab).not.toHaveBeenCalled()
    expect(requireElement(testUtils, '.login-navigation__error').textContent).toContain(message)
    const recoveryActions = testUtils.queries.querySelectorAll('.login-navigation__retry')
    testUtils.fireEvent.click(recoveryActions[0])
    expect(mockAuth.retryInitialization).toHaveBeenCalledTimes(1)
    testUtils.fireEvent.click(recoveryActions[1])
    await flush(testUtils)
    expect(mockAuth.logout).toHaveBeenCalledTimes(1)
  })
})

function createUser(role: 'user' | 'admin' | 'super_admin') {
  return {
    id: 2,
    username: 'store_staff',
    nickname: '门店伙伴',
    phone: null,
    avatar: null,
    role,
    status: 'normal' as const,
    last_login_at: null,
    created_at: '2026-09-01T08:00:00Z',
    updated_at: '2026-09-05T08:00:00Z',
  }
}

function input(testUtils: ReactTestUtil, element: Element, value: string): void {
  const fireCustomEvent = testUtils.fireEvent as unknown as (
    target: Element,
    event: Event,
  ) => void
  fireCustomEvent(element, new CustomEvent('input', {
    bubbles: true,
    detail: { value },
  }))
}

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) throw new Error(`缺少测试元素：${selector}`)
  return element
}
