import Taro from '@tarojs/taro'

export async function requestWeChatLoginCode(): Promise<string> {
  const result = await Taro.login()
  if (typeof result.code !== 'string' || result.code.length === 0) {
    throw new Error('微信未返回可用的登录凭据')
  }
  return result.code
}
