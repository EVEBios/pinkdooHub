import { AppConfigError, resolveEnv } from '../env'

describe('resolveEnv', () => {
  it('解析开发环境并移除 Origin 末尾斜杠', () => {
    expect(resolveEnv({
      TARO_APP_APP_ENV: 'development',
      TARO_APP_API_ORIGIN: 'http://localhost:8000/',
      TARO_ENV: 'weapp',
    })).toEqual({
      appEnv: 'development',
      apiOrigin: 'http://localhost:8000',
      platform: 'weapp',
    })
  })

  it('拒绝生产环境 HTTP Origin', () => {
    expect(() => resolveEnv({
      TARO_APP_APP_ENV: 'production',
      TARO_APP_API_ORIGIN: 'http://api.example.com',
      TARO_ENV: 'h5',
    })).toThrow(AppConfigError)
  })

  it('拒绝生产环境 localhost Origin', () => {
    expect(() => resolveEnv({
      TARO_APP_APP_ENV: 'production',
      TARO_APP_API_ORIGIN: 'https://localhost:8443',
      TARO_ENV: 'h5',
    })).toThrow('生产环境禁止使用本机 API Origin')
  })

  it('拒绝带路径或无效端口的 Origin', () => {
    expect(() => resolveEnv({
      TARO_APP_APP_ENV: 'testing',
      TARO_APP_API_ORIGIN: 'https://api.example.com/api',
      TARO_ENV: 'weapp',
    })).toThrow('TARO_APP_API_ORIGIN 必须是无路径、无凭据的 HTTP(S) Origin')

    expect(() => resolveEnv({
      TARO_APP_APP_ENV: 'testing',
      TARO_APP_API_ORIGIN: 'https://api.example.com:65536',
      TARO_ENV: 'weapp',
    })).toThrow('TARO_APP_API_ORIGIN 端口超出有效范围')
  })

  it('拒绝缺失的业务环境', () => {
    expect(() => resolveEnv({
      TARO_APP_API_ORIGIN: 'https://api.example.com',
      TARO_ENV: 'tt',
    })).toThrow('TARO_APP_APP_ENV 未配置或取值非法')
  })
})
