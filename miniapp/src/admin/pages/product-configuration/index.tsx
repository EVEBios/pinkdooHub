import { Button, Input, Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { useState } from 'react'

import type {
  AdminExperienceProductDetail,
  AdminKitProductDetail,
  ExperienceOptionUpdateRequest,
} from '@/api/endpoints/admin_products'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_PRODUCT_LIST_PATH,
  buildAdminProductConfigurationUrl,
  buildAdminProductDetailUrl,
  parseAdminProductConfigurationRoute,
  useAdminProductConfigurationMutation,
  useAdminProductDetail,
} from '@/features/product'
import { formatPrice } from '@/utils/format'

import './index.scss'

type DayType = 'weekday' | 'holiday'

export interface ExperienceOptionFormValue {
  readonly durationMinutes: string
  readonly participants: string
  readonly dayType: DayType
  readonly price: string
}

const EMPTY_OPTION_FORM: ExperienceOptionFormValue = {
  durationMinutes: '',
  participants: '',
  dayType: 'weekday',
  price: '',
}

export default function AdminProductConfigurationPage() {
  const auth = useAuth()
  const route = parseAdminProductConfigurationRoute(useRouter().params)
  if (!route) return <ConfigurationState title='配置地址无效' description='请从管理商品详情重新进入' />
  if (auth.status === 'initializing') {
    return <ConfigurationState title='正在确认管理员身份…' description='价格与配置管理仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <ConfigurationState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button onClick={auth.retryInitialization}>重新检查</Button>
      </ConfigurationState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <ConfigurationState title='登录后管理商品配置' description='登录后返回管理商品列表再进入详情'>
        <Button onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_PRODUCT_LIST_PATH) })}>去登录</Button>
      </ConfigurationState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <ConfigurationState title='无管理权限' description='当前账号不会请求任何管理端商品 API' />
  }
  return <AuthenticatedAdminProductConfiguration {...route} />
}

export function AuthenticatedAdminProductConfiguration({ productId, productType }: {
  readonly productId: number
  readonly productType: 'experience' | 'kit'
}) {
  const { retry, state } = useAdminProductDetail(productId, productType)
  if (state.status === 'loading') {
    return <ConfigurationState title='正在加载商品配置…' description='正在读取服务端权威详情' />
  }
  if (state.status === 'error') {
    return (
      <ConfigurationState title='商品配置加载失败' description={state.errorMessage}>
        <Button onClick={retry}>重新加载</Button>
      </ConfigurationState>
    )
  }
  return 'options' in state.product
    ? <ExperienceOptionManager key={configurationKey(state.product)} product={state.product} />
    : <KitPriceManager key={configurationKey(state.product)} product={state.product} />
}

function ExperienceOptionManager({ product }: { readonly product: AdminExperienceProductDetail }) {
  const mutation = useAdminProductConfigurationMutation()
  const [editingOptionId, setEditingOptionId] = useState<number>()
  const [form, setForm] = useState<ExperienceOptionFormValue>(EMPTY_OPTION_FORM)
  const [validationMessage, setValidationMessage] = useState('')
  const editable = !product.is_deleted && product.status.value !== 'online'
  const configurationUrl = buildAdminProductConfigurationUrl(product.id, 'experience')

  function updateForm(patch: Partial<ExperienceOptionFormValue>): void {
    setForm((current) => ({ ...current, ...patch }))
    setValidationMessage('')
    if (mutation.state.status === 'failed') mutation.reset()
  }

  function beginEdit(option: AdminExperienceProductDetail['options'][number]): void {
    if (!editable || mutation.state.status === 'submitting' || mutation.state.status === 'unknown') return
    setEditingOptionId(option.id)
    setForm({
      durationMinutes: String(option.duration.value),
      participants: String(option.participants.value),
      dayType: option.day_type.value,
      price: option.price,
    })
    setValidationMessage('')
    mutation.reset()
  }

  function cancelEdit(): void {
    setEditingOptionId(undefined)
    setForm(EMPTY_OPTION_FORM)
    setValidationMessage('')
    mutation.reset()
  }

  async function submitOption(): Promise<void> {
    if (!editable || isMutationBlocked(mutation.state.status)) return
    const normalized = normalizeExperienceOptionForm(form)
    const error = validateExperienceOptionForm(normalized)
    if (error) {
      setValidationMessage(error)
      return
    }
    const request = {
      duration_minutes: Number(normalized.durationMinutes),
      participants: Number(normalized.participants),
      day_type: normalized.dayType,
      price: normalized.price,
    } as const
    const patch = editingOptionId === undefined
      ? undefined
      : buildExperienceOptionPatch(product, editingOptionId, request)
    if (patch && Object.keys(patch).length === 0) {
      setValidationMessage('没有需要保存的 Option 改动')
      return
    }
    const result = editingOptionId === undefined
      ? await mutation.createOption(product.id, request)
      : await mutation.updateOption(editingOptionId, patch!)
    if (result) void Taro.redirectTo({ url: configurationUrl })
  }

  async function deleteOption(optionId: number): Promise<void> {
    if (!editable || isMutationBlocked(mutation.state.status)) return
    let confirmation: Taro.showModal.SuccessCallbackResult
    try {
      confirmation = await Taro.showModal({
        title: '确认逻辑删除 Option',
        content: '删除后未来下单将不再显示此配置；历史订单快照不受影响。再次创建同组合会恢复原 Option ID。',
        confirmText: '确认删除',
        confirmColor: '#b42318',
      })
    } catch {
      return
    }
    if (!confirmation.confirm) return
    const result = await mutation.deleteOption(optionId)
    if (result) void Taro.redirectTo({ url: configurationUrl })
  }

  const feedback = validationMessage || mutationMessage(mutation.state)
  return (
    <View className='admin-product-configuration-page'>
      <ConfigurationSummary product={product} />
      <View className='admin-product-option-editor'>
        <Text className='admin-product-option-editor__title'>
          {editingOptionId === undefined ? '新增或恢复 Option' : `编辑 Option #${editingOptionId}`}
        </Text>
        <ConfigurationInput label='时长（分钟）' value={form.durationMinutes} onInput={(value) => updateForm({ durationMinutes: value })} disabled={!editable} />
        <ConfigurationInput label='参与人数' value={form.participants} onInput={(value) => updateForm({ participants: value })} disabled={!editable} />
        <Text className='admin-product-form__label'>日期类型</Text>
        <View className='admin-product-option-editor__day-types'>
          <Button disabled={!editable} className={`admin-product-option-editor__weekday${form.dayType === 'weekday' ? ' is-selected' : ''}`} onClick={() => updateForm({ dayType: 'weekday' })}>工作日</Button>
          <Button disabled={!editable} className={`admin-product-option-editor__holiday${form.dayType === 'holiday' ? ' is-selected' : ''}`} onClick={() => updateForm({ dayType: 'holiday' })}>节假日</Button>
        </View>
        <ConfigurationInput label='价格' value={form.price} onInput={(value) => updateForm({ price: value })} disabled={!editable} />
        <Text className='admin-product-form__notice'>同一商品内“时长 + 人数 + 日期类型”全历史唯一；已删除组合会恢复原 ID，并使用本次价格。</Text>
        {feedback && <Text className='admin-product-configuration-feedback'>{feedback}</Text>}
        <View className='admin-product-option-editor__actions'>
          <Button className='admin-product-option-editor__submit' type='primary' disabled={!editable || isMutationBlocked(mutation.state.status)} onClick={() => void submitOption()}>
            {mutation.state.status === 'submitting' ? '正在提交…' : editingOptionId === undefined ? '新增 / 恢复' : '保存 Option'}
          </Button>
          {editingOptionId !== undefined && <Button disabled={mutation.state.status === 'submitting'} onClick={cancelEdit}>取消编辑</Button>}
        </View>
      </View>
      <View className='admin-product-option-list'>
        <Text className='admin-product-option-list__title'>有效 Option（{product.options.length}）</Text>
        {product.options.length === 0 && <Text className='admin-product-form__notice'>暂无有效 Option；允许保留草稿，但当前不能满足上架条件。</Text>}
        {product.options.map((option) => (
          <View key={option.id} className='admin-product-option-card'>
            <Text className='admin-product-option-card__identity'>Option #{option.id}</Text>
            <Text>{option.duration.label} · {option.participants.label} · {option.day_type.label}</Text>
            <Text className='admin-product-option-card__price'>¥{formatPrice(option.price)}</Text>
            <Text>专属图片：{option.images.length} 张（从商品详情进入图片管理）</Text>
            <View className='admin-product-option-card__actions'>
              <Button className='admin-product-option-card__edit' disabled={!editable || isMutationBlocked(mutation.state.status)} onClick={() => beginEdit(option)}>编辑</Button>
              <Button className='admin-product-option-card__delete' disabled={!editable || isMutationBlocked(mutation.state.status)} onClick={() => void deleteOption(option.id)}>逻辑删除</Button>
            </View>
          </View>
        ))}
      </View>
      {mutation.state.status === 'unknown' && <Button onClick={() => void Taro.redirectTo({ url: configurationUrl })}>重新加载详情核对</Button>}
      <Button onClick={() => void Taro.redirectTo({ url: buildAdminProductDetailUrl(product.id, 'experience') })}>返回商品详情</Button>
    </View>
  )
}

function KitPriceManager({ product }: { readonly product: AdminKitProductDetail }) {
  const mutation = useAdminProductConfigurationMutation()
  const [price, setPrice] = useState(product.price)
  const [validationMessage, setValidationMessage] = useState('')
  const editable = !product.is_deleted && product.status.value !== 'online'
  const configurationUrl = buildAdminProductConfigurationUrl(product.id, 'kit')

  async function submit(): Promise<void> {
    if (!editable || isMutationBlocked(mutation.state.status)) return
    const normalized = price.trim()
    const error = validatePrice(normalized)
    if (error) {
      setValidationMessage(error)
      return
    }
    if (canonicalPrice(normalized) === product.price) {
      setValidationMessage('套装价格没有变化')
      return
    }
    const result = await mutation.updateKitPrice(product.id, normalized)
    if (result) void Taro.redirectTo({ url: configurationUrl })
  }

  const feedback = validationMessage || mutationMessage(mutation.state)
  return (
    <View className='admin-product-configuration-page'>
      <ConfigurationSummary product={product} />
      <View className='admin-product-kit-price'>
        <Text className='admin-product-kit-price__title'>修改套装价格</Text>
        <ConfigurationInput
          label='当前售价'
          value={price}
          onInput={(value) => {
            setPrice(value)
            setValidationMessage('')
            if (mutation.state.status === 'failed') mutation.reset()
          }}
          disabled={!editable}
        />
        <Text className='admin-product-form__notice'>库存余额 {product.stock} 只读；本页请求只发送 price，库存调整留给 Phase 8.6 Inventory。</Text>
        {feedback && <Text className='admin-product-configuration-feedback'>{feedback}</Text>}
        <Button className='admin-product-form__submit' type='primary' disabled={!editable || isMutationBlocked(mutation.state.status)} onClick={() => void submit()}>
          {mutation.state.status === 'submitting' ? '正在保存…' : '保存价格'}
        </Button>
      </View>
      {mutation.state.status === 'unknown' && <Button onClick={() => void Taro.redirectTo({ url: configurationUrl })}>重新加载详情核对</Button>}
      <Button onClick={() => void Taro.redirectTo({ url: buildAdminProductDetailUrl(product.id, 'kit') })}>返回商品详情</Button>
    </View>
  )
}

function ConfigurationSummary({ product }: {
  readonly product: AdminExperienceProductDetail | AdminKitProductDetail
}) {
  const boundary = product.is_deleted
    ? '已逻辑删除商品不能修改配置。'
    : product.status.value === 'online'
      ? '已上架商品不能修改配置；请先在商品详情下架后再操作。'
      : ''
  return (
    <View className='admin-product-configuration-summary'>
      <Text className='admin-product-configuration-summary__eyebrow'>ADMIN PRODUCT · CONFIGURATION</Text>
      <Text className='admin-product-configuration-summary__title'>{product.name}</Text>
      <Text className='admin-product-configuration-summary__meta'>{product.product_type.label} #{product.id} · {product.status.label}</Text>
      <Text className='admin-product-configuration-summary__history'>价格变更只影响未来下单；历史订单继续使用服务端快照。</Text>
      {boundary && <Text className='admin-product-configuration-summary__boundary'>{boundary}</Text>}
    </View>
  )
}

function ConfigurationInput({ disabled, label, onInput, value }: {
  readonly disabled: boolean
  readonly label: string
  readonly onInput: (value: string) => void
  readonly value: string
}) {
  return (
    <>
      <Text className='admin-product-form__label'>{label}</Text>
      <Input className='admin-product-form__input' disabled={disabled} maxlength={8} type='digit' value={value} onInput={(event) => onInput(event.detail.value)} />
    </>
  )
}

export function normalizeExperienceOptionForm(form: ExperienceOptionFormValue): ExperienceOptionFormValue {
  return {
    durationMinutes: form.durationMinutes.trim(),
    participants: form.participants.trim(),
    dayType: form.dayType,
    price: form.price.trim(),
  }
}

export function validateExperienceOptionForm(form: ExperienceOptionFormValue): string {
  if (!isPositiveSafeIntegerString(form.durationMinutes)) return '时长必须是正整数分钟'
  if (!isPositiveSafeIntegerString(form.participants)) return '参与人数必须是正整数'
  return validatePrice(form.price)
}

export function buildExperienceOptionPatch(
  product: AdminExperienceProductDetail,
  optionId: number,
  request: { readonly duration_minutes: number; readonly participants: number; readonly day_type: DayType; readonly price: string },
): ExperienceOptionUpdateRequest {
  const option = product.options.find((item) => item.id === optionId)
  if (!option) return request
  return {
    ...(option.duration.value === request.duration_minutes ? {} : { duration_minutes: request.duration_minutes }),
    ...(option.participants.value === request.participants ? {} : { participants: request.participants }),
    ...(option.day_type.value === request.day_type ? {} : { day_type: request.day_type }),
    ...(option.price === canonicalPrice(request.price) ? {} : { price: request.price }),
  }
}

export function validatePrice(value: string): string {
  if (!value) return '请输入价格'
  if (!/^\d+(?:\.\d{1,2})?$/.test(value)) return '价格必须是最多两位小数的普通数字'
  const number = Number(value)
  return Number.isFinite(number) && number > 0 && number <= 99_999
    ? ''
    : '价格必须大于 0 且不超过 99999'
}

function canonicalPrice(value: string): string {
  return Number(value).toFixed(2)
}

function isPositiveSafeIntegerString(value: string): boolean {
  return /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value))
}

function isMutationBlocked(status: string): boolean {
  return status === 'submitting' || status === 'unknown' || status === 'succeeded'
}

function mutationMessage(state: ReturnType<typeof useAdminProductConfigurationMutation>['state']): string {
  return state.status === 'failed' || state.status === 'unknown' ? state.errorMessage : ''
}

function configurationKey(product: AdminExperienceProductDetail | AdminKitProductDetail): string {
  return `${product.id}:${product.updated_at}`
}

function ConfigurationState({ children, description, title }: {
  readonly children?: React.ReactNode
  readonly description: string
  readonly title: string
}) {
  return (
    <View className='admin-product-form-state'>
      <Text className='admin-product-form-state__title'>{title}</Text>
      <Text className='admin-product-form-state__description'>{description}</Text>
      {children}
    </View>
  )
}
