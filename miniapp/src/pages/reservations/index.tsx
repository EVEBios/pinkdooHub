import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import type { Reservation } from '@/api/endpoints/reservations'
import { buildLoginUrl, useAuth } from '@/auth'
import {
  buildReservationDetailUrl,
  formatReservationDate,
  reservationStatusClass,
  RESERVATION_LIST_PATH,
  type ReservationListStatusFilter,
  useReservationList,
} from '@/features/reservation'
import { formatPrice } from '@/utils/format'

import './index.scss'

const STATUS_FILTERS: ReadonlyArray<{ value: ReservationListStatusFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待确认' },
  { value: 'confirmed', label: '已确认' },
  { value: 'rejected', label: '未能确认' },
  { value: 'cancelled', label: '已取消' },
]

export default function ReservationsPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <ReservationsState title='正在确认登录状态…' description='我的预约只对当前登录用户可见' />
  }
  if (auth.status === 'error') {
    return (
      <ReservationsState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='reservations-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </ReservationsState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <ReservationsState title='登录后查看我的预约' description='这里只显示当前账号登记的拼豆体验'>
        <Button
          className='reservations-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(RESERVATION_LIST_PATH) })}
        >去登录</Button>
      </ReservationsState>
    )
  }
  if (auth.user?.role !== 'user') {
    return <ReservationsState title='顾客账号才能查看预约' description='管理员请从“管理预约”进入门店工作台' />
  }
  return <AuthenticatedReservations />
}

export function AuthenticatedReservations() {
  const { loadNextPage, retry, setStatusFilter, state, statusFilter } = useReservationList()
  return (
    <View className='reservations-page'>
      <View className='reservations-page__header'>
        <Text className='reservations-page__title'>我的预约</Text>
        <Text className='reservations-page__subtitle'>门店确认、拒绝或店休取消后，最新结果会显示在这里</Text>
      </View>
      <View className='reservations-filters'>
        {STATUS_FILTERS.map((filter) => (
          <Button
            key={filter.value}
            className={`reservations-filters__item${statusFilter === filter.value ? ' reservations-filters__item--active' : ''}`}
            onClick={() => setStatusFilter(filter.value)}
          >{filter.label}</Button>
        ))}
      </View>
      {state.status === 'loading' && <ReservationsState title='正在加载预约…' description='正在读取服务端最新状态' />}
      {state.status === 'empty' && (
        <ReservationsState title='当前筛选下没有预约' description='从拼豆体验详情选择配置后即可登记到店时间'>
          <Button className='reservations-state__action' onClick={() => void Taro.navigateTo({ url: '/pages/index/index' })}>
            浏览拼豆体验
          </Button>
        </ReservationsState>
      )}
      {state.status === 'error' && (
        <ReservationsState title='预约加载失败' description={state.errorMessage ?? '请稍后重试'}>
          <Button className='reservations-state__action' onClick={retry}>重新加载</Button>
        </ReservationsState>
      )}
      {state.status === 'content' && (
        <View className='reservations-content'>
          <View className='reservations-content__summary'>
            <Text>已加载 {state.items.length} 条</Text>
            <Text>共 {state.total} 条</Text>
          </View>
          {state.items.map((item) => <ReservationCard key={item.id} reservation={item} />)}
          {state.errorMessage && <Text className='reservations-content__error'>{state.errorMessage}</Text>}
          {state.page < state.pages ? (
            <Button
              className='reservations-content__load-more'
              disabled={state.loadingMore}
              onClick={loadNextPage}
            >{state.loadingMore ? '正在加载…' : state.errorMessage ? '重试加载更多' : '加载更多'}</Button>
          ) : <Text className='reservations-content__end'>已经到底了</Text>}
        </View>
      )}
    </View>
  )
}

function ReservationCard({ reservation }: { readonly reservation: Reservation }) {
  const statusClass = reservationStatusClass(reservation)
  return (
    <View
      className='reservation-card'
      onClick={() => void Taro.navigateTo({ url: buildReservationDetailUrl(reservation.id) })}
    >
      <View className='reservation-card__heading'>
        <Text className='reservation-card__name'>{reservation.product_name}</Text>
        <Text className={`reservation-card__status reservation-card__status--${statusClass}`}>
          {reservation.status.label}
        </Text>
      </View>
      <Text className='reservation-card__date'>{formatReservationDate(reservation.reservation_date)}</Text>
      <Text className='reservation-card__time'>{reservation.start_time}–{reservation.end_time}</Text>
      <View className='reservation-card__summary'>
        <Text>{reservation.duration_minutes} 分钟 · {reservation.participants} 人</Text>
        <Text className='reservation-card__price'>¥{formatPrice(reservation.price)}</Text>
      </View>
      <Text className='reservation-card__message'>{reservation.customer_message}</Text>
    </View>
  )
}

function ReservationsState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='reservations-page reservations-page--state'>
      <Text className='reservations-state__title'>{title}</Text>
      <Text className='reservations-state__description'>{description}</Text>
      {children}
    </View>
  )
}
