import { Button, Form, Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useState } from 'react'

import {
  InventoryFilterPanel,
  InventoryState,
  InventoryTransactionList,
} from '@/admin/components/inventory'
import type { AdminKitProductDetail } from '@/api/endpoints/admin_products'
import type { InventoryAdjustmentRequest } from '@/api/endpoints/inventory'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  createInventoryInputSnapshot,
  EMPTY_INVENTORY_FILTER_DRAFT,
  EMPTY_INVENTORY_INPUT_SNAPSHOT,
  type InventoryFilterDraft,
  type InventoryInputSnapshot,
  inventoryInputSnapshotsEqual,
  parseInventoryFilters,
  parseKitInventoryRoute,
  replaceInventorySourceType,
  useInventoryAdjustment,
  useInventoryTransactionList,
} from '@/features/inventory'
import {
  ADMIN_PRODUCT_LIST_PATH,
  buildAdminProductDetailUrl,
  useAdminProductDetail,
} from '@/features/product'

import './index.scss'

export default function ProductInventoryPage() {
  const auth = useAuth()
  const route = parseKitInventoryRoute(useRouter().params)
  if (!route) {
    return <InventoryState title='库存管理地址无效' description='请从 Kit 管理详情重新进入' />
  }
  if (auth.status === 'initializing') {
    return <InventoryState title='正在确认管理员身份…' description='库存管理仅对 ADMIN+ 开放' />
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
      <InventoryState title='登录后管理 Kit 库存' description='登录后返回管理商品列表，再选择 Kit 进入库存管理'>
        <Button
          className='inventory-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_PRODUCT_LIST_PATH) })}
        >去登录</Button>
      </InventoryState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <InventoryState title='无管理权限' description='当前账号不会请求任何 Inventory API' />
  }
  return <AuthenticatedProductInventory productId={route.productId} />
}

export function AuthenticatedProductInventory({ productId }: { readonly productId: number }) {
  const detail = useAdminProductDetail(productId, 'kit')
  if (detail.state.status === 'loading') {
    return <InventoryState title='正在加载 Kit…' description='先读取当前权威库存余额' />
  }
  if (detail.state.status === 'error') {
    return (
      <InventoryState title='Kit 管理详情加载失败' description={detail.state.errorMessage}>
        <Button className='inventory-state__action' onClick={detail.retry}>重新加载</Button>
      </InventoryState>
    )
  }
  if (detail.state.product.is_deleted) {
    return (
      <InventoryState title='商品已逻辑删除' description='已删除 Kit 不允许调整或通过指定商品端点查询流水'>
        <Button onClick={() => void Taro.navigateTo({ url: ADMIN_PRODUCT_LIST_PATH })}>返回管理商品</Button>
      </InventoryState>
    )
  }
  if (!('stock' in detail.state.product) || detail.state.product.product_type.value !== 'kit') {
    return <InventoryState title='目标商品不是 Kit' description='Inventory 只管理 Kit 库存' />
  }
  return (
    <KitInventoryWorkspace
      product={detail.state.product}
      refreshProduct={detail.retry}
    />
  )
}

function KitInventoryWorkspace({ product, refreshProduct }: {
  readonly product: AdminKitProductDetail
  readonly refreshProduct: () => void
}) {
  const transactions = useInventoryTransactionList({ kind: 'product', productId: product.id })
  const adjustment = useInventoryAdjustment()
  const [change, setChange] = useState('')
  const [reason, setReason] = useState('')
  const [adjustmentError, setAdjustmentError] = useState('')
  const [filterDraft, setFilterDraft] = useState<InventoryFilterDraft>(EMPTY_INVENTORY_FILTER_DRAFT)
  const [filterError, setFilterError] = useState('')
  const [submittedInputs, setSubmittedInputs] = useState<InventoryInputSnapshot>(EMPTY_INVENTORY_INPUT_SNAPSHOT)
  const hasPendingInput = !inventoryInputSnapshotsEqual(
    createInventoryInputSnapshot(filterDraft, { allowProductId: false }),
    submittedInputs,
  )
  const visibleStock = adjustment.state.status === 'created' || adjustment.state.status === 'replayed'
    ? adjustment.state.result.adjustment.stock
    : product.stock
  const blocked = adjustment.state.status === 'submitting' || adjustment.state.status === 'unknown'

  async function submitAdjustment(): Promise<void> {
    const parsed = parseAdjustment(change, reason)
    if (!parsed.request) {
      setAdjustmentError(parsed.error ?? '库存调整输入无效')
      return
    }
    setAdjustmentError('')
    const result = await adjustment.adjustStock(product.id, parsed.request)
    if (result) {
      setChange('')
      setReason('')
      refreshProduct()
      transactions.retry()
    }
  }

  async function retryUnknown(): Promise<void> {
    const result = await adjustment.retrySameIntent()
    if (result) {
      setChange('')
      setReason('')
      refreshProduct()
      transactions.retry()
    }
  }

  function submitFilters(): void {
    const parsed = parseInventoryFilters(filterDraft, { allowProductId: false })
    if (!parsed.filters) {
      setFilterError(parsed.error)
      return
    }
    setFilterError('')
    setSubmittedInputs(createInventoryInputSnapshot(filterDraft, { allowProductId: false }))
    transactions.applyFilters(parsed.filters)
  }

  function resetFilters(): void {
    setFilterDraft(EMPTY_INVENTORY_FILTER_DRAFT)
    setFilterError('')
    setSubmittedInputs(EMPTY_INVENTORY_INPUT_SNAPSHOT)
    transactions.applyFilters({ transactionType: 'all', sourceType: 'all' })
  }

  function selectTransactionType(transactionType: InventoryFilterDraft['transactionType']): void {
    setFilterDraft((current) => ({ ...current, transactionType }))
    setFilterError('')
    transactions.applyFilters({ ...transactions.filters, transactionType })
  }

  function selectSourceType(sourceType: InventoryFilterDraft['sourceType']): void {
    setFilterDraft((current) => ({
      ...current,
      sourceType,
      ...(sourceType === 'order' ? {} : { sourceId: '' }),
    }))
    if (sourceType !== 'order') {
      setSubmittedInputs((current) => ({ ...current, sourceId: '' }))
    }
    setFilterError('')
    transactions.applyFilters(replaceInventorySourceType(transactions.filters, sourceType))
  }

  const resultMessage = adjustment.state.status === 'created'
    ? `首次调整已提交：库存 ${adjustment.state.result.adjustment.transaction.before_quantity} → ${adjustment.state.result.adjustment.stock}`
    : adjustment.state.status === 'replayed'
      ? `安全重试命中原结果，未重复调整：库存 ${adjustment.state.result.adjustment.stock}`
      : ''
  const mutationError = adjustment.state.status === 'failed' || adjustment.state.status === 'unknown'
    ? adjustment.state.errorMessage
    : ''
  return (
    <View className='product-inventory-page'>
      <View className='product-inventory-page__header'>
        <View className='product-inventory-page__header-topline'>
          <Text className='product-inventory-page__title'>{product.name}</Text>
          <Text className='product-inventory-page__status'>{product.status.label}</Text>
        </View>
        <Text className='product-inventory-page__subtitle'>Kit 商品 · Product #{product.id}</Text>
        <View className='product-inventory-page__stock-panel'>
          <Text className='product-inventory-page__stock-label'>当前权威库存</Text>
          <View className='product-inventory-page__stock-value-row'>
            <Text className='product-inventory-page__stock-value'>{visibleStock}</Text>
            <Text className='product-inventory-page__stock-unit'>件</Text>
          </View>
          <Text className='product-inventory-page__stock-note'>每次变化都会留下可追溯流水</Text>
        </View>
      </View>

      <View className='inventory-adjustment'>
        <Form onSubmit={() => void submitAdjustment()}>
          <Text className='inventory-adjustment__title'>调整库存</Text>
          <Text className='inventory-adjustment__stock'>当前余额：{visibleStock}</Text>
          <Input
            className='inventory-adjustment__input'
            disabled={blocked}
            maxlength={7}
            placeholder='变化量，例如 20 或 -3'
            value={change}
            onInput={(event) => {
              setChange(event.detail.value)
              setAdjustmentError('')
              adjustment.reset()
            }}
          />
          <Input
            className='inventory-adjustment__input'
            disabled={blocked}
            maxlength={256}
            placeholder='原因，例如采购入库或盘点损耗'
            value={reason}
            onInput={(event) => {
              setReason(event.detail.value)
              setAdjustmentError('')
              adjustment.reset()
            }}
          />
          <Text className='inventory-adjustment__hint'>填写变化量，不是最终余额。结果未知时请使用下方安全重试，系统会复用原意图。</Text>
          {(adjustmentError || mutationError) && <Text className='inventory-adjustment__error'>{adjustmentError || mutationError}</Text>}
          {resultMessage && <Text className='inventory-adjustment__success'>{resultMessage}</Text>}
          <Button
            className='inventory-adjustment__submit'
            disabled={blocked}
            type='primary'
            onClick={() => void submitAdjustment()}
          >
            {adjustment.state.status === 'submitting' ? '正在提交…' : '提交库存调整'}
          </Button>
          {adjustment.state.status === 'unknown' && (
            <Button className='inventory-adjustment__retry' onClick={() => void retryUnknown()}>
              安全重试同一次调整
            </Button>
          )}
        </Form>
      </View>

      <InventoryFilterPanel
        allowProductId={false}
        draft={filterDraft}
        errorMessage={filterError}
        hasPendingInput={hasPendingInput}
        onReset={resetFilters}
        onSelectSourceType={selectSourceType}
        onSelectTransactionType={selectTransactionType}
        onSubmit={submitFilters}
        onUpdate={(patch) => {
          setFilterDraft((current) => ({ ...current, ...patch }))
          setFilterError('')
        }}
      />
      <InventoryTransactionList
        loadNextPage={transactions.loadNextPage}
        retry={transactions.retry}
        state={transactions.state}
      />
      <Button
        className='product-inventory-page__back'
        onClick={() => void Taro.redirectTo({ url: buildAdminProductDetailUrl(product.id, 'kit') })}
      >返回 Kit 管理详情</Button>
    </View>
  )
}

function parseAdjustment(changeText: string, reasonText: string): {
  readonly request?: InventoryAdjustmentRequest
  readonly error?: string
} {
  const normalizedChange = changeText.trim()
  const reason = reasonText.trim()
  if (!/^-?[1-9]\d*$/.test(normalizedChange)) {
    return { error: '变化量必须是非零整数，例如 20 或 -3' }
  }
  const change = Number(normalizedChange)
  if (!Number.isSafeInteger(change) || change < -999_999 || change > 999_999) {
    return { error: '变化量必须位于 -999999 至 999999' }
  }
  if (reason.length < 1 || reason.length > 256) {
    return { error: '调整原因去除首尾空白后必须是 1 至 256 个字符' }
  }
  return { request: { change, reason } }
}
