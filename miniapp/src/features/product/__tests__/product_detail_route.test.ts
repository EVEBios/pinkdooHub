import { buildProductDetailUrl, parseProductDetailRoute } from '../product_detail_route'

describe('Product detail route', () => {
  it.each([
    [{ id: '12', type: 'experience' }, { productId: 12, productType: 'experience' }],
    [{ id: '7', type: 'kit' }, { productId: 7, productType: 'kit' }],
  ] as const)('解析合法参数 %p', (params, expected) => {
    expect(parseProductDetailRoute(params)).toEqual(expected)
  })

  it.each([
    {},
    { id: '0', type: 'kit' },
    { id: '-1', type: 'kit' },
    { id: '1.5', type: 'kit' },
    { id: '01', type: 'kit' },
    { id: ' 1', type: 'kit' },
    { id: '1e3', type: 'kit' },
    { id: 'NaN', type: 'kit' },
    { id: '1', type: 'all' },
    { id: '1', type: 'unknown' },
  ])('拒绝非法参数 %p', (params) => {
    expect(parseProductDetailRoute(params)).toBeUndefined()
  })

  it('根据服务端 ProductType 构造详情页 URL', () => {
    expect(buildProductDetailUrl(3, 'experience'))
      .toBe('/pages/product-detail/index?id=3&type=experience')
    expect(buildProductDetailUrl(4, 'kit'))
      .toBe('/pages/product-detail/index?id=4&type=kit')
  })

  it('拒绝非法 Product ID', () => {
    expect(() => buildProductDetailUrl(0, 'kit')).toThrow('Product ID 必须是正安全整数')
  })
})
