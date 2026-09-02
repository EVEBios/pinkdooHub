import { Button, Input, Text, Textarea, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useState } from 'react'

import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_PRODUCT_LIST_PATH,
  buildAdminProductDetailUrl,
  parseAdminProductCreateRoute,
  type AdminProductMutationState,
  type AdminProductRouteType,
  useAdminProductMutation,
} from '@/features/product'

import './index.scss'

export interface AdminProductCreateForm {
  readonly name: string
  readonly description: string
  readonly price: string
}

const EMPTY_FORM: AdminProductCreateForm = { name: '', description: '', price: '' }

export default function AdminProductCreatePage() {
  const auth = useAuth()
  const route = parseAdminProductCreateRoute(useRouter().params)
  if (!route) return <ProductFormState title='创建地址无效' description='请从管理商品列表选择商品类型' />
  if (auth.status === 'initializing') {
    return <ProductFormState title='正在确认管理员身份…' description='创建商品仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <ProductFormState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='admin-product-form-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </ProductFormState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <ProductFormState title='登录后创建商品' description='登录后返回管理商品列表再选择创建类型'>
        <Button
          className='admin-product-form-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_PRODUCT_LIST_PATH) })}
        >去登录</Button>
      </ProductFormState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <ProductFormState title='无管理权限' description='当前账号不会请求任何管理端商品 API' />
  }
  return <AuthenticatedAdminProductCreate productType={route.productType} />
}

export function AuthenticatedAdminProductCreate({ productType }: {
  readonly productType: AdminProductRouteType
}) {
  const { createExperience, createKit, reset, state } = useAdminProductMutation()
  const [form, setForm] = useState<AdminProductCreateForm>(EMPTY_FORM)
  const [validationMessage, setValidationMessage] = useState('')

  function updateForm(patch: Partial<AdminProductCreateForm>): void {
    setForm((current) => ({ ...current, ...patch }))
    setValidationMessage('')
    if (state.status === 'failed') reset()
  }

  async function submit(): Promise<void> {
    if (state.status === 'submitting' || state.status === 'unknown' || state.status === 'succeeded') return
    const normalized = normalizeAdminProductCreateForm(form)
    const error = validateAdminProductCreateForm(productType, normalized)
    if (error) {
      setValidationMessage(error)
      return
    }
    const description = normalized.description || undefined
    const result = productType === 'experience'
      ? await createExperience({ name: normalized.name, ...(description ? { description } : {}) })
      : await createKit({
          name: normalized.name,
          ...(description ? { description } : {}),
          price: normalized.price,
        })
    if (result?.action === 'create_experience' || result?.action === 'create_kit') {
      void Taro.redirectTo({
        url: buildAdminProductDetailUrl(result.product.id, result.product.product_type.value),
      })
    }
  }

  const blocked = state.status === 'submitting' || state.status === 'unknown' || state.status === 'succeeded'
  const title = productType === 'experience' ? '新建拼豆体验' : '新建材料套装'
  return (
    <View className='admin-product-form-page'>
      <View className='admin-product-form-page__header'>
        <Text className='admin-product-form-page__eyebrow'>ADMIN PRODUCT · CREATE</Text>
        <Text className='admin-product-form-page__title'>{title}</Text>
        <Text className='admin-product-form-page__subtitle'>创建后固定为草稿，可继续配置后续能力</Text>
      </View>
      <View className='admin-product-form'>
        <ProductTextField
          label='商品名称'
          maxlength={100}
          placeholder='请输入 1–100 个字符'
          value={form.name}
          onInput={(name) => updateForm({ name })}
        />
        <Text className='admin-product-form__label'>商品描述（选填）</Text>
        <Textarea
          className='admin-product-form__textarea'
          maxlength={2000}
          placeholder='草稿阶段可以留空'
          value={form.description}
          onInput={(event) => updateForm({ description: event.detail.value })}
        />
        {productType === 'kit' && (
          <>
            <ProductTextField
              label='套装价格'
              maxlength={8}
              placeholder='例如 599.00'
              type='digit'
              value={form.price}
              onInput={(price) => updateForm({ price })}
            />
            <Text className='admin-product-form__notice'>新 Kit 库存固定从 0 开始，后续入库必须使用 Inventory 调整。</Text>
          </>
        )}
        <MutationFeedback state={state} validationMessage={validationMessage} />
        <Button
          className='admin-product-form__submit'
          disabled={blocked}
          type='primary'
          onClick={() => void submit()}
        >{state.status === 'submitting' ? '正在创建…' : '创建草稿'}</Button>
      </View>
      {state.status === 'unknown' && (
        <Button onClick={() => void Taro.redirectTo({ url: ADMIN_PRODUCT_LIST_PATH })}>返回列表核对</Button>
      )}
      <Button onClick={() => void Taro.redirectTo({ url: ADMIN_PRODUCT_LIST_PATH })}>取消并返回</Button>
    </View>
  )
}

export function normalizeAdminProductCreateForm(
  form: AdminProductCreateForm,
): AdminProductCreateForm {
  return {
    name: form.name.trim(),
    description: form.description.trim(),
    price: form.price.trim(),
  }
}

export function validateAdminProductCreateForm(
  productType: AdminProductRouteType,
  form: AdminProductCreateForm,
): string {
  if (!form.name) return '请输入商品名称'
  if (form.name.length > 100) return '商品名称不能超过 100 个字符'
  if (form.description.length > 2000) return '商品描述不能超过 2000 个字符'
  if (productType === 'kit') {
    if (!form.price) return '请输入套装价格'
    if (!/^\d+(?:\.\d{1,2})?$/.test(form.price)) return '价格必须是最多两位小数的普通数字'
    const price = Number(form.price)
    if (!Number.isFinite(price) || price <= 0 || price > 99_999) return '价格必须大于 0 且不超过 99999'
  }
  return ''
}

function ProductTextField({ label, maxlength, onInput, placeholder, type = 'text', value }: {
  readonly label: string
  readonly maxlength: number
  readonly placeholder: string
  readonly type?: 'digit' | 'text'
  readonly value: string
  readonly onInput: (value: string) => void
}) {
  return (
    <>
      <Text className='admin-product-form__label'>{label}</Text>
      <Input
        className='admin-product-form__input'
        maxlength={maxlength}
        placeholder={placeholder}
        type={type}
        value={value}
        onInput={(event) => onInput(event.detail.value)}
      />
    </>
  )
}

function MutationFeedback({ state, validationMessage }: {
  readonly state: AdminProductMutationState
  readonly validationMessage: string
}) {
  const message = validationMessage ||
    (state.status === 'failed' || state.status === 'unknown' ? state.errorMessage : '')
  return message ? <Text className='admin-product-form__error'>{message}</Text> : null
}

function ProductFormState({ children, description, title }: {
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
