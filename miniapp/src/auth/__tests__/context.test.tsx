import ReactTestUtil from '@tarojs/test-utils-react'
import { Text } from '@tarojs/components'

import { SessionExpiredError } from '@/api'
import type { UserProfile } from '@/api/endpoints/auth'
import type { StoragePort } from '@/platform/storage'

import { AuthProvider, type AuthContextValue, useAuth } from '../context'
import type { AuthRuntime } from '../runtime'
import { SessionManager, SessionPersistenceClearError } from '../session'

const SESSION_KEY = 'pinkdoohub.session.v1'

const user: UserProfile = {
  id: 2,
  username: 'store_staff',
  nickname: '门店伙伴',
  phone: null,
  avatar: null,
  role: 'admin',
  status: 'normal',
  last_login_at: null,
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-01T08:00:00Z',
}

class ControlledStorage implements StoragePort {
  readonly values = new Map<string, unknown>()
  setCalls = 0
  failRemove = false
  failSetAt?: number

  async get(key: string): Promise<unknown> {
    return this.values.get(key)
  }

  async set(key: string, value: unknown): Promise<void> {
    this.setCalls += 1
    if (this.setCalls === this.failSetAt) throw new Error('set failed')
    this.values.set(key, value)
  }

  async remove(key: string): Promise<void> {
    if (this.failRemove) throw new Error('remove failed')
    this.values.delete(key)
  }
}

describe('AuthProvider 会话清理错误', () => {
  let testUtils: ReactTestUtil
  let latestAuth: AuthContextValue | undefined

  beforeEach(() => {
    testUtils = new ReactTestUtil()
    latestAuth = undefined
  })

  afterEach(() => {
    testUtils.unmout()
  })

  it('失效会话无法从设备安全清除时进入可见 error 状态且不产生未处理拒绝', async () => {
    const storage = new ControlledStorage()
    storage.values.set(SESSION_KEY, {
      version: 1,
      accessToken: 'stale-access-token',
      refreshToken: 'stale-refresh-token',
      expiresAt: 9_000_000,
      user,
    })
    storage.failRemove = true
    // restore 的白名单重写是第一次 set；clearSession 的 tombstone 是第二次。
    storage.failSetAt = 2
    const session = new SessionManager(storage, jest.fn(), { now: () => 1_000_000 })
    const runtime = {
      session,
      api: {
        getMe: jest.fn().mockRejectedValue(new SessionExpiredError(
          { operation: '读取当前用户' },
          new Error('expired'),
        )),
      },
    } as unknown as AuthRuntime

    function Probe() {
      latestAuth = useAuth()
      return <Text>{latestAuth.status}</Text>
    }

    function Subject() {
      return <AuthProvider runtime={runtime}><Probe /></AuthProvider>
    }

    await testUtils.mount(Subject)
    await flush(testUtils)

    expect(latestAuth?.status).toBe('error')
    expect(latestAuth?.user).toBeUndefined()
    expect(latestAuth?.initializationError).toBeInstanceOf(SessionPersistenceClearError)
    expect(latestAuth?.initializationError?.message).toContain('请清理小程序数据')
    expect(JSON.stringify(storage.values.get(SESSION_KEY))).toContain('stale-refresh-token')
  })

  it('运行期清理失败通过 Session 订阅提升为全局可见 error 状态', async () => {
    const storage = new ControlledStorage()
    storage.values.set(SESSION_KEY, {
      version: 1,
      accessToken: 'access-token',
      refreshToken: 'refresh-token',
      expiresAt: 9_000_000,
      user,
    })
    const session = new SessionManager(storage, jest.fn(), { now: () => 1_000_000 })
    const runtime = {
      session,
      api: { getMe: jest.fn().mockResolvedValue(user) },
    } as unknown as AuthRuntime

    function Probe() {
      latestAuth = useAuth()
      return <Text>{latestAuth.status}</Text>
    }

    function Subject() {
      return <AuthProvider runtime={runtime}><Probe /></AuthProvider>
    }

    await testUtils.mount(Subject)
    await flush(testUtils)
    expect(latestAuth?.status).toBe('authenticated')

    storage.failRemove = true
    storage.failSetAt = storage.setCalls + 1
    let cleanupCause: unknown
    await testUtils.act(async () => {
      try {
        await session.clearSession()
      } catch (cause) {
        cleanupCause = cause
      }
    })

    expect(cleanupCause).toBeInstanceOf(SessionPersistenceClearError)
    expect(latestAuth?.status).toBe('error')
    expect(latestAuth?.user).toBeUndefined()
    expect(latestAuth?.initializationError).toBeInstanceOf(SessionPersistenceClearError)
  })
})

async function flush(testUtils: ReactTestUtil): Promise<void> {
  await testUtils.act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}
