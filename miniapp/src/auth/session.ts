import type { AuthSession } from '@/api'
import { SessionSupersededError } from '@/api/errors'
import type { LoginResult, RefreshResult, UserProfile } from '@/api/endpoints/auth'
import { parseUserProfile } from '@/api/endpoints/auth'
import type { StoragePort } from '@/platform/storage'

const SESSION_STORAGE_KEY = 'pinkdoohub.session.v1'
const SESSION_VERSION = 1
const EXPIRY_SKEW_MS = 30_000

interface StoredSession {
  version: typeof SESSION_VERSION
  accessToken: string
  refreshToken: string
  expiresAt: number
  user: UserProfile
}

export interface SessionSnapshot {
  expiresAt: number
  user: UserProfile
}

export interface Clock {
  now(): number
}

export type RefreshAccessToken = (refreshToken: string) => Promise<RefreshResult>
export type SessionListener = (
  snapshot: SessionSnapshot | undefined,
  persistenceError?: SessionPersistenceClearError,
) => void

const systemClock: Clock = { now: () => Date.now() }

export class SessionPersistenceClearError extends Error {
  constructor() {
    super('设备会话未能安全清除，请清理小程序数据')
    this.name = 'SessionPersistenceClearError'
  }
}

export class SessionManager implements AuthSession {
  private session?: StoredSession
  private readonly listeners = new Set<SessionListener>()
  private refreshPromise?: Promise<string>
  private refreshPromiseEpoch?: number
  private persistenceQueue: Promise<void> = Promise.resolve()
  private persistenceClearRequired = false
  private sessionEpoch = 0

  constructor(
    private readonly storage: StoragePort,
    private readonly refresh: RefreshAccessToken,
    private readonly clock: Clock = systemClock,
  ) {}

  getAccessToken(): string | undefined {
    return this.session?.accessToken
  }

  getSessionIdentity(): number | undefined {
    return this.session ? this.sessionEpoch : undefined
  }

  getSnapshot(): SessionSnapshot | undefined {
    return this.session ? toSnapshot(this.session) : undefined
  }

  isAccessTokenExpired(): boolean {
    return Boolean(this.session && this.session.expiresAt <= this.clock.now() + EXPIRY_SKEW_MS)
  }

  async restore(): Promise<SessionSnapshot | undefined> {
    const expectedEpoch = this.sessionEpoch
    return this.enqueuePersistence(async () => {
      if (expectedEpoch !== this.sessionEpoch) return undefined
      if (this.persistenceClearRequired) {
        // 上一次退出/损坏缓存清理失败后，“重新检查”必须先重试失效持久凭据，
        // 不能把仍在 Storage 中的旧 Session 当成可恢复登录。
        this.session = undefined
        await this.removePersistedSession()
        return undefined
      }
      const stored = await this.storage.get(SESSION_STORAGE_KEY)
      if (expectedEpoch !== this.sessionEpoch) return undefined
      const parsed = parseStoredSession(stored)
      if (!parsed) {
        this.session = undefined
        if (stored !== undefined) {
          this.persistenceClearRequired = true
          await this.removePersistedSession()
        }
        return undefined
      }
      // 重写经过白名单投影的数据，清除旧版本或外部篡改留下的额外字段。
      await this.storage.set(SESSION_STORAGE_KEY, parsed)
      if (expectedEpoch !== this.sessionEpoch) return undefined
      this.session = parsed
      return toSnapshot(parsed)
    })
  }

  async start(loginResult: LoginResult): Promise<SessionSnapshot> {
    // 显式新登录是新的身份意图，同样废弃上一会话已在途的 refresh/profile 写入。
    this.sessionEpoch += 1
    const expectedEpoch = this.sessionEpoch
    const session: StoredSession = {
      version: SESSION_VERSION,
      accessToken: loginResult.access_token,
      refreshToken: loginResult.refresh_token,
      expiresAt: this.calculateExpiresAt(loginResult.expires_in),
      user: loginResult.user,
    }
    await this.persist(session, true, expectedEpoch)
    return toSnapshot(session)
  }

  async updateUser(user: UserProfile): Promise<SessionSnapshot> {
    if (!this.session) {
      throw new Error('没有可更新的登录会话')
    }
    const expectedEpoch = this.sessionEpoch
    const session = { ...this.session, user }
    await this.persist(session, true, expectedEpoch)
    return toSnapshot(session)
  }

  async refreshAccessToken(): Promise<string | undefined> {
    if (!this.session) {
      return undefined
    }
    if (this.refreshPromise && this.refreshPromiseEpoch === this.sessionEpoch) {
      return this.refreshPromise
    }

    const refreshToken = this.session.refreshToken
    const expectedEpoch = this.sessionEpoch
    const activeRefresh = this.performRefresh(refreshToken, expectedEpoch)
    this.refreshPromise = activeRefresh
    this.refreshPromiseEpoch = expectedEpoch
    try {
      return await activeRefresh
    } finally {
      if (this.refreshPromise === activeRefresh) {
        this.refreshPromise = undefined
        this.refreshPromiseEpoch = undefined
      }
    }
  }

  async clearSession(expectedSessionIdentity?: unknown): Promise<void> {
    if (
      expectedSessionIdentity !== undefined &&
      !Object.is(this.getSessionIdentity(), expectedSessionIdentity)
    ) {
      return
    }
    this.session = undefined
    this.persistenceClearRequired = true
    this.sessionEpoch += 1
    await this.enqueuePersistence(async () => {
      await this.removePersistedSession()
      this.notify()
    })
  }

  subscribe(listener: SessionListener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  private async removePersistedSession(): Promise<void> {
    try {
      await this.storage.remove(SESSION_STORAGE_KEY)
      this.persistenceClearRequired = false
    } catch {
      try {
        // 删除失败时用不含任何凭据、且无法通过 parseStoredSession 的 tombstone 覆盖旧值。
        await this.storage.set(SESSION_STORAGE_KEY, {
          invalidated: true,
          version: SESSION_VERSION,
        })
        this.persistenceClearRequired = false
      } catch {
        const persistenceError = new SessionPersistenceClearError()
        this.notify(persistenceError)
        throw persistenceError
      }
    }
  }

  private async performRefresh(refreshToken: string, expectedEpoch: number): Promise<string> {
    const result = await this.refresh(refreshToken)
    if (
      expectedEpoch !== this.sessionEpoch ||
      !this.session ||
      this.session.refreshToken !== refreshToken
    ) {
      throw new SessionSupersededError()
    }
    const session: StoredSession = {
      ...this.session,
      accessToken: result.access_token,
      refreshToken: result.refresh_token,
      expiresAt: this.calculateExpiresAt(result.expires_in),
    }
    // access token 刷新不改变用户身份，不通知 React 切换认证状态；
    // 启动恢复时必须先通过 /users/me 验证，避免把缓存身份提前视为服务端授权。
    await this.persist(session, false, expectedEpoch)
    return session.accessToken
  }

  private calculateExpiresAt(expiresIn: number): number {
    return this.clock.now() + expiresIn * 1_000
  }

  private async persist(
    session: StoredSession,
    notify: boolean,
    expectedEpoch: number,
  ): Promise<void> {
    await this.enqueuePersistence(async () => {
      this.assertCurrentEpoch(expectedEpoch)
      await this.storage.set(SESSION_STORAGE_KEY, session)
      this.assertCurrentEpoch(expectedEpoch)
      this.persistenceClearRequired = false
      this.session = session
      if (notify) {
        this.notify()
      }
    })
  }

  private enqueuePersistence<Result>(operation: () => Promise<Result>): Promise<Result> {
    const result = this.persistenceQueue.then(operation)
    this.persistenceQueue = result.then(() => undefined, () => undefined)
    return result
  }

  private assertCurrentEpoch(expectedEpoch: number): void {
    if (expectedEpoch !== this.sessionEpoch) {
      throw new SessionSupersededError()
    }
  }

  private notify(persistenceError?: SessionPersistenceClearError): void {
    const snapshot = this.getSnapshot()
    this.listeners.forEach((listener) => {
      if (persistenceError) {
        listener(snapshot, persistenceError)
      } else {
        listener(snapshot)
      }
    })
  }
}

function toSnapshot(session: StoredSession): SessionSnapshot {
  return { expiresAt: session.expiresAt, user: session.user }
}

function parseStoredSession(value: unknown): StoredSession | undefined {
  if (!isRecord(value)) {
    return undefined
  }
  const user = parseUserProfile(value.user)
  if (!(
    value.version === SESSION_VERSION &&
    isNonEmptyString(value.accessToken) &&
    isNonEmptyString(value.refreshToken) &&
    typeof value.expiresAt === 'number' &&
    Number.isFinite(value.expiresAt) &&
    user
  )) {
    return undefined
  }
  return {
    version: SESSION_VERSION,
    accessToken: value.accessToken,
    refreshToken: value.refreshToken,
    expiresAt: value.expiresAt,
    user,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}
