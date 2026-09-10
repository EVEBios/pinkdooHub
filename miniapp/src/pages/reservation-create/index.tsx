import { Button, Input, Picker, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useRef, useState } from 'react'

import type { ProfileUpdateRequest, UserProfile } from '@/api/endpoints/auth'
import { buildLoginUrl, type AuthContextValue, isAdminRole, useAuth } from '@/auth'
import {
  buildReservationCreateUrl,
  buildReservationDetailUrl,
  formatReservationDate,
  parseReservationCreateRoute,
  RESERVATION_LIST_PATH,
  useReservationCreate,
} from '@/features/reservation'
import { AdminWorkbenchRedirect } from '@/navigation/admin_workbench_redirect'
import { formatPrice } from '@/utils/format'

import './index.scss'

const PHONE_PATTERN = /^1[3-9]\d{9}$/

export default function ReservationCreatePage() {
  const auth = useAuth()
  if (auth.status === 'authenticated') {
    if (!auth.user) {
      return (
        <ReservationCreateState title='账户信息不完整' description='请重新检查登录状态后再提交预约'>
          <Button className='reservation-create-state__action' onClick={auth.retryInitialization}>重新检查</Button>
        </ReservationCreateState>
      )
    }
    if (isAdminRole(auth.user.role)) {
      return <AdminWorkbenchRedirect />
    }
    if (auth.user.role !== 'user') {
      return (
        <ReservationCreateState title='账户角色暂不支持' description='请重新检查登录状态后再提交预约'>
          <Button className='reservation-create-state__action' onClick={auth.retryInitialization}>重新检查</Button>
        </ReservationCreateState>
      )
    }
  }

  return <CustomerReservationCreatePage auth={auth} />
}

function CustomerReservationCreatePage({ auth }: { readonly auth: AuthContextValue }) {
  const route = parseReservationCreateRoute(useRouter().params)
  if (!route) {
    return <ReservationCreateState title='预约地址无效' description='请从拼豆体验详情重新选择配置' />
  }
  if (auth.status === 'initializing') {
    return <ReservationCreateState title='正在确认登录状态…' description='预约只会登记在当前账号下' />
  }
  if (auth.status === 'error') {
    return (
      <ReservationCreateState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='reservation-create-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </ReservationCreateState>
    )
  }
  if (auth.status === 'guest') {
    const redirect = buildReservationCreateUrl(route.productId, route.experienceOptionId)
    return (
      <ReservationCreateState title='登录后提交预约' description='登录后会回到当前体验配置，已选商品不会改变'>
        <Button
          className='reservation-create-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(redirect) })}
        >去登录</Button>
      </ReservationCreateState>
    )
  }
  const customer = auth.user
  if (!customer) {
    return (
      <ReservationCreateState title='账户信息不完整' description='请重新检查登录状态后再提交预约'>
        <Button className='reservation-create-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </ReservationCreateState>
    )
  }
  return (
    <AuthenticatedReservationCreate
      experienceOptionId={route.experienceOptionId}
      initialPhone={customer.phone ?? ''}
      productId={route.productId}
      updateProfile={auth.updateProfile}
    />
  )
}

export function AuthenticatedReservationCreate({
  experienceOptionId,
  initialPhone,
  productId,
  updateProfile,
}: {
  readonly experienceOptionId: number
  readonly initialPhone: string
  readonly productId: number
  readonly updateProfile: (data: ProfileUpdateRequest) => Promise<UserProfile>
}) {
  const reservation = useReservationCreate(productId, experienceOptionId)
  const [phone, setPhone] = useState(initialPhone)
  const [savedPhone, setSavedPhone] = useState(initialPhone)
  const [phoneState, setPhoneState] = useState<
    { readonly status: 'idle' | 'saving' | 'saved' | 'error'; readonly message?: string }
  >({ status: 'idle' })
  const activePhoneSaveRef = useRef<Promise<void>>()
  const normalizedPhone = phone.trim()
  const phoneIsValid = PHONE_PATTERN.test(normalizedPhone)
  const phoneIsSaved = phoneIsValid && normalizedPhone === savedPhone

  function savePhone(): Promise<void> {
    if (activePhoneSaveRef.current) return activePhoneSaveRef.current
    if (!phoneIsValid) {
      setPhoneState({ status: 'error', message: '请输入 11 位中国大陆手机号' })
      return Promise.resolve()
    }
    const active = (async () => {
      setPhoneState({ status: 'saving' })
      try {
        const user = await updateProfile({ phone: normalizedPhone })
        if (user.phone !== normalizedPhone) {
          throw new Error('服务端返回的联系电话与本次保存不一致，请重新加载后再试')
        }
        setPhone(user.phone)
        setSavedPhone(user.phone)
        setPhoneState({ status: 'saved', message: '联系电话已保存，门店可用于核对预约' })
      } catch (cause) {
        setPhoneState({
          status: 'error',
          message: cause instanceof Error ? cause.message : '联系电话保存失败，请重试',
        })
      }
    })()
    activePhoneSaveRef.current = active
    void active.finally(() => {
      if (activePhoneSaveRef.current === active) activePhoneSaveRef.current = undefined
    }).catch(() => undefined)
    return active
  }

  async function submitReservation(): Promise<void> {
    if (!phoneIsSaved) {
      setPhoneState({ status: 'error', message: '请先保存当前联系电话，再提交预约' })
      return
    }
    const result = await reservation.submit()
    if (result) {
      await Taro.redirectTo({ url: buildReservationDetailUrl(result.id) })
    }
  }

  if (reservation.data.status === 'loading') {
    return <ReservationCreateState title='正在读取可预约时间…' description='可选日期与时段均由门店服务端生成' />
  }
  if (reservation.data.status === 'error') {
    return (
      <ReservationCreateState title='预约时间加载失败' description={reservation.data.errorMessage}>
        <Button className='reservation-create-state__action' onClick={reservation.retry}>重新加载</Button>
      </ReservationCreateState>
    )
  }

  const options = reservation.data.options
  if (reservation.data.status === 'empty') {
    return (
      <ReservationCreateState
        title='当前没有可预约时段'
        description={`未来 ${options.booking_window_days} 天内暂无符合当前配置的营业时段`}
      >
        <Button
          className='reservation-create-state__action reservation-create-state__action--secondary'
          onClick={() => void Taro.navigateBack()}
        >重新选择体验配置</Button>
      </ReservationCreateState>
    )
  }

  const selectedDate = options.dates.find((item) => item.date === reservation.reservationDate)
  const dateIndex = Math.max(0, options.dates.findIndex((item) => item.date === reservation.reservationDate))
  const timeIndex = Math.max(0, selectedDate?.start_times.findIndex((item) => item === reservation.startTime) ?? 0)
  const blocked = reservation.submission.status === 'submitting' ||
    reservation.submission.status === 'unknown' || phoneState.status === 'saving'

  return (
    <View className='reservation-create-page'>
      <View className='reservation-create-page__header'>
        <Text className='reservation-create-page__title'>预约拼豆体验</Text>
        <Text className='reservation-create-page__subtitle'>先登记时间，门店确认后到店付款</Text>
      </View>

      <View className='reservation-create-summary'>
        <View className='reservation-create-summary__heading'>
          <Text className='reservation-create-summary__name'>{options.product_name}</Text>
          <Text className='reservation-create-summary__price'>¥{formatPrice(options.price)}</Text>
        </View>
        <Text className='reservation-create-summary__meta'>
          {options.duration_minutes} 分钟 · {options.participants} 人 · {options.day_type.label}
        </Text>
        <Text className='reservation-create-summary__note'>费用采用当前预约价格快照；提交预约不会创建订单或扣款。</Text>
      </View>

      <View className='reservation-create-schedule'>
        <Text className='reservation-create-schedule__title'>选择到店时间</Text>
        <Text className='reservation-create-schedule__hint'>仅显示至少三小时后、可完整结束于营业时间内的时段</Text>
        <Picker
          disabled={blocked}
          mode='selector'
          range={options.dates.map((item) => formatReservationDate(item.date))}
          value={dateIndex}
          onChange={(event) => {
            const item = options.dates[Number(event.detail.value)]
            if (item) reservation.selectDate(item.date)
          }}
        >
          <View className='reservation-create-field'>
            <Text className='reservation-create-field__label'>预约日期</Text>
            <Text className='reservation-create-field__value'>{formatReservationDate(reservation.reservationDate)}</Text>
            <Text className='reservation-create-field__affordance'>更换</Text>
          </View>
        </Picker>
        <Picker
          disabled={blocked}
          mode='selector'
          range={[...(selectedDate?.start_times ?? [])]}
          value={timeIndex}
          onChange={(event) => {
            const value = selectedDate?.start_times[Number(event.detail.value)]
            if (value) reservation.selectStartTime(value)
          }}
        >
          <View className='reservation-create-field'>
            <Text className='reservation-create-field__label'>开始时间</Text>
            <Text className='reservation-create-field__value'>{reservation.startTime}</Text>
            <Text className='reservation-create-field__affordance'>更换</Text>
          </View>
        </Picker>
        <Text className='reservation-create-schedule__business'>
          营业时间 11:00–20:00 · 每{options.weekly_closed_weekday.label}固定店休
        </Text>
      </View>

      <View className='reservation-create-contact'>
        <Text className='reservation-create-contact__title'>联系电话</Text>
        <Text className='reservation-create-contact__hint'>门店处理预约需要手机号；保存后才可提交。</Text>
        <Input
          className='reservation-create-contact__input'
          disabled={blocked}
          maxlength={11}
          placeholder='请输入 11 位手机号'
          type='number'
          value={phone}
          onInput={(event) => {
            setPhone(event.detail.value.replace(/\D/g, '').slice(0, 11))
            setPhoneState({ status: 'idle' })
          }}
        />
        <Button
          className='reservation-create-contact__save'
          disabled={phoneState.status === 'saving' || phoneIsSaved}
          loading={phoneState.status === 'saving'}
          onClick={() => void savePhone()}
        >{phoneIsSaved ? '手机号已保存' : phoneState.status === 'saving' ? '正在保存…' : '保存手机号'}</Button>
        {phoneState.message && (
          <Text className={`reservation-create-feedback reservation-create-feedback--${phoneState.status}`}>
            {phoneState.message}
          </Text>
        )}
      </View>

      <View className='reservation-create-rules'>
        <Text className='reservation-create-rules__title'>提交前请确认</Text>
        <Text>提交后先进入“待门店确认”；店员会根据现场座位确认或因无空位拒绝。</Text>
        <Text>开始前三小时可取消；改期需先取消旧预约，再重新预约，历史记录仍会保留。</Text>
        <Text>首版不会发送微信主动通知，请在“我的预约”查看最新状态。</Text>
      </View>

      {(reservation.submission.status === 'failed' || reservation.submission.status === 'unknown') && (
        <View className={`reservation-create-feedback reservation-create-feedback--${reservation.submission.status}`}>
          <Text>{reservation.submission.errorMessage}</Text>
          {reservation.submission.status === 'unknown' && (
            <Button onClick={() => void Taro.switchTab({ url: RESERVATION_LIST_PATH })}>前往我的预约核对</Button>
          )}
        </View>
      )}
      <Button
        className='reservation-create-page__submit'
        disabled={blocked || !phoneIsSaved}
        loading={reservation.submission.status === 'submitting'}
        onClick={() => void submitReservation()}
      >{reservation.submission.status === 'submitting' ? '正在提交…' : '提交预约申请'}</Button>
    </View>
  )
}

function ReservationCreateState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='reservation-create-page reservation-create-page--state'>
      <Text className='reservation-create-state__title'>{title}</Text>
      <Text className='reservation-create-state__description'>{description}</Text>
      {children}
    </View>
  )
}
