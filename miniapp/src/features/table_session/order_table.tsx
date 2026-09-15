import { Button, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { TableSession } from '@/api/endpoints/table_sessions'
import { isWalletMutationUnknown } from '@/features/wallet/mutation'
import { usePageVisibility } from '@/features/attention/hooks'

import { getTableErrorMessage } from './errors'
import { createTableIntentKey } from './idempotency'
import { getDefaultTableSessionApi } from './runtime'
import { TableSelector } from './table_selector'

export function useOrderTable(orderId: number) {
  const { visible } = usePageVisibility()
  const [session, setSession] = useState<TableSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [claiming, setClaiming] = useState(false)
  const [now, setNow] = useState(Date.now())
  const serverOffset = useRef(0)
  const sequence = useRef(0)
  const claim = useRef<{ tableNo: string; key: string }>()
  const activeClaim = useRef(false)
  const refresh = useCallback(async () => {
    const current = ++sequence.current
    try {
      const value = await getDefaultTableSessionApi().getOrderSession(orderId)
      if (sequence.current !== current) return
      serverOffset.current = value ? Date.parse(value.server_now) - Date.now() : 0
      setNow(Date.now() + serverOffset.current)
      setSession(value)
      setError(undefined)
    } catch (cause) {
      if (sequence.current === current) setError(cause instanceof Error ? cause.message : '桌台读取失败，请重试')
    } finally { if (sequence.current === current) setLoading(false) }
  }, [orderId])
  useEffect(() => {
    setLoading(true)
    setSession(null)
    void refresh()
    return () => { sequence.current += 1 }
  }, [refresh])
  useDidShow(() => { void refresh() })
  useEffect(() => {
    if (!visible || !session || session.status.value === 'closed') return
    const timer = setInterval(() => { setNow(Date.now() + serverOffset.current) }, 1000)
    const poll = setInterval(() => { void refresh() }, 5000)
    return () => { clearInterval(timer); clearInterval(poll) }
  }, [refresh, session, visible])
  const remaining = session ? Math.max(0, Math.ceil((Date.parse(session.payment_deadline_at) - now) / 1000)) : 0
  const blocked = loading || !!error || claiming || (session !== null &&
    (session.status.value !== 'awaiting_payment' || remaining === 0))
  const bind = useCallback(async (tableNo?: string) => {
    if (!tableNo || activeClaim.current) return
    activeClaim.current = true
    setClaiming(true)
    if (claim.current?.tableNo !== tableNo) claim.current = { tableNo, key: createTableIntentKey('claim') }
    try {
      const result = await getDefaultTableSessionApi().createSessionByNumber(tableNo, orderId, claim.current.key)
      setSession(result)
      claim.current = undefined
      await refresh()
    } catch (cause) {
      if (!(cause instanceof Error) || !isWalletMutationUnknown(cause)) claim.current = undefined
      await refresh()
      throw new Error(getTableErrorMessage(cause))
    } finally {
      setClaiming(false)
      activeClaim.current = false
    }
  }, [orderId, refresh])
  return { session, loading, error, claiming, remaining, blocked, bind, refresh }
}

export function OrderTablePanel({ table, pending, hasExperience, disabled }: {
  readonly table: ReturnType<typeof useOrderTable>
  readonly pending: boolean
  readonly hasExperience: boolean
  readonly disabled: boolean
}) {
  if (table.loading || table.error) return <View className='table-selector'>
    <Text>{table.error ?? '正在核对订单桌台…'}</Text>
    {table.error && <Button className='table-selector__clear' onClick={() => void table.refresh()}>重新读取桌台</Button>}
  </View>
  const session = table.session
  const canBind = pending && hasExperience && (!session || session.status.value === 'closed')
  return <>
    {session && <View className='table-selector'>
      <Text className='table-selector__title'>本次桌台 {session.table.table_no} · {session.status.label}</Text>
      <Text className='table-selector__hint'>{session.status.value === 'awaiting_payment'
        ? table.remaining > 0 ? `请在 ${Math.floor(table.remaining / 60)} 分 ${table.remaining % 60} 秒内付款，付款成功开始计时。` : '付款时限已过，请刷新桌台状态后重新选桌。'
        : session.status.value === 'closed' && pending ? '本次占台已结束，请重新选桌后付款。' : '查看本次桌台的计时与使用记录。'}</Text>
      <Button className='table-selector__clear' onClick={() => void Taro.navigateTo({ url: `/pages/table-history/index?sessionNo=${session.session_no}` })}>查看这次桌台</Button>
      {pending && table.remaining === 0 && session.status.value === 'awaiting_payment' && <Button className='table-selector__clear' onClick={() => void table.refresh()}>刷新桌台状态</Button>}
    </View>}
    {canBind && <TableSelector disabled={disabled || table.claiming} allowClear={false} onChange={table.bind} />}
  </>
}
