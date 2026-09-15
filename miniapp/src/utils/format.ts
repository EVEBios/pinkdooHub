/**
 * 金额格式化。
 * 后端金额契约是字符串（如 "299.00"），禁止使用 float；这里只做展示格式化，
 * 不进行任何数值运算，也不改变原始金额语义。
 */
export function formatPrice(price: string): string {
  const normalized = price.trim()
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) {
    return normalized
  }
  const [integer, decimal] = normalized.split('.')
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return decimal ? `${grouped}.${decimal}` : grouped
}

/**
 * 色卡来源可能只提供一个标签，此时 color_code 与 name 会保存为相同值。
 * 展示层只显示一次；有独立名称时仍保留“色号 · 名称”的既有格式。
 */
export function formatColorLabel(colorCode: string, colorName: string): string {
  return colorCode === colorName ? colorCode : `${colorCode} · ${colorName}`
}
