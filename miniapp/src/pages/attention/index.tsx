import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'
import type { AttentionPage, AttentionView } from '@/api/endpoints/attention'
import { AdminWorkbenchLink } from '@/admin/components/workbench_link'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import { AttentionBadge, useAttentionSummary } from '@/features/attention'
import { getAttentionApi } from '@/features/attention/runtime'
import { usePageVisibility } from '@/features/attention/hooks'
import { buildAdminReservationDetailUrl, buildReservationDetailUrl, formatShanghaiUtc, reservationStatusLabel, reservationMessage, RESERVATION_LIST_PATH, ADMIN_RESERVATION_LIST_PATH } from '@/features/reservation'
import './index.scss'

export default function AttentionPageView() {
  const auth = useAuth()
  if (auth.status !== 'authenticated' || !auth.user) {
    return <View className='attention-page'><Text>登录后查看预约提醒</Text><Button onClick={() => void Taro.navigateTo({ url: buildLoginUrl() })}>去登录</Button></View>
  }
  return <ReservationAttentionList key={`${auth.user.id}:${auth.user.role}`} admin={isAdminRole(auth.user.role)} />
}

export function ReservationAttentionList({ admin }: { readonly admin: boolean }) {
  const { summary, refresh } = useAttentionSummary()
  const { visible } = usePageVisibility()
  const [view, setView] = useState<AttentionView>(admin ? 'actionable' : 'unread')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<AttentionPage>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const selected = useRef(false)
  useEffect(() => {
    if (!admin || !summary || selected.current) return
    selected.current = true
    if (summary.reservation_actionable === 0) {
      if (summary.reservation_unread > 0) setView('unread')
      else if (summary.reservation_overdue > 0) setView('overdue')
    }
  }, [admin, summary])
  useEffect(() => {
    if (!visible) return
    let cancelled = false
    setLoading(true)
    setData(undefined)
    void getAttentionApi().list(admin, view, page).then((result) => {
      if (cancelled) return
      setData(result)
      setError('')
    }).catch(() => { if (!cancelled) setError('预约提醒加载失败，请重试') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [admin, attempt, page, summary?.server_now, view, visible])

  const tabs: { value: AttentionView; label: string; count?: number }[] = admin ? [
    { value: 'actionable', label: '待审核', count: summary?.reservation_actionable },
    { value: 'unread', label: '取消变更', count: summary?.reservation_unread },
    { value: 'overdue', label: '已过期', count: summary?.reservation_overdue },
  ] : [{ value: 'unread', label: '新结果', count: summary?.reservation_unread }]
  return (
    <View className='attention-page'>
      <View className='attention-page__header'>
        <Text className='attention-page__title'>{admin ? '预约待办' : '预约新结果'}</Text>
        <Text className='attention-page__description'>{admin ? '及时回应预约，安排好每一次到店' : '门店的最新回复，都在这里'}</Text>
        {admin && <AdminWorkbenchLink />}
      </View>
      <View className='attention-page__filter-panel'>
        <View className='attention-page__filters' ariaRole='tablist'>
          {tabs.map((tab) => <Button key={tab.value} ariaLabel={`${tab.label}，${tab.count ?? '正在加载'} 条${view === tab.value ? '，已选中' : ''}`} className={`attention-page__filter${view === tab.value ? ' attention-page__filter--selected' : ''}`} onClick={() => { selected.current = true; setView(tab.value); setPage(1) }}>
            <Text>{tab.label}</Text>{tab.count !== undefined && <Text className='attention-page__filter-count'>{tab.count}</Text>}
          </Button>)}
        </View>
        <Text className='attention-page__filter-hint'>{view === 'actionable' ? '开始前确认或拒绝，顾客会收到处理结果。' : view === 'overdue' ? '过期记录保留在这里；待跟进和已完成请进入“预约跟进”查看。' : admin ? '顾客取消了已确认的预约，查看后请点击“已知悉”。' : '查看预约详情后，对应的未读提醒会消除。'}</Text>
      </View>
      {loading && !data && <View className='attention-page__state'><Text>正在读取预约…</Text></View>}
      {error && <View className='attention-page__state'><Text className='attention-page__state-title'>暂时无法读取预约</Text><Text>{error}</Text><Button className='attention-page__retry' onClick={() => { setAttempt((value) => value + 1); refresh() }}>重新加载</Button></View>}
      {!loading && !error && data?.items.length === 0 && <View className='attention-page__state'>
        <Text className='attention-page__state-title'>{view === 'actionable' ? '暂时没有待审核预约' : view === 'overdue' ? '没有过期未处理的预约' : '没有新的预约变更'}</Text>
        <Text className='attention-page__state-description'>{view === 'actionable' ? '新的到店预约会显示在这里。' : view === 'overdue' ? '待确认预约都还在可处理时间内。' : '后续有新消息时，这里会提醒你。'}</Text>
        {admin && view === 'actionable' && !!summary?.reservation_overdue && <Button className='attention-page__retry' onClick={() => { selected.current = true; setView('overdue'); setPage(1) }}>查看 {summary.reservation_overdue} 条过期预约</Button>}
      </View>}
      {!!data?.items.length && <View className='attention-page__list-heading'><Text>{tabs.find((tab) => tab.value === view)?.label}</Text><Text>共 {data.total} 条</Text></View>}
      {data?.items.map((item) => <Button className='attention-page__item' key={item.id} onClick={() => void Taro.navigateTo({ url: admin ? buildAdminReservationDetailUrl(item.id) : buildReservationDetailUrl(item.id) })}>
        <View className='attention-page__item-heading'><Text>{item.product_name ?? '到店预约'}</Text>{view === 'unread' ? <AttentionBadge count={1} /> : <Text className={`attention-page__status${view === 'overdue' ? ' attention-page__status--overdue' : ''}`}>{reservationStatusLabel(item, Date.parse(summary?.server_now ?? '') || Date.now())}</Text>}</View>
        <Text className='attention-page__item-time'>{formatShanghaiUtc(item.scheduled_start_at)}</Text>
        <Text className='attention-page__item-message'>{view === 'overdue' ? '未在开始前确认，可查看预约详情及门店跟进记录。' : reservationMessage(item, Date.parse(summary?.server_now ?? '') || Date.now())}</Text>
        <View className='attention-page__item-footer'><Text>预约 #{item.id}</Text><Text className='attention-page__item-action'>{view === 'actionable' ? '查看并处理' : '查看详情'}</Text></View>
      </Button>)}
      {data && data.pages > 1 && <View className='attention-page__pagination'>
        <Button disabled={page <= 1 || loading} onClick={() => setPage((value) => value - 1)}>上一页</Button>
        <Text>{page} / {data.pages}</Text>
        <Button disabled={page >= data.pages || loading} onClick={() => setPage((value) => value + 1)}>下一页</Button>
      </View>}
      {admin && <Button className='attention-page__all' onClick={() => void Taro.navigateTo({ url: '/admin/pages/reservation-followups/index' })}>店休联系与过期跟进</Button>}
      <Button className='attention-page__all' onClick={() => void (admin ? Taro.navigateTo({ url: ADMIN_RESERVATION_LIST_PATH }) : Taro.switchTab({ url: RESERVATION_LIST_PATH }))}>查看全部预约</Button>
    </View>
  )
}
