import { Button, Form, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import type { InventoryTransaction } from '@/api/endpoints/inventory'
import type {
  InventoryFilterDraft,
  InventorySourceTypeFilter,
  InventoryTransactionListState,
  InventoryTransactionTypeFilter,
} from '@/features/inventory'
import { buildAdminOrderDetailUrl } from '@/features/order'

const TRANSACTION_TYPES: ReadonlyArray<{ value: InventoryTransactionTypeFilter; label: string }> = [
  { value: 'all', label: '全部类型' },
  { value: 'opening_balance', label: '期初余额' },
  { value: 'admin_adjustment', label: '管理员调整' },
  { value: 'order_deduction', label: '订单扣减' },
  { value: 'order_cancellation_restore', label: '取消恢复' },
]
const SOURCE_TYPES: ReadonlyArray<{ value: InventorySourceTypeFilter; label: string }> = [
  { value: 'all', label: '全部来源' },
  { value: 'migration', label: '迁移' },
  { value: 'admin', label: '管理员' },
  { value: 'order', label: '订单' },
]
const TRANSACTION_LABELS: Readonly<Record<Exclude<InventoryTransactionTypeFilter, 'all'>, string>> = {
  opening_balance: '期初余额',
  admin_adjustment: '管理员调整',
  order_deduction: '订单扣减',
  order_cancellation_restore: '取消恢复',
}
const SOURCE_LABELS: Readonly<Record<Exclude<InventorySourceTypeFilter, 'all'>, string>> = {
  migration: '迁移',
  admin: '管理员',
  order: '订单',
}

export function InventoryFilterPanel({
  allowProductId,
  draft,
  errorMessage,
  onReset,
  onSubmit,
  onUpdate,
}: {
  readonly allowProductId: boolean
  readonly draft: InventoryFilterDraft
  readonly errorMessage: string
  readonly onUpdate: (patch: Partial<InventoryFilterDraft>) => void
  readonly onSubmit: () => void
  readonly onReset: () => void
}) {
  return (
    <View className='inventory-filters'>
      <Form onSubmit={onSubmit}>
        <Text className='inventory-filters__label'>流水类型</Text>
        <View className='inventory-filters__choices'>
          {TRANSACTION_TYPES.map((item) => (
            <Button
              key={item.value}
              className={draft.transactionType === item.value ? 'inventory-filters__choice--active' : ''}
              size='mini'
              onClick={() => onUpdate({ transactionType: item.value })}
            >{item.label}</Button>
          ))}
        </View>
        <Text className='inventory-filters__label'>来源</Text>
        <View className='inventory-filters__choices'>
          {SOURCE_TYPES.map((item) => (
            <Button
              key={item.value}
              className={draft.sourceType === item.value ? 'inventory-filters__choice--active' : ''}
              size='mini'
              onClick={() => onUpdate({
                sourceType: item.value,
                ...(item.value === 'order' ? {} : { sourceId: '' }),
              })}
            >{item.label}</Button>
          ))}
        </View>
        {allowProductId && (
          <Input
            className='inventory-filters__input'
            maxlength={16}
            placeholder='Product ID（可选）'
            type='number'
            value={draft.productId}
            onInput={(event) => onUpdate({ productId: event.detail.value })}
          />
        )}
        <Input
          className='inventory-filters__input'
          maxlength={16}
          disabled={draft.sourceType !== 'order'}
          placeholder={draft.sourceType === 'order' ? 'Order source ID（可选）' : '选择“订单”后可填写 source ID'}
          type='number'
          value={draft.sourceId}
          onInput={(event) => onUpdate({ sourceId: event.detail.value })}
        />
        <Input
          className='inventory-filters__input'
          maxlength={10}
          placeholder='开始 UTC 日期 YYYY-MM-DD'
          value={draft.createdFrom}
          onInput={(event) => onUpdate({ createdFrom: event.detail.value })}
        />
        <Input
          className='inventory-filters__input'
          maxlength={10}
          placeholder='结束 UTC 日期 YYYY-MM-DD'
          value={draft.createdTo}
          onInput={(event) => onUpdate({ createdTo: event.detail.value })}
        />
        {errorMessage && <Text className='inventory-filters__error'>{errorMessage}</Text>}
        <View className='inventory-filters__actions'>
          <Button formType='submit' type='primary'>查询</Button>
          <Button className='inventory-filters__reset' onClick={onReset}>清空</Button>
        </View>
        <Text className='inventory-filters__hint'>日期按 UTC 解释；结束日期会转换为次日零点的排他上界。</Text>
      </Form>
    </View>
  )
}

export function InventoryTransactionList({ loadNextPage, retry, state }: {
  readonly state: InventoryTransactionListState
  readonly retry: () => void
  readonly loadNextPage: () => void
}) {
  if (state.status === 'loading') {
    return <InventoryState title='正在加载库存流水…' description='正在读取服务端第一页' />
  }
  if (state.status === 'empty') {
    return <InventoryState title='当前筛选下没有流水' description='可清空筛选后重试' />
  }
  if (state.status === 'error') {
    return (
      <InventoryState title='库存流水加载失败' description={state.errorMessage ?? '请稍后重试'}>
        <Button className='inventory-state__action' onClick={retry}>重新加载</Button>
      </InventoryState>
    )
  }
  return (
    <View className='inventory-list'>
      <View className='inventory-list__summary'>
        <Text>已加载 {state.items.length} 条</Text>
        <Text>共 {state.total} 条</Text>
      </View>
      {state.items.map((transaction) => (
        <InventoryTransactionCard key={transaction.id} transaction={transaction} />
      ))}
      {state.errorMessage && <Text className='inventory-list__error'>{state.errorMessage}</Text>}
      {state.page < state.pages ? (
        <Button disabled={state.loadingMore} onClick={loadNextPage}>
          {state.loadingMore ? '正在加载…' : state.errorMessage ? '重试加载更多' : '加载更多'}
        </Button>
      ) : <Text className='inventory-list__end'>已经到底了</Text>}
    </View>
  )
}

export function InventoryTransactionCard({ transaction }: {
  readonly transaction: InventoryTransaction
}) {
  const positive = transaction.change_quantity > 0
  const sourceOrderId = transaction.source_id
  return (
    <View className='inventory-card'>
      <View className='inventory-card__heading'>
        <Text className='inventory-card__type'>{TRANSACTION_LABELS[transaction.transaction_type]}</Text>
        <Text className={`inventory-card__change inventory-card__change--${positive ? 'positive' : 'negative'}`}>
          {positive ? '+' : ''}{transaction.change_quantity}
        </Text>
      </View>
      <Text className='inventory-card__product'>Product #{transaction.product_id} · 流水 #{transaction.id}</Text>
      <Text className='inventory-card__balance'>余额：{transaction.before_quantity} → {transaction.after_quantity}</Text>
      <Text className='inventory-card__reason'>原因：{transaction.reason}</Text>
      <Text className='inventory-card__meta'>来源：{SOURCE_LABELS[transaction.source_type]}</Text>
      {transaction.operator_id && (
        <Text className='inventory-card__meta'>操作人：#{transaction.operator_id} · {transaction.operator_nickname}</Text>
      )}
      {sourceOrderId && transaction.source_order_no && (
        <Button
          className='inventory-card__order'
          size='mini'
          onClick={() => void Taro.navigateTo({ url: buildAdminOrderDetailUrl(sourceOrderId) })}
        >订单 {transaction.source_order_no}</Button>
      )}
      <Text className='inventory-card__time'>UTC：{transaction.created_at}</Text>
    </View>
  )
}

export function InventoryState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='inventory-state'>
      <Text className='inventory-state__title'>{title}</Text>
      <Text className='inventory-state__description'>{description}</Text>
      {children}
    </View>
  )
}
