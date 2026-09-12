import { useCallback, useRef, useState } from 'react'

import {
  ApiClientError,
  BusinessError,
  ContractError,
  HttpError,
  NetworkError,
  RequestCancelledError,
  SessionExpiredError,
  TimeoutError,
} from '@/api'

import { getDefaultAdminUserApi } from './runtime'

export type AdminUserDisableState =
  | { readonly status: 'idle' }
  | { readonly status: 'submitting'; readonly userId: number }
  | { readonly status: 'succeeded'; readonly userId: number }
  | { readonly status: 'failed' | 'unknown'; readonly userId: number; readonly errorMessage: string }

export interface AdminUserDisableSource {
  disableUser(userId: number): Promise<void>
}

export function useAdminUserDisable(
  source: AdminUserDisableSource = getDefaultAdminUserApi(),
) {
  const [state, setState] = useState<AdminUserDisableState>({ status: 'idle' })
  const activeRef = useRef<Promise<boolean>>()

  const disableUser = useCallback((userId: number): Promise<boolean> => {
    if (activeRef.current) return activeRef.current
    const active = (async () => {
      setState({ status: 'submitting', userId })
      try {
        await source.disableUser(userId)
        setState({ status: 'succeeded', userId })
        return true
      } catch (cause) {
        const error = cause instanceof Error ? cause : new Error('禁用用户失败')
        setState(isUnknown(error)
          ? { status: 'unknown', userId, errorMessage: '禁用结果可能未知，请重新加载列表核对；系统不会自动重试' }
          : { status: 'failed', userId, errorMessage: getMessage(error) })
        return false
      }
    })()
    activeRef.current = active
    void active.finally(() => {
      if (activeRef.current === active) activeRef.current = undefined
    }).catch(() => undefined)
    return active
  }, [source])

  const reset = useCallback(() => {
    if (!activeRef.current) setState({ status: 'idle' })
  }, [])

  return { state, disableUser, reset }
}

function isUnknown(error: Error): boolean {
  return error instanceof NetworkError ||
    error instanceof TimeoutError ||
    error instanceof RequestCancelledError ||
    error instanceof ContractError ||
    (error instanceof HttpError && (error.statusCode ?? 0) >= 500)
}

function getMessage(error: Error): string {
  if (error instanceof BusinessError) {
    if (error.code === 1002) return '用户不存在，请重新加载列表'
    if (error.code === 422) return '不能禁用当前登录账号'
    if (error.statusCode === 403) return '当前账号不能禁用该用户'
  }
  if (error instanceof SessionExpiredError) return '登录状态已失效，请重新登录'
  if (error instanceof ApiClientError && error.message) return error.message
  return '禁用用户失败，请稍后重试'
}
