import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { BusinessError, SessionExpiredError } from '@/api'
import type { UserProfile } from '@/api/endpoints/auth'

import { getDefaultAuthRuntime, type AuthRuntime } from './runtime'

export type AuthStatus = 'initializing' | 'guest' | 'authenticated' | 'error'

export interface AuthContextValue {
  status: AuthStatus
  user?: UserProfile
  initializationError?: Error
  login(username: string, password: string): Promise<void>
  logout(): Promise<void>
  retryInitialization(): void
}

interface AuthProviderProps extends PropsWithChildren {
  runtime?: AuthRuntime
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children, runtime: runtimeProp }: AuthProviderProps) {
  const runtimeRef = useRef<AuthRuntime>()
  runtimeRef.current ??= runtimeProp ?? getDefaultAuthRuntime()
  const runtime = runtimeRef.current
  const [status, setStatus] = useState<AuthStatus>('initializing')
  const [user, setUser] = useState<UserProfile>()
  const [initializationError, setInitializationError] = useState<Error>()
  const [initializationAttempt, setInitializationAttempt] = useState(0)

  useEffect(() => {
    return runtime.session.subscribe((snapshot) => {
      setUser(snapshot?.user)
      setStatus(snapshot ? 'authenticated' : 'guest')
    })
  }, [runtime])

  useEffect(() => {
    let active = true

    async function initialize() {
      setStatus('initializing')
      setInitializationError(undefined)
      try {
        const restored = await runtime.session.restore()
        if (!restored) {
          if (active) {
            setUser(undefined)
            setStatus('guest')
          }
          return
        }
        if (runtime.session.isAccessTokenExpired()) {
          await runtime.session.refreshAccessToken()
        }
        const currentUser = await runtime.api.getMe()
        await runtime.session.updateUser(currentUser)
        if (active) {
          setUser(currentUser)
          setStatus('authenticated')
        }
      } catch (cause) {
        if (isInvalidSessionError(cause)) {
          await runtime.session.clearSession()
          return
        }
        if (active) {
          setInitializationError(toError(cause))
          setStatus('error')
        }
      }
    }

    void initialize()
    return () => {
      active = false
    }
  }, [initializationAttempt, runtime])

  const login = useCallback(async (username: string, password: string) => {
    const result = await runtime.api.login({ username, password })
    await runtime.session.start(result)
    setInitializationError(undefined)
    setUser(result.user)
    setStatus('authenticated')
  }, [runtime])

  const logout = useCallback(async () => {
    try {
      await runtime.api.logout()
    } finally {
      await runtime.session.clearSession()
    }
  }, [runtime])

  const retryInitialization = useCallback(() => {
    setInitializationAttempt((attempt) => attempt + 1)
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    status,
    user,
    initializationError,
    login,
    logout,
    retryInitialization,
  }), [initializationError, login, logout, retryInitialization, status, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) {
    throw new Error('useAuth 必须在 AuthProvider 内使用')
  }
  return value
}

function isInvalidSessionError(cause: unknown): boolean {
  return cause instanceof SessionExpiredError || (
    cause instanceof BusinessError && (cause.code === 1005 || cause.code === 1006)
  )
}

function toError(cause: unknown): Error {
  return cause instanceof Error ? cause : new Error('初始化登录状态失败')
}
