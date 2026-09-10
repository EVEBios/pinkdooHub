import {
  ADMIN_WORKBENCH_PATH,
  ADMIN_ORDER_LIST_PATH,
  ADMIN_RESERVATION_LIST_PATH,
  ADMIN_STORE_CLOSURE_LIST_PATH,
  ADMIN_INVENTORY_LIST_PATH,
  ADMIN_PRODUCT_LIST_PATH,
  ADMIN_USER_LIST_PATH,
  buildLoginUrl,
  buildRegisterUrl,
  ORDER_CONFIRM_PATH,
  ORDER_LIST_PATH,
  RESERVATION_LIST_PATH,
  MEMBER_PATH,
  MALL_PATH,
  WALLET_RECHARGE_PATH,
  WALLET_TRANSACTION_LIST_PATH,
  parseLoginRedirect,
  resolveAuthenticatedLanding,
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
    expect(parseLoginRedirect(RESERVATION_LIST_PATH)).toBe(RESERVATION_LIST_PATH)
    expect(buildLoginUrl(ADMIN_ORDER_LIST_PATH)).toBe(
      '/pages/login/index?redirect=%2Fadmin%2Fpages%2Forders%2Findex',
    )
    expect(parseLoginRedirect(ADMIN_ORDER_LIST_PATH)).toBe(ADMIN_ORDER_LIST_PATH)
    expect(parseLoginRedirect(ADMIN_RESERVATION_LIST_PATH)).toBe(ADMIN_RESERVATION_LIST_PATH)
    expect(parseLoginRedirect(ADMIN_STORE_CLOSURE_LIST_PATH)).toBe(ADMIN_STORE_CLOSURE_LIST_PATH)
    expect(buildLoginUrl(ADMIN_PRODUCT_LIST_PATH)).toBe(
      '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fproducts%2Findex',
    )
    expect(parseLoginRedirect(ADMIN_PRODUCT_LIST_PATH)).toBe(ADMIN_PRODUCT_LIST_PATH)
    expect(buildLoginUrl(ADMIN_USER_LIST_PATH)).toBe(
      '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fusers%2Findex',
    )
    expect(parseLoginRedirect(ADMIN_USER_LIST_PATH)).toBe(ADMIN_USER_LIST_PATH)
    expect(buildLoginUrl(ADMIN_INVENTORY_LIST_PATH)).toBe(
      '/pages/login/index?redirect=%2Fadmin%2Fpages%2Finventory-transactions%2Findex',
    )
    expect(parseLoginRedirect(ADMIN_INVENTORY_LIST_PATH)).toBe(ADMIN_INVENTORY_LIST_PATH)
    expect(buildLoginUrl(ADMIN_WORKBENCH_PATH)).toBe(
      '/pages/login/index?redirect=%2Fadmin%2Fpages%2Fworkbench%2Findex',
    )
    expect(parseLoginRedirect(ADMIN_WORKBENCH_PATH)).toBe(ADMIN_WORKBENCH_PATH)
    expect(parseLoginRedirect(MEMBER_PATH)).toBe(MEMBER_PATH)
    expect(parseLoginRedirect(WALLET_RECHARGE_PATH)).toBe(WALLET_RECHARGE_PATH)
    expect(parseLoginRedirect(WALLET_TRANSACTION_LIST_PATH)).toBe(WALLET_TRANSACTION_LIST_PATH)
    expect(buildLoginUrl()).toBe('/pages/login/index')
    expect(buildRegisterUrl()).toBe('/pages/register/index')
    expect(buildRegisterUrl(ORDER_CONFIRM_PATH)).toBe(
      '/pages/register/index?redirect=%2Fpages%2Forder-confirm%2Findex',
    )
  })

  it('只保留与登录角色相容的安全返回目标', () => {
    expect(resolveAuthenticatedLanding('user')).toBe(MALL_PATH)
    expect(resolveAuthenticatedLanding('user', ORDER_LIST_PATH)).toBe(ORDER_LIST_PATH)
    expect(resolveAuthenticatedLanding('user', ADMIN_ORDER_LIST_PATH)).toBe(MALL_PATH)

    expect(resolveAuthenticatedLanding('admin')).toBe(ADMIN_WORKBENCH_PATH)
    expect(resolveAuthenticatedLanding('super_admin', ORDER_LIST_PATH)).toBe(ADMIN_WORKBENCH_PATH)
    expect(resolveAuthenticatedLanding('admin', ADMIN_ORDER_LIST_PATH)).toBe(ADMIN_ORDER_LIST_PATH)
    expect(resolveAuthenticatedLanding('super_admin', ADMIN_WORKBENCH_PATH)).toBe(ADMIN_WORKBENCH_PATH)

    expect(resolveAuthenticatedLanding(undefined, ORDER_LIST_PATH)).toBeUndefined()
    expect(resolveAuthenticatedLanding('unknown', ADMIN_WORKBENCH_PATH)).toBeUndefined()
  })

  it('仅允许规范且完整的预约创建动态回跳', () => {
    const target = '/pages/reservation-create/index?product_id=7&option_id=11' as const
    expect(buildLoginUrl(target)).toBe(
      '/pages/login/index?redirect=%2Fpages%2Freservation-create%2Findex%3Fproduct_id%3D7%26option_id%3D11',
    )
    expect(parseLoginRedirect(encodeURIComponent(target))).toBe(target)
    expect(parseLoginRedirect(target)).toBe(target)

    for (const unsafe of [
      '/pages/reservation-create/index',
      '/pages/reservation-create/index?option_id=11&product_id=7',
      '/pages/reservation-create/index?product_id=0&option_id=11',
      '/pages/reservation-create/index?product_id=7&option_id=11&next=https://evil.example.com',
      '/pages/reservation-create/index?product_id=9007199254740992&option_id=11',
    ]) {
      expect(parseLoginRedirect(unsafe)).toBeUndefined()
    }
  })

  it.each([
    'https://evil.example.com',
    '//evil.example.com',
    '/pages/admin/index',
    '/admin/pages/product-inventory/index?id=7',
    '/admin/pages/workbench/index?mode=preview',
    '%E0%A4%A',
    undefined,
  ])('拒绝未注册、外部或损坏的返回目标：%p', (value) => {
    expect(parseLoginRedirect(value)).toBeUndefined()
  })
})
