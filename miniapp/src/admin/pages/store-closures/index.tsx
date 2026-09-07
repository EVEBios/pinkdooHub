import { Button, Picker, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useState } from 'react'

import type {
  ReservationWeekday,
  StoreBusinessDay,
  StoreClosureMutation,
  WeeklyClosureMutation,
} from '@/api/endpoints/reservations'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_RESERVATION_LIST_PATH,
  ADMIN_STORE_CLOSURE_LIST_PATH,
  formatReservationDate,
  useStoreClosures,
} from '@/features/reservation'

import './index.scss'

export default function StoreClosuresPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <StoreClosuresState title='正在确认管理员身份…' description='店休设置仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <StoreClosuresState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='store-closures-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </StoreClosuresState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <StoreClosuresState title='登录后设置店休' description='登录后仍会根据服务端角色校验权限'>
        <Button
          className='store-closures-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_STORE_CLOSURE_LIST_PATH) })}
        >去登录</Button>
      </StoreClosuresState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <StoreClosuresState title='无管理权限' description='当前账号不会请求任何店休管理 API' />
  }
  return <AuthenticatedStoreClosures />
}

export function AuthenticatedStoreClosures() {
  const closures = useStoreClosures()
  const today = shanghaiToday()
  const [selectedDate, setSelectedDate] = useState(today)
  const [selectedWeekday, setSelectedWeekday] = useState<ReservationWeekday>('monday')
  const currentWeekday = closures.settings.status === 'content'
    ? closures.settings.value.weekly_closed_weekday
    : undefined
  const currentWeekdayValue = currentWeekday?.value
  useEffect(() => {
    if (currentWeekdayValue) setSelectedWeekday(currentWeekdayValue)
  }, [currentWeekdayValue])
  const selectedDateWeekday = weekdayValue(selectedDate)
  const isWeeklyClosedDate = currentWeekday?.value === selectedDateWeekday
  const selectedIsClosed = closures.list.status === 'content' &&
    closures.list.items.some((item) => item.business_date === selectedDate) ||
    closures.mutation.status === 'reconciled' &&
      closures.mutation.businessDate === selectedDate && closures.mutation.isClosed
  const locked = closures.mutation.status === 'submitting' || closures.mutation.status === 'unknown' ||
    closures.weeklyMutation.status === 'submitting' || closures.weeklyMutation.status === 'unknown'

  async function changeWeeklyClosedDay(): Promise<void> {
    if (!currentWeekday || selectedWeekday === currentWeekday.value || locked) return
    const nextLabel = weekdayLabel(selectedWeekday)
    const confirmation = await Taro.showModal({
      title: `更换为每${nextLabel}固定店休？`,
      content: `更换后，每${currentWeekday.label}立即恢复可预约；未来 30 天内每${nextLabel}尚未开始的待确认和已确认预约会统一取消。已添加的单日店休不受影响，历史预约不会恢复。`,
      confirmText: '确认更换',
      confirmColor: '#a92f38',
    })
    if (confirmation.confirm) await closures.changeWeeklyClosedDay(selectedWeekday)
  }

  async function closeSelectedDate(): Promise<void> {
    if (!selectedDate || isWeeklyClosedDate || selectedIsClosed || locked) return
    const confirmation = await Taro.showModal({
      title: `添加 ${formatReservationDate(selectedDate)} 为单日店休？`,
      content: '只关闭这一天，不改变每周固定店休。该日尚未开始的待确认和已确认预约会统一取消，顾客可在“我的预约”查看结果；首版暂不发送微信主动通知。',
      confirmText: '确认添加',
      confirmColor: '#a92f38',
    })
    if (confirmation.confirm) await closures.close(selectedDate)
  }

  async function reopen(day: StoreBusinessDay): Promise<void> {
    if (locked) return
    const confirmation = await Taro.showModal({
      title: `恢复 ${formatReservationDate(day.business_date)} 营业？`,
      content: '恢复营业只移除自定义店休，不会恢复或改写此前被取消的预约历史。',
      confirmText: '恢复营业',
      confirmColor: '#196244',
    })
    if (confirmation.confirm) await closures.reopen(day.business_date)
  }

  return (
    <View className='store-closures-page'>
      <View className='store-closures-page__header'>
        <Text className='store-closures-page__title'>店休设置</Text>
        <Text className='store-closures-page__subtitle'>管理每周固定店休日，也可以临时关闭某一个日期</Text>
        <Button
          className='store-closures-page__reservations'
          onClick={() => void Taro.navigateTo({ url: ADMIN_RESERVATION_LIST_PATH })}
        >返回管理预约</Button>
      </View>

      <View className='store-closure-editor store-closure-editor--weekly'>
        <Text className='store-closure-editor__eyebrow'>长期排班</Text>
        <Text className='store-closure-editor__title'>每周固定店休</Text>
        <Text className='store-closure-editor__hint'>每周重复生效，适合门店的长期固定休息日。</Text>
        {closures.settings.status === 'loading' && <Text className='store-closure-editor__status'>正在读取当前设置…</Text>}
        {closures.settings.status === 'error' && (
          <View className='store-closure-editor__inline-error'>
            <Text>{closures.settings.errorMessage}</Text>
            <Button onClick={closures.retrySettings}>重新加载</Button>
          </View>
        )}
        {currentWeekday && (
          <>
            <View className='store-closure-editor__current-rule'>
              <Text className='store-closure-editor__current-label'>当前固定店休日</Text>
              <Text className='store-closure-editor__current-value'>每{currentWeekday.label}</Text>
            </View>
            <Picker
              mode='selector'
              range={WEEKDAYS.map((item) => item.label)}
              value={Math.max(0, WEEKDAYS.findIndex((item) => item.value === selectedWeekday))}
              onChange={(event) => setSelectedWeekday(WEEKDAYS[Number(event.detail.value)]?.value ?? currentWeekday.value)}
            >
              <View className='store-closure-editor__date-field'>
                <Text className='store-closure-editor__date-label'>新的固定店休日</Text>
                <Text className='store-closure-editor__date-value'>每{weekdayLabel(selectedWeekday)}</Text>
                <Text className='store-closure-editor__date-action'>选择星期</Text>
              </View>
            </Picker>
            {selectedWeekday === currentWeekday.value && (
              <Text className='store-closure-editor__neutral'>请选择与当前设置不同的星期。</Text>
            )}
            <Button
              className='store-closure-editor__submit store-closure-editor__submit--weekly'
              disabled={selectedWeekday === currentWeekday.value || locked}
              loading={closures.weeklyMutation.status === 'submitting'}
              onClick={() => void changeWeeklyClosedDay()}
            >{closures.weeklyMutation.status === 'submitting' ? '正在更换…' : '更换固定店休日'}</Button>
          </>
        )}
      </View>

      <WeeklyClosureFeedback mutation={closures.weeklyMutation} reconcile={closures.reconcileWeekly} />

      <View className='store-closure-editor store-closure-editor--single'>
        <Text className='store-closure-editor__eyebrow'>临时安排</Text>
        <Text className='store-closure-editor__title'>添加单日店休</Text>
        <Text className='store-closure-editor__hint'>只关闭所选日期，不改变每周固定店休日。</Text>
        <Picker
          end='2099-12-31'
          mode='date'
          start={today}
          value={selectedDate}
          onChange={(event) => setSelectedDate(String(event.detail.value))}
        >
          <View className='store-closure-editor__date-field'>
            <Text className='store-closure-editor__date-label'>店休日期</Text>
            <Text className='store-closure-editor__date-value'>{formatReservationDate(selectedDate)}</Text>
            <Text className='store-closure-editor__date-action'>选择日期</Text>
          </View>
        </Picker>
        {isWeeklyClosedDate && <Text className='store-closure-editor__warning'>该日期已是每周固定店休日，无需重复添加。</Text>}
        {selectedIsClosed && <Text className='store-closure-editor__success'>该日期已添加为单日店休。</Text>}
        <Button
          className='store-closure-editor__submit'
          disabled={!currentWeekday || isWeeklyClosedDate || selectedIsClosed || locked}
          loading={closures.mutation.status === 'submitting' && closures.mutation.action === 'close'}
          onClick={() => void closeSelectedDate()}
        >{closures.mutation.status === 'submitting' && closures.mutation.action === 'close' ? '正在添加…' : '添加单日店休'}</Button>
      </View>

      <ClosureMutationFeedback mutation={closures.mutation} reconcile={closures.reconcile} />

      <View className='store-closures-list'>
        <View className='store-closures-list__heading'>
          <Text className='store-closures-list__title'>已添加的单日店休</Text>
          <Text className='store-closures-list__count'>
            {closures.list.status === 'content' ? `共 ${closures.list.total} 天` : '服务端记录'}
          </Text>
        </View>
        {closures.list.status === 'loading' && <StoreClosuresState title='正在加载店休日期…' description='正在读取服务端营业日设置' />}
        {closures.list.status === 'error' && (
          <StoreClosuresState title='店休日期加载失败' description={closures.list.errorMessage}>
            <Button className='store-closures-state__action' onClick={closures.retry}>重新加载</Button>
          </StoreClosuresState>
        )}
        {closures.list.status === 'content' && closures.list.items.length === 0 && (
          <StoreClosuresState title='暂无单日店休' description={`每${currentWeekday?.label ?? '周一'}固定店休仍然有效，不会列在这里`} />
        )}
        {closures.list.status === 'content' && closures.list.items.map((day) => (
          <View className='store-closure-row' key={day.id}>
            <View>
              <Text className='store-closure-row__date'>{formatReservationDate(day.business_date)}</Text>
              <Text className='store-closure-row__meta'>自定义店休 · 当日不可新建预约</Text>
            </View>
            <Button
              className='store-closure-row__reopen'
              disabled={locked}
              onClick={() => void reopen(day)}
            >恢复当天营业</Button>
          </View>
        ))}
        {closures.list.status === 'content' && closures.list.errorMessage && (
          <Text className='store-closures-list__error'>{closures.list.errorMessage}</Text>
        )}
        {closures.list.status === 'content' && closures.list.page < closures.list.pages && (
          <Button
            className='store-closures-list__more'
            disabled={closures.list.loadingMore}
            onClick={closures.loadNextPage}
          >{closures.list.loadingMore ? '正在加载…' : '加载更多'}</Button>
        )}
      </View>
    </View>
  )
}

function WeeklyClosureFeedback({ mutation, reconcile }: {
  readonly mutation: ReturnType<typeof useStoreClosures>['weeklyMutation']
  readonly reconcile: () => Promise<WeeklyClosureMutation | undefined>
}) {
  if (mutation.status === 'failed' || mutation.status === 'unknown') {
    return (
      <View className={`store-closure-feedback store-closure-feedback--${mutation.status}`}>
        <Text>{mutation.errorMessage}</Text>
        {mutation.status === 'unknown' && <Button onClick={reconcile}>核对当前固定店休日</Button>}
      </View>
    )
  }
  if (mutation.status === 'succeeded') {
    const result = mutation.result
    return (
      <View className='store-closure-feedback store-closure-feedback--success'>
        <Text>固定店休日已从每{result.previous_weekly_closed_weekday.label}更换为每{result.weekly_closed_weekday.label}。</Text>
        <Text>本次取消 {result.newly_cancelled_count} 条预约：待确认 {result.cancelled_pending_count} 条，已确认 {result.cancelled_confirmed_count} 条。</Text>
        {result.newly_cancelled_count > 0 && <Text>首版不会主动发送微信通知，请按需人工联系顾客。</Text>}
      </View>
    )
  }
  if (mutation.status === 'reconciled') {
    return <Text className='store-closure-feedback store-closure-feedback--success'>
      {mutation.applied ? `已核对：每${weekdayLabel(mutation.weekday)}为当前固定店休日。` : '已核对：上次更换未生效，可重新提交。'}
    </Text>
  }
  return null
}

function ClosureMutationFeedback({ mutation, reconcile }: {
  readonly mutation: ReturnType<typeof useStoreClosures>['mutation']
  readonly reconcile: () => Promise<StoreClosureMutation | undefined>
}) {
  if (mutation.status === 'failed' || mutation.status === 'unknown') {
    return (
      <View className={`store-closure-feedback store-closure-feedback--${mutation.status}`}>
        <Text>{mutation.errorMessage}</Text>
        {mutation.status === 'unknown' && <Button onClick={reconcile}>重新加载店休列表核对</Button>}
      </View>
    )
  }
  if (mutation.status === 'succeeded') {
    const result = mutation.result
    return mutation.action === 'close' ? (
      <View className='store-closure-feedback store-closure-feedback--success'>
        <Text>{result.is_replay ? '该日期原本已是店休，本次没有重复取消预约。' : '店休已设置。'}</Text>
        <Text>
          本次取消 {result.newly_cancelled_count} 条：待确认 {result.cancelled_pending_count} 条，已确认 {result.cancelled_confirmed_count} 条。
        </Text>
        {result.newly_cancelled_count > 0 && (
          <Text>首版不会主动发送微信通知，请从管理预约详情按需查看手机号并人工联系顾客。</Text>
        )}
      </View>
    ) : <Text className='store-closure-feedback store-closure-feedback--success'>已恢复营业；此前取消的预约历史保持不变。</Text>
  }
  if (mutation.status === 'reconciled') {
    return (
      <Text className='store-closure-feedback store-closure-feedback--success'>
        {mutation.isClosed
          ? `已核对：${mutation.businessDate} 当前为自定义店休。`
          : `已核对：${mutation.businessDate} 当前不在自定义店休中，可按需重新提交。`}
      </Text>
    )
  }
  return null
}

function StoreClosuresState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='store-closures-state'>
      <Text className='store-closures-state__title'>{title}</Text>
      <Text className='store-closures-state__description'>{description}</Text>
      {children}
    </View>
  )
}

function shanghaiToday(): string {
  return new Date(Date.now() + 8 * 60 * 60 * 1_000).toISOString().slice(0, 10)
}

const WEEKDAYS: ReadonlyArray<{ readonly value: ReservationWeekday; readonly label: string }> = [
  { value: 'monday', label: '周一' },
  { value: 'tuesday', label: '周二' },
  { value: 'wednesday', label: '周三' },
  { value: 'thursday', label: '周四' },
  { value: 'friday', label: '周五' },
  { value: 'saturday', label: '周六' },
  { value: 'sunday', label: '周日' },
]

function weekdayLabel(value: ReservationWeekday): string {
  return WEEKDAYS.find((item) => item.value === value)?.label ?? '周一'
}

function weekdayValue(value: string): ReservationWeekday | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return undefined
  const index = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))).getUTCDay()
  return (['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'] as const)[index]
}
