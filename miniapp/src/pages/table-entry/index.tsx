import { Button, Image, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'

import type { EligibleOrder, TableSession } from '@/api/endpoints/table_sessions'
import { buildLoginUrl, isAdminRole, ORDER_LIST_PATH, useAuth } from '@/auth'
import { getDefaultOrderApi } from '@/features/order/runtime'
import {
  buildTableEntryUrl,
  clearPendingTableEntry,
  parseTableCheckoutIntentId,
  parseTableEntryOrderId,
  parseTableEntryRoute,
  timerPhaseAt,
  timerPhaseLabel,
  useTableEntry,
} from '@/features/table_session'
import { shoppingTableStore } from '@/features/table_session/shopping_table'
import { getDefaultTableSessionApi } from '@/features/table_session/runtime'
import { AdminWorkbenchRedirect } from '@/navigation/admin_workbench_redirect'
import { formatPrice } from '@/utils/format'

import { CommerceReceipt } from '@/features/attention'

import './index.scss'
import { TableOrderCatalog } from './table_order_catalog'

export default function TableEntryPage() {
  const routeParams = useRouter().params
  const token = parseTableEntryRoute(routeParams)
  const focusedOrderId = parseTableEntryOrderId(routeParams)
  const focusedIntentId = focusedOrderId === undefined
    ? undefined
    : parseTableCheckoutIntentId(routeParams.table_intent)
  const auth = useAuth()
  if (!token) return <TableState status='无法识别' tone='danger' title='二维码无效' description='请扫描门店桌台上的完整二维码' />
  if (isAdminRole(auth.user?.role)) return <AdminWorkbenchRedirect />
  if (auth.status === 'authenticated' && auth.user?.role !== 'user') {
    return <TableState status='无法开台' tone='danger' title='当前账户不能开台' description='请使用普通顾客账号' />
  }
  return (
    <TableEntryContent
      auth={auth}
      focusedIntentId={focusedIntentId}
      focusedOrderId={focusedOrderId}
      token={token}
    />
  )
}

function TableEntryContent({ auth, focusedIntentId, focusedOrderId, token }: {
  readonly auth: ReturnType<typeof useAuth>
  readonly focusedIntentId?: string
  readonly focusedOrderId?: number
  readonly token: string
}) {
  const authenticated = auth.status === 'authenticated' && auth.user?.role === 'user'
  const entry = useTableEntry(token, authenticated)
  const clock = useServerClock(entry.state.session?.server_now)
  const [showFocusedOrder, setShowFocusedOrder] = useState(focusedOrderId !== undefined)
  const [focusedOrderFinished, setFocusedOrderFinished] = useState(false)

  if (auth.status === 'initializing' || entry.state.status === 'loading') {
    return <TableState status='读取中' tone='loading' title='正在读取桌台' description='桌号与占用状态以服务端为准' />
  }
  if (auth.status === 'error') {
    return <TableState status='暂不可用' tone='danger' title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'} />
  }
  if (entry.state.status === 'error' || !entry.state.code) {
    return (
      <TableState
        status='读取失败'
        tone='danger'
        title='桌台读取失败'
        description={getTableReadErrorDescription(entry.state.errorMessage)}
      >
        <Button className='table-action' onClick={entry.refresh}>重新读取</Button>
      </TableState>
    )
  }
  const code = entry.state.code
  if (!code.is_enabled) return <TableState heroTitle={code.display_name} status='暂停使用' tone='neutral' title='这张桌台暂不可用' description='请联系店员更换桌台' />
  if (auth.status === 'guest') {
    return (
      <TableState heroTitle={code.display_name} status='可开台' tone='success' title='登录后为本桌选体验' description='挑选商品并确认开台后进入支付，支付成功才会开始计时'>
        <Button
          className='table-action'
          onClick={() => void Taro.navigateTo({
            url: buildLoginUrl(buildTableEntryUrl(token, focusedOrderId, focusedIntentId)),
          })}
        >登录并开台</Button>
      </TableState>
    )
  }
  if (!authenticated) return <TableState status='无法开台' tone='danger' title='当前账户不能开台' description='请使用普通顾客账号' />
  if (!code.is_available && !entry.state.session) {
    return <TableState heroTitle={code.display_name} status='使用中' tone='warning' title='桌台正在使用中' description='请联系店员确认，或扫描其他空闲桌台' />
  }

  const sessionStatus = getSessionStatus(entry.state.session)
  const focusRequested = showFocusedOrder && focusedOrderId !== undefined
  const focusedOrder = focusRequested
    ? entry.state.orders.find((order) => order.id === focusedOrderId)
    : undefined
  const focusedOrderMissing = focusRequested && !focusedOrder
  const currentStep = entry.state.session
    ? entry.state.session.status.value === 'awaiting_payment' ? 2 : 3
    : focusRequested && !focusedOrderFinished ? 2 : 1
  const userId = auth.user!.id

  async function claimShoppingOrder(orderId: number): Promise<boolean> {
    const saved = await shoppingTableStore.load(userId).catch(() => undefined)
    const claimed = await entry.claim(orderId)
    if (claimed && saved?.selection?.tableNo === code.table_no) {
      await shoppingTableStore.consumeSelection(userId, saved.selection.selectionId)
        .catch(() => Taro.showToast({ title: '开台成功，选桌记录清理失败', icon: 'none' }))
    }
    return claimed
  }

  async function claimFocusedOrder(orderId: number): Promise<boolean> {
    const claimed = await claimShoppingOrder(orderId)
    if (claimed && focusedIntentId) {
      await clearPendingTableEntry({ intentId: focusedIntentId, token, userId })
        .catch(() => undefined)
    }
    return claimed
  }

  async function leaveMissingFocusedOrder(): Promise<void> {
    if (focusedIntentId) {
      await clearPendingTableEntry({ intentId: focusedIntentId, token, userId })
        .catch(() => undefined)
    }
    await Taro.navigateTo({ url: ORDER_LIST_PATH })
  }

  async function startAnotherTableOrder(): Promise<void> {
    if (focusedIntentId) {
      await clearPendingTableEntry({ intentId: focusedIntentId, token, userId })
        .catch(() => undefined)
    }
    setShowFocusedOrder(false)
    setFocusedOrderFinished(false)
    await Taro.redirectTo({ url: buildTableEntryUrl(token) }).catch(() => undefined)
  }

  return (
    <View className={`table-page${!entry.state.session && !focusRequested ? ' table-page--catalog' : ''}`}>
      <TableHero
        title={entry.state.session?.table.display_name ?? code.display_name}
        status={sessionStatus?.label ?? '可开台'}
        tone={sessionStatus?.tone ?? 'success'}
      />
      <TableJourney currentStep={currentStep} />
      <View className='table-content'>
        {entry.state.session && <CommerceReceipt scope='tables' target={entry.state.session.session_no} revision={`${entry.state.session.status.value}:${entry.state.session.close_reason?.value ?? ''}`} />}
        {entry.state.errorMessage && (
          <View className='table-alert' ariaRole='alert'><Text>{entry.state.errorMessage}</Text></View>
        )}
        {entry.state.session
          ? <SessionPanel session={entry.state.session} clock={clock} paying={entry.state.mutation === 'paying' || entry.state.mutation === 'unknown'} onPay={entry.pay} onRefresh={entry.refresh} />
          : focusedOrder
            ? (
              <OrderReadyPanel
                claiming={entry.state.mutation === 'claiming'}
                onClaim={claimFocusedOrder}
                onContinueShopping={() => setShowFocusedOrder(false)}
                order={focusedOrder}
              />
            )
            : focusedOrderMissing
              ? (
                <FocusedOrderMissingPanel
                  orderId={focusedOrderId!}
                  onFinished={setFocusedOrderFinished}
                  onRefresh={entry.refresh}
                  onStartAnother={() => void startAnotherTableOrder()}
                  onViewOrders={() => void leaveMissingFocusedOrder()}
                />
              )
            : (
              <TableOrderCatalog
                tableNo={code.table_no}
                claiming={entry.state.mutation === 'claiming'}
                orders={entry.state.orders}
                token={token}
                userId={userId}
                onSelectOrder={(order) => void confirmClaim(order, claimShoppingOrder)}
              />
            )}
      </View>
    </View>
  )
}

type MissingFocusedOrderStatus =
  | { readonly kind: 'checking' | 'unavailable' }
  | { readonly kind: 'finished'; readonly orderStatus: 'paid' | 'cancelled' | 'completed'; readonly sessionClosed: boolean }

function FocusedOrderMissingPanel({ onFinished, onRefresh, onStartAnother, onViewOrders, orderId }: {
  readonly orderId: number
  readonly onFinished: (finished: boolean) => void
  readonly onRefresh: () => void
  readonly onStartAnother: () => void
  readonly onViewOrders: () => void
}) {
  const [resolution, setResolution] = useState<MissingFocusedOrderStatus>({ kind: 'checking' })
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let active = true
    onFinished(false)
    void getDefaultOrderApi().getOrderDetail(orderId).then(async (order) => {
      if (order.status.value === 'pending') {
        if (active) setResolution({ kind: 'unavailable' })
        return
      }
      const session = order.status.value === 'paid' || order.status.value === 'completed'
        ? await getDefaultTableSessionApi().getOrderSession(orderId).catch(() => null)
        : null
      if (active) {
        onFinished(true)
        setResolution({
          kind: 'finished',
          orderStatus: order.status.value,
          sessionClosed: session?.status.value === 'closed',
        })
      }
    }).catch(() => {
      if (active) setResolution({ kind: 'unavailable' })
    })
    return () => { active = false }
  }, [onFinished, orderId, reloadKey])

  function refreshOrder(): void {
    setResolution({ kind: 'checking' })
    setReloadKey((value) => value + 1)
    onRefresh()
  }

  if (resolution.kind === 'finished') {
    const experienceEnded = resolution.sessionClosed
    const cancelled = resolution.orderStatus === 'cancelled'
    return (
      <View className='table-ready'>
        <Text className='table-ready__eyebrow'>{experienceEnded ? '上次体验已结束' : cancelled ? '订单已取消' : '订单已付款'}</Text>
        <Text className='table-ready__title'>{experienceEnded ? '这张桌台可以再次开台' : '这笔订单不能再次开台'}</Text>
        <Text className='table-ready__hint'>{experienceEnded
          ? '上一笔订单已付款，桌台计时也已结束。想再体验一次，请重新选择商品。'
          : cancelled
            ? '已取消的订单不能用于开台。请重新选择商品创建新订单。'
            : '已付款或已完成的订单不能重复绑定桌台。请重新选择商品，或到“我的订单”核对。'}</Text>
        <Button className='table-action' onClick={onStartAnother}>重新选择商品</Button>
        <Button className='table-action table-action--secondary' onClick={onViewOrders}>查看我的订单</Button>
      </View>
    )
  }

  return (
    <View className='table-ready' ariaRole='alert'>
      <Text className='table-ready__eyebrow'>正在核对订单</Text>
      <Text className='table-ready__title'>{resolution.kind === 'checking' ? '正在确认这笔订单' : '这笔订单暂时无法开台'}</Text>
      <Text className='table-ready__hint'>{resolution.kind === 'checking'
        ? '请稍候，正在读取订单的最新状态。'
        : '请先重新读取订单状态；若订单仍未出现，请前往“我的订单”核对，避免重复下单。'}</Text>
      <Button className='table-action' disabled={resolution.kind === 'checking'} onClick={refreshOrder}>重新读取</Button>
      <Button className='table-action table-action--secondary' onClick={onViewOrders}>查看我的订单</Button>
    </View>
  )
}

function OrderReadyPanel({ claiming, onClaim, onContinueShopping, order }: {
  readonly claiming: boolean
  readonly onClaim: (orderId: number) => Promise<boolean>
  readonly onContinueShopping: () => void
  readonly order: EligibleOrder
}) {
  return (
    <View className='table-ready'>
      <Text className='table-ready__eyebrow'>订单已创建</Text>
      <Text className='table-ready__title'>确认绑定本桌</Text>
      <Text className='table-ready__hint'>确认后桌台将为你保留 15 分钟；支付成功后，各体验会从同一时刻开始计时。</Text>
      <View className='table-order table-order--ready'>
        <View className='table-order__heading'>
          <View className='table-order__identity'>
            <Text className='table-order__label'>本次体验订单</Text>
            <Text className='table-order__number'>{order.order_no}</Text>
          </View>
          <Text className='table-order__price'>¥{formatPrice(order.total_amount)}</Text>
        </View>
        <View className='table-order__facts'>
          <View className='table-order__fact'>
            <Text className='table-order__fact-label'>体验计时</Text>
            <Text className='table-order__fact-value'>{formatDurationGroups(order)}</Text>
          </View>
          <View className='table-order__fact table-order__fact--deadline'>
            <Text className='table-order__fact-label'>付款时限</Text>
            <Text className='table-order__fact-value'>15 分钟</Text>
          </View>
        </View>
        <Text className='table-order__kit'>{order.kit_item_count > 0 ? `同单含 ${order.kit_item_count} 项材料包，不参与计时` : '材料包不参与计时'}</Text>
      </View>
      <Button
        className='table-action'
        disabled={claiming}
        loading={claiming}
        onClick={() => void confirmClaim(order, onClaim)}
      >确认开台并进入付款</Button>
      <Button
        className='table-action table-action--secondary'
        disabled={claiming}
        onClick={onContinueShopping}
      >继续挑选商品</Button>
    </View>
  )
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

function TableJourney({ currentStep }: { readonly currentStep: 1 | 2 | 3 }) {
  const steps = [
    { label: '选商品', value: 1 },
    { label: '支付', value: 2 },
    { label: '开始计时', value: 3 },
  ] as const
  return (
    <View className='table-journey'>
      <View className='table-journey__steps' ariaRole='list' ariaLabel='开台流程'>
        {steps.map((step) => (
          <View
            ariaRole='listitem'
            ariaLabel={`${step.label}${currentStep === step.value ? '，当前步骤' : currentStep > step.value ? '，已完成' : '，未开始'}`}
            className={`table-journey__step${currentStep === step.value ? ' table-journey__step--current' : ''}${currentStep > step.value ? ' table-journey__step--complete' : ''}`}
            key={step.value}
          >
            <Text className='table-journey__number'>{step.value}</Text>
            <Text className='table-journey__label'>{step.label}</Text>
          </View>
        ))}
      </View>
      <Text className='table-journey__hint'>计时将在支付成功后自动开始</Text>
    </View>
  )
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
        <Text className='table-session__eyebrow'>付款剩余时间</Text>
        <Text className='table-session__countdown'>{formatCountdown(seconds)}</Text>
        <View className='table-session__order'>
          <Text className='table-session__order-label'>当前订单</Text>
          <Text className='table-session__meta'>{session.order_no}</Text>
        </View>
        <Text className='table-section__hint'>使用会员余额付款后立即计时。若已在线下付钱，请让店员确认收款；确认后本页会自动显示计时，请勿重复付款。</Text>
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
        <Text className='table-session__status'>本次体验已结束</Text>
        <Text className='table-section__hint'>{session.close_reason?.label ?? '桌台已释放'} · 订单仍按原状态继续处理</Text>
        <Button className='table-action' onClick={() => void Taro.navigateTo({ url: ORDER_LIST_PATH })}>返回订单</Button>
      </View>
    )
  }
  const tableSeconds = session.table_release_at
    ? remainingSeconds(session.table_release_at, clock)
    : 0
  return (
    <View className='table-section table-session'>
      <Text className='table-session__eyebrow'>整桌剩余时间</Text>
      <Text className='table-session__countdown'>{formatCountdown(tableSeconds)}</Text>
      <Text className='table-section__hint'>整桌最晚释放时间 · {formatLocalTime(session.table_release_at)}</Text>
      <View className='table-timers'>
        {session.timers.map((timer) => {
          const phase = timerPhaseAt(timer.service_ends_at, timer.grace_ends_at, clock)
          const target = phase === 'experience' ? timer.service_ends_at : timer.grace_ends_at
          const seconds = remainingSeconds(target, clock)
          return (
            <View className='table-timer' key={timer.id}>
              <View className='table-timer__heading'><Text>{timer.duration_minutes} 分钟体验</Text><Text className='table-timer__phase'>{timerPhaseLabel(phase)}</Text></View>
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

function formatDurationGroups(order: EligibleOrder): string {
  return order.duration_groups
    .map((group) => `${group.duration_minutes}+10${group.total_quantity > 1 ? ` × ${group.total_quantity}` : ''}`)
    .join(' / ') + ' 分钟'
}

function getTableReadErrorDescription(message?: string): string {
  if (message && /[\u3400-\u9fff]/u.test(message)) return message
  return '没有找到对应桌台，请确认二维码来自门店并保持完整。'
}

type StatusTone = 'danger' | 'loading' | 'neutral' | 'success' | 'warning'

function getSessionStatus(session: TableSession | null): { readonly label: string; readonly tone: StatusTone } | null {
  if (!session) return null
  if (session.status.value === 'awaiting_payment') return { label: '待付款', tone: 'warning' }
  if (session.status.value === 'closed') return { label: '已结束', tone: 'neutral' }
  return { label: '计时中', tone: 'success' }
}

function TableHero({ status, title, tone }: {
  readonly status: string
  readonly title: string
  readonly tone: StatusTone
}) {
  return (
    <View className='table-hero'>
      <Text className='table-hero__eyebrow'>扫码开台</Text>
      <Button
        ariaLabel='返回商城首页'
        className='table-hero__home'
        onClick={() => void Taro.switchTab({ url: '/pages/index/index' })}
      >
        <Image className='table-hero__home-icon' mode='aspectFit' src='/assets/tab-bar/home-outline-white.png' />
        <Text className='table-hero__home-label'>返回商城首页</Text>
      </Button>
      <View className='table-hero__heading'>
        <Text className='table-hero__title'>{title}</Text>
        <View className={`table-status table-status--${tone}`}>
          <View className='table-status__dot' />
          <Text>{status}</Text>
        </View>
      </View>
    </View>
  )
}

function TableState({ children, description, heroTitle = '扫码开台', status, title, tone }: {
  readonly title: string
  readonly description: string
  readonly heroTitle?: string
  readonly status: string
  readonly tone: StatusTone
  readonly children?: React.ReactNode
}) {
  return (
    <View className='table-page table-page--state'>
      <TableHero title={heroTitle} status={status} tone={tone} />
      <View className={`table-state table-state--${tone}`}>
        <Text className='table-state__title'>{title}</Text>
        <Text className='table-state__description'>{description}</Text>
        {children}
      </View>
    </View>
  )
}
