import { Button, Image, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'
import type { AttentionSnapshot } from '@/api/endpoints/attention'
import type { Reservation } from '@/api/endpoints/reservations'
import { useAuth } from '@/auth'
import { attentionStore, getAttentionApi } from './runtime'
import { useAttentionSummary, usePageVisibility } from './hooks'
import './style.scss'
import { buildCommerceAttentionUrl } from './commerce'

export { CommerceReceipt, buildCommerceAttentionUrl, buildSessionHistoryUrl } from './commerce'

export { useAttentionSummary } from './hooks'
export const ATTENTION_PAGE = '/pages/attention/index'

export function AttentionBadge({ count }: { readonly count: number }) {
  return count > 0 ? <Text className='attention-badge'>{count > 99 ? '99+' : count}</Text> : null
}

export function CustomerAttention({ reservationsOnly = false, commerceOnly = false, appearance = 'default' }: {
  readonly reservationsOnly?: boolean
  readonly commerceOnly?: boolean
  readonly appearance?: 'default' | 'member'
}) {
  const { identity, summary, error, refresh } = useAttentionSummary()
  if (!identity) return null
  const permanentTables = appearance === 'member' && !reservationsOnly
  const reservationCount = summary?.reservation_unread ?? 0
  const orderCount = summary?.order_total ?? 0
  const tableCount = summary?.table_total ?? 0
  const walletCount = summary?.wallet_unread ?? 0
  if (!summary && !permanentTables) return error ? <View className='attention-feedback'><Text>{error}</Text><Button onClick={refresh}>刷新提醒</Button></View> : null
  return (
    <View className={`customer-attention customer-attention--${appearance}`}>
    {error && <View className='attention-feedback'><Text>{error}</Text><Button onClick={refresh}>刷新提醒</Button></View>}
    {!commerceOnly && reservationCount > 0 && <Button className='attention-entry' hoverClass={appearance === 'member' ? 'attention-entry--pressed' : 'button-hover'} ariaLabel={`我的预约，${reservationCount} 个新结果`} onClick={() => void Taro.navigateTo({ url: ATTENTION_PAGE })}>
      <CustomerAttentionContent appearance={appearance} title='我的预约' hint='有新结果可查看' count={reservationCount} icon='reservations-solid-white' />
    </Button>}
    {!reservationsOnly && orderCount > 0 && <Button className='attention-entry' hoverClass={appearance === 'member' ? 'attention-entry--pressed' : 'button-hover'} ariaLabel={`我的订单，${orderCount} 件待付款或新结果`} onClick={() => void Taro.navigateTo({ url: buildCommerceAttentionUrl('orders') })}>
      <CustomerAttentionContent appearance={appearance} title='我的订单' hint='待付款与新结果' count={orderCount} icon='document-currency-yen-white' />
    </Button>}
    {!reservationsOnly && (permanentTables || tableCount > 0) && <Button className='attention-entry' hoverClass={appearance === 'member' ? 'attention-entry--pressed' : 'button-hover'} ariaLabel={tableCount > 0 ? `我的桌台，${tableCount} 件待付款或新结果` : '我的桌台，查看进行中与历史桌台'} onClick={() => void Taro.navigateTo({ url: buildCommerceAttentionUrl('tables') })}>
      <CustomerAttentionContent appearance={appearance} title='我的桌台' hint={appearance === 'member' ? tableCount > 0 ? '查看待付款与桌台动态' : '查看进行中与历史桌台' : '付款、超时与结束结果'} count={tableCount} icon='table-two-chairs-white' />
    </Button>}
    {!reservationsOnly && walletCount > 0 && <Button className='attention-entry' hoverClass={appearance === 'member' ? 'attention-entry--pressed' : 'button-hover'} ariaLabel={`余额变动，${walletCount} 笔新调整`} onClick={() => void Taro.navigateTo({ url: buildCommerceAttentionUrl('wallet') })}>
      <CustomerAttentionContent appearance={appearance} title='余额变动' hint='查看门店调整金额与说明' count={walletCount} icon='document-currency-yen-white' />
    </Button>}
    </View>
  )
}

function CustomerAttentionContent({ appearance, title, hint, count, icon }: {
  readonly appearance: 'default' | 'member'
  readonly title: string
  readonly hint: string
  readonly count: number
  readonly icon: string
}) {
  if (appearance === 'default') return <><Text>{title}</Text><Text className='attention-entry__hint'>{hint}</Text><AttentionBadge count={count} /></>
  return <>
    <View className='attention-entry__icon-seat' aria-hidden='true'>
      <Image className='attention-entry__icon' src={`/assets/tab-bar/${icon}.png`} mode='aspectFit' />
    </View>
    <View className='attention-entry__copy'>
      <Text className='attention-entry__title'>{title}</Text>
      <Text className='attention-entry__hint'>{hint}</Text>
    </View>
    <View className='attention-entry__trailing'>
      <AttentionBadge count={count} />
      <Image className='attention-entry__chevron' src='/assets/tab-bar/chevron-right-white.png' mode='aspectFit' aria-hidden='true' />
    </View>
  </>
}

/** 必须与已经渲染的业务版本相同，才允许清除明确展示过的事件。 */
export function ReservationAttentionReceipt({ reservation, admin = false, refreshDetail }: {
  readonly reservation: Reservation; readonly admin?: boolean; readonly refreshDetail: () => void
}) {
  const auth = useAuth()
  const { visible, visibleRef } = usePageVisibility()
  const [snapshot, setSnapshot] = useState<AttentionSnapshot>()
  const [loadedIdentity, setLoadedIdentity] = useState<string>()
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [reading, setReading] = useState(false)
  const acknowledged = useRef(new Set<number>())
  const inFlight = useRef(false)
  const refreshRef = useRef(refreshDetail)
  refreshRef.current = refreshDetail
  const identity = auth.user ? `${auth.user.id}:${auth.user.role}` : undefined
  const scopeRef = useRef(identity)
  scopeRef.current = identity

  useEffect(() => {
    if (!visible || auth.status !== 'authenticated') return
    let cancelled = false
    let fetching = false
    const load = async () => {
      if (fetching) return
      fetching = true
      try {
        const next = await getAttentionApi().snapshot(admin, reservation.id)
        if (cancelled || !visibleRef.current || scopeRef.current !== identity) return
        if (next.reservation_updated_at !== reservation.updated_at) {
          setSnapshot(undefined)
          refreshRef.current()
          return
        }
        setLoadedIdentity(identity)
        setSnapshot(next)
        setError('')
      } catch {
        if (!cancelled && visibleRef.current) setError('提醒读取失败，预约内容仍可正常查看')
      } finally { fetching = false }
    }
    void load()
    const timer = setInterval(() => void load(), admin ? 10_000 : 30_000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [admin, attempt, auth.status, identity, reservation.id, reservation.updated_at, visible, visibleRef])

  const current = loadedIdentity === identity && snapshot?.reservation_id === reservation.id && snapshot.reservation_updated_at === reservation.updated_at ? snapshot : undefined
  const events = current?.events.filter((event) => !acknowledged.current.has(event.id)) ?? []
  const eventKey = events.map((event) => event.id).join(',')
  async function read(): Promise<void> {
    if (!visibleRef.current || inFlight.current || !events.length) return
    const ids = events.map((event) => event.id)
    inFlight.current = true
    setReading(true)
    try {
      await getAttentionApi().read(admin, ids)
      if (!visibleRef.current || scopeRef.current !== identity) return
      ids.forEach((id) => acknowledged.current.add(id))
      setSnapshot((value) => value ? { ...value, events: value.events.filter((event) => !ids.includes(event.id)) } : value)
      setError('')
      attentionStore.invalidate(admin)
    } catch {
      if (visibleRef.current && scopeRef.current === identity) setError('已读状态未保存，请重试；首页提醒暂时保留')
    } finally { inFlight.current = false; if (visibleRef.current) setReading(false) }
  }
  const readRef = useRef(read)
  readRef.current = read
  useEffect(() => {
    if (!admin && visible && eventKey && !error) void readRef.current()
  }, [admin, error, eventKey, visible])

  const overdue = current && reservation.status.value === 'pending' && Date.parse(reservation.scheduled_start_at) <= Date.parse(current.server_now)
  if (!events.length && !error && !overdue) return null
  return (
    <View className='attention-receipt'>
      {overdue && <Text>预约时间已到，尚未获门店确认。{admin ? '此预约已不能审核，后续处理请查看跟进记录。' : '请联系门店确认安排。'}</Text>}
      {events.map((event) => <Text className='attention-receipt__event' key={event.id}>{event.label}</Text>)}
      {error && <Text>{error}</Text>}
      {((admin && events.length > 0) || error) && <Button className='attention-receipt__action' disabled={reading} onClick={() => void (events.length ? read() : setAttempt((value) => value + 1))}>{reading ? '正在保存…' : admin && events.length ? '已知悉' : '重试提醒'}</Button>}
    </View>
  )
}
