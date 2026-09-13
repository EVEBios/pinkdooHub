import type { StoragePort } from '@/platform/storage'

import {
  clearPendingTableEntry,
  loadPendingTableEntry,
  savePendingTableEntry,
} from '../pending_table_entry'

class MemoryStorage implements StoragePort {
  readonly values = new Map<string, unknown>()
  async get(key: string): Promise<unknown> { return this.values.get(key) }
  async set(key: string, value: unknown): Promise<void> { this.values.set(key, value) }
  async remove(key: string): Promise<void> { this.values.delete(key) }
}

class PausedRemoveStorage extends MemoryStorage {
  private allowRemove!: () => void
  private markRemoveStarted!: () => void
  readonly removeStarted = new Promise<void>((resolve) => { this.markRemoveStarted = resolve })
  private readonly removeAllowed = new Promise<void>((resolve) => { this.allowRemove = resolve })

  releaseRemove(): void { this.allowRemove() }

  override async remove(key: string): Promise<void> {
    this.markRemoveStarted()
    await this.removeAllowed
    await super.remove(key)
  }
}

const TOKEN = 'Aa0123456789BbCcDdEeFfGgHhIiJjKk'
const INTENT_ID = 'miniapp-table-checkout-m1234567-1-abcdefghijklmnopqrst'

test('生成可安全放入路由的独立桌台结算意图', async () => {
  const storage = new MemoryStorage()
  const intent = await savePendingTableEntry(TOKEN, 7, storage, 1_000)

  expect(intent).toEqual({
    intentId: expect.stringMatching(
      /^miniapp-table-checkout-[a-z0-9]+-[a-z0-9]+-[a-z0-9]{20}$/,
    ),
    token: TOKEN,
    userId: 7,
  })
})

test('桌台结算意图绑定用户与本次确认页，并在两小时后失效', async () => {
  const storage = new MemoryStorage()
  const expected = { intentId: INTENT_ID, token: TOKEN, userId: 7 }
  expect(await savePendingTableEntry(TOKEN, 7, storage, 1_000, INTENT_ID)).toEqual(expected)
  expect(await loadPendingTableEntry(INTENT_ID, 7, storage, 1_001)).toEqual(expected)
  expect(await loadPendingTableEntry(
    INTENT_ID,
    7,
    storage,
    1_000 + 2 * 60 * 60 * 1_000 + 1,
  )).toBeUndefined()
  expect(storage.values.size).toBe(0)
})

test('普通商城确认页或其他用户不能读取陈旧桌台意图', async () => {
  const storage = new MemoryStorage()
  await savePendingTableEntry(TOKEN, 7, storage, 1_000, INTENT_ID)

  expect(await loadPendingTableEntry(`${INTENT_ID}-other`, 7, storage, 1_001)).toBeUndefined()
  expect(await loadPendingTableEntry(INTENT_ID, 8, storage, 1_001)).toBeUndefined()
  expect(await loadPendingTableEntry(INTENT_ID, 7, storage, 1_001)).toEqual({
    intentId: INTENT_ID,
    token: TOKEN,
    userId: 7,
  })
})

test('无法证明用户归属的旧版 token 记录 fail closed 并清理', async () => {
  const storage = new MemoryStorage()
  await savePendingTableEntry(TOKEN, 7, storage, 1_000, INTENT_ID)
  const [storageKey] = storage.values.keys()
  storage.values.set(storageKey, { version: 1, token: TOKEN, savedAt: 1_000 })

  expect(await loadPendingTableEntry(INTENT_ID, 7, storage, 1_001)).toBeUndefined()
  expect(storage.values.size).toBe(0)
})

test('只在匹配当前结算意图时清除，并拒绝无效输入', async () => {
  const storage = new MemoryStorage()
  await expect(savePendingTableEntry('invalid', 7, storage, 1_000, INTENT_ID))
    .rejects.toThrow('二维码无效')
  await expect(savePendingTableEntry(TOKEN, 0, storage, 1_000, INTENT_ID))
    .rejects.toThrow('用户标识无效')
  await savePendingTableEntry(TOKEN, 7, storage, 1_000, INTENT_ID)

  expect(await clearPendingTableEntry(
    { intentId: INTENT_ID, token: TOKEN, userId: 8 },
    storage,
  )).toBe(false)
  expect(await loadPendingTableEntry(INTENT_ID, 7, storage, 1_001)).toEqual({
    intentId: INTENT_ID,
    token: TOKEN,
    userId: 7,
  })

  expect(await clearPendingTableEntry(
    { intentId: INTENT_ID, token: TOKEN, userId: 7 },
    storage,
  )).toBe(true)
  expect(await clearPendingTableEntry(
    { intentId: INTENT_ID, token: TOKEN, userId: 7 },
    storage,
  )).toBe(false)
  expect(await loadPendingTableEntry(INTENT_ID, 7, storage, 1_001)).toBeUndefined()
})

test('旧意图清理与新意图保存串行，不会删除后来的桌台上下文', async () => {
  const storage = new PausedRemoveStorage()
  const nextIntentId = 'miniapp-table-checkout-m7654321-2-ponmlkjihgfedcbaqrst'
  const nextToken = 'Zz9876543210YyXxWwVvUuTtSsRrQqPp'
  const first = await savePendingTableEntry(TOKEN, 7, storage, 1_000, INTENT_ID)

  const clearing = clearPendingTableEntry(first, storage)
  await storage.removeStarted
  const saving = savePendingTableEntry(nextToken, 7, storage, 1_001, nextIntentId)
  storage.releaseRemove()

  expect(await clearing).toBe(true)
  expect(await saving).toEqual({ intentId: nextIntentId, token: nextToken, userId: 7 })
  expect(await loadPendingTableEntry(nextIntentId, 7, storage, 1_002)).toEqual({
    intentId: nextIntentId,
    token: nextToken,
    userId: 7,
  })
})
