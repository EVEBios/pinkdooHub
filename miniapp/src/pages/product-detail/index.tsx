import { Button, Image, Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useState } from 'react'

import type {
  ExperienceOption,
  ExperienceProductDetail,
  KitColorOption,
  KitProductDetail,
} from '@/api/endpoints/products'
import { buildLoginUrl, useAuth } from '@/auth'
import { BeadColorSwatch } from '@/components/bead_color_swatch'
import { buildReservationCreateUrl } from '@/features/reservation'
import {
  parseProductDetailRoute,
  type ProductDetailRoute,
} from '@/features/product/product_detail_route'
import { useProductDetail } from '@/features/product/use_product_detail'
import { CART_COLOR_ITEM_LIMIT, useCart } from '@/features/order'
import {
  buildColorKitCartItem,
  buildExperienceCartItem,
  buildKitCartItem,
} from '@/features/order/cart_item'
import { resolveAssetUrl } from '@/utils/asset_url'
import { formatColorLabel, formatPrice } from '@/utils/format'

import './index.scss'

export default function ProductDetailPage() {
  const router = useRouter()
  const route = parseProductDetailRoute(router.params)

  if (!route) {
    return (
      <DetailState title='无法打开商品' description='商品链接缺少有效的 ID 或类型'>
        <Button className='product-detail__action' onClick={() => void Taro.navigateBack()}>返回</Button>
      </DetailState>
    )
  }

  return <ProductDetailContent productId={route.productId} productType={route.productType} />
}

function ProductDetailContent({ productId, productType }: ProductDetailRoute) {
  const { retry, state } = useProductDetail(productId, productType)

  if (state.status === 'loading') {
    return <DetailState title='正在加载商品…' description='正在获取服务端最新详情' />
  }
  if (state.status === 'error') {
    return (
      <DetailState title='商品详情加载失败' description={state.errorMessage}>
        <Button className='product-detail__action' onClick={retry}>重新加载</Button>
      </DetailState>
    )
  }
  return isExperienceDetail(state.detail)
    ? <ExperienceDetail detail={state.detail} />
    : <KitDetail detail={state.detail} />
}

function isExperienceDetail(
  detail: ExperienceProductDetail | KitProductDetail,
): detail is ExperienceProductDetail {
  return detail.product_type.value === 'experience'
}

function ExperienceDetail({ detail }: { detail: ExperienceProductDetail }) {
  const [selectedOptionId, setSelectedOptionId] = useState(detail.options[0].id)
  const selectedOption = detail.options.find((option) => option.id === selectedOptionId) ?? detail.options[0]

  return (
    <View className='product-detail'>
      <ProductHeading detail={detail} />
      <View className='product-detail__section'>
        <Text className='product-detail__section-title'>选择有效配置</Text>
        <Text className='product-detail__section-hint'>每一项都是服务端实际可用的完整组合</Text>
        <View className='option-list'>
          {detail.options.map((option) => (
            <OptionButton
              key={option.id}
              option={option}
              selected={option.id === selectedOption.id}
              onSelect={() => setSelectedOptionId(option.id)}
            />
          ))}
        </View>
      </View>
      <View className='product-detail__section'>
        <Text className='product-detail__section-title'>当前选择</Text>
        <Text className='product-detail__selected-price'>¥{formatPrice(selectedOption.price)}</Text>
        <Text className='product-detail__selection-summary'>
          {selectedOption.duration.label} · {selectedOption.participants.label} · {selectedOption.day_type.label}
        </Text>
        <ImageGallery images={selectedOption.images} label='当前配置图片' />
      </View>
      <ReservationAction detail={detail} option={selectedOption} />
      <CartActions item={buildExperienceCartItem(detail, selectedOption)} />
    </View>
  )
}

export function ReservationAction({ detail, option }: {
  readonly detail: ExperienceProductDetail
  readonly option: ExperienceOption
}) {
  const auth = useAuth()
  const target = buildReservationCreateUrl(detail.id, option.id)
  const customerReady = auth.status === 'authenticated' && auth.user?.role === 'user'
  const disabled = auth.status === 'initializing' || auth.status === 'error' ||
    (auth.status === 'authenticated' && !customerReady)

  function openReservation(): void {
    if (disabled) return
    void Taro.navigateTo({ url: auth.status === 'guest' ? buildLoginUrl(target) : target })
  }

  return (
    <View className='product-detail__reservation'>
      <View>
        <Text className='product-detail__reservation-title'>预约到店体验</Text>
        <Text className='product-detail__reservation-hint'>不必先下单，门店确认后按预约时间到店付款。</Text>
      </View>
      <Button
        className='product-detail__reservation-action'
        disabled={disabled}
        onClick={openReservation}
      >
        {auth.status === 'initializing'
          ? '正在确认账号…'
          : auth.status === 'error'
            ? '登录状态暂不可用'
            : auth.status === 'authenticated' && !customerReady
              ? '顾客账号才能预约'
              : auth.status === 'guest'
                ? '登录并预约'
                : '选择预约时间'}
      </Button>
    </View>
  )
}

function OptionButton({
  onSelect,
  option,
  selected,
}: {
  option: ExperienceOption
  selected: boolean
  onSelect(): void
}) {
  return (
    <Button
      className={`option-card${selected ? ' option-card--selected' : ''}`}
      onClick={onSelect}
    >
      <Text className='option-card__configuration'>
        {option.duration.label} · {option.participants.label} · {option.day_type.label}
      </Text>
      <Text className='option-card__price'>¥{formatPrice(option.price)}</Text>
    </Button>
  )
}

function KitDetail({ detail }: { detail: KitProductDetail }) {
  if (detail.kit_kind.value === 'color_selectable') {
    return <ColorSelectableKitDetail detail={detail} />
  }
  const stock = detail.stock ?? 0
  return (
    <View className='product-detail'>
      <ProductHeading detail={detail} />
      <View className='product-detail__section product-detail__kit-summary'>
        <Text className='product-detail__selected-price'>¥{formatPrice(detail.price)}</Text>
        <Text className={detail.available ? 'product-detail__available' : 'product-detail__sold-out'}>
          {detail.available ? `当前库存 ${stock}` : '暂时无货'}
        </Text>
        <Text className='product-detail__section-hint'>库存仅供展示，后续下单仍以服务端实时校验为准</Text>
      </View>
      <CartActions item={buildKitCartItem(detail)} unavailable={!detail.available} />
    </View>
  )
}

export function ColorSelectableKitDetail({ detail }: { detail: KitProductDetail }) {
  const cart = useCart()
  const [query, setQuery] = useState('')
  const [quantities, setQuantities] = useState<Record<number, number>>({})
  const [adding, setAdding] = useState(false)
  const selectedColors = detail.colors.filter((color) => quantities[color.id] !== undefined)
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const visibleColors = detail.colors.filter((color) => normalizedQuery.length === 0 ||
    color.color_code.toLocaleLowerCase().includes(normalizedQuery) ||
    color.name.toLocaleLowerCase().includes(normalizedQuery))
  const totalWeight = selectedColors.reduce(
    (total, color) => total + quantities[color.id] * (detail.sale_unit_grams ?? 10),
    0,
  )

  function toggleColor(color: KitColorOption): void {
    if (!color.available) return
    if (quantities[color.id] !== undefined) {
      setQuantities((current) => {
        const next = { ...current }
        delete next[color.id]
        return next
      })
      return
    }
    if (selectedColors.length >= CART_COLOR_ITEM_LIMIT) {
      void Taro.showToast({ title: `每单最多选择 ${CART_COLOR_ITEM_LIMIT} 种颜色`, icon: 'none' })
      return
    }
    setQuantities((current) => ({ ...current, [color.id]: 1 }))
  }

  function changeQuantity(colorId: number, change: number): void {
    setQuantities((current) => {
      const quantity = current[colorId]
      if (quantity === undefined) return current
      return { ...current, [colorId]: Math.max(1, Math.min(99, quantity + change)) }
    })
  }

  async function addSelectedColors(): Promise<void> {
    if (adding || selectedColors.length === 0 || cart.status !== 'ready') return
    setAdding(true)
    try {
      const items = selectedColors.map((color) => (
        buildColorKitCartItem(detail, color, quantities[color.id])
      ))
      await cart.addItems(items)
      setQuantities({})
      await Taro.showToast({ title: `已加入 ${items.length} 种颜色`, icon: 'success' })
    } catch (cause) {
      await Taro.showToast({ title: toUserMessage(cause), icon: 'none' })
    } finally {
      setAdding(false)
    }
  }

  return (
    <View className='product-detail'>
      <ProductHeading detail={detail} />
      <View className='product-detail__section color-kit-summary'>
        <Text className='product-detail__selected-price'>¥{formatPrice(detail.price)} / 10g</Text>
        <Text className={detail.available ? 'product-detail__available' : 'product-detail__sold-out'}>
          {detail.available ? `${detail.colors.length} 种颜色当前可选` : '所有颜色暂时无货'}
        </Text>
        <Text className='product-detail__section-hint'>全局色板预留 221 个位置；这里只展示已配置并为本商品启用的颜色。库存会在下单时再次校验。</Text>
      </View>

      <View className='product-detail__section color-picker'>
        <View className='color-picker__heading'>
          <View>
            <Text className='product-detail__section-title'>选择颜色</Text>
            <Text className='product-detail__section-hint'>最多 20 色；每色以 10g 为一步，最高 990g。</Text>
          </View>
          <Text className='color-picker__count'>{selectedColors.length}/{CART_COLOR_ITEM_LIMIT}</Text>
        </View>
        <Input
          className='color-picker__search'
          maxlength={100}
          placeholder='搜索色号或颜色名称'
          value={query}
          onInput={(event) => setQuery(event.detail.value)}
        />
        {visibleColors.length === 0 ? (
          <Text className='color-picker__empty'>没有匹配的可选颜色</Text>
        ) : (
          <View className='color-grid'>
            {visibleColors.map((color) => {
              const selected = quantities[color.id] !== undefined
              return (
                <Button
                  key={color.id}
                  className={`color-card${selected ? ' color-card--selected' : ''}`}
                  disabled={!color.available}
                  aria-label={`${selected ? '取消选择' : '选择'} ${formatColorLabel(color.color_code, color.name)}`}
                  onClick={() => toggleColor(color)}
                >
                  <ColorSwatch color={color} />
                  <View className='color-card__copy'>
                    <Text className='color-card__code'>{color.color_code}</Text>
                    {color.name !== color.color_code && <Text className='color-card__name'>{color.name}</Text>}
                    {!color.available && <Text className='color-card__status'>暂时无货</Text>}
                  </View>
                  {selected && <Text className='color-card__selected-label'>已选</Text>}
                </Button>
              )
            })}
          </View>
        )}
      </View>

      {selectedColors.length > 0 && (
        <View className='product-detail__section selected-colors'>
          <View className='selected-colors__heading'>
            <View>
              <Text className='product-detail__section-title'>已选颜色</Text>
              <Text className='product-detail__section-hint'>共 {totalWeight}g，可分别调整重量。</Text>
            </View>
            <Button className='selected-colors__clear' onClick={() => setQuantities({})}>清空</Button>
          </View>
          <View className='selected-colors__list'>
            {selectedColors.map((color) => {
              const quantity = quantities[color.id]
              return (
                <View className='selected-color' key={color.id}>
                  <View className='selected-color__identity'>
                    <ColorSwatch color={color} compact />
                    <View>
                      <Text className='selected-color__code'>{formatColorLabel(color.color_code, color.name)}</Text>
                      <Text className='selected-color__weight'>{quantity * 10}g</Text>
                    </View>
                  </View>
                  <View className='selected-color__controls'>
                    <Button
                      className='selected-color__step'
                      disabled={quantity <= 1}
                      aria-label={`${color.color_code} 减少 10g`}
                      onClick={() => changeQuantity(color.id, -1)}
                    >−</Button>
                    <Text className='selected-color__units'>{quantity}</Text>
                    <Button
                      className='selected-color__step'
                      disabled={quantity >= 99}
                      aria-label={`${color.color_code} 增加 10g`}
                      onClick={() => changeQuantity(color.id, 1)}
                    >＋</Button>
                  </View>
                </View>
              )
            })}
          </View>
        </View>
      )}

      <View className='product-detail__cart-actions'>
        <Button
          className='product-detail__cart-link'
          onClick={() => void Taro.navigateTo({ url: '/pages/cart/index' })}
        >查看购物车</Button>
        <Button
          className='product-detail__add-cart'
          disabled={!detail.available || selectedColors.length === 0 || cart.status !== 'ready'}
          loading={adding}
          onClick={() => void addSelectedColors()}
        >
          {!detail.available
            ? '暂时无货'
            : selectedColors.length === 0
              ? '先选择颜色'
              : `加入 ${selectedColors.length} 种颜色`}
        </Button>
      </View>
    </View>
  )
}

function ColorSwatch({ color, compact = false }: {
  readonly color: KitColorOption
  readonly compact?: boolean
}) {
  const className = `color-swatch${compact ? ' color-swatch--compact' : ''}`
  return (
    <BeadColorSwatch
      className={className}
      emptyClassName='color-swatch--empty'
      emptyLabel={`#${color.slot_no}`}
      swatchHex={color.swatch_hex}
      swatchImageUrl={color.swatch_image_url}
    />
  )
}

function CartActions({
  item,
  unavailable = false,
}: {
  item: ReturnType<typeof buildExperienceCartItem> | ReturnType<typeof buildKitCartItem>
  unavailable?: boolean
}) {
  const cart = useCart()
  const [adding, setAdding] = useState(false)

  const addToCart = async () => {
    if (adding || unavailable || cart.status !== 'ready') {
      return
    }
    setAdding(true)
    try {
      await cart.addItem(item)
      await Taro.showToast({ title: '已加入购物车', icon: 'success' })
    } catch (cause) {
      await Taro.showToast({ title: toUserMessage(cause), icon: 'none' })
    } finally {
      setAdding(false)
    }
  }

  return (
    <View className='product-detail__cart-actions'>
      <Button
        className='product-detail__cart-link'
        onClick={() => void Taro.navigateTo({ url: '/pages/cart/index' })}
      >
        查看购物车
      </Button>
      <Button
        className='product-detail__add-cart'
        disabled={unavailable || cart.status !== 'ready'}
        loading={adding}
        onClick={() => void addToCart()}
      >
        {unavailable
          ? '暂时无货'
          : cart.status === 'initializing'
            ? '购物车加载中'
            : cart.status === 'error'
              ? '购物车不可用'
              : '加入购物车'}
      </Button>
    </View>
  )
}

function ProductHeading({ detail }: { detail: ExperienceProductDetail | KitProductDetail }) {
  return (
    <>
      <ImageGallery images={detail.images} label='商品图片' />
      <View className='product-detail__heading'>
        <Text className='product-detail__type'>{detail.product_type.label}</Text>
        <Text className='product-detail__name'>{detail.name}</Text>
        <Text className='product-detail__description'>{detail.description}</Text>
      </View>
    </>
  )
}

function ImageGallery({
  images,
  label,
}: {
  images: ReadonlyArray<{ id: number; image_url: string }>
  label: string
}) {
  return (
    <View className='product-gallery' aria-label={label}>
      {images.map((image) => <DetailImage key={image.id} imageUrl={image.image_url} />)}
    </View>
  )
}

function DetailImage({ imageUrl }: { imageUrl: string }) {
  const [failed, setFailed] = useState(false)
  return failed ? (
    <View className='product-gallery__image product-gallery__fallback'>
      <Text>图片暂不可用</Text>
    </View>
  ) : (
    <Image
      className='product-gallery__image'
      lazyLoad
      mode='aspectFill'
      src={resolveAssetUrl(imageUrl)}
      onError={() => setFailed(true)}
    />
  )
}

function DetailState({
  children,
  description,
  title,
}: {
  title: string
  description: string
  children?: React.ReactNode
}) {
  return (
    <View className='product-detail product-detail--state'>
      <Text className='product-detail__state-title'>{title}</Text>
      <Text className='product-detail__state-description'>{description}</Text>
      {children}
    </View>
  )
}

function toUserMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : '加入购物车失败，请重试'
}
