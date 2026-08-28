let intentSequence = 0

export type InventoryIdempotencyKeyFactory = () => string

export function createInventoryIdempotencyKey(): string {
  intentSequence = (intentSequence + 1) % Number.MAX_SAFE_INTEGER
  const time = Date.now().toString(36)
  const random = `${Math.random().toString(36).slice(2, 12)}${Math.random().toString(36).slice(2, 12)}`
  return `miniapp-inventory-${time}-${intentSequence.toString(36)}-${random}`
}
