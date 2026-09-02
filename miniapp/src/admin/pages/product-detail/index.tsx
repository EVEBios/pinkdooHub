import { Button, Image, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useRef } from 'react'

import type {
  AdminExperienceProductDetail,
  AdminKitProductDetail,
  AdminProductDetail,
} from '@/api/endpoints/admin_products'
import { buildProductAuditUrl } from '@/features/audit'
import { buildKitInventoryUrl } from '@/features/inventory'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_PRODUCT_LIST_PATH,
  buildAdminProductConfigurationUrl,
  buildAdminProductEditUrl,
  buildAdminProductImagesUrl,
  parseAdminProductDetailRoute,
  translateReadinessIssue,
  useAdminProductDetail,
  useAdminProductLifecycleMutation,
  useAdminProductMutation,
} from '@/features/product'
import { resolveAssetUrl } from '@/utils/asset_url'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function AdminProductDetailPage() {
  const auth = useAuth()
  const route = parseAdminProductDetailRoute(useRouter().params)
  if (!route) {
    return <AdminProductDetailState title='商品地址无效' description='请从管理商品列表重新进入' />
  }
  if (auth.status === 'initializing') {
    return <AdminProductDetailState title='正在确认管理员身份…' description='管理商品详情仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <AdminProductDetailState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='admin-product-detail-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </AdminProductDetailState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <AdminProductDetailState title='登录后查看管理商品' description='登录后返回管理商品列表再进入详情'>
        <Button
          className='admin-product-detail-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_PRODUCT_LIST_PATH) })}
        >去登录</Button>
      </AdminProductDetailState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <AdminProductDetailState title='无管理权限' description='当前账号不会请求任何管理端商品 API' />
  }
  return <AuthenticatedAdminProductDetail {...route} />
}

export function AuthenticatedAdminProductDetail({ productId, productType }: {
  readonly productId: number
  readonly productType: 'experience' | 'kit'
}) {
  const { retry, state } = useAdminProductDetail(productId, productType)
  if (state.status === 'loading') {
    return <AdminProductDetailState title='正在加载管理商品…' description='正在读取服务端商品聚合' />
  }
  if (state.status === 'error') {
    return (
      <AdminProductDetailState title='管理商品详情加载失败' description={state.errorMessage}>
        <Button className='admin-product-detail-state__action' onClick={retry}>重新加载</Button>
        <Button onClick={() => void Taro.navigateTo({ url: ADMIN_PRODUCT_LIST_PATH })}>返回管理商品</Button>
      </AdminProductDetailState>
    )
  }
  const product = state.product
  return <AdminProductDetailContent key={`${product.id}:${product.updated_at}`} product={product} retry={retry} />
}

function AdminProductDetailContent({ product, retry }: {
  readonly product: AdminProductDetail
  readonly retry: () => void
}) {
  const { deleteProduct, state: mutation } = useAdminProductMutation()
  const lifecycle = useAdminProductLifecycleMutation()
  const commandInFlightRef = useRef(false)
  const mutable = !product.is_deleted && product.status.value !== 'online'
  const mutationBlocked = mutation.status === 'submitting' || mutation.status === 'succeeded' || mutation.status === 'unknown'
  const lifecycleBlocked = lifecycle.state.status === 'submitting' || lifecycle.state.status === 'succeeded' || lifecycle.state.status === 'unknown'

  async function confirmDelete(): Promise<void> {
    if (!mutable || mutationBlocked || lifecycleBlocked || commandInFlightRef.current) return
    commandInFlightRef.current = true
    try {
      const confirmation = await Taro.showModal({
        title: '确认逻辑删除',
        content: `删除“${product.name}”后，默认管理列表将不再显示；历史关联数据仍保留。`,
        confirmText: '确认删除',
        confirmColor: '#b42318',
      })
      if (!confirmation.confirm) return
      const result = await deleteProduct(product.id)
      if (result?.action === 'delete') {
        void Taro.redirectTo({ url: ADMIN_PRODUCT_LIST_PATH })
      }
    } catch {
      return
    } finally {
      commandInFlightRef.current = false
    }
  }

  async function confirmStatusChange(): Promise<void> {
    if (product.is_deleted || mutationBlocked || lifecycleBlocked || commandInFlightRef.current) return
    commandInFlightRef.current = true
    const goingOnline = product.status.value !== 'online'
    try {
      const confirmation = await Taro.showModal({
        title: goingOnline ? '确认上架商品' : '确认下架商品',
        content: goingOnline
          ? '服务端将校验名称、描述、公共封面、Option/Kit 配置及图片，并一次返回全部缺项。'
          : '下架后商品不再公开销售，但历史订单、Option、图片和库存记录都会保留。',
        confirmText: goingOnline ? '确认上架' : '确认下架',
        confirmColor: goingOnline ? '#3f6178' : '#895b12',
      })
      if (!confirmation.confirm) return
      const result = goingOnline
        ? await lifecycle.onlineProduct(product.id)
        : await lifecycle.offlineProduct(product.id)
      if (result) retry()
    } catch {
      return
    } finally {
      commandInFlightRef.current = false
    }
  }

  const mutationMessage = mutation.status === 'failed' || mutation.status === 'unknown'
    ? mutation.errorMessage
    : ''
  const lifecycleMessage = lifecycle.state.status === 'failed' || lifecycle.state.status === 'unknown'
    ? lifecycle.state.errorMessage
    : ''
  const readinessIssues = lifecycle.state.status === 'failed'
    ? lifecycle.state.readinessIssues
    : undefined
  return (
    <View className='admin-product-detail-page'>
      <ProductHeading product={product} />
      <View className='admin-product-detail-actions'>
        <Button
          className='admin-product-detail-actions__edit'
          disabled={!mutable || mutationBlocked || lifecycleBlocked}
          onClick={() => void Taro.navigateTo({
            url: buildAdminProductEditUrl(product.id, product.product_type.value),
          })}
        >编辑基本信息</Button>
        <Button
          className='admin-product-detail-actions__configuration'
          disabled={!mutable || mutationBlocked || lifecycleBlocked}
          onClick={() => void Taro.navigateTo({
            url: buildAdminProductConfigurationUrl(product.id, product.product_type.value),
          })}
        >{product.product_type.value === 'experience' ? '管理 Option' : '修改价格'}</Button>
        <Button
          className='admin-product-detail-actions__images'
          disabled={!mutable || mutationBlocked || lifecycleBlocked}
          onClick={() => void Taro.navigateTo({
            url: buildAdminProductImagesUrl(product.id, product.product_type.value),
          })}
        >管理图片</Button>
        <Button
          className='admin-product-detail-actions__audit'
          disabled={mutation.status === 'submitting' || lifecycle.state.status === 'submitting'}
          onClick={() => void Taro.navigateTo({
            url: buildProductAuditUrl(product.id, product.product_type.value),
          })}
        >操作历史</Button>
        {product.product_type.value === 'kit' && (
          <Button
            className='admin-product-detail-actions__inventory'
            disabled={product.is_deleted || mutation.status === 'submitting' || lifecycle.state.status === 'submitting'}
            onClick={() => void Taro.navigateTo({ url: buildKitInventoryUrl(product.id) })}
          >管理库存</Button>
        )}
        <Button
          className='admin-product-detail-actions__status'
          disabled={product.is_deleted || mutationBlocked || lifecycleBlocked}
          onClick={() => void confirmStatusChange()}
        >{lifecycle.state.status === 'submitting'
            ? product.status.value === 'online' ? '正在下架…' : '正在上架…'
            : product.status.value === 'online' ? '下架商品' : '上架商品'}</Button>
        <Button
          className='admin-product-detail-actions__delete'
          disabled={!mutable || mutationBlocked || lifecycleBlocked}
          onClick={() => void confirmDelete()}
        >{mutation.status === 'submitting' ? '正在删除…' : '逻辑删除'}</Button>
      </View>
      {product.is_deleted && <Text className='admin-product-detail-page__boundary'>已删除商品不提供编辑、删除或恢复操作。</Text>}
      {!product.is_deleted && product.status.value === 'online' && (
        <Text className='admin-product-detail-page__boundary'>已上架商品必须先下架，才能修改基本信息、配置或图片；点击“下架商品”即可恢复编辑能力。</Text>
      )}
      {mutationMessage && <Text className='admin-product-detail-page__mutation-error'>{mutationMessage}</Text>}
      {lifecycleMessage && <Text className='admin-product-detail-page__mutation-error'>{lifecycleMessage}</Text>}
      {readinessIssues && (
        <View className='admin-product-detail-readiness-issues'>
          {readinessIssues.map((issue) => <Text key={issue}>• {translateReadinessIssue(issue)}</Text>)}
        </View>
      )}
      {(mutation.status === 'unknown' || lifecycle.state.status === 'unknown') && (
        <Button className='admin-product-detail-page__verify' onClick={retry}>重新加载详情核对</Button>
      )}
      <ProductImages product={product} />
      {'options' in product
        ? <ExperienceConfiguration product={product} />
        : <KitConfiguration product={product} />}
      <View className='admin-product-detail-meta'>
        <Text>创建时间：{product.created_at}</Text>
        <Text>更新时间：{product.updated_at}</Text>
        <Text>删除标记：{product.is_deleted ? '已逻辑删除' : '未删除'}</Text>
      </View>
      <Button onClick={() => void Taro.navigateTo({ url: ADMIN_PRODUCT_LIST_PATH })}>返回管理商品</Button>
    </View>
  )
}

function ProductHeading({ product }: { readonly product: AdminProductDetail }) {
  return (
    <View className='admin-product-detail-heading'>
      <Text className='admin-product-detail-heading__eyebrow'>{product.product_type.label}</Text>
      <Text className='admin-product-detail-heading__name'>{product.name}</Text>
      <View className='admin-product-detail-heading__badges'>
        <Text>{product.status.label}</Text>
        {product.is_deleted && <Text>已删除</Text>}
      </View>
      <Text className='admin-product-detail-heading__description'>{product.description || '暂无商品描述'}</Text>
    </View>
  )
}

function ProductImages({ product }: { readonly product: AdminProductDetail }) {
  if (product.images.length === 0) {
    return <ReadinessNotice>尚未上传 Product 公共图片；草稿允许为空。</ReadinessNotice>
  }
  return (
    <View className='admin-product-detail-images'>
      <Text className='admin-product-detail-section-title'>公共图片</Text>
      <View className='admin-product-detail-images__grid'>
        {product.images.map((image) => (
          <View key={image.id} className='admin-product-detail-images__item'>
            <Image mode='aspectFill' src={resolveAssetUrl(image.image_url)} />
            <Text>{image.is_cover ? '封面' : `排序 ${image.sort}`}</Text>
          </View>
        ))}
      </View>
    </View>
  )
}

function ExperienceConfiguration({ product }: { readonly product: AdminExperienceProductDetail }) {
  if (product.options.length === 0) {
    return <ReadinessNotice>尚未配置 Experience Option；因此列表价格可以为空。</ReadinessNotice>
  }
  return (
    <View className='admin-product-detail-options'>
      <Text className='admin-product-detail-section-title'>体验配置（{product.options.length}）</Text>
      {product.options.map((option) => (
        <View key={option.id} className='admin-product-option'>
          <Text className='admin-product-option__title'>Option #{option.id}</Text>
          <Text>{option.duration.label} · {option.participants.label} · {option.day_type.label}</Text>
          <Text className='admin-product-option__price'>¥{formatPrice(option.price)}</Text>
          <Text>专属图片：{option.images.length} 张</Text>
        </View>
      ))}
    </View>
  )
}

function KitConfiguration({ product }: { readonly product: AdminKitProductDetail }) {
  return (
    <View className='admin-product-detail-kit'>
      <Text className='admin-product-detail-section-title'>套装数据</Text>
      <Text>当前价格：¥{formatPrice(product.price)}</Text>
      <Text>权威库存余额：{product.stock}</Text>
      <Text className='admin-product-detail-kit__hint'>库存调整必须从“管理库存”进入，并经过 Inventory API、流水与幂等键。</Text>
    </View>
  )
}

function ReadinessNotice({ children }: { readonly children: React.ReactNode }) {
  return <Text className='admin-product-readiness'>{children}</Text>
}

function AdminProductDetailState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='admin-product-detail-state'>
      <Text className='admin-product-detail-state__title'>{title}</Text>
      <Text className='admin-product-detail-state__description'>{description}</Text>
      {children}
    </View>
  )
}
