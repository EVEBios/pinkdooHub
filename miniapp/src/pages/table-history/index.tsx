import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { buildLoginUrl, useAuth } from '@/auth'
import { CommerceReceipt } from '@/features/attention'
import { usePageVisibility } from '@/features/attention/hooks'
import { buildOrderDetailUrl } from '@/features/order'
import { formatShanghaiUtc } from '@/features/reservation'
import { SessionCountdowns } from './session_countdowns'
import { useHistorySession } from './use_history_session'
import '../attention/index.scss'
import './index.scss'

export default function TableHistoryPage() {
  const auth = useAuth()
  const sessionNo = useRouter().params.sessionNo
  if (auth.status !== 'authenticated' || !auth.user) return <View className='attention-page'><Text>登录后查看本次桌台</Text><Button className='attention-page__retry' onClick={() => void Taro.navigateTo({ url: buildLoginUrl() })}>去登录</Button></View>
  if (auth.user.role !== 'user' || !sessionNo || !/^TS[0-9A-HJKMNP-TV-Z]{26}$/.test(sessionNo)) return <View className='attention-page'><Text>桌台记录不可用，请从首页重新进入</Text></View>
  return <History key={`${auth.user.id}:${sessionNo}`} sessionNo={sessionNo} />
}

function History({ sessionNo }: { readonly sessionNo: string }) {
  const { visible } = usePageVisibility()
  const { snapshot, error, retry } = useHistorySession(sessionNo, visible)
  const session = snapshot?.session
  return <View className='attention-page'>
    <View className='attention-page__header'><Text className='attention-page__title'>{session?.table.display_name ?? '本次桌台'}</Text><Text className='attention-page__description'>查看本次开台状态与门店处理结果</Text></View>
    {error && <View className='attention-page__state'><Text>{error}</Text><Button className='attention-page__retry' onClick={retry}>重新加载</Button></View>}
    {!session && !error && <View className='attention-page__state'><Text>正在读取本次桌台…</Text></View>}
    {session && <>
      <View className='attention-page__filter-panel'><Text className='attention-page__state-title'>{session.status.label}</Text><Text className='attention-page__item-meta'>开台时间：{formatShanghaiUtc(session.claimed_at)}</Text>
        <Text className='attention-page__item-meta'>{session.close_reason?.label ?? (session.status.value === 'awaiting_payment' ? '核实到账后，门店确认收款并开始计时' : session.status.value === 'closed' ? '本次桌台已结束' : '按各体验项目分别计时，结束后进入缓冲时间')}</Text>
        {session.table_release_at && session.status.value === 'active' && <Text className='attention-page__item-meta'>整桌预计结束：{formatShanghaiUtc(session.table_release_at)}</Text>}
        {snapshot && <SessionCountdowns snapshot={snapshot} visible={visible} />}
      </View>
      <CommerceReceipt scope='tables' target={sessionNo} revision={`${session.status.value}:${session.close_reason?.value ?? ''}`} />
      <Button className='attention-page__all' onClick={() => void Taro.navigateTo({ url: buildOrderDetailUrl(session.order_id) })}>{session.status.value === 'awaiting_payment' ? '查看订单并付款' : '查看关联订单'}</Button>
    </>}
  </View>
}
