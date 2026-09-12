import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import {
  BusinessError,
  NetworkError,
  TimeoutError,
} from '@/api'
import type { AuthContextValue } from '@/auth'

import RegisterPage, {
  getRegistrationErrorMessage,
  normalizeRegistrationForm,
  validateRegistration,
} from '../index'

let mockAuth: AuthContextValue

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
  buildLoginUrl: (redirect?: string) => redirect
    ? `/pages/login/index?redirect=${encodeURIComponent(redirect)}`
    : '/pages/login/index',
  parseLoginRedirect: () => '/pages/orders/index',
  resolveAuthenticatedLanding: (role?: string, redirect?: string) => {
    if (role === 'admin' || role === 'super_admin') return '/admin/pages/workbench/index'
    return role === 'user' ? redirect ?? '/pages/index/index' : undefined
  },
  useAuth: () => mockAuth,
}))

const user = {
  id: 18,
  username: 'new_user',
  nickname: '新用户',
  phone: '13800138008',
  avatar: null,
  role: 'user' as const,
  status: 'normal' as const,
  last_login_at: null,
  created_at: '2026-08-25T12:00:00Z',
  updated_at: '2026-08-25T12:00:00Z',
}

describe('注册页面', () => {
  let testUtils: ReactTestUtil

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    mockAuth = {
      status: 'guest',
      register: jest.fn(async () => user),
      updateProfile: jest.fn(),
      login: jest.fn(),
      loginWithWechat: jest.fn(),
      logout: jest.fn(),
      retryInitialization: jest.fn(),
    }
  })

  afterEach(() => {
    testUtils.unmout()
    jest.clearAllMocks()
  })

  it('提交规范化字段，成功后不自动登录并保留原安全返回目标', async () => {
    await testUtils.mount(RegisterPage)
    const inputs = testUtils.queries.querySelectorAll('.registration-form__input')
    expect(inputs).toHaveLength(5)
    input(testUtils, inputs[0], '  new_user  ')
    input(testUtils, inputs[1], '  新用户  ')
    input(testUtils, inputs[2], '13800138008')
    input(testUtils, inputs[3], 'password-123')
    input(testUtils, inputs[4], 'password-123')

    testUtils.fireEvent.click(requireElement(testUtils, '.registration-form__submit'))
    await flush(testUtils)

    expect(mockAuth.register).toHaveBeenCalledWith({
      username: 'new_user',
      password: 'password-123',
      nickname: '新用户',
      phone: '13800138008',
    })
    expect(mockAuth.login).not.toHaveBeenCalled()
    expect(requireElement(testUtils, '.registration-success').textContent).toContain('注册成功')
    testUtils.fireEvent.click(requireElement(testUtils, '.registration-form__submit'))
    expect(Taro.redirectTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fpages%2Forders%2Findex',
    })
  })

  it('连续点击时只提交一次，且失败后清空两次密码', async () => {
    let rejectRegistration: (cause: unknown) => void = () => undefined
    mockAuth = {
      ...mockAuth,
      register: jest.fn(() => new Promise((_, reject) => {
        rejectRegistration = reject
      })),
    }
    await testUtils.mount(RegisterPage)
    const inputs = testUtils.queries.querySelectorAll('.registration-form__input')
    ;['new_user', '新用户', '13800138008', 'password-123', 'password-123']
      .forEach((value, index) => input(testUtils, inputs[index], value))
    const submit = requireElement(testUtils, '.registration-form__submit')
    testUtils.fireEvent.click(submit)
    testUtils.fireEvent.click(submit)
    expect(mockAuth.register).toHaveBeenCalledTimes(1)

    rejectRegistration(new NetworkError({ operation: 'auth.register' }, new Error('offline')))
    await flush(testUtils)
    expect(requireElement(testUtils, '.registration-form__error').textContent)
      .toContain('注册结果暂无法确认')
    const refreshedInputs = testUtils.queries.querySelectorAll('.registration-form__input')
    expect(refreshedInputs[3].getAttribute('value')).toBe('')
    expect(refreshedInputs[4].getAttribute('value')).toBe('')
  })

  it('已有账号入口返回登录并保留 redirect', async () => {
    await testUtils.mount(RegisterPage)
    testUtils.fireEvent.click(requireElement(testUtils, '.registration-card__login'))
    expect(Taro.redirectTo).toHaveBeenCalledWith({
      url: '/pages/login/index?redirect=%2Fpages%2Forders%2Findex',
    })
  })

  it('返回登录导航失败时保留注册页并提供原目标重试', async () => {
    ;(Taro.redirectTo as jest.Mock)
      .mockRejectedValueOnce(new Error('navigation failed'))
      .mockResolvedValueOnce(undefined)
    await testUtils.mount(RegisterPage)

    testUtils.fireEvent.click(requireElement(testUtils, '.registration-card__login'))
    await flush(testUtils)
    const error = requireElement(testUtils, '.registration-navigation__error')
    expect(error.textContent).toContain('登录页暂时无法打开')
    expect(error.getAttribute('aria-role')).toBe('alert')

    testUtils.fireEvent.click(requireElement(testUtils, '.registration-card__login'))
    await flush(testUtils)
    expect(Taro.redirectTo).toHaveBeenCalledTimes(2)
  })

  it('注册流程外的既有普通用户会话以 switchTab 打开根页目标', async () => {
    mockAuth = { ...mockAuth, status: 'authenticated', user }
    await testUtils.mount(RegisterPage)
    await flush(testUtils)

    expect(Taro.switchTab).toHaveBeenCalledWith({ url: '/pages/orders/index' })
    expect(Taro.reLaunch).not.toHaveBeenCalled()

    input(testUtils, requireElement(testUtils, '.registration-form__input'), 'rerender only')
    await flush(testUtils)
    expect(Taro.switchTab).toHaveBeenCalledTimes(1)
  })

  it('管理员既有会话打开注册页时回到店铺工作台', async () => {
    mockAuth = {
      ...mockAuth,
      status: 'authenticated',
      user: { ...user, role: 'admin' },
    }
    await testUtils.mount(RegisterPage)
    await flush(testUtils)

    expect(Taro.reLaunch).toHaveBeenCalledWith({ url: '/admin/pages/workbench/index' })
  })

  it('既有会话落点导航失败后只重试导航，不重复注册', async () => {
    ;(Taro.switchTab as jest.Mock)
      .mockRejectedValueOnce(new Error('navigation failed'))
      .mockResolvedValueOnce(undefined)
    mockAuth = { ...mockAuth, status: 'authenticated', user }
    await testUtils.mount(RegisterPage)
    await flush(testUtils)

    const navigationError = requireElement(testUtils, '.registration-navigation__error')
    expect(navigationError.textContent).toContain('页面暂时无法打开')
    expect(navigationError.getAttribute('aria-role')).toBe('alert')
    expect(Taro.switchTab).toHaveBeenCalledTimes(1)

    testUtils.fireEvent.click(requireElement(testUtils, '.registration-navigation__retry'))
    await flush(testUtils)

    expect(Taro.switchTab).toHaveBeenCalledTimes(2)
    expect(mockAuth.register).not.toHaveBeenCalled()
  })

  it.each([
    ['缺少用户资料', undefined, '账户信息不完整'],
    ['角色未知', { ...user, role: 'operator' as never }, '账户角色暂不支持'],
  ] as const)('既有会话%s时保持 fail closed 并提供重试与退出', async (_case, profile, message) => {
    mockAuth = { ...mockAuth, status: 'authenticated', user: profile }
    await testUtils.mount(RegisterPage)
    await flush(testUtils)

    expect(Taro.reLaunch).not.toHaveBeenCalled()
    expect(Taro.switchTab).not.toHaveBeenCalled()
    expect(requireElement(testUtils, '.registration-navigation__error').textContent).toContain(message)
    const recoveryActions = testUtils.queries.querySelectorAll('.registration-navigation__retry')
    testUtils.fireEvent.click(recoveryActions[0])
    expect(mockAuth.retryInitialization).toHaveBeenCalledTimes(1)
    testUtils.fireEvent.click(recoveryActions[1])
    await flush(testUtils)
    expect(mockAuth.logout).toHaveBeenCalledTimes(1)
  })
})

describe('注册规则与错误语义', () => {
  const valid = {
    username: 'new_user',
    nickname: '新用户',
    phone: '13800138008',
    password: 'password-123',
    confirmPassword: 'password-123',
  }

  it.each([
    [{ ...valid, username: '' }, '请输入用户名'],
    [{ ...valid, username: 'ab' }, '用户名长度应为 3–32 个字符'],
    [{ ...valid, nickname: '' }, '请输入昵称'],
    [{ ...valid, phone: '12800138000' }, '请输入有效的 11 位中国大陆手机号'],
    [{ ...valid, password: 'short', confirmPassword: 'short' }, '密码长度应为 8–64 个字符'],
    [{ ...valid, confirmPassword: '' }, '请再次输入密码'],
    [{ ...valid, confirmPassword: 'password-456' }, '两次输入的密码不一致'],
  ])('校验注册字段 %#', (form, message) => {
    expect(validateRegistration(form)).toBe(message)
  })

  it('只规范化非密码字段', () => {
    expect(normalizeRegistrationForm({
      ...valid,
      username: ' new_user ',
      nickname: ' 新用户 ',
      phone: ' 13800138008 ',
      password: ' password-123 ',
      confirmPassword: ' password-123 ',
    })).toEqual({
      username: 'new_user',
      nickname: '新用户',
      phone: '13800138008',
      password: ' password-123 ',
      confirmPassword: ' password-123 ',
    })
  })

  it('区分唯一性冲突，并把不确定 POST 引导到登录核对', () => {
    const duplicateUsername = new BusinessError(
      { operation: 'auth.register', statusCode: 400 }, 1001, 'duplicate', null,
    )
    const duplicatePhone = new BusinessError(
      { operation: 'auth.register', statusCode: 400 }, 1007, 'duplicate', null,
    )
    expect(getRegistrationErrorMessage(duplicateUsername)).toContain('用户名已被注册')
    expect(getRegistrationErrorMessage(duplicatePhone)).toContain('手机号已被注册')
    expect(getRegistrationErrorMessage(
      new TimeoutError({ operation: 'auth.register' }, new Error('timeout')),
    )).toContain('请先尝试登录')
  })
})

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
  })
}

function requireElement(testUtils: ReactTestUtil, selector: string): Element {
  const element = testUtils.queries.querySelector(selector)
  if (!element) {
    throw new Error(`缺少测试元素：${selector}`)
  }
  return element
}
