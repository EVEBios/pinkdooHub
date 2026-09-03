import { Button, Image, Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useState } from 'react'

import type {
  AdminProductDetail,
  OptionImageResult,
  ProductImageResult,
} from '@/api/endpoints/admin_products'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_PRODUCT_LIST_PATH,
  buildAdminProductDetailUrl,
  buildAdminProductImagesUrl,
  parseAdminProductImagesRoute,
  useAdminProductDetail,
  useAdminProductLifecycleMutation,
} from '@/features/product'
import type { AdminProductLifecycleFeature } from '@/features/product'
import { TaroImagePickerAdapter } from '@/platform/image_picker'
import type { ImagePickerPort } from '@/platform/image_picker'
import { resolveAssetUrl } from '@/utils/asset_url'

import './index.scss'

const defaultImagePicker = new TaroImagePickerAdapter()

export default function AdminProductImagesPage() {
  const auth = useAuth()
  const route = parseAdminProductImagesRoute(useRouter().params)
  if (!route) return <ImageManagerState title='图片地址无效' description='请从管理商品详情重新进入' />
  if (auth.status === 'initializing') {
    return <ImageManagerState title='正在确认管理员身份…' description='商品图片管理仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <ImageManagerState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button onClick={auth.retryInitialization}>重新检查</Button>
      </ImageManagerState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <ImageManagerState title='登录后管理商品图片' description='登录后返回管理商品列表再进入详情'>
        <Button onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_PRODUCT_LIST_PATH) })}>去登录</Button>
      </ImageManagerState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <ImageManagerState title='无管理权限' description='当前账号不会请求任何管理端商品 API' />
  }
  return <AuthenticatedAdminProductImages {...route} />
}

export function AuthenticatedAdminProductImages({ productId, productType }: {
  readonly productId: number
  readonly productType: 'experience' | 'kit'
}) {
  const { retry, state } = useAdminProductDetail(productId, productType)
  if (state.status === 'loading') {
    return <ImageManagerState title='正在加载商品图片…' description='正在读取服务端权威详情' />
  }
  if (state.status === 'error') {
    return (
      <ImageManagerState title='商品图片加载失败' description={state.errorMessage}>
        <Button onClick={retry}>重新加载</Button>
      </ImageManagerState>
    )
  }
  return <AdminProductImageManager key={`${state.product.id}:${state.product.updated_at}`} product={state.product} />
}

export function AdminProductImageManager({
  picker = defaultImagePicker,
  product,
}: {
  readonly picker?: ImagePickerPort
  readonly product: AdminProductDetail
}) {
  const mutation = useAdminProductLifecycleMutation()
  const [localError, setLocalError] = useState('')
  const editable = !product.is_deleted && product.status.value !== 'online'
  const pageUrl = buildAdminProductImagesUrl(product.id, product.product_type.value)

  async function uploadProductImage(isCover: boolean): Promise<void> {
    if (!editable || isBlocked(mutation)) return
    setLocalError('')
    try {
      const file = await picker.pickOne()
      if (!file) return
      const result = await mutation.uploadProductImage(product.id, file, isCover)
      if (result) reloadPage(pageUrl)
    } catch {
      setLocalError('无法读取所选图片，请重新选择')
    }
  }

  async function uploadOptionImage(optionId: number): Promise<void> {
    if (!editable || isBlocked(mutation)) return
    setLocalError('')
    try {
      const file = await picker.pickOne()
      if (!file) return
      const result = await mutation.uploadOptionImage(optionId, file)
      if (result) reloadPage(pageUrl)
    } catch {
      setLocalError('无法读取所选图片，请重新选择')
    }
  }

  const feedback = getMutationMessage(mutation) || localError
  return (
    <View className='admin-product-images-page'>
      <View className='admin-product-images-summary'>
        <Text className='admin-product-images-summary__title'>{product.name}</Text>
        <Text className='admin-product-images-summary__meta'>#{product.id} · {product.product_type.label} · {product.status.label}</Text>
        <Text className='admin-product-images-summary__notice'>仅支持 jpg/png/webp，最大 2 MiB；客户端检查用于提前反馈，服务端仍会验证真实内容与 MIME。</Text>
        {!editable && <Text className='admin-product-images-summary__boundary'>
          {product.is_deleted ? '已删除商品不能管理图片。' : '已上架商品不能修改图片，请先在商品详情下架。'}
        </Text>}
      </View>

      {feedback && <Text className='admin-product-images-feedback'>{feedback}</Text>}
      {mutation.state.status === 'unknown' && (
        <Button onClick={() => reloadPage(pageUrl)}>重新加载详情核对</Button>
      )}

      <View className='admin-product-images-section'>
        <Text className='admin-product-images-section__title'>Product 公共图片（{product.images.length}）</Text>
        <Text className='admin-product-images-section__hint'>公共封面用于商品列表；同一商品最多一张有效封面。</Text>
        <View className='admin-product-images-section__upload-actions'>
          <Button className='admin-product-images-section__upload-plain' disabled={!editable || isBlocked(mutation)} onClick={() => void uploadProductImage(false)}>上传普通图</Button>
          <Button className='admin-product-images-section__upload-cover' disabled={!editable || isBlocked(mutation)} onClick={() => void uploadProductImage(true)}>上传并设封面</Button>
        </View>
        {product.images.length === 0 && <Text className='admin-product-images-empty'>暂无公共图片，当前不能满足上架条件。</Text>}
        {product.images.map((image) => (
          <ManagedImageCard
            key={image.id}
            editable={editable}
            image={image}
            mutation={mutation}
            pageUrl={pageUrl}
            productImage
          />
        ))}
      </View>

      {'options' in product && product.options.map((option) => (
        <View key={option.id} className='admin-product-images-section admin-product-images-option'>
          <Text className='admin-product-images-section__title'>Option #{option.id} 专属图片（{option.images.length}）</Text>
          <Text className='admin-product-images-section__hint'>{option.duration.label} · {option.participants.label} · {option.day_type.label}；首图按 sort、ID 升序决定，不参与公共封面。</Text>
          <Button className='admin-product-images-option__upload' disabled={!editable || isBlocked(mutation)} onClick={() => void uploadOptionImage(option.id)}>上传 Option 图片</Button>
          {option.images.length === 0 && <Text className='admin-product-images-empty'>此 Option 暂无专属图片，当前不能满足上架条件。</Text>}
          {option.images.map((image) => (
            <ManagedImageCard
              key={image.id}
              editable={editable}
              image={image}
              mutation={mutation}
              pageUrl={pageUrl}
              productImage={false}
            />
          ))}
        </View>
      ))}

      {'options' in product && product.options.length === 0 && (
        <Text className='admin-product-images-empty'>尚无有效 Option；请先在配置页新增 Option，再上传专属图片。</Text>
      )}
      <Button
        onClick={() => void Taro.redirectTo({
          url: buildAdminProductDetailUrl(product.id, product.product_type.value),
        })}
      >返回商品详情</Button>
    </View>
  )
}

function ManagedImageCard({ editable, image, mutation, pageUrl, productImage }: {
  readonly editable: boolean
  readonly image: ProductImageResult | OptionImageResult
  readonly mutation: AdminProductLifecycleFeature
  readonly pageUrl: string
  readonly productImage: boolean
}) {
  const [sort, setSort] = useState(String(image.sort))
  const [validationMessage, setValidationMessage] = useState('')
  const isCover = productImage && 'is_cover' in image && image.is_cover

  async function saveSort(): Promise<void> {
    if (!editable || isBlocked(mutation)) return
    const normalized = sort.trim()
    if (!/^\d+$/.test(normalized) || !Number.isSafeInteger(Number(normalized))) {
      setValidationMessage('排序必须是非负安全整数')
      return
    }
    if (Number(normalized) === image.sort) {
      setValidationMessage('图片排序没有变化')
      return
    }
    const result = await mutation.updateImage(image.id, { sort: Number(normalized) })
    if (result) reloadPage(pageUrl)
  }

  async function setCover(): Promise<void> {
    if (!productImage || isCover || !editable || isBlocked(mutation)) return
    const result = await mutation.updateImage(image.id, { is_cover: true })
    if (result) reloadPage(pageUrl)
  }

  async function deleteImage(): Promise<void> {
    if (!editable || isBlocked(mutation)) return
    let confirmation: Taro.showModal.SuccessCallbackResult
    try {
      confirmation = await Taro.showModal({
        title: isCover ? '确认删除当前封面' : '确认逻辑删除图片',
        content: isCover
          ? '删除后商品将暂时没有公共封面，重新上架前必须设置新封面。'
          : '图片将从有效详情中隐藏；物理文件由独立清理任务延迟处理。',
        confirmText: '确认删除',
        confirmColor: '#b42318',
      })
    } catch {
      return
    }
    if (!confirmation.confirm) return
    const result = await mutation.deleteImage(image.id)
    if (result) reloadPage(pageUrl)
  }

  return (
    <View className='admin-product-image-card'>
      <Image mode='aspectFill' src={resolveAssetUrl(image.image_url)} />
      <View className='admin-product-image-card__content'>
        <Text className='admin-product-image-card__identity'>Image #{image.id}{isCover ? ' · 当前封面' : ''}</Text>
        <Text className='admin-product-image-card__label'>排序</Text>
        <Input
          className='admin-product-image-card__sort'
          disabled={!editable}
          maxlength={10}
          type='number'
          value={sort}
          onInput={(event) => {
            setSort(event.detail.value)
            setValidationMessage('')
            if (mutation.state.status === 'failed') mutation.reset()
          }}
        />
        {validationMessage && <Text className='admin-product-image-card__validation'>{validationMessage}</Text>}
        <View className='admin-product-image-card__actions'>
          <Button disabled={!editable || isBlocked(mutation)} onClick={() => void saveSort()}>保存排序</Button>
          {productImage && !isCover && (
            <Button className='admin-product-image-card__cover' disabled={!editable || isBlocked(mutation)} onClick={() => void setCover()}>设为封面</Button>
          )}
          <Button className='admin-product-image-card__delete' disabled={!editable || isBlocked(mutation)} onClick={() => void deleteImage()}>删除</Button>
        </View>
      </View>
    </View>
  )
}

function isBlocked(mutation: AdminProductLifecycleFeature): boolean {
  return mutation.state.status === 'submitting' || mutation.state.status === 'unknown' ||
    mutation.state.status === 'succeeded'
}

function getMutationMessage(mutation: AdminProductLifecycleFeature): string {
  return mutation.state.status === 'failed' || mutation.state.status === 'unknown'
    ? mutation.state.errorMessage
    : ''
}

function reloadPage(url: string): void {
  void Taro.redirectTo({ url })
}

function ImageManagerState({ children, description, title }: {
  readonly children?: React.ReactNode
  readonly description: string
  readonly title: string
}) {
  return (
    <View className='admin-product-images-state'>
      <Text className='admin-product-images-state__title'>{title}</Text>
      <Text className='admin-product-images-state__description'>{description}</Text>
      {children}
    </View>
  )
}
