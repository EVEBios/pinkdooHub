import { Button, Image, Text, View } from '@tarojs/components'
import { useState } from 'react'

import type { ProductListItem } from '@/api/endpoints/products'
import { useProductDetail } from '@/features/product/use_product_detail'
import { useProductList } from '@/features/product/use_product_list'
import { resolveAssetUrl } from '@/utils/asset_url'
import { formatPrice } from '@/utils/format'

interface PackageSelectorProps {
  readonly disabled: boolean
  readonly dayType?: string
  readonly selectedOptionId?: number
  onSelect(selection: { productId: number; experienceOptionId: number }): void
}

/** 套餐选择仅挂载在展开时，商品故障不会阻断到店预约。 */
export function ReservationPackageSelector(props: PackageSelectorProps) {
  const catalog = useProductList(undefined, 'experience')
  const [productId, setProductId] = useState<number>()
  return (
    <View className='reservation-packages'>
      {catalog.state.status === 'loading' && <Text>正在加载体验项目…</Text>}
      {catalog.state.status === 'empty' && <Text>暂时没有可选体验，可以先预约到店时间。</Text>}
      {catalog.state.errorMessage && (
        <View className='reservation-create-feedback'>
          <Text>体验项目暂时无法加载，仍可预约到店时间。</Text>
          <Button disabled={props.disabled || undefined} onClick={catalog.retry}>重新加载项目</Button>
        </View>
      )}
      <View className={`reservation-packages__grid${catalog.state.items.length === 1 ? ' reservation-packages__grid--single' : ''}`}>
        {catalog.state.items.map((product) => (
          <PackageCard
            key={product.id}
            product={product}
            disabled={props.disabled}
            selected={productId === product.id}
            onSelect={() => setProductId(product.id)}
          />
        ))}
      </View>
      {catalog.state.page < catalog.state.pages && (
        <Button className='reservation-packages__more' disabled={props.disabled || catalog.state.loadingMore || undefined} onClick={catalog.loadNextPage}>
          {catalog.state.loadingMore ? '正在加载…' : '查看更多项目'}
        </Button>
      )}
      {productId !== undefined && <PackageOptions key={productId} {...props} productId={productId} />}
    </View>
  )
}

function PackageCard({ product, disabled, selected, onSelect }: {
  readonly product: ProductListItem
  readonly disabled: boolean
  readonly selected: boolean
  onSelect(): void
}) {
  const [imageFailed, setImageFailed] = useState(false)
  const imageUrl = resolveAssetUrl(product.cover_image)
  return (
    <Button
      className={`reservation-package${selected ? ' reservation-package--selected' : ''}`}
      disabled={disabled || undefined}
      aria-label={`选择${product.name}，${formatPrice(product.display_price)}元起`}
      onClick={onSelect}
    >
      {imageUrl && !imageFailed && (
        <Image className='reservation-package__image' src={imageUrl} mode='aspectFill' lazyLoad onError={() => setImageFailed(true)} />
      )}
      <View className='reservation-package__body'>
        <Text className='reservation-package__name'>{product.name}</Text>
        <Text className='reservation-package__hint'>选择时长与人数</Text>
        <View className='reservation-package__footer'>
          <Text className='reservation-package__price'>¥{formatPrice(product.display_price)} 起</Text>
          <Text>{selected ? '选择规格' : '选择'}</Text>
        </View>
      </View>
    </Button>
  )
}

function PackageOptions({ productId, disabled, dayType, selectedOptionId, onSelect }: PackageSelectorProps & {
  readonly productId: number
}) {
  const product = useProductDetail(productId, 'experience')
  if (product.state.status === 'loading') return <Text>正在加载套餐规格…</Text>
  if (product.state.status === 'error') return (
    <View className='reservation-create-feedback'>
      <Text>套餐规格暂时无法加载，可以重试或到店后再选。</Text>
      <Button disabled={disabled || undefined} onClick={product.retry}>重试加载规格</Button>
    </View>
  )
  const detail = product.state.detail
  if (detail.product_type.value !== 'experience' || !('options' in detail)) return null
  const options = detail.options.filter((option) => !dayType || option.day_type.value === dayType)
  return (
    <View className='reservation-package-options'>
      <Text className='reservation-package-options__title'>{detail.name} · 选择套餐</Text>
      <Text className='reservation-package-options__hint'>按所选日期展示套餐，时长和人数一起选择。</Text>
      {options.length === 0 && <Text>该日期暂无适用套餐，可以更换日期或到店后再选。</Text>}
      {options.map((option) => (
        <Button
          key={option.id}
          className={`reservation-package-options__item${selectedOptionId === option.id ? ' reservation-package-options__item--selected' : ''}`}
          disabled={disabled || undefined}
          onClick={() => onSelect({ productId, experienceOptionId: option.id })}
        >
          <View>
            <Text>{option.duration.label} · {option.participants.label}</Text>
            <Text className='reservation-package-options__day'>{option.day_type.label}</Text>
          </View>
          <Text>¥{formatPrice(option.price)}</Text>
        </Button>
      ))}
    </View>
  )
}
