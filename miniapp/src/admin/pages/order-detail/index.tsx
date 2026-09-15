import { Button, Text, Textarea, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useRef, useState } from 'react'

import type { AdminOrderDetail } from '@/api/endpoints/orders'
import { buildLoginUrl, useAuth } from '@/auth'
import {
  ADMIN_ORDER_LIST_PATH,
  getTransitionAction,
  isAdminRole,
  parseAdminOrderDetailRoute,
  useAdminOrderDetail,
} from '@/features/order'
import {
  getPaymentMethodLabel,
  getPaymentStatusLabel,
  getRefundStatusLabel,
  useAdminRefund,
  useOrderFinancial,
} from '@/features/wallet'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function AdminOrderDetailPage() {
  const auth = useAuth()
  const route = parseAdminOrderDetailRoute(useRouter().params)
  if (!route) {
    return <AdminDetailState title='订单地址无效' description='请从管理订单列表重新进入' />
  }
  if (auth.status === 'initializing') {
    return <AdminDetailState title='正在确认管理员身份…' description='管理订单详情仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <AdminDetailState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='admin-detail-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </AdminDetailState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <AdminDetailState title='登录后查看管理订单' description='登录后返回管理订单列表再进入详情'>
        <Button
          className='admin-detail-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_ORDER_LIST_PATH) })}
        >去登录</Button>
      </AdminDetailState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <AdminDetailState title='无管理权限' description='当前账号不会请求任何管理端订单 API' />
  }
  return <AuthenticatedAdminOrderDetail orderId={route.orderId} />
}

export function AuthenticatedAdminOrderDetail({ orderId }: { readonly orderId: number }) {
  const { advanceStatus, detail, retry, transition } = useAdminOrderDetail(orderId)
  if (detail.status === 'loading') {
    return <AdminDetailState title='正在加载管理订单…' description='正在读取服务端订单快照' />
  }
  if (detail.status === 'error') {
    return (
      <AdminDetailState title='管理订单详情加载失败' description={detail.errorMessage}>
        <Button className='admin-detail-state__action' onClick={retry}>重新加载</Button>
        <Button onClick={() => void Taro.navigateTo({ url: ADMIN_ORDER_LIST_PATH })}>返回管理订单</Button>
      </AdminDetailState>
    )
  }

  return (
    <AdminOrderDetailContent
      advanceStatus={advanceStatus}
      order={detail.order}
      transition={transition}
    />
  )
}

type AdminOrderMutationIntent = 'transition' | 'refund'

function AdminOrderDetailContent({ advanceStatus, order, transition }: {
  readonly advanceStatus: ReturnType<typeof useAdminOrderDetail>['advanceStatus']
  readonly order: AdminOrderDetail
  readonly transition: ReturnType<typeof useAdminOrderDetail>['transition']
}) {
  const financial = useOrderFinancial(order.id, true)
  const refund = useAdminRefund(order.id)
  const activeIntentRef = useRef<AdminOrderMutationIntent>()
  const [activeIntent, setActiveIntent] = useState<AdminOrderMutationIntent>()
  const [confirmedRefundOrderId, setConfirmedRefundOrderId] = useState<number>()
  const action = getTransitionAction(order)
  const financialRecord = financial.state.status === 'content' ? financial.state.financial : undefined
  const hasRefund = financialRecord?.refund !== null && financialRecord?.refund !== undefined
  const refundSucceeded = confirmedRefundOrderId === order.id || refund.state.status === 'succeeded'
  const completionUnavailable = action === 'complete' && (hasRefund || refundSucceeded)
  const refundMayBeInFlight = refund.state.status === 'submitting' || refund.state.status === 'unknown'
  const completionFactsUnavailable = action === 'complete' && financial.state.status !== 'content'
  const transitionLocked = transition.status === 'submitting' || activeIntent !== undefined ||
    (action === 'complete' && (refundMayBeInFlight || completionFactsUnavailable))
  const transitionLocksRefund = transition.status === 'submitting' || transition.status === 'unknown' ||
    activeIntent !== undefined

  function acquireIntent(intent: AdminOrderMutationIntent): boolean {
    if (activeIntentRef.current !== undefined) return false
    activeIntentRef.current = intent
    setActiveIntent(intent)
    return true
  }

  function releaseIntent(intent: AdminOrderMutationIntent): void {
    if (activeIntentRef.current !== intent) return
    activeIntentRef.current = undefined
    setActiveIntent(undefined)
  }

  async function confirmTransition(): Promise<void> {
    if (!action || transitionLocked || !acquireIntent('transition')) return
    const markingPaid = action === 'mark_paid'
    try {
      const confirmation = await Taro.showModal({
        title: markingPaid ? '确认标记为已支付？' : '确认完成订单？',
        content: markingPaid
          ? '只能将待支付订单变更为已支付；此操作不改变库存。'
          : '只能将已支付订单变更为已完成；此操作不改变库存。',
        confirmText: markingPaid ? '标记已支付' : '确认完成',
        confirmColor: '#65487d',
      })
      if (confirmation.confirm) {
        await advanceStatus()
      }
    } finally {
      releaseIntent('transition')
    }
  }

  return (
    <View className='admin-order-detail-page'>
      <AdminOrderHeading order={order} />
      <View className='admin-order-detail-user'>
        <Text>下单用户：#{order.user_id} · {order.user_nickname}</Text>
      </View>
      <View className='admin-order-detail-list'>
        {order.items.map((item) => (
          <View className='admin-order-detail-item' key={item.id}>
            <Text className='admin-order-detail-item__name'>{item.product_name}</Text>
            {item.experience_option_id !== null && item.experience_option_id !== undefined && (
              <Text className='admin-order-detail-item__configuration'>
                {item.option_duration_minutes} 分钟 · {item.option_participants} 人 · {item.option_day_type?.label}
              </Text>
            )}
            <View className='admin-order-detail-item__summary'>
              <Text>¥{formatPrice(item.product_price)} × {item.quantity}</Text>
              <Text>小计 ¥{formatPrice(item.subtotal)}</Text>
            </View>
          </View>
        ))}
      </View>
      <View className='admin-order-detail-meta'>
        <Text>创建时间：{order.created_at}</Text>
        <Text>更新时间：{order.updated_at}</Text>
        {order.remark && <Text>备注：{order.remark}</Text>}
      </View>
      <AdminOrderFinancialPanel
        acquireIntent={acquireIntent}
        financial={financial}
        onRefundSucceeded={() => setConfirmedRefundOrderId(order.id)}
        order={order}
        refund={refund}
        releaseIntent={releaseIntent}
        transitionLocked={transitionLocksRefund}
      />
      <TransitionFeedback transition={transition} />
      {action && transition.status !== 'unknown' && !completionUnavailable && (
        <Button
          className='admin-order-detail-page__transition'
          disabled={transitionLocked}
          loading={transition.status === 'submitting'}
          onClick={() => void confirmTransition()}
        >
          {transition.status === 'submitting'
            ? '正在更新…'
            : action === 'mark_paid' ? '标记为已支付' : '完成订单'}
        </Button>
      )}
      {completionUnavailable && (
        <Text className='admin-order-detail-page__terminal'>资金记录已存在全额退款，不能再完成此订单。</Text>
      )}
      {!action && <Text className='admin-order-detail-page__terminal'>当前状态没有可执行的管理命令。</Text>}
      <Button onClick={() => void Taro.navigateTo({ url: ADMIN_ORDER_LIST_PATH })}>返回管理订单</Button>
    </View>
  )
}

type OrderFinancialFeature = ReturnType<typeof useOrderFinancial>
type AdminRefundFeature = ReturnType<typeof useAdminRefund>

function AdminOrderFinancialPanel({
  acquireIntent,
  financial,
  onRefundSucceeded,
  order,
  refund,
  releaseIntent,
  transitionLocked,
}: {
  readonly acquireIntent: (intent: AdminOrderMutationIntent) => boolean
  readonly financial: OrderFinancialFeature
  readonly onRefundSucceeded: () => void
  readonly order: AdminOrderDetail
  readonly refund: AdminRefundFeature
  readonly releaseIntent: (intent: AdminOrderMutationIntent) => void
  readonly transitionLocked: boolean
}) {
  const [reason, setReason] = useState('')

  if (financial.state.status === 'loading') {
    return <View className='admin-order-financial'><Text>正在读取资金状态…</Text></View>
  }
  if (financial.state.status === 'error') {
    return (
      <View className='admin-order-financial'>
        <Text className='admin-order-financial__error'>{financial.state.errorMessage}</Text>
        <Button className='admin-order-financial__retry' onClick={financial.retry}>重新加载资金状态</Button>
      </View>
    )
  }

  const record = financial.state.financial
  const canRefund = (order.status.value === 'paid' || order.status.value === 'completed') &&
    record.payment?.status === 'succeeded' && record.refund === null
  const reasonValid = reason.trim().length >= 1 && reason.trim().length <= 256
  const refundSettled = refund.state.status === 'succeeded'
  const intentLocked = transitionLocked || refund.state.status === 'submitting' ||
    refund.state.status === 'unknown' || refundSettled

  async function confirmRefund(): Promise<void> {
    if (transitionLocked || refund.state.status === 'submitting' || refundSettled ||
      !canRefund || !reasonValid || !record.payment || !acquireIntent('refund')) return
    try {
      const confirmation = await Taro.showModal({
        title: '确认全额退款？',
        content: `订单 ${order.order_no}\n退款 ¥${formatPrice(record.payment.amount)}\n原路：${getPaymentMethodLabel(record.payment.method)}\n原因：${reason.trim()}\n是否恢复库存以服务端退款结果为准。`,
        confirmText: '确认退款',
        confirmColor: '#b42318',
      })
      if (!confirmation.confirm) return
      if (await refund.submit(reason.trim())) {
        onRefundSucceeded()
        financial.retry()
      }
    } finally {
      releaseIntent('refund')
    }
  }

  return (
    <View className='admin-order-financial'>
      <View className='admin-order-financial__heading'>
        <Text className='admin-order-financial__title'>资金状态</Text>
        <Text className='admin-order-financial__order-state'>{record.order_status.label}</Text>
      </View>
      {record.payment ? (
        <View className='admin-order-financial__record'>
          <Text>收款方式</Text>
          <Text>{getPaymentMethodLabel(record.payment.method)}</Text>
          <Text>收款状态</Text>
          <Text>{getPaymentStatusLabel(record.payment.status)}</Text>
          <Text>收款金额</Text>
          <Text>¥{formatPrice(record.payment.amount)}</Text>
          <Text>支付单号</Text>
          <Text>{record.payment.payment_no}</Text>
        </View>
      ) : <Text className='admin-order-financial__empty'>暂无支付记录</Text>}
      {record.refund && (
        <View className='admin-order-financial__refund-record'>
          <Text>{getRefundStatusLabel(record.refund.status)} · ¥{formatPrice(record.refund.amount)}</Text>
          <Text>退款单号：{record.refund.refund_no}</Text>
          <Text>原因：{record.refund.reason}</Text>
          <Text>{record.refund.inventory_restored ? '库存已恢复' : '本次无需恢复库存'}</Text>
        </View>
      )}
      {canRefund && (
        <View className='admin-order-financial__refund-form'>
          <Text className='admin-order-financial__label'>全额退款原因</Text>
          <Textarea
            className='admin-order-financial__reason'
            maxlength={256}
            disabled={intentLocked}
            placeholder='必填，1–256 个字符；将写入退款与审计记录'
            value={reason}
            onInput={(event) => setReason(event.detail.value)}
          />
          {(refund.state.status === 'failed' || refund.state.status === 'unknown') && (
            <Text className={`admin-order-financial__error admin-order-financial__error--${refund.state.status}`}>
              {refund.state.errorMessage}
            </Text>
          )}
          {refund.state.status === 'succeeded' && <Text className='admin-order-financial__success'>全额退款已提交。</Text>}
          <Button
            className='admin-order-financial__refund'
            disabled={!reasonValid || transitionLocked || refund.state.status === 'submitting' || refundSettled}
            loading={refund.state.status === 'submitting'}
            onClick={() => void confirmRefund()}
          >{refund.state.status === 'submitting'
              ? '正在退款…'
              : refund.state.status === 'unknown'
                ? '重试同一笔退款'
                : `全额退款 ¥${formatPrice(record.payment?.amount ?? order.total_amount)}`}</Button>
        </View>
      )}
      {!canRefund && !record.refund && (
        <Text className='admin-order-financial__hint'>只有 PAID / COMPLETED 且资金已结算、未退款的订单可全额退款。</Text>
      )}
    </View>
  )
}

function AdminOrderHeading({ order }: { readonly order: AdminOrderDetail }) {
  return (
    <View className='admin-order-detail-heading'>
      <Text className='admin-order-detail-heading__title'>管理订单详情</Text>
      <Text className='admin-order-detail-heading__number'>{order.order_no}</Text>
      <Text className='admin-order-detail-heading__status'>{order.status.label}</Text>
      <Text className='admin-order-detail-heading__total'>¥{formatPrice(order.total_amount)}</Text>
    </View>
  )
}

function TransitionFeedback({ transition }: {
  readonly transition: ReturnType<typeof useAdminOrderDetail>['transition']
}) {
  if (transition.status === 'failed' || transition.status === 'unknown') {
    return <Text className={`admin-transition-feedback admin-transition-feedback--${transition.status}`}>{transition.errorMessage}</Text>
  }
  if (transition.status === 'succeeded') {
    return (
      <View className='admin-transition-feedback admin-transition-feedback--success'>
        <Text>{transition.action === 'mark_paid' ? '订单已标记为已支付' : '订单已完成'}</Text>
        {transition.refreshErrorMessage && <Text>{transition.refreshErrorMessage}</Text>}
      </View>
    )
  }
  return null
}

function AdminDetailState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='admin-detail-state'>
      <Text className='admin-detail-state__title'>{title}</Text>
      <Text className='admin-detail-state__description'>{description}</Text>
      {children}
    </View>
  )
}
