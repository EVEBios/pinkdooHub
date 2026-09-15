import { attentionStore } from '@/features/attention/runtime'
import { Button, Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { AdminTableSession } from '@/api/endpoints/table_sessions'
import { isAdminRole, useAuth } from '@/auth'
import { createTableIntentKey, getDefaultTableSessionApi } from '@/features/table_session'
import { isWalletMutationUnknown } from '@/features/wallet'

import { confirmTablePayment, tableAdminError } from '@/features/table_session/admin_table_actions'
import { tableCountdown, useAdminTableClock } from '@/features/table_session/use_admin_table_clock'

import { usePageVisibility } from '@/features/attention/hooks'
import { tableTimeWarnings } from '@/features/table_session/admin_table_attention'

import './index.scss'

export default function AdminTableSessionDetailPage() {
  const auth = useAuth()
  const sessionNo = useRouter().params.session_no
  if (auth.status === 'initializing') return <DetailState title='正在确认管理权限' />
  if (!auth.user || !isAdminRole(auth.user.role)) return <DetailState title='无桌台管理权限' />
  if (!sessionNo || !/^TS[0-9A-HJKMNP-TV-Z]{26}$/.test(sessionNo)) return <DetailState title='会话地址无效' />
  return <AdminSessionContent key={`${auth.user.id}:${auth.user.role}:${sessionNo}`} sessionNo={sessionNo} />
}

function AdminSessionContent({ sessionNo }: { readonly sessionNo: string }) {
  const source = getDefaultTableSessionApi()
  const [session, setSession] = useState<AdminTableSession>()
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [releasing, setReleasing] = useState(false)
  const keyRef = useRef<string>()
  const releaseInFlightRef = useRef(false)
  const { visible, visibleRef } = usePageVisibility()
  const now = useAdminTableClock(session?.server_now, visible)
  const reading = useRef(false)
  const queued = useRef(false)
  const mounted = useRef(false)
  const loadRef = useRef<() => void>(() => undefined)
  const readSequence = useRef(0)
  const load = useCallback(() => {
    if (!mounted.current || !visibleRef.current) return
    if (reading.current) { queued.current = true; return }
    reading.current = true
    const sequence = ++readSequence.current
    void source.getAdminSession(sessionNo).then((result) => {
      if (mounted.current && visibleRef.current && sequence === readSequence.current) { setSession(result); setError('') }
    }).catch((cause: unknown) => {
      if (mounted.current && visibleRef.current && sequence === readSequence.current) setError(tableAdminError(cause))
    }).finally(() => {
      reading.current = false
      if (queued.current) { queued.current = false; loadRef.current() }
    })
  }, [sessionNo, source, visibleRef])
  loadRef.current = load
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; readSequence.current += 1 } }, [])
  useEffect(() => {
    if (!visible) return
    load()
    const timer = setInterval(() => { if (!reading.current) load() }, 10_000)
    return () => { clearInterval(timer); readSequence.current += 1 }
  }, [load, visible])

  async function confirmPayment(): Promise<void> {
    if (releaseInFlightRef.current) return
    releaseInFlightRef.current = true
    setReleasing(true)
    setError('')
    try {
      await confirmTablePayment(source, sessionNo)
      load()
    } catch (cause) {
      setError(tableAdminError(cause))
    } finally {
      releaseInFlightRef.current = false
      setReleasing(false)
    }
  }

  async function release(): Promise<void> {
    if (releaseInFlightRef.current || reason.trim().length === 0) return
    releaseInFlightRef.current = true
    keyRef.current ??= createTableIntentKey('release')
    setReleasing(true)
    setError('')
    try {
      const result = await source.releaseAdminSession(sessionNo, reason, keyRef.current)
      attentionStore.invalidate(true)
      keyRef.current = undefined
      readSequence.current += 1
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
        <Text>会话 {session.session_no}</Text>{session.source === 'direct' ? <Text>直接开台 · 无需顾客账号</Text> : <><Text>订单 {session.order_no}</Text><Text>顾客 {session.user_nickname}（#{session.user_id}）</Text></>}
        {session.opening_note && <Text>备注：{session.opening_note}</Text>}
        {session.opened_by_user_id && <Text>开台管理员 #{session.opened_by_user_id}</Text>}
        <Text>开台 {new Date(session.claimed_at).toLocaleString()}</Text>
        {session.table_release_at && <Text>最晚释放 {new Date(session.table_release_at).toLocaleString()}</Text>}
        {session.close_reason && <Text>关闭原因：{session.close_reason.label}</Text>}
      </View>
      {session.status.value === 'awaiting_payment' && <View className='admin-session-card'>
        {session.payment_deadline_at && <Text>付款等待剩余 {tableCountdown(session.payment_deadline_at, now)}</Text>}
        <Button className='admin-session-card__pay' disabled={(releasing) || undefined} loading={releasing} onClick={() => void confirmPayment()}>确认已收款并计时</Button>
      </View>}
      {session.timers.map((timer) => {
        const ended = session.status.value === 'closed' || now >= Date.parse(timer.grace_ends_at)
        const grace = now >= Date.parse(timer.service_ends_at)
        const warning = tableTimeWarnings(session.status.value, [timer], now)[0]
        return <View className={`admin-session-card${warning ? ' admin-session-card--warning' : ''}`} key={timer.id}>
          <Text>{timer.duration_minutes} 分钟体验 + 10 分钟缓冲</Text>
          <Text className='admin-session-card__countdown'>{ended ? session.status.value === 'closed' ? '已结束' : '本组时间已到' : `${grace ? '缓冲' : '体验'}剩余 ${tableCountdown(grace ? timer.grace_ends_at : timer.service_ends_at, now)}`}</Text>
          {warning && <Text className='admin-session-card__warning'>{warning.phase === 'soon' ? '即将到时，请提醒顾客安排收尾。' : '已进入缓冲，请关注本组收尾。'}</Text>}
          {(timer.experience_items ?? []).map((item) => <Text key={item.order_item_id}>{item.product_name} × {item.quantity}</Text>)}
        </View>
      })}
      {session.status.value === 'active' && session.table_release_at && now >= Date.parse(session.table_release_at) && <View className='admin-session-card'><Text>时间已到，正在确认释放状态。</Text><Button onClick={load}>刷新状态</Button></View>}
      {session.status.value !== 'closed' && <View className='admin-session-card'><Input maxlength={200} placeholder='填写结束使用的原因' value={reason} onInput={(event) => setReason(event.detail.value)} /><Button disabled={(releasing || !reason.trim()) || undefined} loading={releasing} onClick={() => void release()}>结束使用</Button></View>}
      {error && <View className='admin-session-error' ariaRole='alert'><Text>{error}</Text><Button onClick={() => void Taro.navigateBack()}>返回桌台列表</Button></View>}
    </View>
  )
}

function DetailState({ title }: { readonly title: string }) { return <View className='admin-session-page admin-session-page--state'><Text>{title}</Text></View> }
