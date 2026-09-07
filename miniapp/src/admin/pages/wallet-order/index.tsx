import { Button, Input, Text, Textarea, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useState } from 'react'

import type { OrderCreateRequest } from '@/api/endpoints/orders'
import type {
  ExperienceProductDetail,
  KitColorOption,
  KitProductDetail,
  ProductListItem,
} from '@/api/endpoints/products'
import type { AdminUserWallet, AssistedWalletOrderResult } from '@/api/endpoints/wallet'
import { ADMIN_USER_LIST_PATH, buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import { buildAdminOrderDetailUrl, CART_COLOR_ITEM_LIMIT } from '@/features/order'
import { useProductDetail } from '@/features/product/use_product_detail'
import { type ProductTypeFilter, useProductList } from '@/features/product/use_product_list'
import {
  buildAdminUserWalletUrl,
  parseAdminWalletOrderRoute,
  useAdminUserWallet,
  useAdminWalletTransactions,
  useAssistedWalletOrder,
} from '@/features/wallet'
import { moneyToCents } from '@/features/wallet/money'
import { formatColorLabel, formatPrice } from '@/utils/format'

import './index.scss'

const PRODUCT_TYPE_FILTERS: ReadonlyArray<{ value: ProductTypeFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'experience', label: '拼豆体验' },
  { value: 'kit', label: '材料套装' },
]

export default function AdminWalletOrderPage() {
  const auth = useAuth()
  const route = parseAdminWalletOrderRoute(useRouter().params)
  if (!route) return <WalletOrderState title='代客订单地址无效' description='请从用户资金账户重新进入' />
  if (auth.status === 'initializing') {
    return <WalletOrderState title='正在确认管理员身份…' description='代客商品扣款仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <WalletOrderState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='wallet-order-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </WalletOrderState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <WalletOrderState title='登录后创建代客订单' description='登录后请从管理用户重新选择客户'>
        <Button
          className='wallet-order-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_USER_LIST_PATH) })}
        >去登录</Button>
      </WalletOrderState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <WalletOrderState title='无管理权限' description='当前账号不会请求代客商品扣款 API' />
  }
  return <AuthenticatedAdminWalletOrder currentUserId={auth.user?.id ?? 0} userId={route.userId} />
}

export function AuthenticatedAdminWalletOrder({ currentUserId, userId }: {
  readonly currentUserId: number
  readonly userId: number
}) {
  const target = useAdminUserWallet(userId)
  const ledger = useAdminWalletTransactions(userId)
  const catalog = useProductList()
  const assistedOrder = useAssistedWalletOrder(userId)
  const [selectedProduct, setSelectedProduct] = useState<ProductListItem>()

  if (assistedOrder.state.status === 'succeeded') {
    return (
      <AssistedOrderResult
        ledgerStatus={ledger.state.status}
        result={assistedOrder.state.result}
        userId={userId}
        onCreateAnother={assistedOrder.reset}
      />
    )
  }
  if (target.state.status === 'loading') {
    return <WalletOrderState title='正在读取客户钱包…' description='将先核对客户身份、状态与可用余额' />
  }
  if (target.state.status === 'error') {
    return (
      <WalletOrderState title='客户钱包加载失败' description={target.state.errorMessage}>
        <Button className='wallet-order-state__action' onClick={target.retry}>重新加载</Button>
      </WalletOrderState>
    )
  }

  const { user, wallet } = target.state.wallet
  const targetAllowed = user.role === 'user' && user.status === 'normal' && user.id !== currentUserId &&
    wallet.status === 'active'
  if (!targetAllowed) {
    return (
      <WalletOrderState title='该用户不可代客消费' description='只有状态正常的普通用户可创建真实商品扣款订单；已禁用用户仍可返回资金页做人工纠错。'>
        <Button
          className='wallet-order-state__action'
          onClick={() => void Taro.navigateTo({ url: buildAdminUserWalletUrl(userId) })}
        >返回用户资金账户</Button>
      </WalletOrderState>
    )
  }

  const intentLocked = assistedOrder.state.status === 'unknown' || assistedOrder.state.status === 'submitting'
  return (
    <View className='wallet-order-page'>
      <View className='wallet-order-page__header'>
        <Text className='wallet-order-page__eyebrow'>代客商品扣款 · #{user.id}</Text>
        <Text className='wallet-order-page__title'>{user.nickname}</Text>
        <Text className='wallet-order-page__subtitle'>当前余额 ¥{formatPrice(wallet.balance)}；成功后生成真实订单、支付与资金流水。</Text>
      </View>

      {selectedProduct ? (
        <AssistedOrderItemForm
          locked={intentLocked}
          mutation={assistedOrder}
          product={selectedProduct}
          target={target.state.wallet}
          onCommitted={() => {
            target.retry()
            ledger.retry()
          }}
          onSelectAnother={() => setSelectedProduct(undefined)}
        />
      ) : (
        <ProductPicker
          catalog={catalog}
          locked={intentLocked}
          onSelect={setSelectedProduct}
        />
      )}

      <Button
        className='wallet-order-page__back'
        disabled={intentLocked}
        onClick={() => void Taro.navigateTo({ url: buildAdminUserWalletUrl(userId) })}
      >返回用户资金账户</Button>
    </View>
  )
}

function ProductPicker({ catalog, locked, onSelect }: {
  readonly catalog: ReturnType<typeof useProductList>
  readonly locked: boolean
  readonly onSelect: (product: ProductListItem) => void
}) {
  return (
    <View className='wallet-order-catalog'>
      <Text className='wallet-order-catalog__title'>选择当前可售商品</Text>
      <Text className='wallet-order-catalog__hint'>列表与后续配置均来自服务端；最终价格和库存会在提交事务内再次校验。</Text>
      <Input
        className='wallet-order-catalog__search'
        disabled={locked}
        maxlength={100}
        placeholder='搜索商品名称'
        value={catalog.keyword}
        onInput={(event) => catalog.setKeyword(event.detail.value)}
      />
      <View className='wallet-order-catalog__filters'>
        {PRODUCT_TYPE_FILTERS.map((filter) => (
          <Button
            key={filter.value}
            className={`wallet-order-catalog__filter${catalog.productType === filter.value ? ' wallet-order-catalog__filter--active' : ''}`}
            disabled={locked}
            onClick={() => catalog.setProductType(filter.value)}
          >{filter.label}</Button>
        ))}
      </View>
      {catalog.state.status === 'loading' && <Text className='wallet-order-catalog__state'>正在加载可售商品…</Text>}
      {catalog.state.status === 'empty' && <Text className='wallet-order-catalog__state'>暂无可代客下单的商品</Text>}
      {catalog.state.status === 'error' && (
        <View className='wallet-order-catalog__state'>
          <Text>{catalog.state.errorMessage ?? '商品加载失败'}</Text>
          <Button className='wallet-order-catalog__retry' onClick={catalog.retry}>重新加载</Button>
        </View>
      )}
      {catalog.state.status === 'content' && (
        <>
          <View className='wallet-order-catalog__list'>
            {catalog.state.items.map((product) => (
              <Button
                key={product.id}
                className='wallet-order-product'
                disabled={locked}
                onClick={() => onSelect(product)}
              >
                <View>
                  <Text className='wallet-order-product__type'>{product.product_type.label}</Text>
                  <Text className='wallet-order-product__name'>{product.name}</Text>
                </View>
                <Text className='wallet-order-product__price'>
                  ¥{formatPrice(product.display_price)}{
                    product.product_type.value === 'experience'
                      ? ' 起'
                      : product.kit_kind?.value === 'color_selectable'
                        ? ' / 10g'
                        : ''
                  }
                </Text>
              </Button>
            ))}
          </View>
          {catalog.state.page < catalog.state.pages ? (
            <Button
              className='wallet-order-catalog__more'
              disabled={catalog.state.loadingMore || locked}
              onClick={catalog.loadNextPage}
            >{catalog.state.loadingMore ? '正在加载…' : '加载更多商品'}</Button>
          ) : <Text className='wallet-order-catalog__end'>已显示全部可售商品</Text>}
        </>
      )}
    </View>
  )
}

function AssistedOrderItemForm({ locked, mutation, onCommitted, onSelectAnother, product, target }: {
  readonly product: ProductListItem
  readonly target: AdminUserWallet
  readonly locked: boolean
  readonly mutation: ReturnType<typeof useAssistedWalletOrder>
  readonly onCommitted: () => void
  readonly onSelectAnother: () => void
}) {
  const detail = useProductDetail(product.id, product.product_type.value)
  if (detail.state.status === 'loading') {
    return <View className='wallet-order-form'><Text>正在读取商品权威价格与配置…</Text></View>
  }
  if (detail.state.status === 'error') {
    return (
      <View className='wallet-order-form'>
        <Text className='wallet-order-form__error'>{detail.state.errorMessage}</Text>
        <Button className='wallet-order-form__secondary' onClick={detail.retry}>重新加载商品</Button>
        <Button className='wallet-order-form__secondary' onClick={onSelectAnother}>更换商品</Button>
      </View>
    )
  }
  return (
    <LoadedAssistedOrderItemForm
      detail={detail.state.detail}
      locked={locked}
      mutation={mutation}
      target={target}
      onCommitted={onCommitted}
      onSelectAnother={onSelectAnother}
    />
  )
}

function LoadedAssistedOrderItemForm({ detail, locked, mutation, onCommitted, onSelectAnother, target }: {
  readonly detail: ExperienceProductDetail | KitProductDetail
  readonly target: AdminUserWallet
  readonly locked: boolean
  readonly mutation: ReturnType<typeof useAssistedWalletOrder>
  readonly onCommitted: () => void
  readonly onSelectAnother: () => void
}) {
  const experienceDetail = isKitDetail(detail) ? undefined : detail
  const [quantity, setQuantity] = useState(1)
  const [colorQuery, setColorQuery] = useState('')
  const [colorQuantities, setColorQuantities] = useState<Record<number, number>>({})
  const [remark, setRemark] = useState('')
  const [selectedOptionId, setSelectedOptionId] = useState(
    experienceDetail?.options[0].id,
  )
  const kitDetail = isKitDetail(detail) ? detail : undefined
  const colorKitDetail = kitDetail?.kit_kind.value === 'color_selectable' ? kitDetail : undefined
  const option = experienceDetail
    ? experienceDetail.options.find((item) => item.id === selectedOptionId) ?? experienceDetail.options[0]
    : undefined
  const selectedColors = colorKitDetail?.colors.filter(
    (item) => colorQuantities[item.id] !== undefined,
  ) ?? []
  const normalizedColorQuery = colorQuery.trim().toLocaleLowerCase()
  const visibleColors = colorKitDetail?.colors.filter((item) => (
    normalizedColorQuery.length === 0 ||
    item.color_code.toLocaleLowerCase().includes(normalizedColorQuery) ||
    item.name.toLocaleLowerCase().includes(normalizedColorQuery)
  )) ?? []
  const colorUnitGrams = colorKitDetail?.sale_unit_grams ?? 10
  const totalColorUnits = selectedColors.reduce(
    (total, item) => total + colorQuantities[item.id],
    0,
  )
  const totalColorWeight = totalColorUnits * colorUnitGrams
  const unitPrice = option?.price ?? kitDetail?.price ?? '0.00'
  const unitCents = moneyToCents(unitPrice)
  const balanceCents = moneyToCents(target.wallet.balance)
  const totalCents = unitCents === undefined
    ? undefined
    : unitCents * (colorKitDetail ? totalColorUnits : quantity)
  const maxQuantity = kitDetail?.kit_kind.value === 'fixed'
    ? Math.min(99, kitDetail.stock ?? 0)
    : 99
  const purchasable = !kitDetail || (kitDetail.kit_kind.value === 'fixed'
    ? kitDetail.available
    : selectedColors.length > 0 && selectedColors.every((item) => item.available))
  const colorSelectionValid = !colorKitDetail || (
    selectedColors.length <= CART_COLOR_ITEM_LIMIT &&
    selectedColors.every((item) => {
      const colorQuantity = colorQuantities[item.id]
      return Number.isSafeInteger(colorQuantity) && colorQuantity >= 1 && colorQuantity <= 99
    })
  )
  const balanceSufficient = totalCents !== undefined && balanceCents !== undefined && totalCents <= balanceCents
  const canSubmit = !locked && purchasable && colorSelectionValid && balanceSufficient &&
    (colorKitDetail ? selectedColors.length > 0 : quantity >= 1 && quantity <= maxQuantity)
  const request: OrderCreateRequest = {
    items: colorKitDetail
      ? selectedColors.map((item) => ({
        product_id: detail.id,
        kit_color_id: item.id,
        quantity: colorQuantities[item.id],
      }))
      : [{
        product_id: detail.id,
        quantity,
        ...(option ? { experience_option_id: option.id } : {}),
      }],
    ...(remark.trim() ? { remark: remark.trim() } : {}),
  }

  function toggleColor(item: KitColorOption): void {
    if (locked || !item.available) return
    if (colorQuantities[item.id] !== undefined) {
      setColorQuantities((current) => {
        const next = { ...current }
        delete next[item.id]
        return next
      })
      return
    }
    if (selectedColors.length >= CART_COLOR_ITEM_LIMIT) {
      void Taro.showToast({
        title: `每单最多选择 ${CART_COLOR_ITEM_LIMIT} 种颜色`,
        icon: 'none',
      })
      return
    }
    setColorQuantities((current) => ({ ...current, [item.id]: 1 }))
  }

  function changeColorQuantity(colorId: number, change: number): void {
    setColorQuantities((current) => {
      const currentQuantity = current[colorId]
      if (currentQuantity === undefined) return current
      return {
        ...current,
        [colorId]: Math.max(1, Math.min(99, currentQuantity + change)),
      }
    })
  }

  async function confirmCreate(): Promise<void> {
    if (!canSubmit || totalCents === undefined) return
    const configuration = option
      ? `\n配置：${option.duration.label} · ${option.participants.label} · ${option.day_type.label}`
      : colorKitDetail
        ? `\n已选：${selectedColors.map((item) => (
          `${formatColorLabel(item.color_code, item.name)} ${colorQuantities[item.id] * colorUnitGrams}g`
        )).join('、')}`
        : ''
    const priceUnit = colorKitDetail ? ` / ${colorUnitGrams}g` : ''
    const quantityLabel = colorKitDetail
      ? `合计：${selectedColors.length} 种颜色 · ${totalColorWeight}g`
      : `数量：${quantity}`
    const confirmation = await Taro.showModal({
      title: '确认创建并扣款？',
      content: `客户：${target.user.nickname}（ID ${target.user.id}）\n商品：${detail.name}${configuration}\n权威预览单价：¥${formatPrice(unitPrice)}${priceUnit}\n${quantityLabel}\n预计扣款：¥${(totalCents / 100).toFixed(2)}\n提交时服务端会再次校验价格、余额与库存。`,
      confirmText: '创建并扣款',
      confirmColor: '#a92e51',
    })
    if (!confirmation.confirm) return
    const result = await mutation.createOrder(request)
    if (result) onCommitted()
  }

  async function confirmRetry(): Promise<void> {
    const confirmation = await Taro.showModal({
      title: '安全重试同一笔扣款？',
      content: '商品、配置、数量、备注和 Idempotency-Key 都会保持不变；服务端只会返回首次结果或完成同一意图。',
      confirmText: '安全重试',
      confirmColor: '#76531c',
    })
    if (!confirmation.confirm) return
    const result = await mutation.retrySameIntent()
    if (result) onCommitted()
  }

  return (
    <View className='wallet-order-form'>
      <View className='wallet-order-form__heading'>
        <View>
          <Text className='wallet-order-form__type'>{detail.product_type.label}</Text>
          <Text className='wallet-order-form__title'>{detail.name}</Text>
        </View>
        <Button className='wallet-order-form__change' disabled={locked} onClick={onSelectAnother}>更换商品</Button>
      </View>
      {experienceDetail && (
        <View className='wallet-order-options'>
          <Text className='wallet-order-form__label'>体验配置</Text>
          {experienceDetail.options.map((item) => (
            <Button
              key={item.id}
              className={`wallet-order-option${item.id === option?.id ? ' wallet-order-option--active' : ''}`}
              disabled={locked}
              onClick={() => setSelectedOptionId(item.id)}
            >
              <Text>{item.duration.label} · {item.participants.label} · {item.day_type.label}</Text>
              <Text>¥{formatPrice(item.price)}</Text>
            </Button>
          ))}
        </View>
      )}
      {colorKitDetail && (
        <View className='wallet-order-color-picker'>
          <View className='wallet-order-color-picker__heading'>
            <View>
              <Text className='wallet-order-form__label'>选择拼豆颜色</Text>
              <Text className='wallet-order-color-picker__hint'>点击色号多选；每种颜色以 {colorUnitGrams}g 为一步。</Text>
            </View>
            <Text className='wallet-order-color-picker__count'>{selectedColors.length}/{CART_COLOR_ITEM_LIMIT}</Text>
          </View>
          <Input
            className='wallet-order-color-picker__search'
            disabled={locked}
            maxlength={100}
            placeholder='搜索色号或颜色名称'
            value={colorQuery}
            onInput={(event) => setColorQuery(event.detail.value)}
          />
          {visibleColors.length === 0 ? (
            <Text className='wallet-order-color-picker__empty'>没有匹配的颜色</Text>
          ) : (
            <View className='wallet-order-color-grid'>
              {visibleColors.map((item) => {
                const selected = colorQuantities[item.id] !== undefined
                return (
                  <Button
                    key={item.id}
                    className={`wallet-order-color-option${selected ? ' wallet-order-color-option--selected' : ''}`}
                    disabled={locked || !item.available}
                    aria-label={`${selected ? '取消选择' : '选择'} ${formatColorLabel(item.color_code, item.name)}`}
                    onClick={() => toggleColor(item)}
                  >
                    <Text className='wallet-order-color-option__code'>{item.color_code}</Text>
                    {!item.available && <Text className='wallet-order-color-option__status'>无货</Text>}
                    {selected && <Text className='wallet-order-color-option__status'>已选</Text>}
                  </Button>
                )
              })}
            </View>
          )}
          {selectedColors.length > 0 && (
            <View className='wallet-order-selected-colors'>
              <View className='wallet-order-selected-colors__heading'>
                <View>
                  <Text className='wallet-order-selected-colors__title'>已选颜色与数量</Text>
                  <Text className='wallet-order-selected-colors__hint'>共 {totalColorWeight}g，可分别调整每种颜色。</Text>
                </View>
                <Button
                  className='wallet-order-selected-colors__clear'
                  disabled={locked}
                  onClick={() => setColorQuantities({})}
                >清空</Button>
              </View>
              <View className='wallet-order-selected-colors__list'>
                {selectedColors.map((item) => {
                  const colorQuantity = colorQuantities[item.id]
                  return (
                    <View className='wallet-order-selected-color' key={item.id}>
                      <View className='wallet-order-selected-color__identity'>
                        <Text className='wallet-order-selected-color__name'>
                          {formatColorLabel(item.color_code, item.name)}
                        </Text>
                        <Text className='wallet-order-selected-color__weight'>
                          {colorQuantity * colorUnitGrams}g
                        </Text>
                      </View>
                      <View className='wallet-order-selected-color__controls'>
                        <Button
                          className='wallet-order-selected-color__step'
                          disabled={locked || colorQuantity <= 1}
                          aria-label={`${item.color_code} 减少 ${colorUnitGrams}g`}
                          onClick={() => changeColorQuantity(item.id, -1)}
                        >−</Button>
                        <Text className='wallet-order-selected-color__quantity'>{colorQuantity}</Text>
                        <Button
                          className='wallet-order-selected-color__step'
                          disabled={locked || colorQuantity >= 99}
                          aria-label={`${item.color_code} 增加 ${colorUnitGrams}g`}
                          onClick={() => changeColorQuantity(item.id, 1)}
                        >＋</Button>
                      </View>
                    </View>
                  )
                })}
              </View>
            </View>
          )}
        </View>
      )}
      <View className='wallet-order-form__price'>
        <Text className='wallet-order-form__price-label'>服务端当前单价</Text>
        <Text className='wallet-order-form__price-value'>
          ¥{formatPrice(unitPrice)}{colorKitDetail ? ` / ${colorUnitGrams}g` : ''}
        </Text>
      </View>
      {kitDetail?.kit_kind.value === 'fixed' && (
        <Text className={purchasable ? 'wallet-order-form__stock' : 'wallet-order-form__error'}>
          {kitDetail.available ? `当前权威库存 ${kitDetail.stock}` : '当前无库存，不可下单'}
        </Text>
      )}
      {!colorKitDetail && (
        <>
          <Text className='wallet-order-form__label'>Item 数量</Text>
          <View className='wallet-order-quantity'>
            <Button className='wallet-order-quantity__decrease' disabled={locked || quantity <= 1} onClick={() => setQuantity((value) => value - 1)}>−</Button>
            <Text className='wallet-order-quantity__value'>{quantity}</Text>
            <Button className='wallet-order-quantity__increase' disabled={locked || quantity >= maxQuantity} onClick={() => setQuantity((value) => value + 1)}>＋</Button>
          </View>
        </>
      )}
      <Text className='wallet-order-form__label'>订单备注（可选）</Text>
      <Textarea
        className='wallet-order-form__remark'
        disabled={locked}
        maxlength={500}
        placeholder='例如门店接待说明，最多 500 字'
        value={remark}
        onInput={(event) => setRemark(event.detail.value)}
      />
      <View className='wallet-order-form__summary'>
        <Text className='wallet-order-form__summary-label'>预计扣款</Text>
        <Text className='wallet-order-form__total'>¥{totalCents === undefined ? '—' : (totalCents / 100).toFixed(2)}</Text>
        <Text className='wallet-order-form__summary-balance'>客户可用余额 ¥{formatPrice(target.wallet.balance)}</Text>
      </View>
      {!balanceSufficient && <Text className='wallet-order-form__error'>客户余额不足，请减少数量或先进行合规的余额纠错。</Text>}
      {(mutation.state.status === 'failed' || mutation.state.status === 'unknown') && (
        <Text className={`wallet-order-form__feedback wallet-order-form__feedback--${mutation.state.status}`}>
          {mutation.state.errorMessage}
        </Text>
      )}
      {mutation.state.status === 'unknown' ? (
        <Button className='wallet-order-form__retry' onClick={() => void confirmRetry()}>安全重试同一笔扣款</Button>
      ) : (
        <Button
          className='wallet-order-form__submit'
          disabled={!canSubmit}
          loading={mutation.state.status === 'submitting'}
          onClick={() => void confirmCreate()}
        >{mutation.state.status === 'submitting' ? '正在创建并扣款…' : '确认创建真实订单并扣款'}</Button>
      )}
    </View>
  )
}

function AssistedOrderResult({ ledgerStatus, onCreateAnother, result, userId }: {
  readonly result: AssistedWalletOrderResult
  readonly userId: number
  readonly ledgerStatus: ReturnType<typeof useAdminWalletTransactions>['state']['status']
  readonly onCreateAnother: () => void
}) {
  return (
    <View className='wallet-order-result'>
      <View className='wallet-order-result__hero'>
        <Text className='wallet-order-result__label'>真实订单与扣款已完成</Text>
        <Text className='wallet-order-result__number'>{result.order.order_no}</Text>
        <Text className='wallet-order-result__amount'>¥{formatPrice(result.payment.amount)}</Text>
        <Text className='wallet-order-result__balance'>扣款后余额 ¥{formatPrice(result.post_payment_balance)}</Text>
      </View>
      <View className='wallet-order-result__facts'>
        <Text>订单状态：{result.order.status.label}</Text>
        <Text>支付状态：已支付（会员余额）</Text>
        <Text>支付单号：{result.payment.payment_no}</Text>
        <Text>{ledgerStatus === 'loading' ? '正在刷新资金明细…' : ledgerStatus === 'error' ? '资金明细刷新失败，返回资金页后请重新核对' : '钱包与资金明细已刷新'}</Text>
      </View>
      <View className='wallet-order-result__items'>
        {result.order.items.map((item) => (
          <View key={item.id} className='wallet-order-result__item'>
            <Text>{item.product_name}</Text>
            <Text>{item.kit_color_id
              ? `¥${formatPrice(item.product_price)} / 10g × ${item.total_weight_grams}g = ¥${formatPrice(item.subtotal)}`
              : `¥${formatPrice(item.product_price)} × ${item.quantity} = ¥${formatPrice(item.subtotal)}`}</Text>
          </View>
        ))}
      </View>
      <Button
        className='wallet-order-result__primary'
        onClick={() => void Taro.navigateTo({ url: buildAdminOrderDetailUrl(result.order.id) })}
      >查看管理订单详情</Button>
      <Button
        className='wallet-order-result__secondary'
        onClick={() => void Taro.navigateTo({ url: buildAdminUserWalletUrl(userId) })}
      >返回用户资金账户</Button>
      <Button className='wallet-order-result__quiet' onClick={onCreateAnother}>继续为该用户选购</Button>
    </View>
  )
}

function isKitDetail(
  detail: ExperienceProductDetail | KitProductDetail,
): detail is KitProductDetail {
  return detail.product_type.value === 'kit'
}

function WalletOrderState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='wallet-order-state'>
      <Text className='wallet-order-state__title'>{title}</Text>
      <Text className='wallet-order-state__description'>{description}</Text>
      {children}
    </View>
  )
}
