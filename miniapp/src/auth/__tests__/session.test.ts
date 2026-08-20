import type { LoginResult, RefreshResult, UserProfile } from '@/api/endpoints/auth'
import type { StoragePort } from '@/platform/storage'

import { SessionManager } from '../session'

class MemoryStorage implements StoragePort {
  readonly values = new Map<string, unknown>()
  readonly removed: string[] = []

  async get(key: string): Promise<unknown> {
    return this.values.get(key)
  }

  async set(key: string, value: unknown): Promise<void> {
    this.values.set(key, value)
  }

  async remove(key: string): Promise<void> {
    this.removed.push(key)
    this.values.delete(key)
  }
}

const user: UserProfile = {
  id: 7,
  username: 'alice',
  nickname: 'Alice',
  phone: '13800138000',
  avatar: null,
  role: 'admin',
  status: 'normal',
  last_login_at: null,
  created_at: '2026-08-01T08:00:00Z',
  updated_at: '2026-08-20T08:00:00Z',
}

const loginResult: LoginResult = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  token_type: 'Bearer',
  expires_in: 7200,
  user,
}

describe('SessionManager', () => {
  it('只持久化会话必要字段，并以秒计算过期时间', async () => {
    const storage = new MemoryStorage()
    const manager = new SessionManager(
      storage,
      jest.fn(),
      { now: () => 1_000_000 },
    )

    await manager.start(loginResult)

    expect(manager.getAccessToken()).toBe('access-token')
    expect(manager.getSnapshot()).toEqual({
      expiresAt: 8_200_000,
      user,
    })
    const storedJson = JSON.stringify([...storage.values.values()])
    expect(storedJson).not.toContain('password')
    expect(storedJson).toContain('refresh-token')
  })

  it('恢复合法会话，发现损坏数据时主动删除', async () => {
    const storage = new MemoryStorage()
    const first = new SessionManager(storage, jest.fn(), { now: () => 1_000_000 })
    await first.start(loginResult)

    const raw = storage.values.get('pinkdoohub.session.v1') as Record<string, unknown>
    storage.values.set('pinkdoohub.session.v1', {
      ...raw,
      user: { ...(raw.user as UserProfile), password: 'legacy-leak' },
    })

    const restored = new SessionManager(storage, jest.fn(), { now: () => 1_000_000 })
    await expect(restored.restore()).resolves.toMatchObject({ user })
    expect(restored.getAccessToken()).toBe('access-token')
    expect(JSON.stringify([...storage.values.values()])).not.toContain('legacy-leak')

    storage.values.set('pinkdoohub.session.v1', { accessToken: 'broken' })
    const broken = new SessionManager(storage, jest.fn())
    await expect(broken.restore()).resolves.toBeUndefined()
    expect(storage.removed).toContain('pinkdoohub.session.v1')
  })

  it('并发刷新只请求一次，并保留原 refresh token', async () => {
    const storage = new MemoryStorage()
    let refreshCount = 0
    const refresh = async (refreshToken: string): Promise<RefreshResult> => {
      refreshCount += 1
      expect(refreshToken).toBe('refresh-token')
      await Promise.resolve()
      return {
        access_token: 'new-access-token',
        token_type: 'Bearer',
        expires_in: 3600,
      }
    }
    const manager = new SessionManager(storage, refresh, { now: () => 2_000_000 })
    await manager.start(loginResult)

    await expect(Promise.all([
      manager.refreshAccessToken(),
      manager.refreshAccessToken(),
      manager.refreshAccessToken(),
    ])).resolves.toEqual(['new-access-token', 'new-access-token', 'new-access-token'])

    expect(refreshCount).toBe(1)
    expect(manager.getAccessToken()).toBe('new-access-token')
    expect(JSON.stringify([...storage.values.values()])).toContain('refresh-token')
  })

  it('清除内存与持久化会话并通知订阅者', async () => {
    const storage = new MemoryStorage()
    const manager = new SessionManager(storage, jest.fn())
    const listener = jest.fn()
    manager.subscribe(listener)
    await manager.start(loginResult)
    await manager.clearSession()

    expect(manager.getAccessToken()).toBeUndefined()
    expect(listener).toHaveBeenLastCalledWith(undefined)
    expect(storage.values.size).toBe(0)
  })
})
