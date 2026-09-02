import {
  buildAdminProductCreateUrl,
  buildAdminProductConfigurationUrl,
  buildAdminProductDetailUrl,
  buildAdminProductEditUrl,
  buildAdminProductImagesUrl,
  parseAdminProductCreateRoute,
  parseAdminProductConfigurationRoute,
  parseAdminProductDetailRoute,
  parseAdminProductEditRoute,
  parseAdminProductImagesRoute,
} from '../admin_product_route'

describe('ADMIN Product 详情路由', () => {
  it('解析类型与正安全整数 ID', () => {
    expect(parseAdminProductDetailRoute({ id: '7', type: 'kit' }))
      .toEqual({ productId: 7, productType: 'kit' })
    expect(buildAdminProductDetailUrl(8, 'experience'))
      .toBe('/admin/pages/product-detail/index?id=8&type=experience')
  })

  it.each([
    { id: '0', type: 'kit' },
    { id: '1.5', type: 'kit' },
    { id: '9007199254740992', type: 'experience' },
    { id: '1', type: 'unknown' },
    { id: undefined, type: 'kit' },
  ])('拒绝非法动态路由：%p', (params) => {
    expect(parseAdminProductDetailRoute(params)).toBeUndefined()
    expect(parseAdminProductEditRoute(params)).toBeUndefined()
  })

  it('创建和编辑路由只接受冻结的 Product 类型与安全 ID', () => {
    expect(parseAdminProductCreateRoute({ type: 'experience' }))
      .toEqual({ productType: 'experience' })
    expect(parseAdminProductCreateRoute({ type: 'other' })).toBeUndefined()
    expect(buildAdminProductCreateUrl('kit'))
      .toBe('/admin/pages/product-create/index?type=kit')
    expect(parseAdminProductEditRoute({ id: '9', type: 'kit' }))
      .toEqual({ productId: 9, productType: 'kit' })
    expect(buildAdminProductEditUrl(9, 'kit'))
      .toBe('/admin/pages/product-edit/index?id=9&type=kit')
    expect(parseAdminProductConfigurationRoute({ id: '9', type: 'experience' }))
      .toEqual({ productId: 9, productType: 'experience' })
    expect(buildAdminProductConfigurationUrl(9, 'experience'))
      .toBe('/admin/pages/product-configuration/index?id=9&type=experience')
    expect(parseAdminProductImagesRoute({ id: '9', type: 'kit' }))
      .toEqual({ productId: 9, productType: 'kit' })
    expect(buildAdminProductImagesUrl(9, 'kit'))
      .toBe('/admin/pages/product-images/index?id=9&type=kit')
  })
})
