import {
  buildGlobalInventoryRequest,
  buildKitInventoryUrl,
  createInventoryIdempotencyKey,
  parseInventoryFilters,
  parseKitInventoryRoute,
} from '..'

describe('Inventory route、筛选与幂等键', () => {
  it('动态 Kit 库存地址只接受正安全整数 ID', () => {
    expect(buildKitInventoryUrl(7)).toBe('/admin/pages/product-inventory/index?id=7')
    expect(parseKitInventoryRoute({ id: '7' })).toEqual({ productId: 7 })
    expect(parseKitInventoryRoute({ id: '0' })).toBeUndefined()
    expect(parseKitInventoryRoute({ id: '1.5' })).toBeUndefined()
    expect(parseKitInventoryRoute({ id: '9007199254740992' })).toBeUndefined()
  })

  it('把自然日转换为 UTC 半开区间，并生成精确全局 Query', () => {
    const parsed = parseInventoryFilters({
      transactionType: 'order_deduction',
      sourceType: 'order',
      sourceId: '9',
      productId: '7',
      createdFrom: '2026-08-01',
      createdTo: '2026-08-28',
    }, { allowProductId: true })
    expect(parsed.error).toBeUndefined()
    expect(buildGlobalInventoryRequest(parsed.filters!, 2)).toEqual({
      page: 2,
      page_size: 20,
      type: 'order_deduction',
      source_type: 'order',
      source_id: 9,
      product_id: 7,
      created_from: '2026-08-01T00:00:00.000Z',
      created_to: '2026-08-29T00:00:00.000Z',
    })
  })

  it('拒绝不自洽来源与非法日期', () => {
    const base = {
      transactionType: 'all' as const,
      sourceType: 'admin' as const,
      sourceId: '9',
      productId: '',
      createdFrom: '',
      createdTo: '',
    }
    expect(parseInventoryFilters(base, { allowProductId: true }).error).toContain('来源必须')
    expect(parseInventoryFilters({
      ...base,
      sourceId: '',
      createdFrom: '2026-02-30',
    }, { allowProductId: true }).error).toContain('有效')
    expect(parseInventoryFilters({
      ...base,
      sourceId: '',
      createdFrom: '2026-08-29',
      createdTo: '2026-08-28',
    }, { allowProductId: true }).error).toContain('不能早于')
  })

  it('生成互不相同且符合 HTTP Header 约束的幂等键', () => {
    const first = createInventoryIdempotencyKey()
    const second = createInventoryIdempotencyKey()
    expect(first).not.toBe(second)
    expect(first).toMatch(/^[\x20-\x7E]{1,128}$/)
    expect(second).toMatch(/^[\x20-\x7E]{1,128}$/)
  })
})
