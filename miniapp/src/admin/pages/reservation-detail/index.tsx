import { Button, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'

import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_RESERVATION_LIST_PATH,
  formatReservationDate,
  formatShanghaiUtc,
  parseReservationDetailRoute,
  reservationStatusClass,
  type AdminReservationAction,
  useAdminReservationDetail,
} from '@/features/reservation'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function AdminReservationDetailPage() {
  const auth = useAuth()
  const route = parseReservationDetailRoute(useRouter().params)
  if (!route) {
    return <AdminReservationDetailState title='预约地址无效' description='请从管理预约列表重新进入' />
  }
  if (auth.status === 'initializing') {
    return <AdminReservationDetailState title='正在确认管理员身份…' description='管理预约详情仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <AdminReservationDetailState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='admin-reservation-detail-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </AdminReservationDetailState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <AdminReservationDetailState title='登录后处理预约' description='登录后请从管理预约列表重新进入详情'>
        <Button
          className='admin-reservation-detail-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_RESERVATION_LIST_PATH) })}
        >去登录</Button>
      </AdminReservationDetailState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <AdminReservationDetailState title='无管理权限' description='当前账号不会请求任何管理预约 API' />
  }
  return <AuthenticatedAdminReservationDetail reservationId={route.reservationId} />
}

export function AuthenticatedAdminReservationDetail({ reservationId }: { readonly reservationId: number }) {
  const detail = useAdminReservationDetail(reservationId)
  if (detail.detail.status === 'loading') {
    return <AdminReservationDetailState title='正在加载预约…' description='正在读取顾客联系方式与预约状态' />
  }
  if (detail.detail.status === 'error') {
    return (
      <AdminReservationDetailState title='管理预约详情加载失败' description={detail.detail.errorMessage}>
        <Button className='admin-reservation-detail-state__action' onClick={detail.retry}>重新加载</Button>
        <Button
          className='admin-reservation-detail-state__back'
          onClick={() => void Taro.redirectTo({ url: ADMIN_RESERVATION_LIST_PATH })}
        >返回管理预约</Button>
      </AdminReservationDetailState>
    )
  }

  const item = detail.detail.reservation
  const mutationLocked = detail.mutation.status === 'submitting' || detail.mutation.status === 'unknown'

  async function confirmAction(action: AdminReservationAction): Promise<void> {
    if (item.status.value !== 'pending' || mutationLocked) return
    const rejecting = action === 'reject'
    const confirmation = await Taro.showModal({
      title: rejecting ? '因无空位拒绝预约？' : '确认接受预约？',
      content: rejecting
        ? '顾客侧将看到“当前时段无空位”，并可重新选择日期或时段。拒绝后不能撤回。'
        : '请先人工核对座位。确认后顾客侧会显示“已确认”，并提示按时到店付款。',
      confirmText: rejecting ? '拒绝预约' : '确认预约',
      confirmColor: rejecting ? '#a92f38' : '#196244',
    })
    if (!confirmation.confirm) return
    if (rejecting) await detail.reject()
    else await detail.confirm()
  }

  return (
    <View className='admin-reservation-detail-page'>
      <View className='admin-reservation-detail-heading'>
        <View className='admin-reservation-detail-heading__topline'>
          <Text className='admin-reservation-detail-heading__title'>管理预约详情</Text>
          <Text className={`admin-reservation-detail-heading__status admin-reservation-detail-heading__status--${reservationStatusClass(item)}`}>
            {item.status.label}
          </Text>
        </View>
        <Text className='admin-reservation-detail-heading__name'>{item.product_name}</Text>
        <Text className='admin-reservation-detail-heading__date'>{formatReservationDate(item.reservation_date)}</Text>
        <Text className='admin-reservation-detail-heading__time'>{item.start_time}–{item.end_time}</Text>
      </View>

      <View className='admin-reservation-customer'>
        <Text className='admin-reservation-customer__title'>顾客联系方式</Text>
        <AdminFact label='顾客' value={item.user_nickname} />
        <AdminFact label='手机号' value={item.user_phone ?? '未登记'} />
        <AdminFact label='用户 ID' value={`#${item.user_id}`} />
      </View>

      <View className='admin-reservation-facts'>
        <Text className='admin-reservation-facts__title'>预约快照</Text>
        <AdminFact label='体验配置' value={`${item.duration_minutes} 分钟 · ${item.participants} 人 · ${item.day_type.label}`} />
        <AdminFact label='预约价格' value={`¥${formatPrice(item.price)} · 到店支付`} />
        <AdminFact label='预约编号' value={`#${item.id}`} />
        <AdminFact label='取消截止' value={`${formatShanghaiUtc(item.cancellation_deadline_at)}（北京时间）`} />
        <AdminFact label='提交时间' value={`${formatShanghaiUtc(item.created_at)}（北京时间）`} />
        {item.rejection_reason && <AdminFact label='拒绝原因' value={item.rejection_reason.label} />}
        {item.cancellation_reason && <AdminFact label='取消原因' value={item.cancellation_reason.label} />}
      </View>

      <View className={`admin-reservation-message admin-reservation-message--${reservationStatusClass(item)}`}>
        <Text className='admin-reservation-message__label'>顾客侧当前文案</Text>
        <Text>{item.customer_message}</Text>
      </View>

      {item.status.value === 'pending' && (
        <View className='admin-reservation-decision'>
          <Text className='admin-reservation-decision__title'>处理待确认预约</Text>
          <Text className='admin-reservation-decision__hint'>首版不自动防超额，请根据现场座位人工判断。预约开始后服务端会拒绝操作。</Text>
          <View className='admin-reservation-decision__actions'>
            <Button
              className='admin-reservation-decision__confirm'
              disabled={mutationLocked}
              onClick={() => void confirmAction('confirm')}
            >确认预约</Button>
            <Button
              className='admin-reservation-decision__reject'
              disabled={mutationLocked}
              onClick={() => void confirmAction('reject')}
            >因无空位拒绝</Button>
          </View>
        </View>
      )}

      <AdminMutationFeedback mutation={detail.mutation} retry={detail.retry} />

      <Button
        className='admin-reservation-detail-page__back'
        onClick={() => void Taro.redirectTo({ url: ADMIN_RESERVATION_LIST_PATH })}
      >返回管理预约</Button>
    </View>
  )
}

function AdminFact({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <View className='admin-reservation-fact'>
      <Text className='admin-reservation-fact__label'>{label}</Text>
      <Text className='admin-reservation-fact__value'>{value}</Text>
    </View>
  )
}

function AdminMutationFeedback({ mutation, retry }: {
  readonly mutation: ReturnType<typeof useAdminReservationDetail>['mutation']
  readonly retry: () => void
}) {
  if (mutation.status === 'submitting') {
    return <Text className='admin-reservation-feedback admin-reservation-feedback--pending'>正在提交处理结果…</Text>
  }
  if (mutation.status === 'failed' || mutation.status === 'unknown') {
    return (
      <View className={`admin-reservation-feedback admin-reservation-feedback--${mutation.status}`}>
        <Text>{mutation.errorMessage}</Text>
        {mutation.status === 'unknown' && <Button onClick={retry}>重新加载详情核对</Button>}
      </View>
    )
  }
  if (mutation.status === 'succeeded') {
    return (
      <View className='admin-reservation-feedback admin-reservation-feedback--success'>
        <Text>{mutation.action === 'confirm' ? '预约已确认。' : '预约已因无空位拒绝。'}</Text>
        {mutation.refreshErrorMessage && <Text>{mutation.refreshErrorMessage}</Text>}
      </View>
    )
  }
  return null
}

function AdminReservationDetailState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='admin-reservation-detail-state'>
      <Text className='admin-reservation-detail-state__title'>{title}</Text>
      <Text className='admin-reservation-detail-state__description'>{description}</Text>
      {children}
    </View>
  )
}
