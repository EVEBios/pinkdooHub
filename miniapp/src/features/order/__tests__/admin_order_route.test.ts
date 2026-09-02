import {
  buildAdminOrderDetailUrl,
  isAdminRole,
  parseAdminOrderDetailRoute,
} from '../admin_order_route'

describe('Admin order route and role guard', () => {
  it('构造并解析管理订单详情路由', () => {
    expect(buildAdminOrderDetailUrl(101)).toBe('/admin/pages/order-detail/index?id=101')
    expect(parseAdminOrderDetailRoute({ id: '101' })).toEqual({ orderId: 101 })
  })

  it.each([{}, { id: '0' }, { id: '01' }, { id: '-1' }, { id: '1.5' }, { id: '9007199254740992' }])(
    '拒绝不可信的路由参数：%p',
    (params) => expect(parseAdminOrderDetailRoute(params)).toBeUndefined(),
  )

  it('只把 admin 和 super_admin 识别为 ADMIN+', () => {
    expect(isAdminRole('admin')).toBe(true)
    expect(isAdminRole('super_admin')).toBe(true)
    expect(isAdminRole('user')).toBe(false)
    expect(isAdminRole(undefined)).toBe(false)
  })
})
