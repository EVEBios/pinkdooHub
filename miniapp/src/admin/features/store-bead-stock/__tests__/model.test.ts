import type { StoreStock } from '@/api/endpoints/store_bead_stock'
import { changes, matchesStock, parsePacks, summarize } from '../model'

const row = (packs: number | null): StoreStock => ({ bead_color_id: 1, slot_no: 1, color_code: 'A1', color_name: 'A1', packs, revision: packs === null ? 0 : 1 })

describe('门店包库存草稿与两组筛选', () => {
  it('1包同时属于有库存和库存不足，未知仅属于全部', () => {
    expect(matchesStock(row(1), 'available', 'A')).toBe(true)
    expect(matchesStock(row(1), 'low', 'A')).toBe(true)
    expect(matchesStock(row(0), 'empty', '全部')).toBe(true)
    expect(matchesStock(row(0), 'available', '全部')).toBe(false)
    expect(matchesStock(row(2), 'low', '全部')).toBe(false)
    expect(matchesStock(row(1), 'low', 'B')).toBe(false)
    for (const f of ['available', 'empty', 'low'] as const) expect(matchesStock(row(null), f, '全部')).toBe(false)
    expect(matchesStock(row(null), 'all', '全部')).toBe(true)
  })
  it('首次盘点0可提交，改回原值不提交，小数负数空白不合法', () => {
    expect(changes([row(null)], { 1: '0' }).items).toEqual([{ bead_color_id: 1, expected_revision: 0, packs: 0 }])
    expect(changes([row(1)], { 1: '1' }).items).toEqual([])
    for (const s of ['', '-1', '1.5', '1000000', 'abc']) expect(parsePacks(s)).toBeUndefined()
    expect(changes([row(1)], { 1: '' }).invalid).toEqual(['A1'])
  })
  it('初次盘点不伪造增加量，增加和减少分别汇总', () => {
    expect(summarize([{ before_packs: null, after_packs: 5 }, { before_packs: 3, after_packs: 2 }, { before_packs: 0, after_packs: 4 }])).toEqual({ added: 4, removed: 1, initialColors: 1, initialPacks: 5 })
  })
})
