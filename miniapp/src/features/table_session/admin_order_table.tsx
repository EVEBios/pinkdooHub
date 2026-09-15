import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useState } from 'react'

import type { AdminTableSession } from '@/api/endpoints/table_sessions'

import { getDefaultTableSessionApi } from './runtime'
import { buildAdminTableSessionUrl } from './table_session_route'
import './table_selector.scss'

export function AdminOrderTable({ orderId, revision }: { readonly orderId: number; readonly revision: string }) {
  const [session, setSession] = useState<AdminTableSession | null>()
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    void getDefaultTableSessionApi().getAdminOrderSession(orderId).then((value) => {
      if (active) { setSession(value); setError(false) }
    }).catch(() => { if (active) setError(true) })
    return () => { active = false }
  }, [orderId, revision, attempt])
  if (session === null && !error) return null
  return <View className='table-selector'>
    <Text className='table-selector__title'>{session ? `关联桌台 ${session.table.table_no} · ${session.status.label}` : '正在核对关联桌台…'}</Text>
    <Text className='table-selector__hint'>{error ? '桌台暂时读取失败，确认收款前会再次核对。' : session?.status.value === 'closed' ? '本次占台已结束，待付款订单需由顾客重新选桌。' : '有效待付款桌台在确认收款后开始计时。'}</Text>
    {error && <Button className='table-selector__clear' onClick={() => setAttempt((value) => value + 1)}>重新读取桌台</Button>}
    {session && <Button className='table-selector__clear' onClick={() => void Taro.navigateTo({ url: buildAdminTableSessionUrl(session.session_no) })}>查看关联桌台</Button>}
  </View>
}
