import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'

import type { OrderDetail } from '@/api/endpoints/orders'
import {
  buildLoginUrl,
  type AuthContextValue,
  isAdminRole,
  ORDER_LIST_PATH,
  useAuth,
} from '@/auth'
import { parseOrderDetailRoute, useOrderDetail } from '@/features/order'
import {
  getPaymentMethodLabel,
  getPaymentStatusLabel,
  moneyToCents,
  useMemberWallet,
  useOrderFinancial,
  useOrderPayment,
} from '@/features/wallet'
import { AdminWorkbenchRedirect } from '@/navigation/admin_workbench_redirect'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function OrderDetailPage() {
  const auth = useAuth()
  if (auth.status === 'authenticated') {
    if (!auth.user) {
      return (
        <DetailState title='账户信息不完整' description='请重新检查登录状态后再查看订单'>
          <Button className='order-detail-state__action' onClick={auth.retryInitialization}>重新检查</Button>
        </DetailState>
      )
    }
    if (isAdminRole(auth.user.role)) {
      return <AdminWorkbenchRedirect />
    }
    if (auth.user.role !== 'user') {
      return (
        <DetailState title='账户角色暂不支持' description='请重新检查登录状态后再查看订单'>
          <Button className='order-detail-state__action' onClick={auth.retryInitialization}>重新检查</Button>
        </DetailState>
      )
    }
  }

  return <CustomerOrderDetailPage auth={auth} />
}

function CustomerOrderDetailPage({ auth }: { readonly auth: AuthContextValue }) {
  const route = parseOrderDetailRoute(useRouter().params)
  if (!route) {
    return <DetailState title='订单地址无效' description='请从“我的订单”重新进入' />
  }
  if (auth.status === 'initializing') {
    return <DetailState title='正在确认登录状态…' description='订单详情只对所属用户可见' />
  }
  if (auth.status === 'error') {
    return (
      <DetailState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='order-detail-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </DetailState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <DetailState title='登录后查看订单' description='登录后返回我的订单列表，再进入详情'>
        <Button
          className='order-detail-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ORDER_LIST_PATH) })}
        >
          去登录
        </Button>
      </DetailState>
    )
  }
  return <AuthenticatedOrderDetail orderId={route.orderId} />
}

export function AuthenticatedOrderDetail({ orderId }: { readonly orderId: number }) {
  const { cancel, cancellation, detail, retry } = useOrderDetail(orderId)
  const financial = useOrderFinancial(orderId)
  const payment = useOrderPayment(orderId)
  const resetPayment = payment.reset
  const [reconcilingPayment, setReconcilingPayment] = useState(false)
  const activeMutationRef = useRef<'cancel' | 'payment'>()
  const [activeMutation, setActiveMutation] = useState<'cancel' | 'payment'>()
  const paymentReconciliationConverged = reconcilingPayment &&
    detail.status === 'content' && financial.state.status === 'content' &&
    financial.state.financial.order_id === detail.order.id &&
    financial.state.financial.order_status.value === detail.order.status.value &&
    (detail.order.status.value !== 'pending' || financial.state.financial.payment === null)
  const paymentRecheckInFlight = reconcilingPayment &&
    (detail.status === 'loading' || financial.state.status === 'loading')

  useEffect(() => {
    if (!paymentReconciliationConverged) return
    resetPayment()
    setReconcilingPayment(false)
  }, [paymentReconciliationConverged, resetPayment])

  function reconcilePayment(): void {
    setReconcilingPayment(true)
    financial.retry()
    retry()
  }

  if (detail.status === 'loading') {
    return <DetailState title='正在加载订单…' description='正在读取服务端订单快照' />
  }
  if (detail.status === 'error') {
    return (
      <DetailState title='订单详情加载失败' description={detail.errorMessage}>
        <Button
          className='order-detail-state__action'
          onClick={reconcilingPayment ? reconcilePayment : retry}
        >{reconcilingPayment ? '重新核对订单与资金' : '重新加载'}</Button>
        <Button
          className='order-detail-state__back'
          onClick={() => void Taro.switchTab({ url: ORDER_LIST_PATH })}
        >返回我的订单</Button>
      </DetailState>
    )
  }

  const financialConfirmsPending = financial.state.status === 'content' &&
    financial.state.financial.order_id === detail.order.id &&
    financial.state.financial.order_status.value === 'pending' &&
    financial.state.financial.payment === null
  const paymentBlocksCancellation = reconcilingPayment ||
    payment.state.status === 'submitting' || payment.state.status === 'unknown' ||
    payment.state.status === 'succeeded'
  const canCancel = financialConfirmsPending && !paymentBlocksCancellation &&
    activeMutation === undefined &&
    (cancellation.status === 'idle' || cancellation.status === 'failed')

  function acquireMutation(intent: 'cancel' | 'payment'): boolean {
    if (activeMutationRef.current !== undefined) return false
    activeMutationRef.current = intent
    setActiveMutation(intent)
    return true
  }

  function releaseMutation(intent: 'cancel' | 'payment'): void {
    if (activeMutationRef.current !== intent) return
    activeMutationRef.current = undefined
    setActiveMutation(undefined)
  }

  async function confirmCancel(): Promise<void> {
    if (!canCancel || !acquireMutation('cancel')) return
    try {
      const confirmation = await Taro.showModal({
        title: '确认取消订单？',
        content: '仅待支付订单可以取消；材料包库存将由服务端事务恢复。',
        confirmText: '确认取消',
        confirmColor: '#a92e51',
      })
      if (confirmation.confirm) {
        await cancel()
      }
    } finally {
      releaseMutation('cancel')
    }
  }

  return (
    <View className='order-detail-page'>
      <OrderHeading order={detail.order} />
      <View className='order-detail-list'>
        {detail.order.items.map((item) => (
          <View className='order-detail-item' key={item.id}>
            <Text className='order-detail-item__name'>{item.product_name}</Text>
            {item.experience_option_id !== null && item.experience_option_id !== undefined && (
              <Text className='order-detail-item__configuration'>
                {item.option_duration_minutes} 分钟 · {item.option_participants} 人 · {item.option_day_type?.label}
              </Text>
            )}
            <View className='order-detail-item__summary'>
              <Text>¥{formatPrice(item.product_price)} × {item.quantity}</Text>
              <Text>小计 ¥{formatPrice(item.subtotal)}</Text>
            </View>
          </View>
        ))}
      </View>
      <View className='order-detail-meta'>
        <Text>创建时间：{detail.order.created_at}</Text>
        <Text>更新时间：{detail.order.updated_at}</Text>
        {detail.order.remark && <Text>备注：{detail.order.remark}</Text>}
      </View>
      {detail.order.status.value === 'pending' &&
        (cancellation.status === 'idle' || cancellation.status === 'failed') && (
        <OrderPaymentPanel
          acquireMutation={acquireMutation}
          financial={financial}
          mutationLocked={activeMutation !== undefined}
          order={detail.order}
          payment={payment}
          reconciling={reconcilingPayment}
          releaseMutation={releaseMutation}
          rechecking={paymentRecheckInFlight}
          onPaid={reconcilePayment}
          onReconcile={reconcilePayment}
        />
      )}
      <CancellationFeedback status={cancellation} />
      {detail.order.status.value === 'pending' && cancellation.status !== 'unknown' && (
        <Button
          className='order-detail-page__cancel'
          disabled={!canCancel}
          loading={cancellation.status === 'submitting'}
          onClick={() => void confirmCancel()}
        >
          {cancellation.status === 'submitting'
            ? '正在取消…'
            : payment.state.status === 'submitting'
              ? '支付处理中，暂不能取消'
              : payment.state.status === 'unknown' || reconcilingPayment
                ? '请先核对支付结果'
                : !financialConfirmsPending
                  ? '正在核对资金状态…'
                  : '取消订单'}
        </Button>
      )}
      <Button
        className='order-detail-page__back'
        onClick={() => void Taro.switchTab({ url: ORDER_LIST_PATH })}
      >
        返回我的订单
      </Button>
    </View>
  )
}

function OrderPaymentPanel({
  acquireMutation,
  financial,
  mutationLocked,
  onPaid,
  onReconcile,
  order,
  payment,
  rechecking,
  reconciling,
  releaseMutation,
}: {
  readonly order: OrderDetail
  readonly financial: ReturnType<typeof useOrderFinancial>
  readonly payment: ReturnType<typeof useOrderPayment>
  readonly reconciling: boolean
  readonly rechecking: boolean
  readonly mutationLocked: boolean
  readonly acquireMutation: (intent: 'cancel' | 'payment') => boolean
  readonly releaseMutation: (intent: 'cancel' | 'payment') => void
  readonly onPaid: () => void
  readonly onReconcile: () => void
}) {
  const member = useMemberWallet()
  const [method, setMethod] = useState<'wallet' | 'wechat'>('wallet')
  const wallet = member.state.status === 'content' ? member.state.member.wallet : undefined
  const user = member.state.status === 'content' ? member.state.member.user : undefined
  const balanceCents = wallet ? moneyToCents(wallet.balance) : undefined
  const totalCents = moneyToCents(order.total_amount)
  const sufficient = balanceCents !== undefined && totalCents !== undefined && balanceCents >= totalCents
  const walletReady = wallet?.capabilities.wallet_payment_enabled === true && wallet.status === 'active' && user?.status === 'normal'
  const canPay = method === 'wallet' && sufficient && walletReady &&
    financial.state.status === 'content' && financial.state.financial.order_id === order.id &&
    financial.state.financial.order_status.value === 'pending' &&
    financial.state.financial.payment === null && !reconciling && !mutationLocked &&
    payment.state.status !== 'submitting' && payment.state.status !== 'unknown' &&
    payment.state.status !== 'succeeded'

  async function confirmPayment(): Promise<void> {
    if (!canPay || !acquireMutation('payment')) return
    try {
      const confirmation = await Taro.showModal({
        title: '确认使用余额支付？',
        content: `将从会员余额扣除 ¥${formatPrice(order.total_amount)}。支付与订单状态会在同一服务端事务中提交。`,
        confirmText: '确认支付',
        confirmColor: '#a92e51',
      })
      if (!confirmation.confirm) return
      if (await payment.payWithWallet()) {
        member.retry()
        onPaid()
      }
    } finally {
      releaseMutation('payment')
    }
  }

  return (
    <View className='order-payment'>
      <View className='order-payment__heading'>
        <Text className='order-payment__title'>选择支付方式</Text>
        <Text className='order-payment__amount'>应付 ¥{formatPrice(order.total_amount)}</Text>
      </View>
      <Button
        className={`order-payment__method${method === 'wallet' ? ' order-payment__method--active' : ''}`}
        disabled={!walletReady || member.state.status !== 'content' || mutationLocked}
        onClick={() => setMethod('wallet')}
      >
        <View>
          <Text className='order-payment__method-name'>会员余额</Text>
          <Text className='order-payment__method-meta'>
            {wallet ? `可用 ¥${formatPrice(wallet.balance)}${sufficient ? '' : ' · 余额不足'}` : '正在读取余额…'}
          </Text>
        </View>
        <Text className='order-payment__method-state'>{method === 'wallet' ? '已选择' : '选择'}</Text>
      </Button>
      {member.state.status === 'error' && (
        <View className='order-payment__feedback order-payment__feedback--error'>
          <Text>{member.state.errorMessage}</Text>
          <Button className='order-payment__retry' onClick={member.retry}>重新读取余额</Button>
        </View>
      )}
      <Button className='order-payment__method order-payment__method--unavailable' disabled>
        <View>
          <Text className='order-payment__method-name'>微信支付</Text>
          <Text className='order-payment__method-meta'>商户能力与小程序关联尚未完成</Text>
        </View>
        <Text className='order-payment__method-state'>暂未开通</Text>
      </Button>
      {financial.state.status === 'loading' && <Text className='order-payment__hint'>正在核对订单资金状态…</Text>}
      {financial.state.status === 'error' && (
        <View className='order-payment__feedback order-payment__feedback--error'>
          <Text>{financial.state.errorMessage}</Text>
          <Button
            className='order-payment__retry'
            disabled={rechecking}
            onClick={payment.state.status === 'unknown' || reconciling ? onReconcile : financial.retry}
          >重新核对</Button>
        </View>
      )}
      {financial.state.status === 'content' && financial.state.financial.payment && (
        <Text className='order-payment__hint'>
          已存在{getPaymentMethodLabel(financial.state.financial.payment.method)}记录：
          {getPaymentStatusLabel(financial.state.financial.payment.status)}
        </Text>
      )}
      {payment.state.status === 'failed' && (
        <Text className='order-payment__feedback order-payment__feedback--failed'>
          {payment.state.errorMessage}
        </Text>
      )}
      {payment.state.status === 'unknown' && (
        <View className='order-payment__feedback order-payment__feedback--unknown'>
          <Text>{payment.state.errorMessage}</Text>
          <Button
            className='order-payment__retry order-payment__reconcile'
            disabled={rechecking}
            onClick={onReconcile}
          >{rechecking ? '正在核对资金与订单…' : '重新核对资金与订单状态'}</Button>
        </View>
      )}
      {reconciling && payment.state.status !== 'unknown' && (
        <View className='order-payment__feedback order-payment__feedback--unknown'>
          <Text>{rechecking ? '正在核对支付后的订单与资金状态…' : '订单与资金状态尚未一致，请再次核对'}</Text>
          <Button
            className='order-payment__retry order-payment__reconcile'
            disabled={rechecking}
            onClick={onReconcile}
          >{rechecking ? '正在核对资金与订单…' : '再次核对资金与订单状态'}</Button>
        </View>
      )}
      <Button
        className='order-payment__submit'
        disabled={!canPay}
        loading={payment.state.status === 'submitting'}
        onClick={() => void confirmPayment()}
      >
        {payment.state.status === 'submitting'
          ? '正在支付…'
          : !walletReady ? '余额支付不可用' : !sufficient ? '余额不足' : '余额支付'}
      </Button>
      <Text className='order-payment__footnote'>不支持余额与微信混合支付；微信入口当前不会发起请求或返回成功。</Text>
    </View>
  )
}

function OrderHeading({ order }: { readonly order: OrderDetail }) {
  return (
    <View className='order-detail-heading'>
      <Text className='order-detail-heading__title'>订单详情</Text>
      <Text className='order-detail-heading__number'>{order.order_no}</Text>
      <Text className='order-detail-heading__status'>{order.status.label}</Text>
      <Text className='order-detail-heading__total'>¥{formatPrice(order.total_amount)}</Text>
      <Text className='order-detail-heading__hint'>金额和明细来自服务端历史快照</Text>
    </View>
  )
}

function CancellationFeedback({ status }: {
  readonly status: ReturnType<typeof useOrderDetail>['cancellation']
}) {
  if (status.status === 'failed' || status.status === 'unknown') {
    return (
      <View className={`order-cancel-feedback order-cancel-feedback--${status.status}`}>
        <Text>{status.errorMessage}</Text>
      </View>
    )
  }
  if (status.status === 'succeeded') {
    return (
      <View className='order-cancel-feedback order-cancel-feedback--success'>
        <Text>订单已取消</Text>
        {status.refreshErrorMessage && <Text>{status.refreshErrorMessage}</Text>}
      </View>
    )
  }
  return null
}

function DetailState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='order-detail-page order-detail-page--state'>
      <Text className='order-detail-state__title'>{title}</Text>
      <Text className='order-detail-state__description'>{description}</Text>
      {children}
    </View>
  )
}
