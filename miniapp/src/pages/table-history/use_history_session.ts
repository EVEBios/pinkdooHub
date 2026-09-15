import { useEffect, useState } from 'react'
import type { TableSession } from '@/api/endpoints/table_sessions'
import { nextSessionBoundaryDelay } from '@/features/table_session/clock'
import { getDefaultTableSessionApi } from '@/features/table_session/runtime'

export interface SessionSnapshot {
  readonly session: TableSession
  readonly receivedAt: number
}

export function useHistorySession(sessionNo: string, visible: boolean) {
  const [snapshot, setSnapshot] = useState<SessionSnapshot>()
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const closed = snapshot?.session.status.value === 'closed'

  useEffect(() => {
    if (!visible || closed) return
    let cancelled = false
    let fetching = false
    let boundary: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      if (fetching || cancelled) return
      fetching = true
      try {
        const session = await getDefaultTableSessionApi().getHistorySession(sessionNo)
        if (cancelled) return
        setSnapshot({ session, receivedAt: Date.now() })
        setError('')
        clearTimeout(boundary)
        const delay = nextSessionBoundaryDelay(session)
        // 截止后略留余量查询，遵守付款截止等于当前时间时仍有效的边界。
        if (delay !== undefined) boundary = setTimeout(() => void load(), delay)
      } catch {
        if (!cancelled) setError('本次桌台暂时无法读取，请重试')
      } finally { fetching = false }
    }
    void load()
    const poll = setInterval(() => void load(), 5_000)
    return () => { cancelled = true; clearInterval(poll); clearTimeout(boundary) }
  }, [sessionNo, visible, attempt, closed])

  return { snapshot, error, retry: () => setAttempt((value) => value + 1) }
}
