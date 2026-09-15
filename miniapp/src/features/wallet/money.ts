const MONEY_DRAFT_PATTERN = /^-?(?:0|[1-9]\d{0,7})(?:\.\d{0,2})?$/
const MONEY_PATTERN = /^-?(?:0|[1-9]\d{0,7})\.\d{2}$/

export function normalizeMoneyDraft(value: string, allowNegative = false): string | undefined {
  const normalized = value.trim()
  if (!MONEY_DRAFT_PATTERN.test(normalized) || (!allowNegative && normalized.startsWith('-'))) {
    return undefined
  }
  const negative = normalized.startsWith('-')
  const unsigned = negative ? normalized.slice(1) : normalized
  const [integer, decimal = ''] = unsigned.split('.')
  const fixed = `${integer}.${decimal.padEnd(2, '0')}`
  return negative ? `-${fixed}` : fixed
}

export function moneyToCents(value: string): number | undefined {
  if (!MONEY_PATTERN.test(value)) return undefined
  const negative = value.startsWith('-')
  const unsigned = negative ? value.slice(1) : value
  const [integer, decimal] = unsigned.split('.')
  const cents = Number(integer) * 100 + Number(decimal)
  return negative ? -cents : cents
}
