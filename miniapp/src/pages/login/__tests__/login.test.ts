import ReactTestUtil from '@tarojs/test-utils-react'
import Taro from '@tarojs/taro'

import { BusinessError, NetworkError } from '@/api'
import type { AuthContextValue } from '@/auth'

import LoginPage, { getLoginErrorMessage, validateLogin } from '../index'

let mockAuth: AuthContextValue

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    navigateTo: jest.fn(),
    reLaunch: jest.fn(),
  },
  useRouter: () => ({ params: { redirect: '%2Fpages%2Forders%2Findex' } }),
}))

jest.mock('@/auth', () => ({
  buildRegisterUrl: (redirect?: string) => redirect
    ? `/pages/register/index?redirect=${encodeURIComponent(redirect)}`
    : '/pages/register/index',
  parseLoginRedirect: () => '/pages/orders/index',
  useAuth: () => mockAuth,
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
      login: jest.fn(),
      logout: jest.fn(),
      retryInitialization: jest.fn(),
    }
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
    expect(Taro.navigateTo).toHaveBeenCalledWith({
      url: '/pages/register/index?redirect=%2Fpages%2Forders%2Findex',
    })
  })
})
