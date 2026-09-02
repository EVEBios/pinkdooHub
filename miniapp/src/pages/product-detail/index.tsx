import { Button, Image, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useState } from 'react'

import type {
  ExperienceOption,
  ExperienceProductDetail,
  KitProductDetail,
} from '@/api/endpoints/products'
import {
  parseProductDetailRoute,
  type ProductDetailRoute,
} from '@/features/product/product_detail_route'
import { useProductDetail } from '@/features/product/use_product_detail'
import { useCart } from '@/features/order'
import {
  buildExperienceCartItem,
  buildKitCartItem,
} from '@/features/order/cart_item'
import { resolveAssetUrl } from '@/utils/asset_url'
import { formatPrice } from '@/utils/format'

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
      <CartActions item={buildExperienceCartItem(detail, selectedOption)} />
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
  return (
    <View className='product-detail'>
      <ProductHeading detail={detail} />
      <View className='product-detail__section product-detail__kit-summary'>
        <Text className='product-detail__selected-price'>¥{formatPrice(detail.price)}</Text>
        <Text className={detail.available ? 'product-detail__available' : 'product-detail__sold-out'}>
          {detail.available ? `当前库存 ${detail.stock}` : '暂时无货'}
        </Text>
        <Text className='product-detail__section-hint'>库存仅供展示，后续下单仍以服务端实时校验为准</Text>
      </View>
      <CartActions item={buildKitCartItem(detail)} unavailable={!detail.available} />
    </View>
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
