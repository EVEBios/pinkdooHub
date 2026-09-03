import { Button, Form, Image, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import type { AdminProductListItem } from '@/api/endpoints/admin_products'
import { buildLoginUrl, isAdminRole, useAuth } from '@/auth'
import {
  ADMIN_PRODUCT_LIST_PATH,
  buildAdminProductCreateUrl,
  buildAdminProductDetailUrl,
  EMPTY_ADMIN_PRODUCT_FILTERS,
  type AdminProductFilterDraft,
  type AdminProductStatusFilter,
  type AdminProductTypeFilter,
  useAdminProductList,
} from '@/features/product'
import { resolveAssetUrl } from '@/utils/asset_url'
import { formatPrice } from '@/utils/format'

import './index.scss'

const TYPE_FILTERS: ReadonlyArray<{ value: AdminProductTypeFilter; label: string }> = [
  { value: 'all', label: '全部类型' },
  { value: 'experience', label: '拼豆体验' },
  { value: 'kit', label: '材料套装' },
]

const STATUS_FILTERS: ReadonlyArray<{ value: AdminProductStatusFilter; label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: 'draft', label: '草稿' },
  { value: 'online', label: '已上架' },
  { value: 'offline', label: '已下架' },
]

export default function AdminProductsPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <AdminProductsState title='正在确认管理员身份…' description='管理商品仅对 ADMIN+ 开放' />
  }
  if (auth.status === 'error') {
    return (
      <AdminProductsState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='admin-products-state__action' onClick={auth.retryInitialization}>重新检查</Button>
      </AdminProductsState>
    )
  }
  if (auth.status === 'guest') {
    return (
      <AdminProductsState title='登录后进入商品管理' description='登录后仍会根据服务端角色校验权限'>
        <Button
          className='admin-products-state__action'
          onClick={() => void Taro.navigateTo({ url: buildLoginUrl(ADMIN_PRODUCT_LIST_PATH) })}
        >去登录</Button>
      </AdminProductsState>
    )
  }
  if (!isAdminRole(auth.user?.role)) {
    return <AdminProductsState title='无管理权限' description='当前账号不会请求任何管理端商品 API' />
  }
  return <AuthenticatedAdminProducts />
}

export function AuthenticatedAdminProducts() {
  const { applyFilters, filters, loadNextPage, retry, state } = useAdminProductList()
  const [draft, setDraft] = useState<AdminProductFilterDraft>(EMPTY_ADMIN_PRODUCT_FILTERS)
  const [submittedKeyword, setSubmittedKeyword] = useState('')
  const hasPendingInput = draft.keyword.trim() !== submittedKeyword

  function updateDraft(patch: Partial<AdminProductFilterDraft>): void {
    setDraft((current) => ({ ...current, ...patch }))
  }

  function resetFilters(): void {
    setDraft(EMPTY_ADMIN_PRODUCT_FILTERS)
    setSubmittedKeyword('')
    applyFilters(EMPTY_ADMIN_PRODUCT_FILTERS)
  }

  function submitFilters(): void {
    const keyword = draft.keyword.trim()
    setSubmittedKeyword(keyword)
    applyFilters({ ...draft, keyword })
  }

  function selectButtonFilter(patch: Partial<Pick<
    AdminProductFilterDraft,
    'productType' | 'status' | 'includeDeleted'
  >>): void {
    setDraft((current) => ({ ...current, ...patch }))
    applyFilters({ ...filters, ...patch })
  }

  return (
    <View className='admin-products-page'>
      <View className='admin-products-page__header'>
        <Text className='admin-products-page__title'>管理商品</Text>
        <Text className='admin-products-page__subtitle'>查看全部状态商品、草稿配置与逻辑删除记录</Text>
      </View>

      <View className='admin-products-create'>
        <Button
          className='admin-products-create__experience'
          type='primary'
          onClick={() => void Taro.navigateTo({ url: buildAdminProductCreateUrl('experience') })}
        >新建 Experience</Button>
        <Button
          className='admin-products-create__kit'
          onClick={() => void Taro.navigateTo({ url: buildAdminProductCreateUrl('kit') })}
        >新建 Kit</Button>
      </View>

      <View className='admin-product-filters'>
        <Form onSubmit={submitFilters}>
          <Text className='admin-product-filters__label'>商品类型</Text>
          <FilterButtons
            filters={TYPE_FILTERS}
            selected={draft.productType}
            onSelect={(productType) => selectButtonFilter({ productType })}
          />
          <Text className='admin-product-filters__label'>商品状态</Text>
          <FilterButtons
            filters={STATUS_FILTERS}
            selected={draft.status}
            onSelect={(status) => selectButtonFilter({ status })}
          />
          <Input
            className='admin-product-filters__input'
            maxlength={100}
            placeholder='搜索商品名称'
            value={draft.keyword}
            onInput={(event) => updateDraft({ keyword: event.detail.value })}
          />
          <Text className='admin-product-filters__label'>删除记录</Text>
          <View className='admin-product-filters__buttons'>
            <Button
              className={`admin-product-filters__deleted${!draft.includeDeleted ? ' admin-product-filters__deleted--active' : ''}`}
              onClick={() => selectButtonFilter({ includeDeleted: false })}
            >不含删除记录</Button>
            <Button
              className={`admin-product-filters__deleted${draft.includeDeleted ? ' admin-product-filters__deleted--active' : ''}`}
              onClick={() => selectButtonFilter({ includeDeleted: true })}
            >包含删除记录</Button>
          </View>
          {hasPendingInput && (
            <Text className='admin-product-filters__pending'>输入条件尚未应用，点击「查询」后生效</Text>
          )}
          <View className='admin-product-filters__actions'>
            <Button type='primary' onClick={submitFilters}>查询</Button>
            <Button onClick={resetFilters}>清空</Button>
          </View>
        </Form>
      </View>

      {state.status === 'loading' && <AdminProductsState title='正在加载管理商品…' description='正在读取服务端第一页' />}
      {state.status === 'empty' && <AdminProductsState title='当前筛选下没有商品' description='可调整条件后重新查询' />}
      {state.status === 'error' && (
        <AdminProductsState title='管理商品加载失败' description={state.errorMessage ?? '请稍后重试'}>
          <Button className='admin-products-state__action' onClick={retry}>重新加载</Button>
        </AdminProductsState>
      )}
      {state.status === 'content' && (
        <View className='admin-products-content'>
          <View className='admin-products-content__summary'>
            <Text>已加载 {state.items.length} 件</Text>
            <Text>共 {state.total} 件</Text>
          </View>
          {state.items.map((product) => <AdminProductCard key={product.id} product={product} />)}
          {state.errorMessage && <Text className='admin-products-content__error'>{state.errorMessage}</Text>}
          {state.page < state.pages ? (
            <Button disabled={state.loadingMore} onClick={loadNextPage}>
              {state.loadingMore ? '正在加载…' : state.errorMessage ? '重试加载更多' : '加载更多'}
            </Button>
          ) : <Text className='admin-products-content__end'>已经到底了</Text>}
        </View>
      )}
    </View>
  )
}

function FilterButtons<T extends string>({ filters, onSelect, selected }: {
  readonly filters: ReadonlyArray<{ value: T; label: string }>
  readonly selected: T
  readonly onSelect: (value: T) => void
}) {
  return (
    <View className='admin-product-filters__buttons'>
      {filters.map((filter) => (
        <Button
          key={filter.value}
          className={`admin-product-filters__button${selected === filter.value ? ' admin-product-filters__button--active' : ''}`}
          onClick={() => onSelect(filter.value)}
        >{filter.label}</Button>
      ))}
    </View>
  )
}

function AdminProductCard({ product }: { readonly product: AdminProductListItem }) {
  return (
    <View
      className={`admin-product-card${product.is_deleted ? ' admin-product-card--deleted' : ''}`}
      onClick={() => void Taro.navigateTo({
        url: buildAdminProductDetailUrl(product.id, product.product_type.value),
      })}
    >
      {product.cover_image ? (
        <Image className='admin-product-card__image' mode='aspectFill' src={resolveAssetUrl(product.cover_image)} />
      ) : (
        <View className='admin-product-card__image admin-product-card__image--empty'><Text>暂无封面</Text></View>
      )}
      <View className='admin-product-card__body'>
        <View className='admin-product-card__badges'>
          <Text>{product.product_type.label}</Text>
          <Text>{product.status.label}</Text>
          {product.is_deleted && <Text>已删除</Text>}
        </View>
        <Text className='admin-product-card__name'>{product.name}</Text>
        <Text className='admin-product-card__price'>
          {product.display_price ? `¥${formatPrice(product.display_price)}` : '价格待配置'}
        </Text>
        <Text className='admin-product-card__time'>更新：{product.updated_at}</Text>
      </View>
    </View>
  )
}

function AdminProductsState({ children, description, title }: {
  readonly title: string
  readonly description: string
  readonly children?: React.ReactNode
}) {
  return (
    <View className='admin-products-state'>
      <Text className='admin-products-state__title'>{title}</Text>
      <Text className='admin-products-state__description'>{description}</Text>
      {children}
    </View>
  )
}
