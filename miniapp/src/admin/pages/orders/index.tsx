import { Button, Form, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import type { AdminOrderListItem } from '@/api/endpoints/orders'
import { MaskedDateInput } from '@/admin/components/masked_date_input'
import { buildLoginUrl, useAuth } from '@/auth'
import {
  ADMIN_ORDER_LIST_PATH,
  buildAdminOrderDetailUrl,
  EMPTY_ADMIN_ORDER_FILTER_DRAFT,
  type AdminOrderFilterDraft,
  type AdminOrderStatusFilter,
  isAdminRole,
  parseAdminOrderFilters,
  useAdminOrderList,
} from '@/features/order'
import { formatPrice } from '@/utils/format'

import './index.scss'

const STATUS_FILTERS: ReadonlyArray<{ value: AdminOrderStatusFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待支付' },
  { value: 'paid', label: '已支付' },
  { value: 'cancelled', label: '已取消' },
  { value: 'completed', label: '已完成' },
]

const EMPTY_INPUT_SIGNATURE = buildInputSignature(EMPTY_ADMIN_ORDER_FILTER_DRAFT)

export default function AdminOrdersPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <AdminOrdersState title='正在确认管理员身份…' description='管理订单仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <AdminOrdersState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='admin-orders-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </AdminOrdersState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <AdminOrdersState title='登录后进入管理订单' description='登录后仍会根据服务端角色校验权限'>
        <Button
          className='admin-orders-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_ORDER_LIST_PATH) })}
        >
          去登录
        </Button>
      </AdminOrdersState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <AdminOrdersState title='无管理权限' description='当前账号不会请求任何管理端订单 API' />
  }
  return <AuthenticatedAdminOrders />
}

export function AuthenticatedAdminOrders() {
  const { applyFilters, filters, loadNextPage, retry, state } = useAdminOrderList()
  const [draft, setDraft] = useState<AdminOrderFilterDraft>(EMPTY_ADMIN_ORDER_FILTER_DRAFT)
  const [filterError, setFilterError] = useState('')
  const [submittedInputSignature, setSubmittedInputSignature] = useState(EMPTY_INPUT_SIGNATURE)
  const hasPendingInput = buildInputSignature(draft) !== submittedInputSignature

  function updateDraft(patch: Partial<AdminOrderFilterDraft>): void {
    setDraft((current) => ({ ...current, ...patch }))
    setFilterError('')
  }

  function submitFilters(): void {
    const parsed = parseAdminOrderFilters(draft)
    if (!parsed.filters) {
      setFilterError(parsed.error ?? '筛选条件无效')
      return
    }
    setFilterError('')
    setSubmittedInputSignature(buildInputSignature(draft))
    applyFilters(parsed.filters)
  }

  function selectStatus(status: AdminOrderStatusFilter): void {
    updateDraft({ status })
    setFilterError('')
    applyFilters({ ...filters, status })
  }

  function resetFilters(): void {
    setDraft(EMPTY_ADMIN_ORDER_FILTER_DRAFT)
    setFilterError('')
    setSubmittedInputSignature(EMPTY_INPUT_SIGNATURE)
    applyFilters({ status: 'all' })
  }

  return (
    <View className='admin-orders-page'>
      <View className='admin-orders-page__header'>
        <Text className='admin-orders-page__title'>管理订单</Text>
        <Text className='admin-orders-page__subtitle'>查询全部用户订单，并执行契约允许的状态变迁</Text>
      </View>

      <View className='admin-order-filters'>
        <Form onSubmit={submitFilters}>
          <View className='admin-order-filters__statuses'>
            {STATUS_FILTERS.map((filter) => (
              <Button
                key={filter.value}
                className={`admin-order-filters__status${draft.status === filter.value ? ' admin-order-filters__status--active' : ''}`}
                onClick={() => selectStatus(filter.value)}
              >
                {filter.label}
              </Button>
            ))}
          </View>
          <Input
            className='admin-order-filters__input'
            maxlength={100}
            placeholder='商品名称（支持部分匹配）'
            value={draft.productName}
            onInput={(event) => updateDraft({ productName: event.detail.value })}
          />
          <Input
            className='admin-order-filters__input'
            maxlength={28}
            placeholder='精确订单号（可选）'
            value={draft.orderNo}
            onInput={(event) => updateDraft({ orderNo: event.detail.value })}
          />
          <Input
            className='admin-order-filters__input'
            maxlength={16}
            placeholder='用户 ID（可选）'
            type='number'
            value={draft.userId}
            onInput={(event) => updateDraft({ userId: event.detail.value })}
          />
          <View className='admin-order-filters__dates'>
            <MaskedDateInput
              label='开始日期（UTC）'
              value={draft.createdFrom}
              onChange={(createdFrom) => updateDraft({ createdFrom })}
            />
            <MaskedDateInput
              label='结束日期（UTC）'
              value={draft.createdTo}
              onChange={(createdTo) => updateDraft({ createdTo })}
            />
          </View>
          {filterError && <Text className='admin-order-filters__error'>{filterError}</Text>}
          {hasPendingInput && (
            <Text className='admin-order-filters__pending'>输入条件尚未应用，点击「查询」后生效</Text>
          )}
          <View className='admin-order-filters__actions'>
            <Button type='primary' onClick={submitFilters}>查询</Button>
            <Button onClick={resetFilters}>清空</Button>
          </View>
          <Text className='admin-order-filters__hint'>结束日期按当日包含处理，客户端会转为 API 要求的次日排他上界。</Text>
        </Form>
      </View>

      {state.status === 'loading' && <AdminOrdersState title='正在加载管理订单…' description='正在读取服务端第一页' />}
      {state.status === 'empty' && <AdminOrdersState title='当前筛选下没有订单' description='可清空筛选后重试' />}
      {state.status === 'error' && (
        <AdminOrdersState title='管理订单加载失败' description={state.errorMessage ?? '请稍后重试'}>
          <Button className='admin-orders-state__action' onClick={retry}>重新加载</Button>
        </AdminOrdersState>
      )}
      {state.status === 'content' && (
        <View className='admin-orders-content'>
          <View className='admin-orders-content__summary'>
            <Text>已加载 {state.items.length} 单</Text>
            <Text>共 {state.total} 单</Text>
          </View>
          {state.items.map((order) => <AdminOrderCard key={order.id} order={order} />)}
          {state.errorMessage && <Text className='admin-orders-content__error'>{state.errorMessage}</Text>}
          {state.page < state.pages ? (
            <Button disabled={state.loadingMore} onClick={loadNextPage}>
              {state.loadingMore ? '正在加载…' : state.errorMessage ? '重试加载更多' : '加载更多'}
            </Button>
          ) : <Text className='admin-orders-content__end'>已经到底了</Text>}
        </View>
      )}
      {(filters.status !== 'all' || filters.productName) && (
        <Text className='admin-orders-page__active-filter'>
          {filters.status !== 'all' ? `当前状态：${filters.status}` : ''}
          {filters.status !== 'all' && filters.productName ? ' · ' : ''}
          {filters.productName ? `商品名称：${filters.productName}` : ''}
        </Text>
      )}
    </View>
  )
}

function buildInputSignature(draft: AdminOrderFilterDraft): string {
  return JSON.stringify([
    draft.productName.trim(),
    draft.orderNo.trim().toUpperCase(),
    draft.userId.trim(),
    draft.createdFrom.trim(),
    draft.createdTo.trim(),
  ])
}

function AdminOrderCard({ order }: { readonly order: AdminOrderListItem }) {
  return (
    <View
      className='admin-order-card'
      onClick={() => void Taro.navigateTo({ url: buildAdminOrderDetailUrl(order.id) })}
    >
      <View className='admin-order-card__heading'>
        <Text className='admin-order-card__number'>{order.order_no}</Text>
        <Text className={`admin-order-card__status admin-order-card__status--${order.status.value}`}>{order.status.label}</Text>
      </View>
      <Text className='admin-order-card__user'>用户 #{order.user_id} · {order.user_nickname}</Text>
      <View className='admin-order-card__summary'>
        <Text>{order.item_count} 种商品配置</Text>
        <Text className='admin-order-card__total'>¥{formatPrice(order.total_amount)}</Text>
      </View>
      <Text className='admin-order-card__time'>创建时间：{order.created_at}</Text>
    </View>
  )
}

function AdminOrdersState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='admin-orders-state'>
      <Text className='admin-orders-state__title'>{title}</Text>
      <Text className='admin-orders-state__description'>{description}</Text>
      {children}
    </View>
  )
}
