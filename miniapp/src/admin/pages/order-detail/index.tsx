import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'

import type { AdminOrderDetail } from '@/api/endpoints/orders'
import { buildLoginUrl, useAuth } from '@/auth'
import {
  ADMIN_ORDER_LIST_PATH,
  getTransitionAction,
  isAdminRole,
  parseAdminOrderDetailRoute,
  useAdminOrderDetail,
} from '@/features/order'
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

  const action = getTransitionAction(detail.order)

  async function confirmTransition(): Promise<void> {
    if (!action) return
    const markingPaid = action === 'mark_paid'
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
  }

  return (
    <View className='admin-order-detail-page'>
      <AdminOrderHeading order={detail.order} />
      <View className='admin-order-detail-user'>
        <Text>下单用户：#{detail.order.user_id} · {detail.order.user_nickname}</Text>
      </View>
      <View className='admin-order-detail-list'>
        {detail.order.items.map((item) => (
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
        <Text>创建时间：{detail.order.created_at}</Text>
        <Text>更新时间：{detail.order.updated_at}</Text>
        {detail.order.remark && <Text>备注：{detail.order.remark}</Text>}
      </View>
      <TransitionFeedback transition={transition} />
      {action && transition.status !== 'unknown' && (
        <Button
          className='admin-order-detail-page__transition'
          disabled={transition.status === 'submitting'}
          loading={transition.status === 'submitting'}
          onClick={() => void confirmTransition()}
        >
          {transition.status === 'submitting'
            ? '正在更新…'
            : action === 'mark_paid' ? '标记为已支付' : '完成订单'}
        </Button>
      )}
      {!action && <Text className='admin-order-detail-page__terminal'>当前状态没有可执行的管理命令。</Text>}
      <Button onClick={() => void Taro.navigateTo({ url: ADMIN_ORDER_LIST_PATH })}>返回管理订单</Button>
    </View>
  )
}

function AdminOrderHeading({ order }: { readonly order: AdminOrderDetail }) {
  return (
    <View className='admin-order-detail-heading'>
      <Text className='admin-order-detail-heading__eyebrow'>管理订单详情</Text>
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
