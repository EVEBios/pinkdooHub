import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import type { OrderListItem } from '@/api/endpoints/orders'
import { buildLoginUrl, ORDER_LIST_PATH, useAuth } from '@/auth'
import {
  buildOrderDetailUrl,
  type OrderStatusFilter,
  useOrderList,
} from '@/features/order'
import { formatPrice } from '@/utils/format'

import './index.scss'

const STATUS_FILTERS: ReadonlyArray<{ value: OrderStatusFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待支付' },
  { value: 'paid', label: '已支付' },
  { value: 'cancelled', label: '已取消' },
  { value: 'completed', label: '已完成' },
]

export default function OrdersPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <OrdersState title='正在确认登录状态…' description='我的订单只对当前登录用户可见' />
  }
  if (auth.status === 'error') {
    return (
      <OrdersState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='orders-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </OrdersState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <OrdersState title='登录后查看我的订单' description='只会显示当前账号创建的订单'>
        <Button
          className='orders-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ORDER_LIST_PATH) })}
        >
          去登录
        </Button>
      </OrdersState>
    )
  }
  return <AuthenticatedOrders />
}

export function AuthenticatedOrders() {
  const { loadNextPage, retry, setStatusFilter, state, statusFilter } = useOrderList()
  return (
    <View className='orders-page'>
      <View className='orders-page__header'>
        <Text className='orders-page__eyebrow'>MY ORDERS</Text>
        <Text className='orders-page__title'>我的订单</Text>
        <Text className='orders-page__subtitle'>状态、金额和数量均来自服务端</Text>
      </View>
      <View className='orders-filters'>
        {STATUS_FILTERS.map((filter) => (
          <Button
            key={filter.value}
            className={`orders-filters__item${statusFilter === filter.value ? ' orders-filters__item--active' : ''}`}
            size='mini'
            onClick={() => setStatusFilter(filter.value)}
          >
            {filter.label}
          </Button>
        ))}
      </View>
      {state.status === 'loading' && <OrdersState title='正在加载订单…' description='正在读取服务端第一页' />}
      {state.status === 'empty' && <OrdersState title='当前筛选下没有订单' description='创建订单后会显示在这里' />}
      {state.status === 'error' && (
        <OrdersState title='订单加载失败' description={state.errorMessage ?? '请稍后重试'}>
          <Button className='orders-state__action' onClick={retry}>重新加载</Button>
        </OrdersState>
      )}
      {state.status === 'content' && (
        <View className='orders-content'>
          <View className='orders-content__summary'>
            <Text>已加载 {state.items.length} 单</Text>
            <Text>共 {state.total} 单</Text>
          </View>
          {state.items.map((order) => <OrderCard key={order.id} order={order} />)}
          {state.errorMessage && <Text className='orders-content__error'>{state.errorMessage}</Text>}
          {state.page < state.pages ? (
            <Button
              className='orders-content__load-more'
              disabled={state.loadingMore}
              onClick={loadNextPage}
            >
              {state.loadingMore ? '正在加载…' : state.errorMessage ? '重试加载更多' : '加载更多'}
            </Button>
          ) : <Text className='orders-content__end'>已经到底了</Text>}
        </View>
      )}
    </View>
  )
}

function OrderCard({ order }: { order: OrderListItem }) {
  return (
    <View
      className='order-card'
      onClick={() => void Taro.navigateTo({ url: buildOrderDetailUrl(order.id) })}
    >
      <View className='order-card__heading'>
        <Text className='order-card__number'>{order.order_no}</Text>
        <Text className={`order-card__status order-card__status--${order.status.value}`}>
          {order.status.label}
        </Text>
      </View>
      <View className='order-card__summary'>
        <Text>{order.item_count} 种商品配置</Text>
        <Text className='order-card__total'>¥{formatPrice(order.total_amount)}</Text>
      </View>
      <Text className='order-card__time'>创建时间：{order.created_at}</Text>
    </View>
  )
}

function OrdersState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='orders-page orders-page--state'>
      <Text className='orders-state__title'>{title}</Text>
      <Text className='orders-state__description'>{description}</Text>
      {children}
    </View>
  )
}
