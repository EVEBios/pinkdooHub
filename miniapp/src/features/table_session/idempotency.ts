let sequence = 0

export function createTableIntentKey(intent: 'checkout' | 'claim' | 'release' | 'direct'): string {
  sequence = (sequence + 1) % Number.MAX_SAFE_INTEGER
  const random = [Math.random(), Math.random()]
    .map((value) => value.toString(36).slice(2, 12).padEnd(10, '0'))
    .join('')
  return `miniapp-table-${intent}-${Date.now().toString(36)}-${sequence.toString(36)}-${random}`
}
