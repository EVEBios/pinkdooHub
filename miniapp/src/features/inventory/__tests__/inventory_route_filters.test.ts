import {
  buildGlobalInventoryRequest,
  buildKitInventoryUrl,
  createInventoryInputSnapshot,
  createInventoryIdempotencyKey,
  EMPTY_INVENTORY_INPUT_SNAPSHOT,
  inventoryInputSnapshotsEqual,
  parseInventoryFilters,
  parseKitInventoryRoute,
  replaceInventorySourceType,
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
      createdFrom: '20260801',
      createdTo: '20260828',
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
      createdFrom: '2026020',
    }, { allowProductId: true }).error).toContain('8 位日期')
    expect(parseInventoryFilters({
      ...base,
      sourceId: '',
      createdFrom: '20260230',
    }, { allowProductId: true }).error).toContain('有效')
    expect(parseInventoryFilters({
      ...base,
      sourceId: '',
      createdFrom: '20260829',
      createdTo: '20260828',
    }, { allowProductId: true }).error).toContain('不能早于')
  })

  it('接受紧凑闰日，并只比较需要查询提交的输入条件', () => {
    const draft = {
      transactionType: 'order_deduction' as const,
      sourceType: 'order' as const,
      sourceId: ' 9 ',
      productId: ' 7 ',
      createdFrom: '20280229',
      createdTo: '',
    }
    expect(parseInventoryFilters(draft, { allowProductId: true }).filters?.createdFrom)
      .toBe('2028-02-29T00:00:00.000Z')
    expect(createInventoryInputSnapshot(draft, { allowProductId: true })).toEqual({
      sourceId: '9',
      productId: '7',
      createdFrom: '20280229',
      createdTo: '',
    })
    expect(inventoryInputSnapshotsEqual(
      createInventoryInputSnapshot({ ...draft, transactionType: 'admin_adjustment' }, { allowProductId: true }),
      createInventoryInputSnapshot(draft, { allowProductId: true }),
    )).toBe(true)
    expect(inventoryInputSnapshotsEqual(EMPTY_INVENTORY_INPUT_SNAPSHOT, {
      ...EMPTY_INVENTORY_INPUT_SNAPSHOT,
      createdFrom: '20280229',
    })).toBe(false)
  })

  it('按钮切换非订单来源时移除已提交的 source ID 并保留其他文字筛选', () => {
    expect(replaceInventorySourceType({
      transactionType: 'order_deduction',
      sourceType: 'order',
      sourceId: 9,
      productId: 7,
      createdFrom: '2026-08-01T00:00:00.000Z',
    }, 'admin')).toEqual({
      transactionType: 'order_deduction',
      sourceType: 'admin',
      productId: 7,
      createdFrom: '2026-08-01T00:00:00.000Z',
    })
  })

  it('生成互不相同且符合 HTTP Header 约束的幂等键', () => {
    const first = createInventoryIdempotencyKey()
    const second = createInventoryIdempotencyKey()
    expect(first).not.toBe(second)
    expect(first).toMatch(/^[\x20-\x7E]{1,128}$/)
    expect(second).toMatch(/^[\x20-\x7E]{1,128}$/)
  })
})
