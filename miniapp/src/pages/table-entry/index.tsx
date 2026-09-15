import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'

import type { EligibleOrder, TableSession } from '@/api/endpoints/table_sessions'
import { buildLoginUrl, isAdminRole, ORDER_LIST_PATH, useAuth } from '@/auth'
import {
  buildTableEntryUrl,
  parseTableEntryRoute,
  savePendingTableEntry,
  timerPhaseAt,
  timerPhaseLabel,
  useTableEntry,
} from '@/features/table_session'
import { AdminWorkbenchRedirect } from '@/navigation/admin_workbench_redirect'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function TableEntryPage() {
  const token = parseTableEntryRoute(useRouter().params)
  const auth = useAuth()
  if (!token) return <TableState title='二维码无效' description='请扫描门店桌台上的完整二维码' />
  if (isAdminRole(auth.user?.role)) return <AdminWorkbenchRedirect />
  if (auth.status === 'authenticated' && auth.user?.role !== 'user') {
    return <TableState title='当前账户不能开台' description='请使用普通顾客账号' />
  }
  return <TableEntryContent auth={auth} token={token} />
}

function TableEntryContent({ auth, token }: {
  readonly auth: ReturnType<typeof useAuth>
  readonly token: string
}) {
  const authenticated = auth.status === 'authenticated' && auth.user?.role === 'user'
  const entry = useTableEntry(token, authenticated)
  const clock = useServerClock(entry.state.session?.server_now)

  if (auth.status === 'initializing' || entry.state.status === 'loading') {
    return <TableState title='正在读取桌台…' description='桌号与占用状态以服务端为准' />
  }
  if (auth.status === 'error') {
    return <TableState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'} />
  }
  if (entry.state.status === 'error' || !entry.state.code) {
    return (
      <TableState title='桌台读取失败' description={entry.state.errorMessage ?? '请重新扫描二维码'}>
        <Button className='table-action' onClick={entry.refresh}>重新读取</Button>
      </TableState>
    )
  }
  const code = entry.state.code
  if (!code.is_enabled) return <TableState title={`${code.display_name} 暂停使用`} description='请联系店员更换桌台' />
  if (auth.status === 'guest') {
    return (
      <TableState title={code.display_name} description='登录后选择本人待支付体验订单，桌台会为你保留 15 分钟'>
        <Button
          className='table-action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(buildTableEntryUrl(token)) })}
        >登录并开台</Button>
      </TableState>
    )
  }
  if (!authenticated) return <TableState title='当前账户不能开台' description='请使用普通顾客账号' />

  return (
    <View className='table-page'>
      <View className='table-hero'>
        <Text className='table-hero__eyebrow'>TABLE SESSION</Text>
        <Text className='table-hero__title'>{entry.state.session?.table.display_name ?? code.display_name}</Text>
        <Text className='table-hero__subtitle'>付款成功后，各体验计时会从同一时刻开始</Text>
      </View>
      {entry.state.errorMessage && (
        <View className='table-alert' ariaRole='alert'><Text>{entry.state.errorMessage}</Text></View>
      )}
      {entry.state.session
        ? <SessionPanel session={entry.state.session} clock={clock} paying={entry.state.mutation === 'paying' || entry.state.mutation === 'unknown'} onPay={entry.pay} onRefresh={entry.refresh} />
        : <OrderSelection codeAvailable={code.is_available} orders={entry.state.orders} claiming={entry.state.mutation === 'claiming'} onClaim={entry.claim} token={token} />}
    </View>
  )
}

function OrderSelection({ claiming, codeAvailable, onClaim, orders, token }: {
  readonly claiming: boolean
  readonly codeAvailable: boolean
  readonly orders: readonly EligibleOrder[]
  readonly onClaim: (orderId: number) => Promise<boolean>
  readonly token: string
}) {
  if (!codeAvailable) return <TableState title='桌台正在使用中' description='请联系店员确认，或扫描其他空闲桌台' />
  return (
    <View className='table-section'>
      <Text className='table-section__title'>选择待支付订单</Text>
      <Text className='table-section__hint'>开台后保留 15 分钟；材料包不参与计时。</Text>
      {orders.length === 0 && (
        <View className='table-empty'>
          <Text>当前没有可开台的体验订单</Text>
          <Button onClick={() => void startOrderFlow(token)}>去商城创建订单</Button>
        </View>
      )}
      {orders.map((order) => (
        <View className='table-order' key={order.id}>
          <View className='table-order__heading'>
            <Text>{order.order_no}</Text><Text>¥{formatPrice(order.total_amount)}</Text>
          </View>
          <Text className='table-order__meta'>
            {order.duration_groups.map((group) => `${group.duration_minutes}+10 分钟 × ${group.total_quantity} 份`).join(' · ')}
          </Text>
          {order.kit_item_count > 0 && <Text className='table-order__kit'>同单含 {order.kit_item_count} 项材料包，不参与计时</Text>}
          <Button
            className='table-action'
            disabled={claiming}
            loading={claiming}
            onClick={() => void confirmClaim(order, onClaim)}
          >确认用此订单开台</Button>
        </View>
      ))}
    </View>
  )
}

async function startOrderFlow(token: string): Promise<void> {
  try {
    await savePendingTableEntry(token)
  } catch {
    await Taro.showToast({ title: '无法保存桌台，请创建订单后重新扫码', icon: 'none' })
  }
  await Taro.switchTab({ url: '/pages/index/index' })
}

async function confirmClaim(
  order: EligibleOrder,
  onClaim: (orderId: number) => Promise<boolean>,
): Promise<void> {
  const durations = order.duration_groups.map((group) => `${group.duration_minutes}+10 分钟`).join('、')
  const result = await Taro.showModal({
    title: '确认开台',
    content: `订单 ${order.order_no}\n计时 ${durations}\n桌台将先保留 15 分钟等待付款。`,
    confirmText: '确认开台',
  })
  if (result.confirm) await onClaim(order.id)
}

function SessionPanel({ clock, onPay, onRefresh, paying, session }: {
  readonly session: TableSession
  readonly clock: number
  readonly paying: boolean
  readonly onPay: () => Promise<boolean>
  readonly onRefresh: () => void
}) {
  if (session.status.value === 'awaiting_payment') {
    const seconds = remainingSeconds(session.payment_deadline_at, clock)
    return (
      <View className='table-section table-session'>
        <Text className='table-session__status'>等待付款</Text>
        <Text className='table-session__countdown'>{formatCountdown(seconds)}</Text>
        <Text className='table-session__meta'>订单 {session.order_no}</Text>
        <Text className='table-section__hint'>可使用会员余额付款，也可以让店员人工确认；到 0 后会向服务端确认状态。</Text>
        <Button className='table-action' disabled={paying || seconds === 0} loading={paying} onClick={() => void onPay()}>
          {paying ? '正在确认支付结果…' : '使用会员余额付款'}
        </Button>
        <Button className='table-action table-action--secondary' onClick={onRefresh}>刷新状态</Button>
      </View>
    )
  }
  if (session.status.value === 'closed') {
    return (
      <View className='table-section table-session'>
        <Text className='table-session__status'>本次开台已结束</Text>
        <Text className='table-section__hint'>{session.close_reason?.label ?? '桌台已释放'} · 订单仍按原状态继续处理</Text>
        <Button className='table-action' onClick={() => void Taro.switchTab({ url: ORDER_LIST_PATH })}>返回订单</Button>
      </View>
    )
  }
  const tableSeconds = session.table_release_at
    ? remainingSeconds(session.table_release_at, clock)
    : 0
  return (
    <View className='table-section table-session'>
      <Text className='table-session__status'>计时中</Text>
      <Text className='table-session__countdown'>{formatCountdown(tableSeconds)}</Text>
      <Text className='table-section__hint'>整桌最晚释放时间 · {formatLocalTime(session.table_release_at)}</Text>
      <View className='table-timers'>
        {session.timers.map((timer) => {
          const phase = timerPhaseAt(timer.service_ends_at, timer.grace_ends_at, clock)
          const target = phase === 'experience' ? timer.service_ends_at : timer.grace_ends_at
          const seconds = remainingSeconds(target, clock)
          return (
            <View className='table-timer' key={timer.id}>
              <View className='table-timer__heading'><Text>{timer.duration_minutes} 分钟体验</Text><Text>{timerPhaseLabel(phase)}</Text></View>
              <Text className='table-timer__countdown'>{formatCountdown(seconds)}</Text>
              {timer.experience_items.map((item) => <Text key={item.order_item_id}>{item.product_name} × {item.quantity}</Text>)}
            </View>
          )
        })}
      </View>
      <Button className='table-action table-action--secondary' onClick={onRefresh}>校准计时</Button>
    </View>
  )
}

function useServerClock(serverNow?: string): number {
  const [clientNow, setClientNow] = useState(Date.now())
  const anchorRef = useRef<{
    readonly value: string
    readonly serverTime: number
    readonly clientTime: number
  }>()
  if (serverNow && anchorRef.current?.value !== serverNow) {
    anchorRef.current = {
      value: serverNow,
      serverTime: Date.parse(serverNow),
      clientTime: clientNow,
    }
  }
  useEffect(() => {
    const timer = setInterval(() => setClientNow(Date.now()), 1_000)
    return () => clearInterval(timer)
  }, [])
  const anchor = anchorRef.current
  return anchor && serverNow
    ? anchor.serverTime + clientNow - anchor.clientTime
    : clientNow
}

export function remainingSeconds(target: string, estimatedServerNow: number): number {
  return Math.max(0, Math.ceil((Date.parse(target) - estimatedServerNow) / 1_000))
}

function formatCountdown(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  return [hours, minutes, seconds].map((value) => String(value).padStart(2, '0')).join(':')
}

function formatLocalTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : '等待服务端确认'
}

function TableState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return <View className='table-page table-page--state'><Text className='table-state__title'>{title}</Text><Text className='table-state__description'>{description}</Text>{children}</View>
}
