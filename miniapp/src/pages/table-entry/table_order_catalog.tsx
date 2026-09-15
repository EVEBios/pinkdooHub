import { Button, Image, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useMemo, useState } from 'react'

import type { ProductListItem } from '@/api/endpoints/products'
import type { EligibleOrder } from '@/api/endpoints/table_sessions'
import { type CartItem, useCart } from '@/features/order'
import { buildProductDetailUrl } from '@/features/product/product_detail_route'
import {
  type ProductTypeFilter,
  useProductList,
} from '@/features/product/use_product_list'
import { rememberScannedTable } from '@/features/table_session/table_selector'
import { shoppingTableStore } from '@/features/table_session/shopping_table'
import { moneyToCents } from '@/features/wallet'
import { resolveAssetUrl } from '@/utils/asset_url'
import { formatPrice } from '@/utils/format'

interface TableOrderCatalogProps {
  readonly tableNo: string
  readonly claiming: boolean
  readonly orders: readonly EligibleOrder[]
  readonly token: string
  readonly userId: number
  onSelectOrder(order: EligibleOrder): void
}

export function TableOrderCatalog({
  tableNo,
  claiming,
  onSelectOrder,
  orders,
  token,
  userId,
}: TableOrderCatalogProps) {
  const cart = useCart()
  const catalog = useProductList(undefined, 'experience')
  const [showExistingOrders, setShowExistingOrders] = useState(false)
  const hasExperience = cart.items.some((item) => item.productType === 'experience')
  const itemCount = cart.items.length
  const totalCents = calculateCartTotal(cart.items)

  const [selectionReady, setSelectionReady] = useState(false)
  const [selectionError, setSelectionError] = useState<string>()
  const [selectionRevision, setSelectionRevision] = useState(0)
  useEffect(() => {
    let active = true
    setSelectionReady(false)
    void rememberScannedTable(userId, tableNo).then((selected) => {
      if (active) {
        setSelectionReady(selected)
        setSelectionError(selected ? undefined : '已保留原桌台，可前往购物车继续结算')
      }
    }).catch((cause) => { if (active) setSelectionError(cause instanceof Error ? cause.message : '保存桌台失败，请重试') })
    return () => { active = false }
  }, [userId, tableNo, selectionRevision])
  if (!selectionReady) return <View>
    <Text>{selectionError ?? '正在记录本次桌台…'}</Text>
    {selectionError && <>
      <Button className='table-action' onClick={() => setSelectionRevision((value) => value + 1)}>重新选择本桌</Button>
      <Button className='table-action--secondary' onClick={() => void Taro.switchTab({ url: '/pages/cart/index' })}>查看购物车</Button>
    </>}
  </View>

  return (
    <>
      <View className='table-catalog'>
        <View className='table-catalog__heading'>
          <Text className='table-catalog__title'>为本桌选择项目</Text>
          <Text className='table-catalog__hint'>先选体验项目，也可以顺手添加材料包</Text>
        </View>

        <ProductTypeTabs
          value={catalog.productType}
          onChange={catalog.setProductType}
        />

        <ProductCatalogState
          catalog={catalog}
          cartItems={cart.items}
        />

        {orders.length > 0 && (
          <View className='table-existing-orders'>
            <View className='table-existing-orders__heading'>
              <View>
                <Text className='table-existing-orders__title'>已有待支付体验订单</Text>
                <Text className='table-existing-orders__hint'>也可以直接选择已有订单开台</Text>
              </View>
              <Button
                className='table-existing-orders__toggle'
                onClick={() => setShowExistingOrders((value) => !value)}
              >
                {showExistingOrders ? '收起' : `查看 ${orders.length} 笔`}
              </Button>
            </View>
            {showExistingOrders && (
              <View className='table-existing-orders__list'>
                {orders.map((order) => (
                  <Button
                    className='table-existing-order'
                    disabled={claiming}
                    key={order.id}
                    onClick={() => onSelectOrder(order)}
                  >
                    <View className='table-existing-order__copy'>
                      <Text className='table-existing-order__number'>{order.order_no}</Text>
                      <Text className='table-existing-order__meta'>
                        {formatDurationGroups(order)} · 付款后开始计时
                      </Text>
                    </View>
                    <Text className='table-existing-order__price'>¥{formatPrice(order.total_amount)}</Text>
                  </Button>
                ))}
              </View>
            )}
          </View>
        )}
      </View>

      <View className='table-cart-bar'>
        <View className='table-cart-bar__summary'>
          <Text className='table-cart-bar__count'>已选 {itemCount} 项</Text>
          <Text className='table-cart-bar__total'>合计 ¥{formatCents(totalCents)}</Text>
          <Text className='table-cart-bar__hint'>支付成功后开始计时</Text>
        </View>
        <Button
          className='table-cart-bar__action'
          disabled={cart.status !== 'ready' || !hasExperience}
          onClick={() => void continueToOrder(token, userId, hasExperience)}
        >
          {cart.status === 'initializing'
            ? '正在准备…'
            : hasExperience
              ? '确认本桌订单'
              : itemCount > 0
                ? '还需体验项目'
                : '先选择体验'}
        </Button>
      </View>
    </>
  )
}

function ProductTypeTabs({ onChange, value }: {
  readonly value: ProductTypeFilter
  onChange(value: ProductTypeFilter): void
}) {
  return (
    <View className='table-catalog-tabs' ariaRole='tablist'>
      {([
        { label: '体验项目', value: 'experience' },
        { label: '材料包', value: 'kit' },
      ] as const).map((tab) => (
        <Button
          aria-role='tab'
          aria-label={`${tab.label}${value === tab.value ? '，当前分类' : ''}`}
          aria-selected={value === tab.value}
          className={`table-catalog-tabs__item${value === tab.value ? ' table-catalog-tabs__item--active' : ''}`}
          key={tab.value}
          onClick={() => onChange(tab.value)}
        >
          {tab.label}
        </Button>
      ))}
    </View>
  )
}

function ProductCatalogState({ catalog, cartItems }: {
  readonly catalog: ReturnType<typeof useProductList>
  readonly cartItems: readonly CartItem[]
}) {
  if (catalog.state.status === 'loading') {
    return <CatalogMessage title='正在准备商品' description='马上就可以为本桌挑选体验' />
  }
  if (catalog.state.status === 'error') {
    return (
      <CatalogMessage title='商品暂时没有加载出来' description={catalog.state.errorMessage ?? '请稍后重试'}>
        <Button className='table-catalog-message__action' onClick={catalog.retry}>重新加载</Button>
      </CatalogMessage>
    )
  }
  if (catalog.state.status === 'empty') {
    return (
      <CatalogMessage
        title={catalog.productType === 'experience' ? '暂时没有可选体验' : '暂时没有可选材料包'}
        description='门店上架新项目后会显示在这里'
      />
    )
  }
  return (
    <>
      <View className='table-product-grid'>
        {catalog.state.items.map((product) => (
          <TableProductCard
            cartItems={cartItems}
            key={product.id}
            product={product}
          />
        ))}
      </View>
      {catalog.state.errorMessage && (
        <Text className='table-catalog__pagination-error'>{catalog.state.errorMessage}</Text>
      )}
      {catalog.state.page < catalog.state.pages && (
        <Button
          className='table-catalog__load-more'
          disabled={catalog.state.loadingMore}
          onClick={catalog.loadNextPage}
        >
          {catalog.state.loadingMore ? '正在加载…' : '查看更多项目'}
        </Button>
      )}
    </>
  )
}

function TableProductCard({ cartItems, product }: {
  readonly cartItems: readonly CartItem[]
  readonly product: ProductListItem
}) {
  const [renderFailed, setRenderFailed] = useState(false)
  const remoteImageUrl = useMemo(() => resolveAssetUrl(product.cover_image), [product.cover_image])
  const localImage = useLocalDevelopmentImage(remoteImageUrl)
  const imageFailed = renderFailed || localImage.failed
  const imageUrl = localImage.url
  useEffect(() => setRenderFailed(false), [remoteImageUrl])
  const selectedQuantity = cartItems
    .filter((item) => item.productId === product.id)
    .reduce((total, item) => total + item.quantity, 0)
  const experience = product.product_type.value === 'experience'
  const priceSuffix = experience
    ? ' 起'
    : product.kit_kind?.value === 'color_selectable'
      ? ' / 10g'
      : ''
  const spokenPriceSuffix = experience
    ? '元起'
    : product.kit_kind?.value === 'color_selectable'
      ? '元每10克'
      : '元'
  const meta = experience
    ? '选择时长与人数'
    : product.kit_kind?.value === 'color_selectable'
      ? '选择颜色与重量'
      : '查看材料包详情'

  return (
    <Button
      aria-label={`选择${product.name}，${formatPrice(product.display_price)}${spokenPriceSuffix}，${meta}${selectedQuantity > 0 ? `，已选${selectedQuantity}件` : ''}`}
      className='table-product'
      onClick={() => void openProduct(product)}
    >
      {imageFailed ? (
        <View className='table-product__image table-product__image--fallback'>
          <Text>图片暂不可用</Text>
        </View>
      ) : !imageUrl ? (
        <View className='table-product__image table-product__image--loading' />
      ) : (
        <Image
          className='table-product__image'
          lazyLoad
          mode='aspectFill'
          src={imageUrl}
          onError={() => setRenderFailed(true)}
        />
      )}
      <View className='table-product__body'>
        <Text className='table-product__name'>{product.name}</Text>
        <Text className='table-product__meta'>{meta}</Text>
        <View className='table-product__footer'>
          <Text className='table-product__price'>¥{formatPrice(product.display_price)}{priceSuffix}</Text>
          <Text className={`table-product__select${selectedQuantity > 0 ? ' table-product__select--selected' : ''}`}>
            {selectedQuantity > 0 ? `已选 ${selectedQuantity}` : '选择'}
          </Text>
        </View>
      </View>
    </Button>
  )
}

/**
 * 新版微信开发者工具不再允许 <Image> 直接读取本机 HTTP 地址。
 * 仅在微信开发期将 localhost 图片下载为临时文件；线上 HTTPS 与 H5 保持原路径。
 */
function useLocalDevelopmentImage(
  remoteUrl: string,
): { readonly failed: boolean; readonly url?: string } {
  const needsDownload = process.env.TARO_ENV === 'weapp' &&
    /^http:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?(?:\/|$)/.test(remoteUrl)
  const [displayUrl, setDisplayUrl] = useState<string | undefined>(
    needsDownload ? undefined : remoteUrl,
  )
  const [downloadFailed, setDownloadFailed] = useState(false)

  useEffect(() => {
    let active = true
    setDownloadFailed(false)
    if (!needsDownload) {
      setDisplayUrl(remoteUrl)
      return () => { active = false }
    }
    setDisplayUrl(undefined)
    void Taro.downloadFile({ url: remoteUrl })
      .then((result) => {
        if (!active) return
        if (result.statusCode < 200 || result.statusCode >= 300 || !result.tempFilePath) {
          setDownloadFailed(true)
          return
        }
        setDisplayUrl(result.tempFilePath)
      })
      .catch(() => {
        if (active) setDownloadFailed(true)
      })
    return () => { active = false }
  }, [needsDownload, remoteUrl])

  return { failed: downloadFailed, url: displayUrl }
}

function CatalogMessage({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='table-catalog-message'>
      <Text className='table-catalog-message__title'>{title}</Text>
      <Text className='table-catalog-message__description'>{description}</Text>
      {children}
    </View>
  )
}

async function openProduct(product: ProductListItem): Promise<void> {
  await Taro.navigateTo({
    url: buildProductDetailUrl(product.id, product.product_type.value),
  })
}

async function continueToOrder(
  _token: string,
  userId: number,
  hasExperience: boolean,
): Promise<void> {
  if (!hasExperience) {
    await Taro.showToast({ title: '开台订单至少需要一个体验项目', icon: 'none' })
    return
  }
  try {
    const saved = await shoppingTableStore.load(userId)
    if (!saved.selection) throw new Error('请重新选择桌台')
    await Taro.navigateTo({ url: '/pages/order-confirm/index' })
  } catch {
    await Taro.showToast({ title: '无法读取桌台，请重试', icon: 'none' })
  }
}

function calculateCartTotal(items: readonly CartItem[]): number {
  return items.reduce((total, item) => {
    const unitCents = moneyToCents(item.unitPrice)
    return unitCents === undefined ? total : total + unitCents * item.quantity
  }, 0)
}

function formatCents(cents: number): string {
  const integer = Math.floor(cents / 100)
  const decimal = String(cents % 100).padStart(2, '0')
  return formatPrice(`${integer}.${decimal}`)
}

function formatDurationGroups(order: EligibleOrder): string {
  return order.duration_groups
    .map((group) => `${group.duration_minutes}+10 分钟`)
    .join(' / ')
}
