import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'
import { useAuth } from '@/auth'
import { formatShanghaiUtc } from '@/features/reservation/presentation'
import type { CommerceScope, CommerceSnapshot } from '@/api/endpoints/attention'
import { usePageVisibility } from './hooks'
import { attentionStore, getAttentionApi } from './runtime'

export const COMMERCE_ATTENTION_PAGE = '/pages/commerce-attention/index'
export const buildCommerceAttentionUrl = (scope: CommerceScope) => `${COMMERCE_ATTENTION_PAGE}?scope=${scope}`
export const buildSessionHistoryUrl = (sessionNo: string) => `/pages/table-history/index?sessionNo=${encodeURIComponent(sessionNo)}`
export const buildWalletResultUrl = (eventId: number) => `/pages/wallet-result/index?id=${eventId}`

/** 每条结果完整展示后确认明确事件；保留摘要，不因已读而闪退内容。 */
export function CommerceReceipt({ scope, target, revision, linkedSessionNo, onResult }: { readonly scope: CommerceScope; readonly target: number | string; readonly revision?: string; readonly linkedSessionNo?: string; readonly onResult?: () => void }) {
  const auth = useAuth()
  const { visible, visibleRef } = usePageVisibility()
  const identity = auth.status === 'authenticated' && auth.user?.role === 'user' ? `${auth.user.id}:${auth.user.role}` : undefined
  const key = `${identity}:${scope}:${target}`
  const resultHandler = useRef(onResult)
  resultHandler.current = onResult
  const seenResult = useRef('')
  const currentKey = useRef(key)
  currentKey.current = key
  const [data, setData] = useState<{ key: string; snapshot: CommerceSnapshot }>()
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const reading = useRef(false)
  const acknowledged = useRef<{ key: string; ids: Set<number> }>({ key, ids: new Set() })
  if (acknowledged.current.key !== key) acknowledged.current = { key, ids: new Set() }
  const readFailure = useRef<string>()
  const [readPending, setReadPending] = useState(false)
  const current = data?.key === key ? data.snapshot : undefined
  const unread = current?.events.filter((event) => !event.read).map((event) => event.id) ?? []
  const idsKey = unread.join(',')
  useEffect(() => {
    if (!identity || !visible) return
    let cancelled = false
    let fetching = false
    const load = async () => {
      if (fetching) return
      fetching = true
      try {
        const snapshot = await getAttentionApi().commerceSnapshot(scope, target)
        if (!cancelled && visibleRef.current && currentKey.current === key) {
          setData({ key, snapshot: { ...snapshot, events: snapshot.events.map((event) => acknowledged.current.ids.has(event.id) ? { ...event, read: true } : event) } }); setError(readFailure.current === key ? '已读状态未保存，首页提醒暂时保留，请重试' : '')
          const resultKey = `${key}:${snapshot.events.map((event) => event.id).join(',')}`
          if (snapshot.events.length && seenResult.current !== resultKey) { seenResult.current = resultKey; resultHandler.current?.() }
        }
      } catch {
        if (!cancelled && currentKey.current === key) setError(scope === 'wallet' ? '余额变动暂时无法读取，请重试；也可查看资金明细' : '结果提醒暂不可用，订单和桌台仍可正常操作')
      } finally { fetching = false }
    }
    void load()
    const timer = scope === 'orders' ? setInterval(() => void load(), 30_000) : undefined
    return () => { cancelled = true; if (timer) clearInterval(timer) }
  }, [identity, key, scope, target, revision, visible, visibleRef, attempt])
  useEffect(() => {
    if (!identity || !visible || !idsKey || error || reading.current || readFailure.current === key) return
    const ids = idsKey.split(',').map(Number).filter((id) => !acknowledged.current.ids.has(id))
    if (ids.length === 0) return
    reading.current = true
    setReadPending(true)
    void getAttentionApi().read(false, ids).then(() => {
      if (!visibleRef.current || currentKey.current !== key) return
      // 在 React 提交状态更新前先去重，避免后台刷新携带旧未读快照再次确认。
      ids.forEach((id) => acknowledged.current.ids.add(id))
      setData((value) => value?.key === key ? { key, snapshot: { ...value.snapshot, events: value.snapshot.events.map((event) => ids.includes(event.id) ? { ...event, read: true } : event) } } : value)
      attentionStore.invalidate(false)
    }).catch(() => {
      if (visibleRef.current && currentKey.current === key) {
        readFailure.current = key
        setError('已读状态未保存，首页提醒暂时保留，请重试')
      }
    }).finally(() => { reading.current = false; if (currentKey.current === key) setReadPending(false) })
  }, [error, identity, idsKey, key, readPending, visible, visibleRef])
  if (!identity) return null
  if (!current?.events.length && !error) return scope === 'wallet' ? <View className='attention-receipt'><Text>正在读取余额变动…</Text></View> : null
  return <View className='attention-receipt'>
    {current?.events.map((event, index, events) => <View key={event.id}>
      <Text className='attention-receipt__event'>{event.label}</Text>
      <Text className='attention-receipt__event'>{event.message}</Text>
      {event.wallet_transaction && <>
        <Text className='attention-receipt__event'>调整时间：{formatShanghaiUtc(event.occurred_at)}</Text>
        <Text className='attention-receipt__event'>流水编号：{event.wallet_transaction.id}</Text>
        <Text className='attention-receipt__event'>调整金额：{event.wallet_transaction.change_amount.startsWith('-') ? '' : '+'}{event.wallet_transaction.change_amount} 元</Text>
        <Text className='attention-receipt__event'>调整前余额：¥{event.wallet_transaction.before_balance}</Text>
        <Text className='attention-receipt__event'>调整后余额：¥{event.wallet_transaction.after_balance}（本笔发生时）</Text>
        <Text className='attention-receipt__event'>调整说明：{event.wallet_transaction.reason}</Text>
      </>}
      {scope === 'orders' && event.session_no && event.session_no !== linkedSessionNo &&
        !events.slice(0, index).some((previous) => previous.session_no === event.session_no) &&
        <Button className='attention-receipt__action' onClick={() => void Taro.navigateTo({ url: buildSessionHistoryUrl(event.session_no!) })}>查看这次桌台</Button>}
    </View>)}
    {error && <><Text>{error}</Text><Button className='attention-receipt__action' onClick={() => { readFailure.current = undefined; setError(''); setAttempt((value) => value + 1) }}>重试提醒</Button></>}
  </View>
}
