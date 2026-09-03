import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'

import type { OrderDetail } from '@/api/endpoints/orders'
import { buildLoginUrl, ORDER_LIST_PATH, useAuth } from '@/auth'
import { parseOrderDetailRoute, useOrderDetail } from '@/features/order'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function OrderDetailPage() {
  const auth = useAuth()
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
  if (detail.status === 'loading') {
    return <DetailState title='正在加载订单…' description='正在读取服务端订单快照' />
  }
  if (detail.status === 'error') {
    return (
      <DetailState title='订单详情加载失败' description={detail.errorMessage}>
        <Button className='order-detail-state__action' onClick={retry}>重新加载</Button>
        <Button
          className='order-detail-state__back'
          onClick={() => void Taro.navigateTo({ url: ORDER_LIST_PATH })}
        >返回我的订单</Button>
      </DetailState>
    )
  }

  async function confirmCancel(): Promise<void> {
    const confirmation = await Taro.showModal({
      title: '确认取消订单？',
      content: '仅待支付订单可以取消；材料包库存将由服务端事务恢复。',
      confirmText: '确认取消',
      confirmColor: '#a92e51',
    })
    if (confirmation.confirm) {
      await cancel()
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
      <CancellationFeedback status={cancellation} />
      {detail.order.status.value === 'pending' && cancellation.status !== 'unknown' && (
        <Button
          className='order-detail-page__cancel'
          disabled={cancellation.status === 'submitting'}
          loading={cancellation.status === 'submitting'}
          onClick={() => void confirmCancel()}
        >
          {cancellation.status === 'submitting' ? '正在取消…' : '取消订单'}
        </Button>
      )}
      <Button
        className='order-detail-page__back'
        onClick={() => void Taro.navigateTo({ url: ORDER_LIST_PATH })}
      >
        返回我的订单
      </Button>
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
