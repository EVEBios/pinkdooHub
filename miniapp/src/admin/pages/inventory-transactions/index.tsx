import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import {
  InventoryFilterPanel,
  InventoryState,
  InventoryTransactionList,
} from '@/admin/components/inventory'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_INVENTORY_LIST_PATH,
  createInventoryInputSnapshot,
  EMPTY_INVENTORY_FILTER_DRAFT,
  EMPTY_INVENTORY_INPUT_SNAPSHOT,
  type InventoryFilterDraft,
  type InventoryInputSnapshot,
  inventoryInputSnapshotsEqual,
  parseInventoryFilters,
  replaceInventorySourceType,
  useInventoryTransactionList,
} from '@/features/inventory'

import './index.scss'

export default function InventoryTransactionsPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <InventoryState title='正在确认管理员身份…' description='全局库存流水仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <InventoryState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='inventory-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </InventoryState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <InventoryState title='登录后查看库存流水' description='登录后会返回全局库存流水，并由服务端再次校验角色'>
        <Button
          className='inventory-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_INVENTORY_LIST_PATH) })}
        >去登录</Button>
      </InventoryState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <InventoryState title='无管理权限' description='当前账号不会请求任何 Inventory API' />
  }
  return <AuthenticatedInventoryTransactions />
}

export function AuthenticatedInventoryTransactions() {
  const list = useInventoryTransactionList({ kind: 'global' })
  const [draft, setDraft] = useState<InventoryFilterDraft>(EMPTY_INVENTORY_FILTER_DRAFT)
  const [filterError, setFilterError] = useState('')
  const [submittedInputs, setSubmittedInputs] = useState<InventoryInputSnapshot>(EMPTY_INVENTORY_INPUT_SNAPSHOT)
  const hasPendingInput = !inventoryInputSnapshotsEqual(
    createInventoryInputSnapshot(draft, { allowProductId: true }),
    submittedInputs,
  )

  function submitFilters(): void {
    const parsed = parseInventoryFilters(draft, { allowProductId: true })
    if (!parsed.filters) {
      setFilterError(parsed.error)
      return
    }
    setFilterError('')
    setSubmittedInputs(createInventoryInputSnapshot(draft, { allowProductId: true }))
    list.applyFilters(parsed.filters)
  }

  function resetFilters(): void {
    setDraft(EMPTY_INVENTORY_FILTER_DRAFT)
    setFilterError('')
    setSubmittedInputs(EMPTY_INVENTORY_INPUT_SNAPSHOT)
    list.applyFilters({ transactionType: 'all', sourceType: 'all' })
  }

  function selectTransactionType(transactionType: InventoryFilterDraft['transactionType']): void {
    setDraft((current) => ({ ...current, transactionType }))
    setFilterError('')
    list.applyFilters({ ...list.filters, transactionType })
  }

  function selectSourceType(sourceType: InventoryFilterDraft['sourceType']): void {
    setDraft((current) => ({
      ...current,
      sourceType,
      ...(sourceType === 'order' ? {} : { sourceId: '' }),
    }))
    if (sourceType !== 'order') {
      setSubmittedInputs((current) => ({ ...current, sourceId: '' }))
    }
    setFilterError('')
    list.applyFilters(replaceInventorySourceType(list.filters, sourceType))
  }

  return (
    <View className='inventory-transactions-page'>
      <View className='inventory-transactions-page__header'>
        <Text className='inventory-transactions-page__eyebrow'>INVENTORY LEDGER</Text>
        <Text className='inventory-transactions-page__title'>库存流水</Text>
        <Text className='inventory-transactions-page__subtitle'>查询管理员调整、订单扣减、取消恢复与期初余额</Text>
      </View>
      <InventoryFilterPanel
        allowProductId
        draft={draft}
        errorMessage={filterError}
        hasPendingInput={hasPendingInput}
        onReset={resetFilters}
        onSelectSourceType={selectSourceType}
        onSelectTransactionType={selectTransactionType}
        onSubmit={submitFilters}
        onUpdate={(patch) => {
          setDraft((current) => ({ ...current, ...patch }))
          setFilterError('')
        }}
      />
      <InventoryTransactionList
        loadNextPage={list.loadNextPage}
        retry={list.retry}
        state={list.state}
      />
    </View>
  )
}
