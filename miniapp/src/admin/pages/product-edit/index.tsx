import { Button, Input, Text, Textarea, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useState } from 'react'

import type {
  AdminProductDetail,
  ProductBasicInfoUpdateRequest,
} from '@/api/endpoints/admin_products'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_PRODUCT_LIST_PATH,
  buildAdminProductDetailUrl,
  parseAdminProductEditRoute,
  type AdminProductRouteType,
  useAdminProductDetail,
  useAdminProductMutation,
} from '@/features/product'

import './index.scss'

export interface AdminProductEditForm {
  readonly name: string
  readonly description: string
}

export default function AdminProductEditPage() {
  const auth = useAuth()
  const route = parseAdminProductEditRoute(useRouter().params)
  if (!route) return <ProductEditState title='编辑地址无效' description='请从管理商品详情重新进入' />
  if (auth.status === 'initializing') {
    return <ProductEditState title='正在确认管理员身份…' description='编辑商品仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <ProductEditState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='admin-product-form-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </ProductEditState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <ProductEditState title='登录后编辑商品' description='登录后返回管理商品列表再进入详情'>
        <Button
          className='admin-product-form-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_PRODUCT_LIST_PATH) })}
        >去登录</Button>
      </ProductEditState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <ProductEditState title='无管理权限' description='当前账号不会请求任何管理端商品 API' />
  }
  return <AuthenticatedAdminProductEdit {...route} />
}

export function AuthenticatedAdminProductEdit({ productId, productType }: {
  readonly productId: number
  readonly productType: AdminProductRouteType
}) {
  const { retry, state } = useAdminProductDetail(productId, productType)
  if (state.status === 'loading') {
    return <ProductEditState title='正在加载商品…' description='正在读取服务端当前基本信息' />
  }
  if (state.status === 'error') {
    return (
      <ProductEditState title='商品加载失败' description={state.errorMessage}>
        <Button className='admin-product-form-state__action' onClick={retry}>重新加载</Button>
      </ProductEditState>
    )
  }
  return (
    <AdminProductEditFormView
      key={`${state.product.id}:${state.product.updated_at}`}
      product={state.product}
      productType={productType}
    />
  )
}

function AdminProductEditFormView({ product, productType }: {
  readonly product: AdminProductDetail
  readonly productType: AdminProductRouteType
}) {
  const { reset, state, updateBasicInfo } = useAdminProductMutation()
  const [form, setForm] = useState<AdminProductEditForm>({
    name: product.name,
    description: product.description ?? '',
  })
  const [validationMessage, setValidationMessage] = useState('')
  const detailUrl = buildAdminProductDetailUrl(product.id, productType)
  const editable = !product.is_deleted && product.status.value !== 'online'

  function updateForm(patch: Partial<AdminProductEditForm>): void {
    setForm((current) => ({ ...current, ...patch }))
    setValidationMessage('')
    if (state.status === 'failed') reset()
  }

  async function submit(): Promise<void> {
    if (!editable || state.status === 'submitting' || state.status === 'unknown' || state.status === 'succeeded') return
    const normalized = normalizeAdminProductEditForm(form)
    const error = validateAdminProductEditForm(normalized)
    if (error) {
      setValidationMessage(error)
      return
    }
    const patch = buildProductBasicInfoPatch(product, normalized)
    if (Object.keys(patch).length === 0) {
      setValidationMessage('没有需要保存的改动')
      return
    }
    const result = await updateBasicInfo(product.id, patch)
    if (result?.action === 'update_basic_info') {
      void Taro.redirectTo({ url: detailUrl })
    }
  }

  const blocked = !editable || state.status === 'submitting' || state.status === 'unknown' || state.status === 'succeeded'
  const boundaryMessage = product.is_deleted
    ? '已逻辑删除商品不能编辑'
    : product.status.value === 'online'
      ? '已上架商品不能编辑，请在 Phase 8.5 下架后再修改'
      : ''
  const mutationMessage = state.status === 'failed' || state.status === 'unknown' ? state.errorMessage : ''
  return (
    <View className='admin-product-form-page'>
      <View className='admin-product-form-page__header'>
        <Text className='admin-product-form-page__title'>编辑基本信息</Text>
        <Text className='admin-product-form-page__subtitle'>{product.product_type.label} #{product.id}</Text>
      </View>
      <View className='admin-product-form'>
        <Text className='admin-product-form__label'>商品名称</Text>
        <Input
          className='admin-product-form__input'
          disabled={!editable}
          maxlength={100}
          value={form.name}
          onInput={(event) => updateForm({ name: event.detail.value })}
        />
        <Text className='admin-product-form__label'>商品描述</Text>
        <Textarea
          className='admin-product-form__textarea'
          disabled={!editable}
          maxlength={2000}
          placeholder='留空并保存表示清空描述'
          value={form.description}
          onInput={(event) => updateForm({ description: event.detail.value })}
        />
        {boundaryMessage && <Text className='admin-product-form__notice'>{boundaryMessage}</Text>}
        {(validationMessage || mutationMessage) && (
          <Text className='admin-product-form__error'>{validationMessage || mutationMessage}</Text>
        )}
        <Button
          className='admin-product-form__submit'
          disabled={blocked}
          type='primary'
          onClick={() => void submit()}
        >{state.status === 'submitting' ? '正在保存…' : '保存改动'}</Button>
      </View>
      {state.status === 'unknown' && (
        <Button onClick={() => void Taro.redirectTo({ url: detailUrl })}>返回详情核对</Button>
      )}
      <Button onClick={() => void Taro.redirectTo({ url: detailUrl })}>取消并返回详情</Button>
    </View>
  )
}

export function normalizeAdminProductEditForm(form: AdminProductEditForm): AdminProductEditForm {
  return { name: form.name.trim(), description: form.description.trim() }
}

export function validateAdminProductEditForm(form: AdminProductEditForm): string {
  if (!form.name) return '请输入商品名称'
  if (form.name.length > 100) return '商品名称不能超过 100 个字符'
  if (form.description.length > 2000) return '商品描述不能超过 2000 个字符'
  return ''
}

export function buildProductBasicInfoPatch(
  product: Pick<AdminProductDetail, 'name' | 'description'>,
  form: AdminProductEditForm,
): ProductBasicInfoUpdateRequest {
  const initialDescription = product.description ?? ''
  return {
    ...(form.name === product.name ? {} : { name: form.name }),
    ...(form.description === initialDescription
      ? {}
      : { description: form.description || null }),
  }
}

function ProductEditState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='admin-product-form-state'>
      <Text className='admin-product-form-state__title'>{title}</Text>
      <Text className='admin-product-form-state__description'>{description}</Text>
      {children}
    </View>
  )
}
