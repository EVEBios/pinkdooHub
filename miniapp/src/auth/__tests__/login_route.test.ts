import {
  ADMIN_ORDER_LIST_PATH,
  buildLoginUrl,
  ORDER_CONFIRM_PATH,
  ORDER_LIST_PATH,
  parseLoginRedirect,
} from '../login_route'

describe('登录安全返回路由', () => {
  it('只为注册页面白名单构造编码后的登录地址', () => {
    expect(buildLoginUrl(ORDER_CONFIRM_PATH)).toBe(
      '/pages/login/index?redirect=%2Fpages%2Forder-confirm%2Findex',
    )
    expect(parseLoginRedirect('%2Fpages%2Forder-confirm%2Findex')).toBe(ORDER_CONFIRM_PATH)
    expect(parseLoginRedirect(ORDER_CONFIRM_PATH)).toBe(ORDER_CONFIRM_PATH)
    expect(buildLoginUrl(ORDER_LIST_PATH)).toBe(
      '/pages/login/index?redirect=%2Fpages%2Forders%2Findex',
    )
    expect(parseLoginRedirect(ORDER_LIST_PATH)).toBe(ORDER_LIST_PATH)
    expect(buildLoginUrl(ADMIN_ORDER_LIST_PATH)).toBe(
      '/pages/login/index?redirect=%2Fadmin%2Fpages%2Forders%2Findex',
    )
    expect(parseLoginRedirect(ADMIN_ORDER_LIST_PATH)).toBe(ADMIN_ORDER_LIST_PATH)
  })

  it.each([
    'https://evil.example.com',
    '//evil.example.com',
    '/pages/admin/index',
    '%E0%A4%A',
    undefined,
  ])('拒绝未注册、外部或损坏的返回目标：%p', (value) => {
    expect(parseLoginRedirect(value)).toBeUndefined()
  })
})
