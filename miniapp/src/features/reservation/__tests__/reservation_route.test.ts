import {
  buildAdminReservationDetailUrl,
  buildReservationCreateUrl,
  buildReservationDetailUrl,
  parseReservationCreateRoute,
  parseReservationDetailRoute,
} from '../reservation_route'

describe('预约页面路由', () => {
  it('构造并解析顾客预约创建地址', () => {
    expect(buildReservationCreateUrl(7, 11)).toBe(
      '/pages/reservation-create/index?product_id=7&option_id=11',
    )
    expect(parseReservationCreateRoute({ product_id: '7', option_id: '11' })).toEqual({
      productId: 7,
      experienceOptionId: 11,
    })
  })

  it.each([
    { product_id: '0', option_id: '11' },
    { product_id: '7', option_id: '-1' },
    { product_id: '7.5', option_id: '11' },
    { product_id: '9007199254740992', option_id: '11' },
    { product_id: '7' },
  ])('拒绝非正安全整数或缺失参数：%p', (params) => {
    expect(parseReservationCreateRoute(params)).toBeUndefined()
  })

  it('构造顾客和管理员详情地址并严格解析 ID', () => {
    expect(buildReservationDetailUrl(23)).toBe('/pages/reservation-detail/index?id=23')
    expect(buildAdminReservationDetailUrl(23)).toBe('/admin/pages/reservation-detail/index?id=23')
    expect(parseReservationDetailRoute({ id: '23' })).toEqual({ reservationId: 23 })
    expect(parseReservationDetailRoute({ id: '23x' })).toBeUndefined()
  })
})
