import { buildProductAuditUrl, parseProductAuditRoute } from '../product_audit_route'

describe('Product Audit 路由', () => {
  it('只编码正安全整数商品 ID 与冻结类型', () => {
    expect(parseProductAuditRoute({ id: '7', type: 'experience' }))
      .toEqual({ productId: 7, productType: 'experience' })
    expect(buildProductAuditUrl(7, 'kit'))
      .toBe('/admin/pages/product-audit/index?id=7&type=kit')
  })

  it.each([
    { id: '0', type: 'kit' },
    { id: '1.5', type: 'kit' },
    { id: '9007199254740992', type: 'experience' },
    { id: '7', type: 'other' },
    { id: undefined, type: 'kit' },
  ])('拒绝非法参数：%p', (params) => {
    expect(parseProductAuditRoute(params)).toBeUndefined()
  })
})
