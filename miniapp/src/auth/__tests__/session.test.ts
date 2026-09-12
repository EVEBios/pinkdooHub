import type { LoginResult, RefreshResult, UserProfile } from '@/api/endpoints/auth'
import { SessionSupersededError } from '@/api/errors'
import type { StoragePort } from '@/platform/storage'

import { SessionManager, SessionPersistenceClearError } from '../session'

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

class FaultyStorage extends MemoryStorage {
  failRemove = false
  failSet = false

  override async set(key: string, value: unknown): Promise<void> {
    if (this.failSet) throw new Error('set failed')
    await super.set(key, value)
  }

  override async remove(key: string): Promise<void> {
    if (this.failRemove) throw new Error('remove failed')
    await super.remove(key)
  }
}

class DeferredSetStorage extends MemoryStorage {
  private nextSet?: {
    readonly started: () => void
    readonly waitForRelease: Promise<void>
  }

  deferNextSet(): { readonly started: Promise<void>; release(): void } {
    let markStarted: () => void = () => undefined
    let release: () => void = () => undefined
    const started = new Promise<void>((resolve) => {
      markStarted = resolve
    })
    const waitForRelease = new Promise<void>((resolve) => {
      release = resolve
    })
    this.nextSet = { started: markStarted, waitForRelease }
    return { started, release }
  }

  override async set(key: string, value: unknown): Promise<void> {
    const deferred = this.nextSet
    this.nextSet = undefined
    if (deferred) {
      deferred.started()
      await deferred.waitForRelease
    }
    await super.set(key, value)
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

  it('损坏记录删除失败时也用无凭据 tombstone 覆盖', async () => {
    const storage = new FaultyStorage()
    storage.values.set('pinkdoohub.session.v1', {
      accessToken: 'stale-access-token',
      refreshToken: 'stale-refresh-token',
    })
    storage.failRemove = true
    const manager = new SessionManager(storage, jest.fn())

    await expect(manager.restore()).resolves.toBeUndefined()

    expect(storage.values.get('pinkdoohub.session.v1')).toEqual({
      invalidated: true,
      version: 1,
    })
    expect(JSON.stringify([...storage.values.values()])).not.toContain('stale-refresh-token')
  })

  it('损坏记录删除与覆盖都失败时发布可辨识持久化错误', async () => {
    const storage = new FaultyStorage()
    storage.values.set('pinkdoohub.session.v1', {
      accessToken: 'stale-access-token',
      refreshToken: 'stale-refresh-token',
    })
    storage.failRemove = true
    storage.failSet = true
    const manager = new SessionManager(storage, jest.fn())
    const listener = jest.fn()
    manager.subscribe(listener)

    await expect(manager.restore()).rejects.toBeInstanceOf(SessionPersistenceClearError)

    expect(listener).toHaveBeenLastCalledWith(undefined, expect.any(SessionPersistenceClearError))
    expect(JSON.stringify([...storage.values.values()])).toContain('stale-refresh-token')
  })

  it('并发刷新只请求一次，并原子替换 refresh token', async () => {
    const storage = new MemoryStorage()
    let refreshCount = 0
    const refresh = async (refreshToken: string): Promise<RefreshResult> => {
      refreshCount += 1
      expect(refreshToken).toBe('refresh-token')
      await Promise.resolve()
      return {
        access_token: 'new-access-token',
        refresh_token: 'new-refresh-token',
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
    const storedJson = JSON.stringify([...storage.values.values()])
    expect(storedJson).toContain('new-refresh-token')
    expect(storedJson).not.toContain('"refreshToken":"refresh-token"')
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

  it('删除持久会话失败时用无凭据 tombstone 安全覆盖', async () => {
    const storage = new FaultyStorage()
    const manager = new SessionManager(storage, jest.fn())
    const listener = jest.fn()
    manager.subscribe(listener)
    await manager.start(loginResult)
    storage.failRemove = true

    await expect(manager.clearSession()).resolves.toBeUndefined()

    expect(manager.getAccessToken()).toBeUndefined()
    expect(listener).toHaveBeenLastCalledWith(undefined)
    expect(storage.values.get('pinkdoohub.session.v1')).toEqual({
      invalidated: true,
      version: 1,
    })
    expect(JSON.stringify([...storage.values.values()])).not.toContain('access-token')
    expect(JSON.stringify([...storage.values.values()])).not.toContain('refresh-token')
  })

  it('删除与安全覆盖都失败时发布持久化错误并抛出同一可辨识错误', async () => {
    const storage = new FaultyStorage()
    const manager = new SessionManager(storage, jest.fn())
    const listener = jest.fn()
    manager.subscribe(listener)
    await manager.start(loginResult)
    storage.failRemove = true
    storage.failSet = true

    await expect(manager.clearSession()).rejects.toBeInstanceOf(SessionPersistenceClearError)

    expect(manager.getAccessToken()).toBeUndefined()
    expect(listener).toHaveBeenLastCalledWith(undefined, expect.any(SessionPersistenceClearError))
    expect(JSON.stringify([...storage.values.values()])).toContain('refresh-token')
  })

  it('清理失败后的重新恢复会先失效旧凭据，不会把退出前 Session 重新登录', async () => {
    const storage = new FaultyStorage()
    const manager = new SessionManager(storage, jest.fn())
    await manager.start(loginResult)
    storage.failRemove = true
    storage.failSet = true
    await expect(manager.clearSession()).rejects.toBeInstanceOf(SessionPersistenceClearError)
    expect(JSON.stringify([...storage.values.values()])).toContain('refresh-token')

    storage.failRemove = false
    storage.failSet = false
    await expect(manager.restore()).resolves.toBeUndefined()

    expect(manager.getAccessToken()).toBeUndefined()
    expect(storage.values.has('pinkdoohub.session.v1')).toBe(false)
  })

  it('退出会排在旧资料持久化之后并废弃迟到提交，不会复活旧会话', async () => {
    const storage = new DeferredSetStorage()
    const manager = new SessionManager(storage, jest.fn())
    await manager.start(loginResult)
    const listener = jest.fn()
    manager.subscribe(listener)
    const updatedUser = { ...user, nickname: '迟到资料' }
    const deferredSet = storage.deferNextSet()

    const updatePromise = manager.updateUser(updatedUser)
    await deferredSet.started
    const clearPromise = manager.clearSession()
    expect(manager.getAccessToken()).toBeUndefined()
    deferredSet.release()

    await expect(updatePromise).rejects.toBeInstanceOf(SessionSupersededError)
    await expect(clearPromise).resolves.toBeUndefined()
    expect(manager.getAccessToken()).toBeUndefined()
    expect(manager.getSnapshot()).toBeUndefined()
    expect(storage.values.has('pinkdoohub.session.v1')).toBe(false)
    expect(listener).not.toHaveBeenCalledWith(expect.objectContaining({ user: updatedUser }))
    expect(listener).toHaveBeenLastCalledWith(undefined)
  })

  it('退出会废弃已进入持久化的旧 Token 刷新，并在其后最终清除凭据', async () => {
    const storage = new DeferredSetStorage()
    const refresh = jest.fn(async (): Promise<RefreshResult> => ({
      access_token: 'late-access-token',
      refresh_token: 'late-refresh-token',
      token_type: 'Bearer',
      expires_in: 3600,
    }))
    const manager = new SessionManager(storage, refresh)
    await manager.start(loginResult)
    const listener = jest.fn()
    manager.subscribe(listener)
    const deferredSet = storage.deferNextSet()

    const refreshPromise = manager.refreshAccessToken()
    await deferredSet.started
    const clearPromise = manager.clearSession()
    expect(manager.getAccessToken()).toBeUndefined()
    deferredSet.release()

    await expect(refreshPromise).rejects.toBeInstanceOf(SessionSupersededError)
    await expect(clearPromise).resolves.toBeUndefined()
    expect(manager.getAccessToken()).toBeUndefined()
    expect(storage.values.has('pinkdoohub.session.v1')).toBe(false)
    expect(JSON.stringify([...storage.values.values()])).not.toContain('late-refresh-token')
    expect(listener).toHaveBeenLastCalledWith(undefined)
  })

  it('新登录不复用旧会话在途的 refresh Promise', async () => {
    let resolveOldRefresh!: (result: RefreshResult) => void
    const oldRefresh = new Promise<RefreshResult>((resolve) => {
      resolveOldRefresh = resolve
    })
    const refresh = jest.fn((refreshToken: string): Promise<RefreshResult> => {
      if (refreshToken === 'refresh-token') return oldRefresh
      return Promise.resolve({
        access_token: 'replacement-refreshed-access',
        refresh_token: 'replacement-refreshed-refresh',
        token_type: 'Bearer',
        expires_in: 3600,
      })
    })
    const storage = new MemoryStorage()
    const manager = new SessionManager(storage, refresh)
    await manager.start(loginResult)

    const staleRefreshPromise = manager.refreshAccessToken()
    await Promise.resolve()
    await manager.start({
      ...loginResult,
      access_token: 'replacement-access',
      refresh_token: 'replacement-refresh',
      user: { ...user, id: 8, username: 'replacement' },
    })
    await expect(manager.refreshAccessToken()).resolves.toBe('replacement-refreshed-access')

    resolveOldRefresh({
      access_token: 'stale-refreshed-access',
      refresh_token: 'stale-refreshed-refresh',
      token_type: 'Bearer',
      expires_in: 3600,
    })
    await expect(staleRefreshPromise).rejects.toBeInstanceOf(SessionSupersededError)
    expect(manager.getAccessToken()).toBe('replacement-refreshed-access')
    expect(refresh).toHaveBeenNthCalledWith(1, 'refresh-token')
    expect(refresh).toHaveBeenNthCalledWith(2, 'replacement-refresh')
  })

  it('迟到失效只能清理原请求会话，不会清理后续新登录', async () => {
    const storage = new MemoryStorage()
    const manager = new SessionManager(storage, jest.fn())
    await manager.start(loginResult)
    const oldIdentity = manager.getSessionIdentity()

    await manager.start({
      ...loginResult,
      access_token: 'replacement-access',
      refresh_token: 'replacement-refresh',
      user: { ...user, id: 8, username: 'replacement' },
    })
    await manager.clearSession(oldIdentity)

    expect(manager.getAccessToken()).toBe('replacement-access')
    expect(manager.getSnapshot()?.user.username).toBe('replacement')
    expect(JSON.stringify([...storage.values.values()])).toContain('replacement-refresh')
  })

  it('更新用户资料时保留 Token、持久化白名单用户并通知订阅者', async () => {
    const storage = new MemoryStorage()
    const manager = new SessionManager(storage, jest.fn(), { now: () => 1_000_000 })
    const listener = jest.fn()
    manager.subscribe(listener)
    await manager.start(loginResult)

    const updatedUser = { ...user, phone: '13900139000' }
    await expect(manager.updateUser(updatedUser)).resolves.toMatchObject({ user: updatedUser })

    expect(manager.getAccessToken()).toBe('access-token')
    expect(manager.getSnapshot()?.user).toEqual(updatedUser)
    expect(listener).toHaveBeenLastCalledWith(expect.objectContaining({ user: updatedUser }))
  })
})
