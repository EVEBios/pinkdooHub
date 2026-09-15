import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useState } from 'react'
import { isAdminRole, useAuth } from '@/auth'
import type { FollowupItem, FollowupKind, FollowupPage } from '@/api/endpoints/reservation_followups'
import { AdminWorkbenchLink } from '@/admin/components/workbench_link'
import { getFollowupApi } from '@/admin/features/reservation-followup/runtime'
import { usePageVisibility } from '@/features/attention/hooks'
import { buildAdminReservationDetailUrl, formatShanghaiUtc } from '@/features/reservation'
import './index.scss'

export default function FollowupPageView() {
  const auth = useAuth()
  if (auth.status !== 'authenticated' || !isAdminRole(auth.user?.role)) return <View className='followup-page'><Text>请使用管理员账号查看预约跟进。</Text><AdminWorkbenchLink /></View>
  return <FollowupList key={`${auth.user?.id}:${auth.user?.role}`} />
}

export function FollowupList() {
  const { visible } = usePageVisibility()
  const [kind, setKind] = useState<FollowupKind>('contact')
  const [view, setView] = useState<'pending' | 'completed'>('pending')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<FollowupPage<FollowupItem>>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => { setData(undefined) }, [kind, view, page])
  useEffect(() => {
    if (!visible) return
    let cancelled = false
    let busy = false
    async function load() {
      if (busy) return
      busy = true; setLoading(true)
      try { const result = await getFollowupApi().list(kind, view, page); if (!cancelled) { setData(result); setError('') } }
      catch { if (!cancelled) setError('跟进列表加载失败，请重试。') }
      finally { busy = false; if (!cancelled) setLoading(false) }
    }
    void load()
    const timer = setInterval(() => void load(), 10_000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [kind, view, page, attempt, visible])
  return <View className='followup-page'>
    <View className='followup-page__header'><Text className='followup-page__title'>预约跟进</Text><Text className='followup-page__subtitle'>记录每次联系，让交接有据可查</Text><AdminWorkbenchLink /></View>
    <View className='followup-page__filters'>
      <View className='followup-page__row'>{(['contact', 'overdue'] as const).map((value) => <Button key={value} className={`followup-page__tab${kind === value ? ' followup-page__tab--active' : ''}`} ariaLabel={`${value === 'contact' ? '店休联系' : '过期跟进'}${kind === value ? '，已选中' : ''}`} onClick={() => { setKind(value); setPage(1) }}>{value === 'contact' ? '店休联系' : '过期跟进'}</Button>)}</View>
      <View className='followup-page__row'>{(['pending', 'completed'] as const).map((value) => <Button key={value} ariaLabel={`${value === 'pending' ? '待处理' : '已完成'}${view === value ? '，已选中' : ''}`} className={`followup-page__tab${view === value ? ' followup-page__tab--active' : ''}`} onClick={() => { setView(value); setPage(1) }}>{value === 'pending' ? '待处理' : '已完成'}</Button>)}</View>
      <Text className='followup-page__hint'>{kind === 'contact' ? '店休取消后需人工联系；顾客已读不会自动完成联系任务。' : '已过开始时间且未获确认的预约。跟进结果不改变原预约状态。'}</Text>
    </View>
    {error && <View className='followup-page__state'><Text>{error}{data ? ' 当前显示上次结果。' : ''}</Text><Button className='followup-page__button' onClick={() => setAttempt((v) => v + 1)}>重新加载</Button></View>}
    {!data && loading && <Text>正在读取跟进事项…</Text>}
    {data && <Text className='followup-page__hint'>共 {data.total} 条 · 按预约时间排列</Text>}
    {data?.items.map((item) => <Button key={item.reservation_id} className='followup-page__item' onClick={() => void Taro.navigateTo({ url: buildAdminReservationDetailUrl(item.reservation_id) })}>
      <View className='followup-page__item-top'><Text>{item.product_name ?? '到店预约'}</Text><Text className='followup-page__status'>{item.latest?.label ?? (kind === 'contact' ? '待联系' : '待跟进')}</Text></View>
      <Text className='followup-page__time'>{formatShanghaiUtc(item.scheduled_start_at)}</Text>
      <Text className='followup-page__hint'>{item.customer_name} · 预约 #{item.reservation_id}</Text>
      {item.latest && <Text className='followup-page__note'>{item.latest.note}</Text>}
      <Text className='followup-page__action'>{view === 'pending' ? '查看并跟进' : '查看处理记录'}</Text>
    </Button>)}
    {data?.items.length === 0 && <View className='followup-page__state'><Text>{view === 'pending' ? '暂无待处理事项' : '暂无已完成记录'}</Text><Text className='followup-page__hint'>{view === 'pending' ? '需要跟进的预约会显示在这里。' : '完成后的联系与处理记录会保留在这里。'}</Text></View>}
    {data && data.pages > 1 && <View className='followup-page__row'><Button className='followup-page__button' disabled={(loading || page === 1) || undefined} onClick={() => setPage((v) => v - 1)}>上一页</Button><Text>{page} / {data.pages}</Text><Button className='followup-page__button' disabled={(loading || page >= data.pages) || undefined} onClick={() => setPage((v) => v + 1)}>下一页</Button></View>}
  </View>
}
