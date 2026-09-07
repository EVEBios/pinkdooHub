import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'

import type { Reservation } from '@/api/endpoints/reservations'
import { buildLoginUrl, useAuth } from '@/auth'
import {
  buildReservationCreateUrl,
  canRequestReservationCancellation,
  formatReservationDate,
  formatShanghaiUtc,
  parseReservationDetailRoute,
  reservationStatusClass,
  RESERVATION_LIST_PATH,
  useReservationDetail,
} from '@/features/reservation'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function ReservationDetailPage() {
  const auth = useAuth()
  const route = parseReservationDetailRoute(useRouter().params)
  if (!route) {
    return <ReservationDetailState title='预约地址无效' description='请从“我的预约”重新进入' />
  }
  if (auth.status === 'initializing') {
    return <ReservationDetailState title='正在确认登录状态…' description='预约详情只对所属顾客可见' />
  }
  if (auth.status === 'error') {
    return (
      <ReservationDetailState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='reservation-detail-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </ReservationDetailState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <ReservationDetailState title='登录后查看预约' description='登录后先返回我的预约，再打开对应详情'>
        <Button
          className='reservation-detail-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(RESERVATION_LIST_PATH) })}
        >去登录</Button>
      </ReservationDetailState>
    )
  }
  if (auth.user?.role !== 'user') {
    return <ReservationDetailState title='顾客账号才能查看预约' description='管理员请从管理预约列表进入' />
  }
  return <AuthenticatedReservationDetail reservationId={route.reservationId} />
}

export function AuthenticatedReservationDetail({ reservationId }: { readonly reservationId: number }) {
  const { cancel, cancellation, detail, retry } = useReservationDetail(reservationId)

  if (detail.status === 'loading') {
    return <ReservationDetailState title='正在加载预约…' description='正在读取服务端预约状态' />
  }
  if (detail.status === 'error') {
    return (
      <ReservationDetailState title='预约详情加载失败' description={detail.errorMessage}>
        <Button className='reservation-detail-state__action' onClick={retry}>重新加载</Button>
        <Button
          className='reservation-detail-state__back'
          onClick={() => void Taro.redirectTo({ url: RESERVATION_LIST_PATH })}
        >返回我的预约</Button>
      </ReservationDetailState>
    )
  }

  const item = detail.reservation
  const cancellable = canRequestReservationCancellation(item)
  const mutationUnknown = cancellation.status === 'unknown'

  async function confirmCancellation(): Promise<void> {
    if (!cancellable || cancellation.status === 'submitting' || mutationUnknown) return
    const confirmation = await Taro.showModal({
      title: '确认取消预约？',
      content: '开始前三小时可取消。取消后不会删除历史记录；如需改期，请再创建一条新预约。',
      confirmText: '确认取消',
      confirmColor: '#a92f38',
    })
    if (confirmation.confirm) await cancel()
  }

  return (
    <View className='reservation-detail-page'>
      <View className='reservation-detail-heading'>
        <View className='reservation-detail-heading__topline'>
          <Text className='reservation-detail-heading__title'>预约详情</Text>
          <Text className={`reservation-detail-heading__status reservation-detail-heading__status--${reservationStatusClass(item)}`}>
            {item.status.label}
          </Text>
        </View>
        <Text className='reservation-detail-heading__name'>{item.product_name}</Text>
        <Text className='reservation-detail-heading__time'>{formatReservationDate(item.reservation_date)}</Text>
        <Text className='reservation-detail-heading__clock'>{item.start_time}–{item.end_time}</Text>
      </View>

      <View className={`reservation-detail-message reservation-detail-message--${reservationStatusClass(item)}`}>
        <Text>{item.customer_message}</Text>
      </View>

      <ReservationFacts reservation={item} />

      {cancellable && (
        <View className='reservation-detail-cancellation'>
          <Text className='reservation-detail-cancellation__title'>取消与改期</Text>
          <Text className='reservation-detail-cancellation__deadline'>
            取消截止：{formatShanghaiUtc(item.cancellation_deadline_at)}（北京时间）
          </Text>
          <Text className='reservation-detail-cancellation__hint'>是否仍在取消窗口内以服务端提交时判断为准。</Text>
          <Button
            className='reservation-detail-cancellation__action'
            disabled={cancellation.status === 'submitting' || mutationUnknown}
            loading={cancellation.status === 'submitting'}
            onClick={() => void confirmCancellation()}
          >{cancellation.status === 'submitting' ? '正在取消…' : mutationUnknown ? '请先核对取消结果' : '取消预约'}</Button>
        </View>
      )}

      <CancellationFeedback cancellation={cancellation} retry={retry} />

      {(item.status.value === 'rejected' || item.status.value === 'cancelled') && (
        <Button
          className='reservation-detail-page__rebook'
          onClick={() => void Taro.navigateTo({
            url: buildReservationCreateUrl(item.product_id, item.experience_option_id),
          })}
        >重新选择日期和时段</Button>
      )}
      <Button
        className='reservation-detail-page__back'
        onClick={() => void Taro.redirectTo({ url: RESERVATION_LIST_PATH })}
      >返回我的预约</Button>
    </View>
  )
}

function ReservationFacts({ reservation }: { readonly reservation: Reservation }) {
  return (
    <View className='reservation-detail-facts'>
      <Text className='reservation-detail-facts__title'>预约快照</Text>
      <Fact label='体验配置' value={`${reservation.duration_minutes} 分钟 · ${reservation.participants} 人 · ${reservation.day_type.label}`} />
      <Fact label='预约价格' value={`¥${formatPrice(reservation.price)} · 到店支付`} />
      <Fact label='预约编号' value={`#${reservation.id}`} />
      <Fact label='提交时间' value={`${formatShanghaiUtc(reservation.created_at)}（北京时间）`} />
      {reservation.rejection_reason && <Fact label='未能确认原因' value={reservation.rejection_reason.label} />}
      {reservation.cancellation_reason && <Fact label='取消原因' value={reservation.cancellation_reason.label} />}
    </View>
  )
}

function Fact({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <View className='reservation-detail-fact'>
      <Text className='reservation-detail-fact__label'>{label}</Text>
      <Text className='reservation-detail-fact__value'>{value}</Text>
    </View>
  )
}

function CancellationFeedback({ cancellation, retry }: {
  readonly cancellation: ReturnType<typeof useReservationDetail>['cancellation']
  readonly retry: () => void
}) {
  if (cancellation.status === 'failed' || cancellation.status === 'unknown') {
    return (
      <View className={`reservation-detail-feedback reservation-detail-feedback--${cancellation.status}`}>
        <Text>{cancellation.errorMessage}</Text>
        {cancellation.status === 'unknown' && <Button onClick={retry}>重新加载预约核对</Button>}
      </View>
    )
  }
  if (cancellation.status === 'succeeded') {
    return (
      <View className='reservation-detail-feedback reservation-detail-feedback--success'>
        <Text>预约已取消，历史记录已保留。</Text>
        {cancellation.refreshErrorMessage && <Text>{cancellation.refreshErrorMessage}</Text>}
      </View>
    )
  }
  return null
}

function ReservationDetailState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='reservation-detail-state'>
      <Text className='reservation-detail-state__title'>{title}</Text>
      <Text className='reservation-detail-state__description'>{description}</Text>
      {children}
    </View>
  )
}
