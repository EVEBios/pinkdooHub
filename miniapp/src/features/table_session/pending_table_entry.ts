import type { StoragePort } from '@/platform/storage'
import { TaroStorageAdapter } from '@/platform/storage'

import { parseTableToken } from './table_session_route'

const STORAGE_KEY = 'pinkdoohub.table-entry.v1'
const MAX_AGE_MS = 2 * 60 * 60 * 1_000

interface StoredTableEntry {
  readonly version: 1
  readonly token: string
  readonly savedAt: number
}

let defaultStorage: StoragePort | undefined

function getDefaultStorage(): StoragePort {
  defaultStorage ??= new TaroStorageAdapter()
  return defaultStorage
}

export async function savePendingTableEntry(
  token: string,
  storage: StoragePort = getDefaultStorage(),
  now = Date.now(),
): Promise<void> {
  const parsed = parseTableToken(token)
  if (!parsed) throw new Error('桌台二维码无效')
  await storage.set(STORAGE_KEY, { version: 1, token: parsed, savedAt: now })
}

export async function loadPendingTableEntry(
  storage: StoragePort = getDefaultStorage(),
  now = Date.now(),
): Promise<string | undefined> {
  const value = await storage.get(STORAGE_KEY)
  if (!isStoredTableEntry(value) || now - value.savedAt > MAX_AGE_MS || value.savedAt > now) {
    if (value !== undefined) await storage.remove(STORAGE_KEY)
    return undefined
  }
  return value.token
}

export async function clearPendingTableEntry(
  storage: StoragePort = getDefaultStorage(),
): Promise<void> {
  await storage.remove(STORAGE_KEY)
}

function isStoredTableEntry(value: unknown): value is StoredTableEntry {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const item = value as Record<string, unknown>
  return item.version === 1 && parseTableToken(item.token) !== undefined &&
    typeof item.savedAt === 'number' && Number.isSafeInteger(item.savedAt) && item.savedAt >= 0
}
