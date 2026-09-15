let intentSequence = 0

export type WalletIdempotencyKeyFactory = (
  intent: 'recharge' | 'payment' | 'adjustment' | 'refund' | 'assisted-order',
) => string

export function createWalletIdempotencyKey(intent: Parameters<WalletIdempotencyKeyFactory>[0]): string {
  intentSequence = (intentSequence + 1) % Number.MAX_SAFE_INTEGER
  const time = Date.now().toString(36)
  const random = `${Math.random().toString(36).slice(2, 12)}${Math.random().toString(36).slice(2, 12)}`
  return `miniapp-wallet-${intent}-${time}-${intentSequence.toString(36)}-${random}`
}
