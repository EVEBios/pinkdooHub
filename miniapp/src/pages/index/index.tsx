import { Button, Image, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useState } from 'react'

import type { ProductListItem } from '@/api/endpoints/products'
import { isAdminRole, useAuth } from '@/auth'
import { type ProductTypeFilter, useProductList } from '@/features/product/use_product_list'
import { buildProductDetailUrl } from '@/features/product/product_detail_route'
import { buildTableEntryUrl, parseTableToken } from '@/features/table_session'
import { AdminWorkbenchRedirect } from '@/navigation/admin_workbench_redirect'
import { ROOT_TAB_INDEX, useRootTabSelection } from '@/navigation/root_tabs'
import { resolveAssetUrl } from '@/utils/asset_url'
import { formatPrice } from '@/utils/format'

import './index.scss'

export default function ProductListPage() {
  const auth = useAuth()
  if (auth.status === 'initializing') {
    return <ProductGateState title='正在确认使用身份…' description='确认后即可进入商城' />
  }
  if (auth.status === 'error') {
    return (
      <ProductGateState title='登录状态暂不可用' description={auth.initializationError?.message ?? '请稍后重试'}>
        <Button className='product-page__state-action' onClick={auth.retryInitialization}>重新检查</Button>
      </ProductGateState>
    )
  }
  if (auth.status === 'authenticated' && !auth.user) {
    return (
      <ProductGateState title='账户信息不完整' description='请重新检查登录状态后再进入商城'>
        <Button className='product-page__state-action' onClick={auth.retryInitialization}>重新检查</Button>
      </ProductGateState>
    )
  }
  if (isAdminRole(auth.user?.role)) {
    return <AdminWorkbenchRedirect />
  }
  if (auth.status === 'authenticated' && auth.user?.role !== 'user') {
    return (
      <ProductGateState title='账户角色暂不支持' description='请重新检查登录状态后再进入商城'>
        <Button className='product-page__state-action' onClick={auth.retryInitialization}>重新检查</Button>
      </ProductGateState>
    )
  }
  return <CustomerProductList />
}

export function CustomerProductList() {
  useRootTabSelection(ROOT_TAB_INDEX.mall)
  const {
    keyword,
    loadNextPage,
    productType,
    retry,
    setKeyword,
    setProductType,
    state,
  } = useProductList()

  return (
    <View className='product-page'>
      <View className='product-page__header'>
        <View className='product-page__header-inner'>
          <Text className='product-page__brand'>pinkdooHub</Text>
          <View className='product-page__intro'>
            <Text className='product-page__title'>发现下一幅拼豆作品</Text>
            <Text className='product-page__subtitle'>选一场体验，或带一套材料回家。</Text>
            <Button className='product-page__scan-table' onClick={() => void scanTableCode()}>
              扫码开台
            </Button>
          </View>
        </View>
      </View>

      <View className='product-page__content'>
        <ProductFilters
          keyword={keyword}
          productType={productType}
          onKeywordChange={setKeyword}
          onProductTypeChange={setProductType}
        />

        {state.status === 'loading' && (
          <PageState title='正在加载商品…' description='正在向 FastAPI 请求第一页数据' />
        )}

        {state.status === 'empty' && (
          <PageState title='暂时没有可浏览的商品' description='只有已经上架且未删除的商品会显示在这里' />
        )}

        {state.status === 'error' && (
          <PageState title='商品加载失败' description={state.errorMessage ?? '请稍后重试'}>
            <Button className='product-page__state-action' onClick={retry}>重新加载</Button>
          </PageState>
        )}

        {state.status === 'content' && (
          <>
            <View className='product-page__summary'>
              <Text>本页 {state.items.length} 件</Text>
              <Text>全部 {state.total} 件</Text>
            </View>
            <View className='product-grid'>
              {state.items.map((product) => (
                <ProductCard key={product.id} product={product} />
              ))}
            </View>
            {state.errorMessage && (
              <Text className='product-page__pagination-error'>{state.errorMessage}</Text>
            )}
            {state.page < state.pages ? (
              <Button
                className='product-page__load-more'
                disabled={state.loadingMore}
                onClick={loadNextPage}
              >
                {state.loadingMore ? '正在加载…' : state.errorMessage ? '重试加载更多' : '加载更多'}
              </Button>
            ) : (
              <Text className='product-page__end'>已经到底了</Text>
            )}
          </>
        )}
      </View>
    </View>
  )
}

async function scanTableCode(): Promise<void> {
  try {
    const result = await Taro.scanCode({ scanType: ['qrCode'] })
    const token = parseTableToken(result.result)
    if (!token) {
      await Taro.showToast({ title: '这不是有效的桌台二维码', icon: 'none' })
      return
    }
    await Taro.navigateTo({ url: buildTableEntryUrl(token) })
  } catch (cause) {
    const message = cause && typeof cause === 'object' && 'errMsg' in cause
      ? String(cause.errMsg)
      : ''
    if (!message.toLowerCase().includes('cancel')) {
      await Taro.showToast({ title: '扫码暂不可用，请稍后重试', icon: 'none' })
    }
  }
}

function ProductGateState({ children, description, title }: PageStateProps) {
  return (
    <View className='product-page product-page--gate'>
      <PageState title={title} description={description}>{children}</PageState>
    </View>
  )
}

interface ProductFiltersProps {
  productType: ProductTypeFilter
  keyword: string
  onProductTypeChange(productType: ProductTypeFilter): void
  onKeywordChange(keyword: string): void
}

const PRODUCT_TYPE_FILTERS: ReadonlyArray<{ value: ProductTypeFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'experience', label: '拼豆体验' },
  { value: 'kit', label: '材料套装' },
]

function ProductFilters({ keyword, onKeywordChange, onProductTypeChange, productType }: ProductFiltersProps) {
  return (
    <View className='product-filters'>
      <Input
        className='product-filters__search'
        maxlength={100}
        placeholder='搜索商品名称'
        placeholderClass='product-filters__search-placeholder'
        value={keyword}
        onInput={(event) => onKeywordChange(event.detail.value)}
      />
      <View className='product-filters__types'>
        {PRODUCT_TYPE_FILTERS.map((filter) => (
          <Button
            key={filter.value}
            className={`product-filters__type${productType === filter.value ? ' product-filters__type--active' : ''}`}
            onClick={() => onProductTypeChange(filter.value)}
          >
            {filter.label}
          </Button>
        ))}
      </View>
    </View>
  )
}

interface PageStateProps {
  title: string
  description: string
  children?: React.ReactNode
}

function PageState({ children, description, title }: PageStateProps) {
  return (
    <View className='product-page__state'>
      <Text className='product-page__state-title'>{title}</Text>
      <Text className='product-page__state-description'>{description}</Text>
      {children}
    </View>
  )
}

function ProductCard({ product }: { product: ProductListItem }) {
  const [imageFailed, setImageFailed] = useState(false)
  const experience = product.product_type.value === 'experience'
  const priceSuffix = experience
    ? ' 起'
    : product.kit_kind?.value === 'color_selectable'
      ? ' / 10g'
      : ''

  return (
    <View
      className='product-card'
      onClick={() => void Taro.navigateTo({
        url: buildProductDetailUrl(product.id, product.product_type.value),
      })}
    >
      {imageFailed ? (
        <View className='product-card__image product-card__image--fallback'>
          <Text>图片暂不可用</Text>
        </View>
      ) : (
        <Image
          className='product-card__image'
          lazyLoad
          mode='aspectFill'
          src={resolveAssetUrl(product.cover_image)}
          onError={() => setImageFailed(true)}
        />
      )}
      <View className='product-card__body'>
        <Text className='product-card__type'>{product.product_type.label}</Text>
        <Text className='product-card__name'>{product.name}</Text>
        <Text className='product-card__price'>
          ¥{formatPrice(product.display_price)}{priceSuffix}
        </Text>
      </View>
    </View>
  )
}
