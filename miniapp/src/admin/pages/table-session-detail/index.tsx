import { Button, Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'

import type { AdminTableSession } from '@/api/endpoints/table_sessions'
import { isAdminRole, useAuth } from '@/auth'
import { createTableIntentKey, getDefaultTableSessionApi } from '@/features/table_session'
import { isWalletMutationUnknown } from '@/features/wallet'

import './index.scss'

export default function AdminTableSessionDetailPage() {
  const auth = useAuth()
  const sessionNo = useRouter().params.session_no
  if (auth.status === 'initializing') return <DetailState title='正在确认管理权限' />
  if (!auth.user || !isAdminRole(auth.user.role)) return <DetailState title='无桌台管理权限' />
  if (!sessionNo || !/^TS[0-9A-HJKMNP-TV-Z]{26}$/.test(sessionNo)) return <DetailState title='会话地址无效' />
  return <AdminSessionContent sessionNo={sessionNo} />
}

function AdminSessionContent({ sessionNo }: { readonly sessionNo: string }) {
  const source = getDefaultTableSessionApi()
  const [session, setSession] = useState<AdminTableSession>()
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [releasing, setReleasing] = useState(false)
  const keyRef = useRef<string>()
  const releaseInFlightRef = useRef(false)
  useEffect(() => { void source.getAdminSession(sessionNo).then(setSession).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '会话读取失败')) }, [sessionNo, source])

  async function release(): Promise<void> {
    if (releaseInFlightRef.current || reason.trim().length === 0) return
    releaseInFlightRef.current = true
    keyRef.current ??= createTableIntentKey('release')
    setReleasing(true)
    setError('')
    try {
      const result = await source.releaseAdminSession(sessionNo, reason, keyRef.current)
      keyRef.current = undefined
      setSession(result)
    } catch (cause) {
      const releaseError = cause instanceof Error ? cause : new Error('桌台释放失败')
      const unknown = isWalletMutationUnknown(releaseError)
      if (!unknown) keyRef.current = undefined
      setError(unknown ? '释放结果可能未知，请重读会话；若仍未释放，可安全重试原操作' : releaseError.message)
    } finally {
      releaseInFlightRef.current = false
      setReleasing(false)
    }
  }

  if (!session) return <DetailState title={error || '正在读取桌台会话'} />
  return (
    <View className='admin-session-page'>
      <View className='admin-session-card'>
        <Text className='admin-session-card__title'>{session.table.display_name} · {session.status.label}</Text>
        <Text>会话 {session.session_no}</Text><Text>订单 {session.order_no}</Text><Text>顾客 {session.user_nickname}（#{session.user_id}）</Text>
        <Text>开台 {new Date(session.claimed_at).toLocaleString()}</Text>
        {session.table_release_at && <Text>最晚释放 {new Date(session.table_release_at).toLocaleString()}</Text>}
        {session.close_reason && <Text>关闭原因：{session.close_reason.label}</Text>}
      </View>
      {session.timers.map((timer) => <View className='admin-session-card' key={timer.id}><Text>{timer.duration_minutes}+10 分钟 · {timer.phase.label}</Text>{timer.experience_items.map((item) => <Text key={item.order_item_id}>{item.product_name} × {item.quantity}</Text>)}</View>)}
      {session.status.value !== 'closed' && <View className='admin-session-card'><Input maxlength={200} placeholder='填写应急释放原因' value={reason} onInput={(event) => setReason(event.detail.value)} /><Button disabled={releasing || !reason.trim()} loading={releasing} onClick={() => void release()}>应急释放桌台</Button></View>}
      {error && <View className='admin-session-error' ariaRole='alert'><Text>{error}</Text><Button onClick={() => void Taro.navigateBack()}>返回桌台列表</Button></View>}
    </View>
  )
}

function DetailState({ title }: { readonly title: string }) { return <View className='admin-session-page admin-session-page--state'><Text>{title}</Text></View> }
