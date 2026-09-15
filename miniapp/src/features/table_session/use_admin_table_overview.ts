import { useCallback, useEffect, useRef, useState } from 'react'
import type { AdminTableList } from '@/api/endpoints/table_sessions'
import { usePageVisibility } from '@/features/attention/hooks'
import { getDefaultTableSessionApi } from '@/features/table_session'
import { tableAdminError } from './admin_table_actions'
import { tableAttentionCounts } from './admin_table_attention'
import { useAdminTableClock } from './use_admin_table_clock'

/** 一个可见页面只保留一个读请求；后台停止轮询，回来立即校准服务端时间。 */
export function useAdminTableOverview() {
  const source = getDefaultTableSessionApi()
  const [data, setData] = useState<AdminTableList>()
  const [error, setError] = useState('')
  const { visible, visibleRef } = usePageVisibility()
  const mounted = useRef(false)
  const inFlight = useRef(false)
  const queued = useRef(false)
  const refreshRef = useRef<() => void>(() => undefined)
  const now = useAdminTableClock(data?.server_now, visible)
  const refresh = useCallback(() => {
    if (!mounted.current || !visibleRef.current) return
    if (inFlight.current) { queued.current = true; return }
    inFlight.current = true
    void source.listAdminTables().then((result) => {
      if (mounted.current && visibleRef.current) { setData(result); setError('') }
    }).catch((cause: unknown) => {
      if (mounted.current && visibleRef.current) setError(tableAdminError(cause))
    }).finally(() => {
      inFlight.current = false
      if (queued.current) { queued.current = false; refreshRef.current() }
    })
  }, [source, visibleRef])
  refreshRef.current = refresh
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    if (!visible) return
    refresh()
    const timer = setInterval(() => { if (!inFlight.current) refresh() }, 10_000)
    return () => clearInterval(timer)
  }, [refresh, visible])
  const readError = error ? `桌台状态更新失败。${data ? '当前显示上次数据，请刷新后核实。' : '请刷新重试。'}${error}` : ''
  return { data, error: readError, refresh, now, counts: tableAttentionCounts(data?.items ?? [], now) }
}
