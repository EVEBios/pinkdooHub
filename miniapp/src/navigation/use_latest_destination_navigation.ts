import Taro from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import { isRootTabUrl } from './root_tabs'

export interface DestinationNavigationTarget {
  readonly method: 'reLaunch' | 'switchTab'
  readonly url: string
}

interface NavigationRequest extends DestinationNavigationTarget {
  readonly id: number
  readonly key: string
}

export function resolvePathNavigationTarget(url: string): DestinationNavigationTarget {
  return { method: isRootTabUrl(url) ? 'switchTab' : 'reLaunch', url }
}

/**
 * 串行执行角色落点导航，并在目标变化时只重放最新目标。
 * 原生导航不可取消，因此旧调用结束前绝不并发发起下一次调用；旧失败也不能覆盖新目标状态。
 */
export function useLatestDestinationNavigation() {
  const latestRequestRef = useRef<NavigationRequest>()
  const committedKeyRef = useRef('')
  const runningRef = useRef(false)
  const sequenceRef = useRef(0)
  const mountedRef = useRef(true)
  const [navigationError, setNavigationError] = useState('')

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const openDestination = useCallback(async (target: DestinationNavigationTarget): Promise<void> => {
    const key = `${target.method}:${target.url}`
    if (
      latestRequestRef.current?.key === key &&
      (runningRef.current || committedKeyRef.current === key)
    ) return

    const request: NavigationRequest = {
      ...target,
      id: sequenceRef.current + 1,
      key,
    }
    sequenceRef.current = request.id
    latestRequestRef.current = request
    if (runningRef.current) return

    runningRef.current = true
    try {
      while (latestRequestRef.current) {
        const current: NavigationRequest = latestRequestRef.current
        if (committedKeyRef.current === current.key) return
        if (mountedRef.current) setNavigationError('')
        try {
          if (current.method === 'switchTab') {
            await Taro.switchTab({ url: current.url })
          } else {
            await Taro.reLaunch({ url: current.url })
          }
        } catch {
          if (latestRequestRef.current?.id !== current.id) continue
          latestRequestRef.current = undefined
          committedKeyRef.current = ''
          if (mountedRef.current) setNavigationError('页面暂时无法打开，请稍后重试。')
          return
        }
        // 无论该请求是否仍为最新目标，都先记录原生端已经成功落到的真实页面。
        // 否则 A 已落点→B 在途→目标又回 A 时，B 成功后会被误判为仍在 A。
        committedKeyRef.current = current.key
        if (latestRequestRef.current?.id === current.id) return
      }
    } finally {
      runningRef.current = false
    }
  }, [])

  const resetNavigation = useCallback((): void => {
    latestRequestRef.current = undefined
    committedKeyRef.current = ''
    sequenceRef.current += 1
    setNavigationError('')
  }, [])

  return { navigationError, openDestination, resetNavigation } as const
}
