let sequence = 0

export function createTableIntentKey(intent: 'claim' | 'release'): string {
  sequence = (sequence + 1) % Number.MAX_SAFE_INTEGER
  const random = `${Math.random().toString(36).slice(2, 12)}${Math.random().toString(36).slice(2, 12)}`
  return `miniapp-table-${intent}-${Date.now().toString(36)}-${sequence.toString(36)}-${random}`
}
