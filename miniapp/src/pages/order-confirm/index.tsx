import { Button, Text, Textarea, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useCallback, useEffect, useRef, useState } from 'react'

import { BusinessError, SessionExpiredError } from '@/api'
import type { OrderDetail } from '@/api/endpoints/orders'
import {
  buildLoginUrl,
  type AuthContextValue,
  isAdminRole,
  ORDER_CONFIRM_PATH,
  ORDER_LIST_PATH,
  useAuth,
} from '@/auth'
import {
  cartItemKey,
  ORDER_REMARK_LIMIT,
  type OrderSubmissionState,
  useCart,
  useOrderSubmission,
} from '@/features/order'
import {
  buildTableEntryUrl,
  buildTableOrderConfirmUrl,
  clearPendingTableEntry,
  loadPendingTableEntry,
  parseTableOrderConfirmRoute,
  type PendingTableEntryIntent,
} from '@/features/table_session'
import { AdminWorkbenchRedirect } from '@/navigation/admin_workbench_redirect'
import { formatColorLabel, formatPrice } from '@/utils/format'

import './index.scss'

export default function OrderConfirmPage() {
  const auth = useAuth()
  const tableIntentId = parseTableOrderConfirmRoute(useRouter().params)

  if (auth.status === 'initializing') {
    return <ConfirmState title='正在确认登录状态…' description='创建订单必须关联当前登录用户' />
  }
  if (auth.status === 'error') {
    return (
      <ConfirmState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='order-confirm-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </ConfirmState>
    )
  }
  if (auth.status === 'authenticated') {
    if (!auth.user) {
      return (
        <ConfirmState title='账户信息不完整' description='请重新检查登录状态后再确认订单'>
          <Button className='order-confirm-state__action' onClick={auth.retryInitialization}>重新检查</Button>
        </ConfirmState>
      )
    }
    if (isAdminRole(auth.user.role)) {
      return <AdminWorkbenchRedirect />
    }
    if (auth.user.role !== 'user') {
      return (
        <ConfirmState title='账户角色暂不支持' description='请重新检查登录状态后再确认订单'>
          <Button className='order-confirm-state__action' onClick={auth.retryInitialization}>重新检查</Button>
        </ConfirmState>
      )
    }
  }

  return <CustomerOrderConfirmPage auth={auth} tableIntentId={tableIntentId} />
}

function CustomerOrderConfirmPage({ auth, tableIntentId }: {
  readonly auth: AuthContextValue
  readonly tableIntentId?: string
}) {
  const cart = useCart()
  const submission = useOrderSubmission()
  const [remark, setRemark] = useState('')

  // 服务端成功是最高优先级事实；Cart 对账可能已先发布空列表，不能遮住创建结果。
  if (submission.state.status === 'succeeded') {
    return (
      <OrderResult
        state={submission.state}
        tableIntentId={tableIntentId}
        userId={auth.user?.id}
      />
    )
  }

  if (cart.status === 'initializing') {
    return <ConfirmState title='正在准备订单…' description='正在恢复当前设备的购物清单' />
  }
  if (cart.status === 'error') {
    return (
      <ConfirmState title='购物清单暂不可用' description={cart.initializationError?.message ?? '请稍后重试'}>
        <Button className='order-confirm-state__action' onClick={cart.retryInitialization}>重新加载</Button>
      </ConfirmState>
    )
  }
  if (cart.items.length === 0) {
    return (
      <ConfirmState title='没有可以确认的商品' description='请先从商品详情加入真实配置或材料包'>
        <Button
          className='order-confirm-state__action'
          onClick={() => void Taro.switchTab({ url: '/pages/index/index' })}
        >
          去选择商品
        </Button>
      </ConfirmState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <ConfirmState title='登录后才能创建订单' description='登录完成后会回到当前订单确认页，购物清单不会被清空'>
        <Button
          className='order-confirm-state__action order-confirm-state__login'
          onClick={() => void Taro.navigateTo({
            url: buildLoginUrl(
              tableIntentId ? buildTableOrderConfirmUrl(tableIntentId) : ORDER_CONFIRM_PATH,
            ),
          })}
        >
          去登录
        </Button>
      </ConfirmState>
    )
  }

  const submitDisabled = submission.state.status === 'submitting' ||
    submission.state.status === 'unknown'

  return (
    <View className='order-confirm-page'>
      <View className='order-confirm-page__header'>
        <Text className='order-confirm-page__title'>确认订单</Text>
        <Text className='order-confirm-page__subtitle'>{cart.items.length} 项商品，提交前请核对配置、数量与备注。</Text>
      </View>
      <View className='order-confirm-page__notice'>
        <Text>这里展示的是本地预览。商品、配置、库存和金额会在创建订单时由后端重新校验并生成快照。</Text>
      </View>

      <View className='order-confirm-list'>
        {cart.items.map((item) => (
          <View className='order-confirm-item' key={cartItemKey(item)}>
            <Text className='order-confirm-item__type'>
              {item.productType === 'experience' ? '拼豆体验' : '拼豆套装'}
            </Text>
            <Text className='order-confirm-item__name'>{item.productName}</Text>
            {item.configurationLabel && (
              <Text className='order-confirm-item__configuration'>{item.configurationLabel}</Text>
            )}
            <View className='order-confirm-item__summary'>
              <Text>预览单价 ¥{formatPrice(item.unitPrice)}{item.kitColorId === null ? '' : ` / ${item.saleUnitGrams}g`}</Text>
              <Text>{item.kitColorId === null ? `数量 × ${item.quantity}` : `重量 ${item.quantity * item.saleUnitGrams}g`}</Text>
            </View>
          </View>
        ))}
      </View>

      <View className='order-confirm-remark'>
        <Text className='order-confirm-remark__label'>订单备注（可选）</Text>
        <Textarea
          className='order-confirm-remark__input'
          maxlength={ORDER_REMARK_LIMIT}
          placeholder='例如到店时间，最多 500 字'
          value={remark}
          onInput={(event) => setRemark(event.detail.value)}
        />
        <Text className='order-confirm-remark__count'>{remark.length}/{ORDER_REMARK_LIMIT}</Text>
      </View>

      <SubmissionFeedback state={submission.state} />

      <Button
        className='order-confirm-page__submit'
        disabled={submitDisabled}
        loading={submission.state.status === 'submitting'}
        onClick={() => void submission.submit(cart.items, remark)}
      >
        {submission.state.status === 'submitting'
          ? '正在创建订单…'
          : submission.state.status === 'unknown'
            ? '请先核对订单结果'
            : '确认创建订单'}
      </Button>
    </View>
  )
}

function OrderResult({
  state,
  tableIntentId,
  userId,
}: {
  state: Extract<OrderSubmissionState, { status: 'succeeded' }>
  readonly tableIntentId?: string
  readonly userId?: number
}) {
  const { order } = state
  const hasExperience = order.items.some(
    (item) => item.experience_option_id !== null && item.experience_option_id !== undefined,
  )
  const tableReturn = usePendingTableReturn(
    order.id,
    hasExperience,
    tableIntentId,
    userId,
  )
  const tableReturnBusy = tableReturn.status === 'checking' || tableReturn.status === 'returning'
  return (
    <View className='order-result-page'>
      <View className='order-result-hero'>
        <Text className='order-result-hero__eyebrow'>订单创建成功</Text>
        <Text className='order-result-hero__number'>{order.order_no}</Text>
        <Text className='order-result-hero__status'>{order.status.label}</Text>
        <Text className='order-result-hero__total'>¥{formatPrice(order.total_amount)}</Text>
        <Text className='order-result-hero__hint'>以上金额和明细来自服务端订单快照</Text>
      </View>

      <View className='order-result-list'>
        {order.items.map((item) => (
          <View className='order-result-item' key={item.id}>
            <Text className='order-result-item__name'>{item.product_name}</Text>
            {item.experience_option_id !== null && item.experience_option_id !== undefined && (
              <Text className='order-result-item__configuration'>{formatOrderOption(item)}</Text>
            )}
            {item.kit_color_id !== null && item.kit_color_id !== undefined && (
              <Text className='order-result-item__configuration'>{formatOrderColor(item)}</Text>
            )}
            <View className='order-result-item__summary'>
              <Text>¥{formatPrice(item.product_price)} × {item.quantity}</Text>
              <Text>小计 ¥{formatPrice(item.subtotal)}</Text>
            </View>
          </View>
        ))}
      </View>

      <View className='order-result-meta'>
        <Text>状态：{order.status.label}</Text>
        <Text>创建时间：{order.created_at}</Text>
        {order.remark && <Text>备注：{order.remark}</Text>}
      </View>

      {(state.cartReconciliationError || state.cartReconciliation?.status === 'conflict') && (
        <View className='order-result-warning'>
          <Text>订单已经创建，但本地购物清单在提交期间发生变化或未能完全清理。请返回购物清单手动核对，不要重复创建本订单。</Text>
        </View>
      )}

      {tableReturn.status === 'failed' && (
        <View className='order-result-warning' ariaRole='alert'>
          <Text>订单已创建，但暂时无法返回扫码桌台。桌台信息已保留，请重试。</Text>
        </View>
      )}

      <View className='order-result-actions'>
        {tableReturn.status === 'checking' && (
          <Button
            className='order-result-actions__primary'
            disabled
            loading
          >正在确认扫码桌台…</Button>
        )}
        {tableReturn.status === 'returning' && (
          <Button
            className='order-result-actions__primary'
            disabled
            loading
          >正在返回扫码桌台…</Button>
        )}
        {tableReturn.status === 'failed' && (
          <Button
            className='order-result-actions__primary'
            onClick={() => void tableReturn.retry()}
          >重新返回桌台</Button>
        )}
        <Button
          disabled={tableReturnBusy}
          onClick={() => void leaveTableOrderResult(tableReturn.discard, ORDER_LIST_PATH)}
        >查看我的订单</Button>
        <Button
          className='order-result-actions__primary'
          disabled={tableReturnBusy}
          onClick={() => void leaveTableOrderResult(tableReturn.discard, '/pages/index/index')}
        >
          继续选购
        </Button>
      </View>
    </View>
  )
}

type PendingTableReturnState =
  | { readonly status: 'checking' | 'idle' | 'returning' }
  | { readonly status: 'failed' }

function usePendingTableReturn(
  orderId: number,
  hasExperience: boolean,
  intentId?: string,
  userId?: number,
) {
  const canLoadIntent = intentId !== undefined && userId !== undefined
  const [state, setState] = useState<PendingTableReturnState>(
    canLoadIntent && hasExperience ? { status: 'checking' } : { status: 'idle' },
  )
  const mountedRef = useRef(true)
  const navigatingRef = useRef(false)
  const autoStartedOrderRef = useRef<number>()

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const openTable = useCallback(async (intent: PendingTableEntryIntent): Promise<void> => {
    if (navigatingRef.current) return
    navigatingRef.current = true
    if (mountedRef.current) setState({ status: 'returning' })
    try {
      // order_id 只是让开台页在服务端 eligible 列表中聚焦新订单，不参与领取校验。
      await Taro.reLaunch({
        url: buildTableEntryUrl(intent.token, orderId, intent.intentId),
      })
    } catch {
      if (mountedRef.current) setState({ status: 'failed' })
      return
    } finally {
      navigatingRef.current = false
    }
    // 导航成功仍保留意图；由桌台 claim 成功或用户明确退出流程后精确消费。
  }, [orderId])

  useEffect(() => {
    if (!intentId || userId === undefined) {
      setState({ status: 'idle' })
      return
    }
    if (!hasExperience) {
      setState({ status: 'idle' })
      void loadPendingTableEntry(intentId, userId)
        .then((intent) => intent && clearPendingTableEntry(intent))
        .catch(() => undefined)
      return
    }
    let active = true
    void loadPendingTableEntry(intentId, userId)
      .then((intent) => {
        if (!active) return
        if (!intent) {
          setState({ status: 'idle' })
          return
        }
        if (autoStartedOrderRef.current === orderId) return
        autoStartedOrderRef.current = orderId
        void openTable(intent)
      })
      .catch(() => {
        if (active) setState({ status: 'failed' })
      })
    return () => { active = false }
  }, [hasExperience, intentId, openTable, orderId, userId])

  const retry = useCallback(async (): Promise<void> => {
    if (state.status !== 'failed' || !intentId || userId === undefined) return
    setState({ status: 'checking' })
    try {
      const intent = await loadPendingTableEntry(intentId, userId)
      if (intent) await openTable(intent)
      else if (mountedRef.current) setState({ status: 'idle' })
    } catch {
      if (mountedRef.current) setState({ status: 'failed' })
    }
  }, [intentId, openTable, state.status, userId])

  const discard = useCallback(async (): Promise<void> => {
    if (intentId && userId !== undefined) {
      const intent = await loadPendingTableEntry(intentId, userId).catch(() => undefined)
      if (intent) await clearPendingTableEntry(intent).catch(() => undefined)
    }
  }, [intentId, userId])

  return { ...state, discard, retry } as const
}

async function leaveTableOrderResult(
  discard: () => Promise<void>,
  url: string,
): Promise<void> {
  await discard()
  if (url === ORDER_LIST_PATH) {
    await Taro.navigateTo({ url })
  } else {
    await Taro.switchTab({ url })
  }
}

function formatOrderOption(item: OrderDetail['items'][number]): string {
  return `${item.option_duration_minutes} 分钟 · ${item.option_participants} 人 · ${item.option_day_type?.label}`
}

function formatOrderColor(item: OrderDetail['items'][number]): string {
  return `${formatColorLabel(item.kit_color_code ?? '', item.kit_color_name ?? '')} · ${item.total_weight_grams}g`
}

function SubmissionFeedback({ state }: { state: OrderSubmissionState }) {
  if (state.status === 'failed') {
    return (
      <View className='order-confirm-feedback order-confirm-feedback--error'>
        <Text>{getOrderCreateErrorMessage(state.error)}</Text>
      </View>
    )
  }
  if (state.status === 'unknown') {
    return (
      <View className='order-confirm-feedback order-confirm-feedback--unknown'>
        <Text>请求结果可能未知。购物清单已保留，请不要立即重复创建；后续可前往“我的订单”确认。</Text>
        <Button
          className='order-confirm-feedback__action'
          onClick={() => void Taro.navigateTo({ url: ORDER_LIST_PATH })}
        >
          查看我的订单
        </Button>
      </View>
    )
  }
  return null
}

function ConfirmState({
  children,
  description,
  title,
}: {
  title: string
  description: string
  children?: React.ReactNode
}) {
  return (
    <View className='order-confirm-page order-confirm-page--state'>
      <Text className='order-confirm-state__title'>{title}</Text>
      <Text className='order-confirm-state__description'>{description}</Text>
      {children}
    </View>
  )
}

export function getOrderCreateErrorMessage(error: Error): string {
  if (error instanceof BusinessError) {
    if (error.code === 40931) {
      return '商品库存不足，请返回购物清单调整数量'
    }
    if (error.code === 42231) {
      return '有商品当前不可下单，请返回购物清单重新选择'
    }
    if (error.code === 42232) {
      return '有体验配置当前不可用，请返回商品详情重新选择'
    }
  }
  if (error instanceof SessionExpiredError) {
    return '登录状态已失效，请重新登录后再确认订单'
  }
  return error.message || '创建订单失败，请稍后重试'
}
