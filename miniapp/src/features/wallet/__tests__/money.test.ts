import { moneyToCents, normalizeMoneyDraft } from '../money'

describe('钱包金额工具', () => {
  it.each([
    ['1', '1.00'],
    ['1.2', '1.20'],
    ['1000.00', '1000.00'],
  ])('将输入草稿 %s 标准化为 %s', (draft, expected) => {
    expect(normalizeMoneyDraft(draft)).toBe(expected)
  })

  it('负数只在管理员调账路径显式允许', () => {
    expect(normalizeMoneyDraft('-20', false)).toBeUndefined()
    expect(normalizeMoneyDraft('-20', true)).toBe('-20.00')
  })

  it('使用整数分位解析，拒绝超过两位小数', () => {
    expect(moneyToCents('1000.00')).toBe(100000)
    expect(moneyToCents('-0.01')).toBe(-1)
    expect(moneyToCents('0.001')).toBeUndefined()
  })
})
