import { Button, Form, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import { MaskedDateInput } from '@/admin/components/masked_date_input'
import type { AdminReservationListItem } from '@/api/endpoints/reservations'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_RESERVATION_LIST_PATH,
  ADMIN_STORE_CLOSURE_LIST_PATH,
  buildAdminReservationDetailUrl,
  EMPTY_ADMIN_RESERVATION_FILTER_DRAFT,
  formatReservationDate,
  type AdminReservationFilterDraft,
  type AdminReservationStatusFilter,
  parseAdminReservationFilters,
  reservationStatusClass,
  useAdminReservationList,
} from '@/features/reservation'
import { formatPrice } from '@/utils/format'

import './index.scss'

const STATUS_FILTERS: ReadonlyArray<{ value: AdminReservationStatusFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待确认' },
  { value: 'confirmed', label: '已确认' },
  { value: 'rejected', label: '未能确认' },
  { value: 'cancelled', label: '已取消' },
]

const EMPTY_SIGNATURE = buildSignature(EMPTY_ADMIN_RESERVATION_FILTER_DRAFT)

export default function AdminReservationsPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <AdminReservationsState title='正在确认管理员身份…' description='管理预约仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <AdminReservationsState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='admin-reservations-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </AdminReservationsState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <AdminReservationsState title='登录后管理预约' description='登录后仍会根据服务端角色校验权限'>
        <Button
          className='admin-reservations-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_RESERVATION_LIST_PATH) })}
        >去登录</Button>
      </AdminReservationsState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <AdminReservationsState title='无管理权限' description='当前账号不会请求任何管理预约 API' />
  }
  return <AuthenticatedAdminReservations />
}

export function AuthenticatedAdminReservations() {
  const reservations = useAdminReservationList()
  const [draft, setDraft] = useState<AdminReservationFilterDraft>(EMPTY_ADMIN_RESERVATION_FILTER_DRAFT)
  const [filterError, setFilterError] = useState('')
  const [submittedSignature, setSubmittedSignature] = useState(EMPTY_SIGNATURE)
  const pendingInput = buildSignature(draft) !== submittedSignature

  function updateDraft(patch: Partial<AdminReservationFilterDraft>): void {
    setDraft((current) => ({ ...current, ...patch }))
    setFilterError('')
  }

  function selectStatus(status: AdminReservationStatusFilter): void {
    updateDraft({ status })
    reservations.applyFilters({ ...reservations.filters, status })
  }

  function submitFilters(): void {
    const parsed = parseAdminReservationFilters(draft)
    if (!parsed.filters) {
      setFilterError(parsed.error ?? '筛选条件无效')
      return
    }
    setFilterError('')
    setSubmittedSignature(buildSignature(draft))
    reservations.applyFilters(parsed.filters)
  }

  function resetFilters(): void {
    setDraft(EMPTY_ADMIN_RESERVATION_FILTER_DRAFT)
    setFilterError('')
    setSubmittedSignature(EMPTY_SIGNATURE)
    reservations.applyFilters({ status: 'pending' })
  }

  return (
    <View className='admin-reservations-page'>
      <View className='admin-reservations-page__header'>
        <Text className='admin-reservations-page__title'>管理预约</Text>
        <Text className='admin-reservations-page__subtitle'>首版由店员人工判断座位；待确认预约可确认或因无空位拒绝</Text>
        <Button
          className='admin-reservations-page__closures'
          onClick={() => void Taro.navigateTo({ url: ADMIN_STORE_CLOSURE_LIST_PATH })}
        >进入店休设置</Button>
      </View>

      <View className='admin-reservation-filters'>
        <View className='admin-reservation-filters__statuses'>
          {STATUS_FILTERS.map((filter) => (
            <Button
              key={filter.value}
              className={`admin-reservation-filters__status${draft.status === filter.value ? ' admin-reservation-filters__status--active' : ''}`}
              onClick={() => selectStatus(filter.value)}
            >{filter.label}</Button>
          ))}
        </View>
        <Form onSubmit={submitFilters}>
          <MaskedDateInput
            label='预约日期'
            value={draft.businessDate}
            onChange={(businessDate) => updateDraft({ businessDate })}
          />
          <View className='admin-reservation-filters__ids'>
            <Input
              className='admin-reservation-filters__input'
              maxlength={20}
              placeholder='用户 ID'
              type='number'
              value={draft.userId}
              onInput={(event) => updateDraft({ userId: event.detail.value })}
            />
            <Input
              className='admin-reservation-filters__input'
              maxlength={20}
              placeholder='商品 ID'
              type='number'
              value={draft.productId}
              onInput={(event) => updateDraft({ productId: event.detail.value })}
            />
          </View>
          {filterError && <Text className='admin-reservation-filters__error'>{filterError}</Text>}
          {pendingInput && <Text className='admin-reservation-filters__pending'>日期或 ID 尚未应用</Text>}
          <Text className='admin-reservation-filters__hint'>状态点击后立即生效；日期与 ID 需点击“应用筛选”。</Text>
          <View className='admin-reservation-filters__actions'>
            <Button formType='submit'>应用筛选</Button>
            <Button onClick={resetFilters}>重置为待确认</Button>
          </View>
        </Form>
      </View>

      {reservations.state.status === 'loading' && <AdminReservationsState title='正在加载预约…' description='正在读取服务端预约队列' />}
      {reservations.state.status === 'empty' && <AdminReservationsState title='当前筛选下没有预约' description='可以调整状态、日期、用户或商品筛选' />}
      {reservations.state.status === 'error' && (
        <AdminReservationsState title='管理预约加载失败' description={reservations.state.errorMessage ?? '请稍后重试'}>
          <Button className='admin-reservations-state__action' onClick={reservations.retry}>重新加载</Button>
        </AdminReservationsState>
      )}
      {reservations.state.status === 'content' && (
        <View className='admin-reservations-content'>
          <View className='admin-reservations-content__summary'>
            <Text>已加载 {reservations.state.items.length} 条</Text>
            <Text>共 {reservations.state.total} 条</Text>
          </View>
          {reservations.state.items.map((item) => <AdminReservationCard key={item.id} reservation={item} />)}
          {reservations.state.errorMessage && <Text className='admin-reservations-content__error'>{reservations.state.errorMessage}</Text>}
          {reservations.state.page < reservations.state.pages ? (
            <Button
              className='admin-reservations-content__load-more'
              disabled={reservations.state.loadingMore}
              onClick={reservations.loadNextPage}
            >{reservations.state.loadingMore ? '正在加载…' : '加载更多'}</Button>
          ) : <Text className='admin-reservations-content__end'>已经到底了</Text>}
        </View>
      )}
    </View>
  )
}

function AdminReservationCard({ reservation }: { readonly reservation: AdminReservationListItem }) {
  return (
    <View
      className='admin-reservation-card'
      onClick={() => void Taro.navigateTo({ url: buildAdminReservationDetailUrl(reservation.id) })}
    >
      <View className='admin-reservation-card__heading'>
        <Text className='admin-reservation-card__name'>{reservation.product_name}</Text>
        <Text className={`admin-reservation-card__status admin-reservation-card__status--${reservationStatusClass(reservation)}`}>
          {reservation.status.label}
        </Text>
      </View>
      <Text className='admin-reservation-card__customer'>
        {reservation.user_nickname} · {reservation.user_phone_masked ?? '未登记手机号'} · 用户 #{reservation.user_id}
      </Text>
      <Text className='admin-reservation-card__date'>{formatReservationDate(reservation.reservation_date)}</Text>
      <Text className='admin-reservation-card__time'>{reservation.start_time}–{reservation.end_time}</Text>
      <View className='admin-reservation-card__summary'>
        <Text>{reservation.participants} 人 · {reservation.duration_minutes} 分钟</Text>
        <Text className='admin-reservation-card__price'>¥{formatPrice(reservation.price)}</Text>
      </View>
    </View>
  )
}

function buildSignature(draft: AdminReservationFilterDraft): string {
  return `${draft.businessDate}|${draft.userId}|${draft.productId}`
}

function AdminReservationsState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='admin-reservations-state'>
      <Text className='admin-reservations-state__title'>{title}</Text>
      <Text className='admin-reservations-state__description'>{description}</Text>
      {children}
    </View>
  )
}
