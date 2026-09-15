import { buildOrderDetailUrl, parseOrderDetailRoute } from '../order_route'

describe('Order detail route', () => {
  it('解析正安全整数并构造详情 URL', () => {
    expect(parseOrderDetailRoute({ id: '101' })).toEqual({ orderId: 101 })
    expect(buildOrderDetailUrl(101)).toBe('/pages/order-detail/index?id=101')
  })

  it.each([
    {},
    { id: '0' },
    { id: '-1' },
    { id: '01' },
    { id: '1.5' },
    { id: ' 1' },
    { id: '1e3' },
    { id: '9007199254740992' },
  ])('拒绝不可信路由参数：%p', (params) => {
    expect(parseOrderDetailRoute(params)).toBeUndefined()
  })

  it('拒绝非法构造输入', () => {
    expect(() => buildOrderDetailUrl(0)).toThrow('Order ID 必须是正安全整数')
  })
})

describe('订单状态入口', () => {
  const { buildOrderListUrl, parseOrderStatusFilter } = jest.requireActual('../order_route')
  it.each(['pending', 'paid', 'completed', 'cancelled'])('保留合法状态 %s', (status) => {
    expect(parseOrderStatusFilter(status)).toBe(status)
    expect(buildOrderListUrl(status)).toBe(`/pages/orders/index?status=${status}`)
  })
  it.each([undefined, '', 'all', 'shipped', 'pending&admin=true', ['paid']])('未知状态回落全部：%s', (status) => {
    expect(parseOrderStatusFilter(status)).toBe('all')
    expect(buildOrderListUrl()).toBe('/pages/orders/index')
  })
})
