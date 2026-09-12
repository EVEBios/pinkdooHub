import { formatColorLabel, formatPrice } from '../format'

describe('formatPrice', () => {
  it('保留两位小数字段', () => {
    expect(formatPrice('299.00')).toBe('299.00')
  })

  it('为整数部分添加千分位', () => {
    expect(formatPrice('1234567.50')).toBe('1,234,567.50')
  })

  it('无小数时只格式化整数部分', () => {
    expect(formatPrice('1200')).toBe('1,200')
  })

  it('非法输入原样返回', () => {
    expect(formatPrice('  abc  ')).toBe('abc')
  })
})

describe('formatColorLabel', () => {
  it('名称与色号相同时只展示一次', () => {
    expect(formatColorLabel('A1', 'A1')).toBe('A1')
  })

  it('存在独立名称时保留色号和名称', () => {
    expect(formatColorLabel('A01', '白色')).toBe('A01 · 白色')
  })
})
