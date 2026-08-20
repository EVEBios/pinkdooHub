import type { AuthSession } from '@/api'
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
export type SessionListener = (snapshot: SessionSnapshot | undefined) => void

const systemClock: Clock = { now: () => Date.now() }

export class SessionManager implements AuthSession {
  private session?: StoredSession
  private readonly listeners = new Set<SessionListener>()
  private refreshPromise?: Promise<string>

  constructor(
    private readonly storage: StoragePort,
    private readonly refresh: RefreshAccessToken,
    private readonly clock: Clock = systemClock,
  ) {}

  getAccessToken(): string | undefined {
    return this.session?.accessToken
  }

  getSnapshot(): SessionSnapshot | undefined {
    return this.session ? toSnapshot(this.session) : undefined
  }

  isAccessTokenExpired(): boolean {
    return Boolean(this.session && this.session.expiresAt <= this.clock.now() + EXPIRY_SKEW_MS)
  }

  async restore(): Promise<SessionSnapshot | undefined> {
    const stored = await this.storage.get(SESSION_STORAGE_KEY)
    const parsed = parseStoredSession(stored)
    if (!parsed) {
      this.session = undefined
      if (stored !== undefined) {
        await this.storage.remove(SESSION_STORAGE_KEY)
      }
      return undefined
    }
    // 重写经过白名单投影的数据，清除旧版本或外部篡改留下的额外字段。
    await this.storage.set(SESSION_STORAGE_KEY, parsed)
    this.session = parsed
    return toSnapshot(parsed)
  }

  async start(loginResult: LoginResult): Promise<SessionSnapshot> {
    const session: StoredSession = {
      version: SESSION_VERSION,
      accessToken: loginResult.access_token,
      refreshToken: loginResult.refresh_token,
      expiresAt: this.calculateExpiresAt(loginResult.expires_in),
      user: loginResult.user,
    }
    await this.persist(session, true)
    return toSnapshot(session)
  }

  async updateUser(user: UserProfile): Promise<SessionSnapshot> {
    if (!this.session) {
      throw new Error('没有可更新的登录会话')
    }
    const session = { ...this.session, user }
    await this.persist(session, true)
    return toSnapshot(session)
  }

  async refreshAccessToken(): Promise<string | undefined> {
    if (!this.session) {
      return undefined
    }
    if (this.refreshPromise) {
      return this.refreshPromise
    }

    const refreshToken = this.session.refreshToken
    const activeRefresh = this.performRefresh(refreshToken)
    this.refreshPromise = activeRefresh
    try {
      return await activeRefresh
    } finally {
      if (this.refreshPromise === activeRefresh) {
        this.refreshPromise = undefined
      }
    }
  }

  async clearSession(): Promise<void> {
    this.session = undefined
    await this.storage.remove(SESSION_STORAGE_KEY)
    this.notify()
  }

  subscribe(listener: SessionListener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  private async performRefresh(refreshToken: string): Promise<string> {
    const result = await this.refresh(refreshToken)
    if (!this.session || this.session.refreshToken !== refreshToken) {
      throw new Error('刷新期间登录会话已发生变化')
    }
    const session: StoredSession = {
      ...this.session,
      accessToken: result.access_token,
      expiresAt: this.calculateExpiresAt(result.expires_in),
    }
    // access token 刷新不改变用户身份，不通知 React 切换认证状态；
    // 启动恢复时必须先通过 /users/me 验证，避免把缓存身份提前视为服务端授权。
    await this.persist(session, false)
    return session.accessToken
  }

  private calculateExpiresAt(expiresIn: number): number {
    return this.clock.now() + expiresIn * 1_000
  }

  private async persist(session: StoredSession, notify: boolean): Promise<void> {
    await this.storage.set(SESSION_STORAGE_KEY, session)
    this.session = session
    if (notify) {
      this.notify()
    }
  }

  private notify(): void {
    const snapshot = this.getSnapshot()
    this.listeners.forEach((listener) => listener(snapshot))
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
