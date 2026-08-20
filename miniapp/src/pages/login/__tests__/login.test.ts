import { BusinessError, NetworkError } from '@/api'

import { getLoginErrorMessage, validateLogin } from '../index'

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
