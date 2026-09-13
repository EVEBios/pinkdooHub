import type { StoragePort } from '@/platform/storage'
import { TaroStorageAdapter } from '@/platform/storage'

import { createTableIntentKey } from './idempotency'
import { parseTableCheckoutIntentId, parseTableToken } from './table_session_route'

const STORAGE_KEY = 'pinkdoohub.table-entry.v1'
const MAX_AGE_MS = 2 * 60 * 60 * 1_000

export interface PendingTableEntryIntent {
  readonly intentId: string
  readonly token: string
  readonly userId: number
}

interface StoredTableEntry extends PendingTableEntryIntent {
  readonly version: 2
  readonly savedAt: number
}

let defaultStorage: StoragePort | undefined
const storageQueues = new WeakMap<StoragePort, Promise<void>>()

function getDefaultStorage(): StoragePort {
  defaultStorage ??= new TaroStorageAdapter()
  return defaultStorage
}

export async function savePendingTableEntry(
  token: string,
  userId: number,
  storage: StoragePort = getDefaultStorage(),
  now = Date.now(),
  intentId = createTableIntentKey('checkout'),
): Promise<PendingTableEntryIntent> {
  const parsed = parseTableToken(token)
  if (!parsed) throw new Error('桌台二维码无效')
  if (!isPositiveSafeInteger(userId)) throw new Error('用户标识无效')
  if (!Number.isSafeInteger(now) || now < 0) throw new Error('桌台结算时间无效')
  const parsedIntentId = parseTableCheckoutIntentId(intentId)
  if (!parsedIntentId) throw new Error('桌台结算意图无效')
  const intent = { intentId: parsedIntentId, token: parsed, userId } as const
  await withStorageLock(storage, () => storage.set(STORAGE_KEY, {
    ...intent,
    savedAt: now,
    version: 2,
  }))
  return intent
}

export async function loadPendingTableEntry(
  intentId: string,
  userId: number,
  storage: StoragePort = getDefaultStorage(),
  now = Date.now(),
): Promise<PendingTableEntryIntent | undefined> {
  const parsedIntentId = parseTableCheckoutIntentId(intentId)
  if (!parsedIntentId || !isPositiveSafeInteger(userId)) return undefined
  return withStorageLock(storage, async () => {
    const value = await storage.get(STORAGE_KEY)
    if (!isStoredTableEntry(value) || now - value.savedAt > MAX_AGE_MS || value.savedAt > now) {
      if (value !== undefined) await storage.remove(STORAGE_KEY)
      return undefined
    }
    if (value.intentId !== parsedIntentId || value.userId !== userId) return undefined
    return { intentId: value.intentId, token: value.token, userId: value.userId }
  })
}

export async function clearPendingTableEntry(
  expected: PendingTableEntryIntent,
  storage: StoragePort = getDefaultStorage(),
): Promise<boolean> {
  const parsedIntentId = parseTableCheckoutIntentId(expected.intentId)
  const parsedToken = parseTableToken(expected.token)
  if (
    parsedIntentId === undefined ||
    parsedToken === undefined ||
    !isPositiveSafeInteger(expected.userId)
  ) return false
  return withStorageLock(storage, async () => {
    const value = await storage.get(STORAGE_KEY)
    if (value === undefined) return false
    if (!isStoredTableEntry(value)) {
      await storage.remove(STORAGE_KEY)
      return false
    }
    if (
      value.intentId !== parsedIntentId ||
      value.token !== parsedToken ||
      value.userId !== expected.userId
    ) return false
    await storage.remove(STORAGE_KEY)
    return true
  })
}

function isStoredTableEntry(value: unknown): value is StoredTableEntry {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const item = value as Record<string, unknown>
  return item.version === 2 && parseTableCheckoutIntentId(item.intentId) !== undefined &&
    parseTableToken(item.token) !== undefined && isPositiveSafeInteger(item.userId) &&
    typeof item.savedAt === 'number' && Number.isSafeInteger(item.savedAt) && item.savedAt >= 0
}

function isPositiveSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function withStorageLock<T>(storage: StoragePort, operation: () => Promise<T>): Promise<T> {
  const previous = storageQueues.get(storage) ?? Promise.resolve()
  const result = previous.catch(() => undefined).then(operation)
  const settled = result.then(() => undefined, () => undefined)
  storageQueues.set(storage, settled)
  return result.finally(() => {
    if (storageQueues.get(storage) === settled) storageQueues.delete(storage)
  })
}
