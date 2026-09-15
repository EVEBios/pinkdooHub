import { formatShanghaiUtc } from '@/features/reservation'
import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useEffect, useState } from 'react'
import { AdminWorkbenchLink } from '@/admin/components/workbench_link'
import { ADMIN_TABLES_PATH, buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import type { CommercePage, CommerceScope, CommerceView } from '@/api/endpoints/attention'
import { AttentionBadge, buildSessionHistoryUrl, useAttentionSummary } from '@/features/attention'
import { usePageVisibility } from '@/features/attention/hooks'
import { getAttentionApi } from '@/features/attention/runtime'
import { buildWalletResultUrl } from '@/features/attention/commerce'
import { buildAdminOrderDetailUrl, buildOrderDetailUrl, ADMIN_ORDER_LIST_PATH } from '@/features/order'
import { buildAdminTableSessionUrl } from '@/features/table_session'
import '../attention/index.scss'

export default function CommerceAttentionPage() {
  const auth = useAuth()
  const scope = useRouter().params.scope
  if (auth.status !== 'authenticated' || !auth.user) return <View className='attention-page'><Text>登录后查看提醒</Text><Button className='attention-page__retry' onClick={() => void Taro.navigateTo({ url: buildLoginUrl() })}>去登录</Button></View>
  if ((scope !== 'orders' && scope !== 'tables' && scope !== 'wallet') || (scope === 'wallet' && auth.user.role !== 'user')) return <View className='attention-page'><Text>提醒入口无效，请从首页重新进入</Text></View>
  return <CommerceList key={`${auth.user.id}:${auth.user.role}:${scope}`} scope={scope} admin={isAdminRole(auth.user.role)} />
}

export function CommerceList({ scope, admin }: { readonly scope: CommerceScope; readonly admin: boolean }) {
  const myTables = !admin && scope === 'tables'
  const wallet = scope === 'wallet'
  const { summary, refresh, error: summaryError } = useAttentionSummary()
  const { visible } = usePageVisibility()
  const [view, setView] = useState<CommerceView>(wallet ? 'unread' : admin && scope === 'tables' ? 'pending' : 'all')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<CommercePage>()
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!visible) return
    let cancelled = false
    setData(undefined)
    setError('')
    const request = myTables && view === 'all' ? getAttentionApi().myTableSessions(page) : getAttentionApi().commerceList(admin, scope, view, page)
    void request.then((value) => { if (!cancelled) setData(value) }).catch(() => { if (!cancelled) setError('提醒加载失败，请重试') })
    return () => { cancelled = true }
  }, [admin, scope, view, page, visible, attempt, summary?.server_now, myTables])
  const tabs: { value: CommerceView; label: string }[] = admin && scope === 'tables' ? [{ value: 'pending', label: '待付款' }] : [{ value: 'all', label: myTables ? '全部桌台' : '全部事项' }, { value: 'pending', label: '待付款' }]
  if (wallet) tabs.splice(0, tabs.length, { value: 'all', label: '全部调整' })
  if (admin && scope === 'orders') tabs.push({ value: 'fulfillment', label: '待履约' })
  if (!admin) tabs.push({ value: 'unread', label: '新结果' })
  return <View className='attention-page'>
    <View className='attention-page__header'><Text className='attention-page__title'>{wallet ? '余额变动' : scope === 'orders' ? '订单提醒' : myTables ? '我的桌台' : '桌台提醒'}</Text>
      <Text className='attention-page__description'>{wallet ? '逐笔核对门店的余额调整' : admin ? scope === 'orders' ? '核实收款，跟进每一笔订单服务' : '核实到账后确认，顾客无需再次提交申请' : myTables ? '查看进行中的桌台，随时回看开台记录' : '待付款和门店的新结果，都在这里'}</Text>
      {admin && <AdminWorkbenchLink />}
    </View>
    <View className='attention-page__filter-panel'><View className='attention-page__filters'>
      {tabs.map((tab) => <Button key={tab.value} className={`attention-page__filter${view === tab.value ? ' attention-page__filter--selected' : ''}`} onClick={() => { setView(tab.value); setPage(1) }}>{tab.label}</Button>)}
    </View><Text className='attention-page__filter-hint'>{wallet ? '查看列表不会清除提醒。订单扣款与退款结果请在“我的订单”查看。' : scope === 'orders' ? '仍在付款时限内的占台订单，统一在桌台提醒中处理。' : myTables ? '每次开台独立保留；付款完成或结果已读后仍可查看。' : '按每次桌台计数；超时只释放桌台，订单仍需处理。'}</Text></View>
    {summaryError && <View className='attention-feedback'><Text>{summaryError}</Text><Button onClick={refresh}>刷新提醒</Button></View>}
    {error ? <View className='attention-page__state'><Text>{error}</Text><Button className='attention-page__retry' onClick={() => { setAttempt((value) => value + 1); refresh() }}>重新加载</Button></View> : !data ? <View className='attention-page__state'><Text>正在读取提醒…</Text></View> : data.items.length === 0 ? <View className='attention-page__state'><Text className='attention-page__state-title'>{myTables && view === 'all' ? '还没有开台记录' : '当前没有这类事项'}</Text><Text>{myTables && view === 'all' ? '扫码开台或下单时选择桌台后，可在这里查看。' : '后续有待处理事项或新结果时，会在这里提醒。'}</Text></View> : <>
      <View className='attention-page__list-heading'><Text>{tabs.find((tab) => tab.value === view)?.label}</Text><Text>共 {data.total} 件</Text></View>
      {data.items.map((item) => <Button key={item.id} className='attention-page__item' onClick={() => void Taro.navigateTo({ url: item.scope === 'wallet' ? buildWalletResultUrl(item.id) : item.scope === 'orders' ? admin ? buildAdminOrderDetailUrl(item.order_id!) : buildOrderDetailUrl(item.order_id!) : admin ? buildAdminTableSessionUrl(item.session_no!) : buildSessionHistoryUrl(item.session_no!) })}>
        <View className='attention-page__item-heading'><Text>{item.title}</Text>{item.unread ? <AttentionBadge count={1} /> : <Text className='attention-page__status'>{item.status_label}</Text>}</View>
        <Text className='attention-page__item-meta'>{item.scope === 'orders' ? item.reference : `${wallet ? '余额调整' : '开台记录'} · ${formatShanghaiUtc(item.created_at)}`}</Text>{item.unread && <Text className='attention-page__item-meta'>{item.status_label} · 有新结果</Text>}
        <Text className='attention-page__item-meta'>{admin ? '查看并处理' : '查看详情'}</Text>
      </Button>)}
      {data.pages > 1 && <View className='attention-page__pagination'><Button disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</Button><Text>{page} / {data.pages}</Text><Button disabled={page >= data.pages} onClick={() => setPage(page + 1)}>下一页</Button></View>}
    </>}
    {admin && <Button className='attention-page__all' onClick={() => void Taro.navigateTo({ url: scope === 'orders' ? ADMIN_ORDER_LIST_PATH : ADMIN_TABLES_PATH })}>{scope === 'orders' ? '查看全部订单' : '进入桌台工作台'}</Button>}
  </View>
}
