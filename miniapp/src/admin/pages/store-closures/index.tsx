import { Button, Picker, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import type { StoreBusinessDay, StoreClosureMutation } from '@/api/endpoints/reservations'
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
  const isMonday = weekday(selectedDate) === 1
  const selectedIsClosed = closures.list.status === 'content' &&
    closures.list.items.some((item) => item.business_date === selectedDate) ||
    closures.mutation.status === 'reconciled' &&
      closures.mutation.businessDate === selectedDate && closures.mutation.isClosed
  const locked = closures.mutation.status === 'submitting' || closures.mutation.status === 'unknown'

  async function closeSelectedDate(): Promise<void> {
    if (!selectedDate || isMonday || selectedIsClosed || locked) return
    const confirmation = await Taro.showModal({
      title: `将 ${selectedDate} 设为店休？`,
      content: '该日已有的待确认和已确认预约会在同一事务中批量取消，原因统一为“门店店休”。顾客可在“我的预约”查看结果；N1 暂不发送微信主动通知。',
      confirmText: '设为店休',
      confirmColor: '#a92f38',
    })
    if (confirmation.confirm) await closures.close(selectedDate)
  }

  async function reopen(day: StoreBusinessDay): Promise<void> {
    if (locked) return
    const confirmation = await Taro.showModal({
      title: `恢复 ${day.business_date} 营业？`,
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
        <Text className='store-closures-page__subtitle'>为某个日期暂停预约，并批量取消当日尚未开始的待确认或已确认预约</Text>
        <Button
          className='store-closures-page__reservations'
          onClick={() => void Taro.navigateTo({ url: ADMIN_RESERVATION_LIST_PATH })}
        >返回管理预约</Button>
      </View>

      <View className='store-closure-editor'>
        <Text className='store-closure-editor__title'>新增店休日期</Text>
        <Text className='store-closure-editor__hint'>周一固定店休；这里用于临时休息、包场或其他额外闭店日期。</Text>
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
            <Text className='store-closure-editor__date-action'>更换</Text>
          </View>
        </Picker>
        {isMonday && <Text className='store-closure-editor__warning'>周一已经固定店休，无需重复设置。</Text>}
        {selectedIsClosed && <Text className='store-closure-editor__success'>该日期已在自定义店休列表中。</Text>}
        <Button
          className='store-closure-editor__submit'
          disabled={isMonday || selectedIsClosed || locked}
          loading={closures.mutation.status === 'submitting' && closures.mutation.action === 'close'}
          onClick={() => void closeSelectedDate()}
        >{closures.mutation.status === 'submitting' && closures.mutation.action === 'close' ? '正在批量处理…' : '设为店休并取消已有预约'}</Button>
      </View>

      <ClosureMutationFeedback mutation={closures.mutation} reconcile={closures.reconcile} />

      <View className='store-closures-list'>
        <View className='store-closures-list__heading'>
          <Text className='store-closures-list__title'>自定义店休</Text>
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
          <StoreClosuresState title='暂无自定义店休' description='周一固定店休仍然有效，不会列在这里' />
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
            >恢复营业</Button>
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

function weekday(value: string): number | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return undefined
  return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))).getUTCDay()
}
