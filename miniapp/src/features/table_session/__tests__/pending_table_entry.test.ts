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

const TOKEN = 'Aa0123456789BbCcDdEeFfGgHhIiJjKk'

test('新订单返回桌台意图只保存合法 token 并在两小时后失效', async () => {
  const storage = new MemoryStorage()
  await savePendingTableEntry(TOKEN, storage, 1_000)
  expect(await loadPendingTableEntry(storage, 1_001)).toBe(TOKEN)
  expect(await loadPendingTableEntry(storage, 1_000 + 2 * 60 * 60 * 1_000 + 1)).toBeUndefined()
  expect(storage.values.size).toBe(0)
})

test('清除返回意图且拒绝无效桌台 token', async () => {
  const storage = new MemoryStorage()
  await expect(savePendingTableEntry('invalid', storage, 1_000)).rejects.toThrow('二维码无效')
  await savePendingTableEntry(TOKEN, storage, 1_000)
  await clearPendingTableEntry(storage)
  expect(await loadPendingTableEntry(storage, 1_001)).toBeUndefined()
})
